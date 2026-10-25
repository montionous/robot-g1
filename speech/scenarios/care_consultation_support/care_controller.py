from __future__ import annotations

from care_urgent_assistance import submit_urgent_assistance, urgent_reply


from care_question_state import (
    analyze_care_questions, guard_care_questions, question_state_prompt, question_topics,
)

from care_answer_judge_llm import CareAnswerJudgeLLM

from care_db import (
    create_assistance_request,
)

from care_intent import (
    detect_care_domain,
    is_care_trigger,
    wants_contact_family,
    wants_to_end,
)


from care_end_intent_llm import (
    CareEndIntentLLM,
)

from care_prompt import (
    build_policy_context,
)

from care_personalization import (
    build_personalization_plan,
    build_personalization_prompt,
    build_personalized_risk_modifier,
    check_personalized_reply,
)

from care_risk import (
    classify_risk,
)

from llm_client import (
    CareLLM,
)

from care_need_bridge import (
    CareNeedBridge,
)


class CareConsultation:

    def __init__(
        self,
        *,
        elderly_id,
        session_id,
        max_rounds=20,
        llm=None,
        dry_run=False,
        answer_judge=None,
        record_urgent_needs=False,
    ):

        self.elderly_id = elderly_id
        self.session_id = session_id
        self.dry_run = bool(dry_run)
        self.record_urgent_needs = bool(record_urgent_needs)
        self.urgent_assistance = None

        # 仅作为模型上下文的轮次预算，
        # 不再用于强制结束护理咨询。
        self.max_rounds = max(
            20,
            int(max_rounds or 20),
        )

        self.round_no = 0

        self.state = "IDLE"

        self.history = []

        self.care_domain = None
        self.risk_level = None

        self.last_user_text = ""

        # needs_staff 第一次出现时，
        # 自动创建工作人员关注事项。
        # 后续轮次不重复创建。
        self.staff_follow_up_created = False
        self.assistance_request_id = None

        # dry_run=True 时：
        # 模拟工作人员关注事项创建，
        # 但不实际写入 care_assistance_request。
        self.staff_follow_up_simulated = False

        # 跨场景共享老人需求。
        #
        # dry_run/showcase 时不会写入公共 elder_need 表。
        self.care_need_bridge = (
            CareNeedBridge(
                elderly_id=
                    self.elderly_id,

                session_id=
                    self.session_id,

                dry_run=
                    self.dry_run,
            )
        )

        self.shared_need_id = None
        self.shared_need_error = None

        self.last_end_decision = None
        self.last_personalization_plan = None
        self.last_personalization_check = None
        self.last_personalized_risk = None
        self.last_question_state = None
        self.answer_judge = answer_judge
        self.answer_decisions = {}
        self.last_answer_decision = None

        self.llm = (
            llm
            if llm is not None
            else CareLLM()
        )

        # 单独的大模型只负责判断
        # 老人是否希望结束本次护理咨询。
        self.end_intent_llm = (
            CareEndIntentLLM()
        )


    def _base_result(
        self,
        **kwargs,
    ):

        result = {
            "ok":
                True,

            "state":
                self.state,

            "round_no":
                self.round_no,

            "care_domain":
                self.care_domain,

            "risk_level":
                self.risk_level,

            "staff_follow_up_created":
                self.staff_follow_up_created,

            "assistance_request_id":
                self.assistance_request_id,

            "staff_follow_up_simulated":
                self.staff_follow_up_simulated,

            "shared_need_id":
                self.shared_need_id,

            "shared_need_error":
                self.shared_need_error,

            "urgent_assistance": self.urgent_assistance,
            "question_state": self.last_question_state,
            "answer_decision": self.last_answer_decision,

            "personalization_plan":
                self.last_personalization_plan,

            "personalization_check":
                self.last_personalization_check,

            "personalized_risk":
                self.last_personalized_risk,

            "end_decision":
                self.last_end_decision,
        }

        result.update(
            kwargs
        )

        return result


    def start(
        self,
        text,
        *,
        preclassified=False,
    ):

        if (
            not preclassified
            and classify_risk(text, history=self.history).get("route_to") != "URGENT_ASSISTANCE"
            and not is_care_trigger(
                text
            )
        ):

            return {
                "ok":
                    False,

                "state":
                    "NOT_CARE_CONSULTATION",

                "reply":
                    None,
            }

        self.state = "CONSULTING"

        return self.handle_user_text(
            text
        )


    def _should_end_consultation(
        self,
        text,
    ):

        # 明确规则优先。
        if wants_to_end(
            text
        ):

            return {
                "should_end":
                    True,

                "source":
                    "rule",

                "confidence":
                    1.0,

                "reason":
                    "matched_end_rule",
            }


        # 规则没有识别出来时，
        # 再由单独的大模型判断自然结束表达。
        try:

            result = (
                self.end_intent_llm
                .classify(
                    text,
                    history=self.history,
                )
            )

            result["source"] = (
                "llm"
            )

            return result

        except Exception as exc:

            return {
                "should_end":
                    False,

                "source":
                    "llm_error",

                "confidence":
                    0.0,

                "reason":
                    repr(exc),
            }


    def finalize_shared_need(
        self,
        end_reason,
    ):

        try:

            row = (
                self.care_need_bridge
                .finalize(
                    care_domain=
                        self.care_domain
                        or "general_care",

                    risk_level=
                        self.risk_level
                        or "low",

                    end_reason=
                        end_reason,

                    staff_follow_up_created=
                        self.staff_follow_up_created,

                    assistance_request_id=
                        self.assistance_request_id,
                )
            )

            if row is not None:

                self.shared_need_id = (
                    row[
                        "id"
                    ]
                )

            self.shared_need_error = None

            return row

        except Exception as exc:

            # 公共需求表异常不能破坏
            # 已经完成的护理主流程。
            self.shared_need_error = (
                repr(exc)
            )

            return None


    def _judge_current_answer(self):
        self.last_answer_decision = None
        if len(self.history) < 2 or self.history[-2].get("role") != "assistant":
            return
        question = self.history[-2]["content"]
        topics = question_topics(question)
        if len(topics) != 1:
            return
        topic = next(iter(topics))
        previous = analyze_care_questions(self.history[:-1], answer_decisions=self.answer_decisions)
        if topic in previous["confirmed"]:
            return
        try:
            if self.answer_judge is None:
                self.answer_judge = CareAnswerJudgeLLM()
            decision = self.answer_judge.classify(
                question=question, answer=self.history[-1]["content"],
                topic=topic, history=self.history[:-2],
            )
            used = decision["confidence"] >= 0.80
            self.last_answer_decision = {**decision, "source": "llm", "used": used}
            if used:
                self.answer_decisions[len(self.history)-1] = decision
        except Exception as exc:
            # The existing conservative state rules remain available on failure.
            # No LLM error or low-confidence output creates a new health fact.
            self.last_answer_decision = {
                "source": "rule_fallback", "topic": topic, "used": False,
                "reason": type(exc).__name__,
            }


    def handle_user_text(
        self,
        text,
    ):

        text = str(
            text or ""
        ).strip()

        if not text:

            return self._base_result(
                reply=None,
            )


        # Urgent facts take precedence over end-intent LLMs, family routing,
        # personalization and normal care replies. No model call delays the handoff.
        risk = classify_risk(text, care_domain=self.care_domain, history=self.history)
        if risk.get("route_to") == "URGENT_ASSISTANCE":
            self.last_user_text = text
            self.care_domain = self.care_domain or detect_care_domain(text)
            self.risk_level = "external_route"
            self.state = "TRANSFER_EXTERNAL_ABNORMALITY"
            self.round_no += 1
            self.history.append({"role": "user", "content": text})
            self.urgent_assistance = submit_urgent_assistance(
                elderly_id=self.elderly_id, session_id=self.session_id,
                care_domain=self.care_domain, raw_text=text,
                matched_risk=risk["matched"], history=self.history,
                round_no=self.round_no,
                dry_run=self.dry_run and not self.record_urgent_needs,
            )
            if self.urgent_assistance["status"] == "recorded":
                self.shared_need_id = self.urgent_assistance["need_id"]
                self.assistance_request_id = self.urgent_assistance["assistance_request_id"]
                self.staff_follow_up_created = True
                self.shared_need_error = None
            elif self.urgent_assistance["status"] == "failed":
                self.shared_need_error = self.urgent_assistance.get("error")
            return self._base_result(
                ok=self.urgent_assistance["status"] != "failed",
                reply=urgent_reply(self.urgent_assistance),
                transfer_to="URGENT_ASSISTANCE", transfer_text=text,
                matched_risk=risk["matched"], end_reason="external_abnormality_route",
            )

        # -------------------------------------------------
        # 老人主动结束
        # -------------------------------------------------

        end_decision = (
            self._should_end_consultation(
                text
            )
        )

        self.last_end_decision = (
            end_decision
        )

        if (
            end_decision.get(
                "should_end",
                False,
            )
            and end_decision.get(
                "confidence",
                0.0,
            )
            >= 0.80
        ):

            self.state = "ENDED"

            return self._base_result(
                reply=(
                    "好的，这次护理咨询先到这里。"
                    "如果之后还有不舒服，"
                    "可以随时再告诉我或工作人员。"
                ),

                end_reason=
                    "user_requested",
            )


        # -------------------------------------------------
        # 转 CONTACT_FAMILY
        # -------------------------------------------------

        if wants_contact_family(
            text
        ):

            self.state = (
                "TRANSFER_CONTACT_FAMILY"
            )

            return self._base_result(
                transfer_to=
                    "CONTACT_FAMILY",

                transfer_text=
                    text,

                end_reason=
                    "transfer_contact_family",
            )


        self.last_user_text = text


        # -------------------------------------------------
        # 护理领域
        # -------------------------------------------------

        detected_domain = (
            detect_care_domain(
                text
            )
        )

        # -------------------------------------------------
        # 一次护理咨询锁定一个主要护理领域。
        #
        # 例如：
        # “我有点头晕”
        #     -> dizziness
        #
        # 下一轮：
        # “站起来有一点不稳”
        #
        # 这里的“站起来”只是头晕后的功能影响，
        # 不能因此把整个咨询切换成 mobility。
        #
        # 只有最开始无法确定领域（general_care）时，
        # 后续才允许升级成一个明确领域。
        # -------------------------------------------------

        if self.care_domain is None:

            self.care_domain = (
                detected_domain
            )

        elif (
            self.care_domain
            == "general_care"
            and detected_domain
            != "general_care"
        ):

            self.care_domain = (
                detected_domain
            )


        # -------------------------------------------------
        # 风险 / 场景边界判断
        # -------------------------------------------------

        risk = classify_risk(
            text,
            care_domain=
                self.care_domain,
            history=self.history,
        )


        # -------------------------------------------------
        # 个体化风险修正
        #
        # 通用风险模型只判断当前表达；
        # 这里额外比较当前情况与该老人自己的护理基线。
        #
        # 注意：
        # 既往疾病本身不会自动升级风险。
        # -------------------------------------------------

        personalized_risk = (
            build_personalized_risk_modifier(
                elderly_id=
                    self.elderly_id,

                care_domain=
                    self.care_domain,

                user_text=
                    text,

                history=
                    self.history,
            )
        )

        self.last_personalized_risk = (
            personalized_risk
        )


        current_risk = (
            risk[
                "risk_level"
            ]
        )


        # -------------------------------------------------
        # 个体化风险只允许向上修正，
        # 绝不把通用风险结果降级。
        # -------------------------------------------------

        if (
            current_risk == "low"
            and personalized_risk.get(
                "risk_level"
            )
            == "needs_staff"
        ):

            current_risk = (
                "needs_staff"
            )

            risk[
                "matched"
            ] = (
                list(
                    risk.get(
                        "matched",
                        [],
                    )
                )
                + list(
                    personalized_risk.get(
                        "matched",
                        [],
                    )
                )
            )


        # 一旦本次会话已经达到 needs_staff，
        # 后续普通问题不再自动降回 low。
        if (
            self.risk_level
            == "needs_staff"
            and current_risk == "low"
        ):

            current_risk = (
                "needs_staff"
            )

            if not risk[
                "matched"
            ]:
                risk[
                    "matched"
                ] = [
                    "carried_forward_needs_staff"
                ]


        self.risk_level = (
            current_risk
        )


        # -------------------------------------------------
        # 正常进入护理大模型
        # -------------------------------------------------

        self.round_no += 1

        self.history.append(
            {
                "role":
                    "user",

                "content":
                    text,
            }
        )


        # -------------------------------------------------
        # 个体化护理规划
        # -------------------------------------------------

        self._judge_current_answer()
        self.last_question_state = analyze_care_questions(
            self.history, answer_decisions=self.answer_decisions,
        )

        personalization_plan = (
            build_personalization_plan(
                elderly_id=
                    self.elderly_id,

                care_domain=
                    self.care_domain,

                user_text=
                    text,

                round_no=
                    self.round_no,

                history=
                    self.history,

                risk_level=
                    self.risk_level,

                question_state=self.last_question_state,
            )
        )

        self.last_personalization_plan = (
            personalization_plan
        )


        prompt = (
            build_policy_context(
                care_domain=
                    self.care_domain,

                risk_level=
                    self.risk_level,

                round_no=
                    self.round_no,

                max_rounds=
                    self.max_rounds,
            )
        )


        personalization_context = (
            build_personalization_prompt(
                personalization_plan
            )
        )


        policy_context = (
            prompt[
                "policy_context"
            ]
        )

        if personalization_context:

            policy_context += (
                "\n\n"
                + personalization_context
            )


        policy_context += "\n\n" + question_state_prompt(self.last_question_state)

        prompt["tags"][
            "PERSONALIZED"
        ] = (
            "yes"
            if personalization_plan.get(
                "personalized"
            )
            else "no"
        )

        prompt["tags"][
            "PERSONALIZATION_STRATEGY"
        ] = (
            personalization_plan.get(
                "strategy"
            )
            or "none"
        )


        # -------------------------------------------------
        # 第一次生成
        # -------------------------------------------------

        llm_result = (
            self.llm.generate_reply(
                history=
                    self.history,

                round_no=
                    self.round_no,

                max_rounds=
                    self.max_rounds,

                policy_context=
                    policy_context,
            )
        )


        reply = str(
            llm_result[
                "text"
            ]
        ).strip()


        check = (
            check_personalized_reply(
                reply,
                personalization_plan,
            )
        )

        check[
            "retry_count"
        ] = 0

        check[
            "fallback_used"
        ] = False


        # -------------------------------------------------
        # 个体化内容缺失：
        # 允许大模型自动重新生成一次
        # -------------------------------------------------

        if (
            personalization_plan.get(
                "personalized"
            )
            and not check[
                "passed"
            ]
        ):

            retry_context = (
                policy_context
                + "\n\n"
                + "[PERSONALIZATION_RETRY]\n"
                + (
                    "上一版回答没有充分体现本轮要求的"
                    "个体护理信息。\n"
                )
                + (
                    "缺失项："
                    + "、".join(
                        check[
                            "missing"
                        ]
                    )
                    + "。\n"
                )
                + (
                    "请重新生成。"
                    "必须自然体现这些个体信息，"
                    "同时仍然只能回复1到2句话。"
                )
            )


            retry_result = (
                self.llm.generate_reply(
                    history=
                        self.history,

                    round_no=
                        self.round_no,

                    max_rounds=
                        self.max_rounds,

                    policy_context=
                        retry_context,
                )
            )


            retry_reply = str(
                retry_result[
                    "text"
                ]
            ).strip()


            retry_check = (
                check_personalized_reply(
                    retry_reply,
                    personalization_plan,
                )
            )

            retry_check[
                "retry_count"
            ] = 1

            retry_check[
                "fallback_used"
            ] = False


            if retry_check[
                "passed"
            ]:

                reply = retry_reply
                llm_result = retry_result
                check = retry_check

            else:

                fallback = (
                    personalization_plan.get(
                        "fallback_reply"
                    )
                )

                if fallback:

                    # 两次都没覆盖到个体化目标，
                    # 使用程序预先审核的个体化兜底，
                    # 从而保证比赛演示稳定。
                    reply = fallback

                    check = (
                        check_personalized_reply(
                            reply,
                            personalization_plan,
                        )
                    )

                    check[
                        "retry_count"
                    ] = 1

                    check[
                        "fallback_used"
                    ] = True


        # This guard follows both model attempts and the program fallback.
        # An answered question must not be reintroduced by either path.
        guarded_reply = guard_care_questions(reply, self.last_question_state)
        guard_changed = guarded_reply != reply
        reply = guarded_reply
        previous_check = check
        check = check_personalized_reply(reply, personalization_plan)
        check["retry_count"] = previous_check["retry_count"]
        check["fallback_used"] = previous_check["fallback_used"]
        check["repeated_question_removed"] = guard_changed

        self.last_personalization_check = (
            check
        )


        # -------------------------------------------------
        # needs_staff：
        # 自动记录 + 自动创建工作人员关注事项
        # -------------------------------------------------

        new_staff_follow_up = False

        if (
            self.risk_level
            == "needs_staff"
            and not self.staff_follow_up_created
        ):

            # ---------------------------------------------
            # 根据风险来源生成工作人员摘要
            # ---------------------------------------------

            personalized_risk = (
                self.last_personalized_risk
                or {}
            )

            if risk.get("reason"):
                follow_up_summary = str(risk["reason"])

            elif personalized_risk.get(
                "applied",
                False,
            ):

                follow_up_summary = (
                    "个体化护理评估发现："
                    + str(
                        personalized_risk.get(
                            "reason",
                            "当前情况较老人本人护理基线发生变化",
                        )
                    )
                    + "。建议工作人员进一步关注。"
                )

            else:

                follow_up_summary = (
                    "老人报告日常护理相关不适，"
                    "系统判断情况存在持续、反复、"
                    "加重或功能影响等需要关注的表现，"
                    "建议工作人员进一步关注。"
                )


            # ---------------------------------------------
            # 测试模式：
            # 不向工作人员关注事项表写入测试数据。
            # ---------------------------------------------

            if self.dry_run:

                self.assistance_request_id = None

                self.staff_follow_up_simulated = (
                    True
                )

            else:

                self.assistance_request_id = (
                    create_assistance_request(
                        session_id=
                            self.session_id,

                        elderly_id=
                            self.elderly_id,

                        care_domain=
                            self.care_domain
                            or "general_care",

                        risk_level=
                            "needs_staff",

                        user_description=
                            self.last_user_text,

                        summary=
                            follow_up_summary,
                    )
                )


            self.staff_follow_up_created = True
            new_staff_follow_up = True


            # 正式运行时才向老人明确说
            # “已经记录/已经提醒工作人员”。
            #
            # dry_run 中没有真的创建工作人员事项，
            # 因此不能产生这种不真实的播报。
            if not self.dry_run:

                reply = (
                    reply.rstrip(
                        "。！？!?"
                    )
                    + "。"
                    + (
                        "我已经把这个情况记录下来，"
                        "也会提醒工作人员进一步关注。"
                    )
                )


        self.history.append(
            {
                "role":
                    "assistant",

                "content":
                    reply,
            }
        )


        self.state = "CONSULTING"


        # -------------------------------------------------
        # 同步跨场景共享需求
        #
        # 一次护理 session 始终只对应一条 elder_need。
        # 后续轮次只更新风险和处理状态。
        # -------------------------------------------------

        try:

            shared_need = (
                self.care_need_bridge
                .sync(
                    care_domain=
                        self.care_domain
                        or "general_care",

                    risk_level=
                        self.risk_level
                        or "low",

                    raw_text=
                        self.last_user_text,

                    round_no=
                        self.round_no,

                    staff_follow_up_created=
                        self.staff_follow_up_created,

                    assistance_request_id=
                        self.assistance_request_id,
                )
            )

            if shared_need is not None:

                self.shared_need_id = (
                    shared_need[
                        "id"
                    ]
                )

            self.shared_need_error = None

        except Exception as exc:

            # 共享层异常只记录，
            # 不阻塞护理咨询本身。
            self.shared_need_error = (
                repr(exc)
            )


        return self._base_result(
            reply=
                reply,

            tags=
                prompt[
                    "tags"
                ],

            knowledge_used=
                prompt[
                    "knowledge_used"
                ],

            care_stage=
                prompt[
                    "care_stage"
                ],

            matched_risk=
                risk[
                    "matched"
                ],

            risk_reason=risk.get("reason"),

            new_staff_follow_up=
                new_staff_follow_up,

            llm_ms=
                llm_result[
                    "llm_ms"
                ],

            model=
                llm_result[
                    "model"
                ],
        )

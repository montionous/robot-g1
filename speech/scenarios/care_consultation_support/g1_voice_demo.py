#!/usr/bin/env python3

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path


SCENE_DIR = Path(
    __file__
).resolve().parent

SPEECH_ROOT = (
    SCENE_DIR.parents[1]
)

sys.path.insert(
    0,
    str(SPEECH_ROOT),
)

sys.path.insert(
    0,
    str(SCENE_DIR),
)


from speech_client import SpeechClient
from speech.prepared_audio import PreparedPromptCatalog
from decision_announcer import announce_decision
from companion_recording import (
    record_asr,
    record_speech_receipt,
    record_speech_request,
    recording_mark_interrupted,
    recording_mark_failed,
    run_recorded_scene,
    validate_elderly_id,
)

from robot_leds import (
    RobotLedClient,
    add_robot_led_arguments,
    validate_robot_led_arguments,
)

from robot_actions import (
    RobotActionClient,
)

from care_controller import (
    CareConsultation,
)

from care_db import (
    add_message,
    create_session,
    get_elderly,
    update_session_context,
)

from care_intent import (
    is_care_trigger,
)

from care_intent_llm import (
    CareIntentLLM,
)

from care_session_finalize import (
    finalize_care_session,
)

from care_profile_announcement import (
    build_showcase_profile_announcement,
)

from care_memory_announcement import (
    build_memory_announcement,
)


PREPARED_PROMPTS = PreparedPromptCatalog(
    SCENE_DIR / "prepared_prompts.json"
)

# Match the existing entertainment scene's lead for the recorded invite.
# Its slow start should happen before a supportive care reply is spoken.
ACKNOWLEDGE_LEAD_SECONDS = 1.5


CARE_DOMAIN_LABELS = {
    "mobility":
        "肢体活动和肌肉关节不适",

    "dizziness":
        "头晕和一般状态",

    "sleep":
        "睡眠护理",

    "appetite":
        "饮食和食欲",

    "bowel":
        "排便和生活护理",

    "fatigue":
        "疲劳和一般状态",

    "general_care":
        "一般日常护理",
}


def log(
    name,
    value="",
):

    if value:
        print(
            f"{name}: {value}"
        )
    else:
        print(name)


def trigger_robot_action(
    actions,
    action_name,
    *,
    source,
):
    """Keep optional G1 gestures separate from the care decision flow."""

    try:
        return actions.play(
            action_name,
            source=source,
            blocking=False,
        )
    except Exception as exc:
        log("机器人动作异常", repr(exc))
        return None


def should_acknowledge_care_reply(result):
    """Only accompany a direct reassurance; routine questions never opt in.

    Keep a conservative set of opening phrases rather than searching quoted
    advice or symptoms anywhere in the reply. No matching phrase means no arm
    gesture. The caller limits this to one opportunity per consultation.
    """
    if result.get("transfer_to") or result.get("state") == "ENDED":
        return False
    reply = str(result.get("reply") or "").strip()
    return reply.startswith((
        "您先别着急", "您别着急", "先别着急", "别着急",
        "您先别担心", "您别担心", "先别担心", "别担心",
        "我会陪着您", "我在这儿陪着您", "我在这里陪着您",
        "我会在这里陪着您", "我会一直陪着您", "咱们慢慢来",
        "我会认真听您说",
    ))


def log_memory_persistence(
    finalize_result,
):

    memory = (
        finalize_result.get(
            "memory"
        )
        or {}
    )

    error = (
        finalize_result.get(
            "memory_error"
        )
    )


    if error:

        log(
            "长期护理记忆",
            (
                "本次未完成沉淀；"
                "不影响护理咨询记录"
            ),
        )

        log(
            "记忆沉淀错误",
            error,
        )

        return


    if memory.get(
        "stored"
    ):

        log(
            "长期护理记忆",
            "已更新",
        )

        log(
            "护理记忆主题",
            str(
                memory.get(
                    "memory_key"
                )
            ),
        )

        log(
            "历史咨询次数",
            str(
                memory.get(
                    "occurrence_count"
                )
            ),
        )

        summary = (
            memory.get(
                "summary"
            )
        )

        if summary:

            log(
                "本次护理摘要",
                summary,
            )

        return


    reason = memory.get(
        "reason"
    )

    # test / showcase 等主动关闭长期记忆的模式，
    # 不当成错误，也不需要在正常比赛日志中反复提示。
    if reason in {
        "session_memory_disabled",
        "dry_run",
    }:
        return


    if reason == "no_long_term_value":

        log(
            "长期护理记忆",
            "本次无新增长期信息",
        )


def speak(
    speech,
    text,
    *,
    dialect,
):

    log(
        "机器人",
        text,
    )

    record_speech_request("care_consultation_support", text, source="speak")
    try:
        result = PREPARED_PROMPTS.play_or_speak(
            speech,
            text,
            style="companion",
            dialect=dialect,
        )
    except BaseException as error:
        record_speech_receipt(
            "care_consultation_support",
            text,
            source="speak",
            error=error,
        )
        raise
    record_speech_receipt(
        "care_consultation_support",
        text,
        result=result,
        source="speak",
    )

    time.sleep(
        0.4
    )


def listen(
    speech,
    *,
    seconds,
):

    log(
        "正在听",
        (
            "等待老人开口；"
            f"开口后最多 {seconds:.1f} 秒"
        ),
    )

    result = speech.listen_g1(
        seconds=seconds,

        # 老年人可能需要一些反应时间，
        # 先等待开口，再开始计算说话时长。
        wait_for_speech=True,

        # 没开口时最多等待多久。
        # 演示循环不会因此直接结束，
        # 只会返回一次空识别。
        start_timeout=15.0,

        # 老人说完后连续静音达到该时间，
        # 才认为本轮表达结束。
        silence_timeout=1.8,

        # G1 PCM16 的起声 RMS 阈值。
        # 后续可根据实机环境微调。
        speech_rms_threshold=450,

        # 这是本轮自动创建的中间录音，识别和审计元数据完成后
        # 不需要继续占用 speech/input。
        delete_audio_after_transcribe=True,
    )

    text = str(
        result.get(
            "text",
            "",
        )
    ).strip()

    log(
        "ASR",
        text or "(未识别)",
    )

    record_asr(
        "care_consultation_support",
        text,
        source="listen",
        result=result,
    )

    return text


def save_user_message(
    *,
    session_id,
    consultation,
    text,
):

    add_message(
        session_id=session_id,

        round_no=max(
            1,
            consultation.round_no,
        ),

        role="user",

        content=text,

        tags=None,
    )


def save_assistant_message(
    *,
    session_id,
    consultation,
    text,
    tags,
):

    add_message(
        session_id=session_id,

        round_no=max(
            1,
            consultation.round_no,
        ),

        role="assistant",

        content=text,

        tags=tags,
    )


def build_care_decision_message(
    result,
    *,
    showcase=False,
):

    transfer_to = result.get(
        "transfer_to"
    )

    risk_level = result.get(
        "risk_level"
    )

    care_domain = result.get(
        "care_domain"
    )

    end_reason = result.get(
        "end_reason"
    )


    if (
        transfer_to
        == "URGENT_ASSISTANCE"
    ):

        return (
            "您描述的情况"
            "不属于一般日常护理咨询，"
            "将转交异常情况处理流程。"
        )


    if (
        transfer_to
        == "CONTACT_FAMILY"
    ):

        return (
            "您有联系家人的需求。"
        )


    if (
        end_reason
        == "user_requested"
    ):

        return (
            "您希望结束本次护理咨询。"
        )


    if result.get(
        "new_staff_follow_up"
    ):

        personalized_risk = (
            result.get(
                "personalized_risk"
            )
            or {}
        )

        reason = str(
            personalized_risk.get(
                "reason"
            )
            or ""
        ).strip().rstrip(
            "。！？!?"
        )


        # 只有个体化风险本身明确要求 needs_staff，
        # 才把该 reason 作为“升级原因”播报。
        #
        # applied=True 但 risk_level=None 时，
        # 它只表示使用了个人基线继续评估，
        # 不能把它错误解释成工作人员关注的直接原因。
        personalized_escalation = (
            personalized_risk.get(
                "applied",
                False,
            )
            and personalized_risk.get(
                "risk_level"
            )
            == "needs_staff"
            and bool(
                reason
            )
        )


        if (
            showcase
            and personalized_escalation
        ):

            decision_text = (
                "结合您的个人护理基线，"
                + reason
                + "。"
                + "系统判断需要工作人员"
                "进一步关注。"
            )

        else:

            decision_text = (
                "不适存在持续、反复"
                "或需要进一步关注的表现，"
                "系统判断需要工作人员"
                "进一步关注。"
            )


        if "headache_staff_review" in result.get("matched_risk", []) and result.get("risk_reason"):
            decision_text = str(result["risk_reason"])

        # 正式运行：
        # 确实创建了工作人员关注事项。
        if result.get(
            "assistance_request_id"
        ):

            decision_text += (
                "相关情况已自动记录，"
                "并生成工作人员关注事项。"
            )


        # showcase / dry-run：
        # controller 只模拟创建，
        # 因此不能声称已经真实写入。
        elif result.get(
            "staff_follow_up_simulated"
        ):

            log("工作人员关注事项", "当前为演示模式，已模拟生成工作人员关注事项。")


        return decision_text


    # 一般护理判断只在第一轮播报一次。
    # 后续仍处于 low 时不重复播报相同领域。
    if (
        risk_level == "low"
        and result.get(
            "round_no"
        ) == 1
    ):

        domain_text = (
            CARE_DOMAIN_LABELS.get(
                care_domain,
                "一般日常护理",
            )
        )

        return (
            f"您咨询的是{domain_text}，"
            "目前进入一般护理评估。"
        )


    return None


def run_scene(
    *,
    elderly_id,
    max_rounds,
    dialect,
    listen_seconds,
    announce_decisions,
    showcase,
    robot_actions="off",
    confirm_g1_actions=False,
    robot_leds="off",
    confirm_g1_led_demo=False,
):

    print()
    print("=" * 72)
    print(
        "CARE_CONSULTATION_SUPPORT"
        " 日常护理咨询"
    )
    print("=" * 72)

    elderly = get_elderly(
        elderly_id
    )

    if elderly is None:

        raise RuntimeError(
            "老人不存在: "
            f"elderly_id={elderly_id}"
        )


    model_round_budget = max(
        20,
        int(max_rounds),
    )


    log(
        "当前老人",
        elderly["name"],
    )

    log(
        "护理模式",
        "专业护理对话 + 自动记录",
    )

    log(
        "对话轮次",
        "无固定上限",
    )

    if showcase:
        log(
            "结束策略",
            "演示模式：老人主动结束",
        )
    else:
        log(
            "结束策略",
            "正常模式：老人主动结束 / 长时间无响应结束",
        )


    speech = SpeechClient()
    leds = RobotLedClient(
        mode=robot_leds,
        confirm_writes=confirm_g1_led_demo,
    )

    log(
        "机器人灯光",
        robot_leds,
    )

    actions = RobotActionClient(
        mode=robot_actions,
        confirm_writes=confirm_g1_actions,
    )

    log(
        "机器人动作",
        robot_actions,
    )


    first_text = ""

    for _ in range(2):

        leds.show(
            "listening",
            source="care_consultation_support:initial_listen",
        )

        first_text = listen(
            speech,
            seconds=listen_seconds,
        )

        if first_text:
            break

        speak(
            speech,
            (
                "我没有听清，"
                "您可以再说一遍哪里不舒服。"
            ),
            dialect=dialect,
        )


    if not first_text:

        leds.show(
            "retry",
            source="care_consultation_support:initial_not_heard",
        )

        speak(
            speech,
            (
                "这次护理咨询先到这里。"
                "如果之后还有不舒服，"
                "可以再告诉我。"
            ),
            dialect=dialect,
        )

        leds.show(
            "farewell",
            source="care_consultation_support:initial_timeout",
        )

        return


    # =====================================================
    # 护理场景识别
    #
    # 先走快速规则；
    # 规则没有命中时，再让大模型做语义兜底。
    # 这样可以容忍“酸 -> 伤”一类 ASR 误识别。
    # =====================================================

    leds.show(
        "processing",
        source="care_consultation_support:initial_classification",
    )

    care_detected = (
        is_care_trigger(
            first_text
        )
    )

    care_intent_source = (
        "rule"
        if care_detected
        else None
    )

    semantic_intent = None


    if not care_detected:

        leds.show(
            "retry",
            source="care_consultation_support:not_care",
        )

        try:

            semantic_intent = (
                CareIntentLLM()
                .classify(
                    first_text
                )
            )

            log(
                "护理语义判断",
                str(
                    semantic_intent
                ),
            )

            if (
                semantic_intent.get(
                    "is_care",
                    False,
                )
                and semantic_intent.get(
                    "confidence",
                    0.0,
                )
                >= 0.70
            ):

                care_detected = True
                care_intent_source = (
                    "llm"
                )

        except Exception as exc:

            # 语义兜底失败时不能让整个语音程序崩掉。
            log(
                "护理语义判断失败",
                repr(exc),
            )


    if not care_detected:

        log(
            "场景判断",
            "NOT_CARE_CONSULTATION",
        )

        speak(
            speech,
            (
                "我暂时没有听出具体的护理问题。"
                "如果身体有哪里不舒服，"
                "可以直接告诉我。"
            ),
            dialect=dialect,
        )

        leds.show(
            "farewell",
            source="care_consultation_support:not_care_end",
        )

        return


    log(
        "场景判断来源",
        care_intent_source,
    )

    log(
        "场景判断",
        "CARE_CONSULTATION_SUPPORT",
    )


    session_id = create_session(
        elderly_id,
        model_round_budget,

        session_source=(
            "showcase"
            if showcase
            else "runtime"
        ),

        # 比赛彩排 / showcase 不写长期护理记忆，
        # 避免反复演示造成虚假的历史咨询次数。
        persist_memory=(
            not showcase
        ),
    )


    consultation = (
        CareConsultation(
            elderly_id=
                elderly_id,

            session_id=
                session_id,

            max_rounds=
                model_round_budget,

            # showcase 只展示完整护理能力，
            # 不写工作人员关注事项、
            # elder_need 或长期护理记忆。
            dry_run=
                showcase,
        )
    )


    current_text = first_text
    first_turn = True
    empty_count = 0
    acknowledged_once = False

    # 演示模式中记录已经播报过的个人档案，
    # 避免每轮机械重复相同病史或历史咨询。
    announced_profile_reasons = set()


    try:

        while True:

            try:

                leds.show(
                    "processing",
                    source="care_consultation_support:consultation",
                )

                if first_turn:

                    result = (
                        consultation.start(
                            current_text,
                            preclassified=True,
                        )
                    )

                    first_turn = False

                else:

                    result = (
                        consultation
                        .handle_user_text(
                            current_text
                        )
                    )

            except Exception as exc:

                leds.show(
                    "retry",
                    source="care_consultation_support:processing_error",
                )

                log(
                    "护理处理失败",
                    repr(exc),
                )
                recording_mark_failed(exc)

                speak(
                    speech,
                    (
                        "我现在没能完成这次护理咨询。"
                        "如果您仍然不舒服，"
                        "请告诉工作人员帮您看看。"
                    ),
                    dialect=dialect,
                )

                finalize_care_session(
                    session_id=
                        session_id,

                    consultation=
                        consultation,

                    end_reason=
                        "processing_error",
                )

                leds.show(
                    "farewell",
                    source="care_consultation_support:processing_error_end",
                )

                return


            # 每一轮老人原话自动保存。
            save_user_message(
                session_id=
                    session_id,

                consultation=
                    consultation,

                text=
                    current_text,
            )


            update_session_context(
                session_id=
                    session_id,

                care_domain=
                    result.get(
                        "care_domain"
                    ),

                risk_level=
                    result.get(
                        "risk_level"
                    ),
            )


            log(
                "护理领域",
                str(
                    result.get(
                        "care_domain"
                    )
                ),
            )

            log(
                "护理阶段",
                str(
                    result.get(
                        "care_stage"
                    )
                ),
            )

            log(
                "风险等级",
                str(
                    result.get(
                        "risk_level"
                    )
                ),
            )


            matched = result.get(
                "matched_risk"
            )

            if matched:

                log(
                    "风险依据",
                    ", ".join(
                        str(x)
                        for x in matched
                    ),
                )


            knowledge = result.get(
                "knowledge_used"
            )

            if knowledge:

                print(
                    "护理知识:"
                )

                for item in knowledge:

                    print(
                        "  -",
                        item,
                    )


            tags = result.get(
                "tags"
            )

            if tags:

                log(
                    "护理Tags",
                    str(tags),
                )


            request_id = result.get(
                "assistance_request_id"
            )

            if (
                result.get(
                    "new_staff_follow_up"
                )
                and request_id
            ):

                log(
                    "自动护理记录",
                    "已保存",
                )

                log(
                    "工作人员关注事项",
                    (
                        "已生成 "
                        f"id={request_id}"
                    ),
                )


            # -------------------------------------------------
            # 演示模式：显式播报本轮实际采用的个人护理档案。
            #
            # 数据直接来自 controller 已生成的
            # personalization_plan，不重新查询数据库，
            # 从而保证“播报的依据”和“实际护理使用的依据”
            # 完全一致。
            #
            # 同一条档案在一次 session 中只播报一次。
            # -------------------------------------------------

            if showcase:

                profile_announcement = (
                    build_showcase_profile_announcement(
                        result.get(
                            "personalization_plan"
                        )
                        or {},

                        announced_reasons=
                            announced_profile_reasons,

                        max_items=3,
                    )
                )


                if profile_announcement.get(
                    "text"
                ):

                    log(
                        "个体化护理档案",
                        "；".join(
                            profile_announcement.get(
                                "items",
                                [],
                            )
                        ),
                    )

                    speak(
                        speech,

                        profile_announcement[
                            "text"
                        ],

                        # 档案说明统一普通话，
                        # 后续正常护理回复仍按场景 dialect。
                        dialect="mandarin",
                    )


                    announced_profile_reasons.update(
                        profile_announcement.get(
                            "reason_keys",
                            [],
                        )
                    )


            decision_message = (
                build_care_decision_message(
                    result,
                    showcase=showcase,
                )
            )

            if decision_message:

                announce_decision(
                    speech,
                    decision_message,

                    enabled=
                        announce_decisions,

                    # 判断播报统一普通话。
                    dialect="mandarin",
                    prepared_prompts=PREPARED_PROMPTS,
                )


            if result.get("answer_decision"):
                log("护理回答判断", str(result["answer_decision"]))

            reply = result.get(
                "reply"
            )

            if reply:

                if (
                    not acknowledged_once
                    and should_acknowledge_care_reply(result)
                ):
                    action_result = trigger_robot_action(
                        actions,
                        "acknowledge",
                        source="care_consultation_support:supportive_reply",
                    )
                    if (
                        isinstance(action_result, dict)
                        and action_result.get("status") == "started"
                    ):
                        log("抬手起势提前量", f"{ACKNOWLEDGE_LEAD_SECONDS:.1f} 秒")
                        time.sleep(ACKNOWLEDGE_LEAD_SECONDS)
                    acknowledged_once = True

                speak(
                    speech,
                    reply,
                    dialect=dialect,
                )

                save_assistant_message(
                    session_id=
                        session_id,

                    consultation=
                        consultation,

                    text=
                        reply,

                    tags=
                        tags,
                )

                leds.show(
                    "acknowledged",
                    source="care_consultation_support:reply",
                )


            if result.get(
                "llm_ms"
            ) is not None:

                log(
                    "护理大模型耗时",
                    (
                        f"{result['llm_ms']:.0f} ms"
                    ),
                )


            transfer_to = result.get(
                "transfer_to"
            )

            if transfer_to:

                log(
                    "场景转移",
                    transfer_to,
                )

                transfer_text = (
                    result.get(
                        "transfer_text"
                    )
                )

                if transfer_text:

                    log(
                        "转场原话",
                        transfer_text,
                    )


                finalize_care_session(
                    session_id=
                        session_id,

                    consultation=
                        consultation,

                    end_reason=
                        result.get(
                            "end_reason",
                            "transfer",
                        ),
                )

                leds.show(
                    "farewell",
                    source="care_consultation_support:transfer",
                )

                return


            if (
                result.get(
                    "state"
                )
                == "ENDED"
            ):

                end_reason = (
                    result.get(
                        "end_reason",
                        "completed",
                    )
                )


                finalize_result = (
                    finalize_care_session(
                        session_id=
                            session_id,

                        consultation=
                            consultation,

                        end_reason=
                            end_reason,
                    )
                )


                log_memory_persistence(
                    finalize_result
                )


                # -------------------------------------------------
                # showcase：
                # 将本次咨询经过正式长期价值判断后得到的
                # “长期护理记忆预览”显式展示出来。
                #
                # 注意：
                # preview=True 只表示已经完成摘要和长期价值判断，
                # 不表示已经写入正式长期护理数据库。
                # -------------------------------------------------

                if showcase:

                    memory_announcement = (
                        build_memory_announcement(
                            finalize_result,
                            showcase=True,
                        )
                    )


                    if (
                        memory_announcement.get(
                            "kind"
                        )
                        == "preview"
                    ):

                        log(
                            "长期护理记忆",
                            "演示预览",
                        )
                        log("演示模式", memory_announcement["console_text"])

                        memory_key = (
                            memory_announcement.get(
                                "memory_key"
                            )
                        )

                        if memory_key:

                            log(
                                "护理记忆主题",
                                str(
                                    memory_key
                                ),
                            )


                        summary = (
                            memory_announcement.get(
                                "summary"
                            )
                        )

                        if summary:

                            log(
                                "护理记忆预览摘要",
                                summary,
                            )


                        announcement_text = (
                            memory_announcement.get(
                                "text"
                            )
                        )

                        if announcement_text:

                            speak(
                                speech,
                                announcement_text,

                                # 长期护理记忆说明统一普通话。
                                dialect="mandarin",
                            )


                log(
                    "护理咨询",
                    "结束",
                )

                if end_reason == "user_requested":
                    trigger_robot_action(
                        actions,
                        "goodbye",
                        source="care_consultation_support:user_requested_end",
                    )

                leds.show(
                    "farewell",
                    source="care_consultation_support:completed",
                )

                return


            leds.show(
                "listening",
                source="care_consultation_support:followup_listen",
            )
            current_text = listen(
                speech,
                seconds=listen_seconds,
            )


            if not current_text:

                empty_count += 1

                # 第一次连续没听到时先等待，
                # 第二次再进行一次自然提醒。
                if empty_count == 2:

                    leds.show(
                        "retry",
                        source="care_consultation_support:followup_not_heard",
                    )

                    speak(
                        speech,
                        (
                            "我还在听。"
                            "如果还有想问的，"
                            "您可以接着说。"
                        ),
                        dialect=dialect,
                    )


                # 正常运行：
                # 连续多次没有收到老人语音，
                # 自动结束，避免会话永久占用。
                if (
                    not showcase
                    and empty_count >= 4
                ):

                    speak(
                        speech,
                        (
                            "您好像暂时没有其他问题了。"
                            "这次护理咨询先到这里，"
                            "需要的时候可以再告诉我。"
                        ),
                        dialect=dialect,
                    )

                    finalize_result = (
                        finalize_care_session(
                            session_id=
                                session_id,

                            consultation=
                                consultation,

                            end_reason=
                                "no_response",
                        )
                    )

                    log_memory_persistence(
                        finalize_result
                    )

                    trigger_robot_action(
                        actions,
                        "goodbye",
                        source="care_consultation_support:no_response_end",
                    )

                    leds.show(
                        "farewell",
                        source="care_consultation_support:no_response",
                    )

                    return


                # 演示模式：
                # 不因为沉默自动结束。
                # 等老人明确表达“先这样吧”等结束意图。
                continue


            empty_count = 0


    except KeyboardInterrupt:

        print()

        log(
            "运行状态",
            "用户中断",
        )

        recording_mark_interrupted()

        finalize_care_session(
            session_id=
                session_id,

            consultation=
                consultation,

            end_reason=
                "manual_interrupt",
        )

        leds.show(
            "farewell",
            source="care_consultation_support:manual_interrupt",
        )


def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--elderly-id",
        type=int,
        default=None,
    )

    parser.add_argument(
        "--max-rounds",
        type=int,
        default=20,
        help=(
            "仅作为护理大模型的上下文轮次预算；"
            "不会因为达到该值强制结束演示"
        ),
    )

    parser.add_argument(
        "--dialect",
        default="mandarin",
        choices=[
            "mandarin",
            "shaanxi",
        ],
    )

    parser.add_argument(
        "--listen-seconds",
        type=float,
        default=6.0,
    )

    parser.add_argument(
        "--announce-decisions",
        action="store_true",
        help="播报关键护理判断结果",
    )

    parser.add_argument(
        "--showcase",
        action="store_true",
        help=(
            "比赛演示模式："
            "不因长时间无响应自动结束，"
            "等待老人主动结束"
        ),
    )

    parser.add_argument(
        "--robot-actions",
        choices=("off", "dry-run", "execute"),
        default="dry-run",
        help="机器人手臂动作模式；默认 dry-run，不向 G1 写入",
    )

    parser.add_argument(
        "--confirm-g1-actions",
        action="store_true",
        help="仅与 --robot-actions execute 一起使用",
    )

    add_robot_led_arguments(parser)

    parser.add_argument(
        "--elder-id",
        dest="elderly_id",
        type=int,
        help=argparse.SUPPRESS,
    )

    parser.add_argument(
        "--record-log",
        type=Path,
        help="care_session_record_v1 journal path",
    )

    parser.add_argument(
        "--record-mode",
        choices=("live", "replay"),
        default="live",
    )

    args = parser.parse_args()

    if args.robot_actions == "execute" and not args.confirm_g1_actions:
        parser.error(
            "--robot-actions execute requires --confirm-g1-actions"
        )
    if args.confirm_g1_actions and args.robot_actions != "execute":
        parser.error(
            "--confirm-g1-actions requires --robot-actions execute"
        )

    validate_robot_led_arguments(parser, args)


    if args.record_log is not None and args.elderly_id is None:
        parser.error("--record-log requires explicit --elderly-id")
    elderly_id = args.elderly_id if args.elderly_id is not None else 1
    try:
        validate_elderly_id(elderly_id)
    except ValueError as error:
        parser.error(str(error))

    def runner():
        return run_scene(
            elderly_id=elderly_id,
            max_rounds=args.max_rounds,
            dialect=args.dialect,
            listen_seconds=args.listen_seconds,
            announce_decisions=args.announce_decisions,
            showcase=args.showcase,
            robot_actions=args.robot_actions,
            confirm_g1_actions=args.confirm_g1_actions,
            robot_leds=args.robot_leds,
            confirm_g1_led_demo=args.confirm_g1_led_demo,
        )

    run_recorded_scene(
        runner,
        record_log=args.record_log,
        elderly_id=elderly_id,
        record_mode=args.record_mode,
        source_scene="care_consultation_support",
        stderr=sys.stderr,
    )


if __name__ == "__main__":
    main()

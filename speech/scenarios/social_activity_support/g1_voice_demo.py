#!/usr/bin/env python3

from __future__ import annotations

import argparse
from contextvars import ContextVar
from functools import wraps
import sys
import time
from pathlib import Path


SCENE_DIR = (
    Path(__file__)
    .resolve()
    .parent
)

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

from activity_controller import (
    ActivityController,
)

from activity_llm_intent import (
    ActivityIntentLLM,
)

from activity_need_integration import (
    ActivityNeedSession,
)


PREPARED_PROMPTS = PreparedPromptCatalog(
    SCENE_DIR / "prepared_prompts.json"
)


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

    record_speech_request("social_activity_support", text, source="speak")
    try:
        result = PREPARED_PROMPTS.play_or_speak(
            speech,
            text,
            style="companion",
            dialect=dialect,
        )
    except BaseException as error:
        record_speech_receipt(
            "social_activity_support",
            text,
            source="speak",
            error=error,
        )
        raise
    record_speech_receipt(
        "social_activity_support",
        text,
        result=result,
        source="speak",
    )

    # 避免 TTS 刚结束就马上开始录音
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
            f"开口后最多 {seconds:.1f} 秒，"
            "静音 1.2 秒结束"
        ),
    )

    result = speech.listen_g1(
        seconds=seconds,
        wait_for_speech=True,
        start_timeout=15.0,
        silence_timeout=1.2,
        speech_rms_threshold=450,
        delete_audio_after_transcribe=True,
    )

    text = str(
        result.get(
            "text",
            ""
        )
    ).strip()

    emotion = result.get(
        "emotion"
    )

    log(
        "ASR",
        text or "(未识别)",
    )

    record_asr(
        "social_activity_support",
        text,
        source="listen",
        result=result,
    )

    if emotion:
        log(
            "情绪",
            str(emotion),
        )

    return text



def describe_activity_query(
    text,
):

    value = str(
        text or ""
    ).replace(
        " ",
        "",
    )

    date_text = ""

    if "明天" in value:
        date_text = "明天"

    elif "今天" in value:
        date_text = "今天"


    period = ""

    if any(
        x in value
        for x in [
            "上午",
            "早上",
            "早晨",
        ]
    ):
        period = "上午"

    elif "下午" in value:
        period = "下午"

    elif any(
        x in value
        for x in [
            "晚上",
            "今晚",
        ]
    ):
        period = "晚上"


    subject = ""

    mappings = [
        (
            [
                "唱歌",
                "合唱",
                "音乐",
            ],
            "唱歌",
        ),
        (
            [
                "聊天",
                "聊聊天",
                "交友",
                "和大家",
            ],
            "社交交流",
        ),
        (
            [
                "健康",
                "讲座",
                "保健",
            ],
            "健康讲座",
        ),
        (
            [
                "电影",
                "观影",
            ],
            "观影",
        ),
        (
            [
                "戏曲",
                "京剧",
                "黄梅戏",
            ],
            "戏曲",
        ),
        (
            ["书法"],
            "书法",
        ),
        (
            [
                "棋牌",
                "象棋",
            ],
            "棋牌",
        ),
        (
            ["手工"],
            "手工",
        ),
        (
            ["茶话会"],
            "茶话会",
        ),
    ]

    for words, label in mappings:

        if any(
            word in value
            for word in words
        ):
            subject = label
            break


    scope = (
        date_text
        + period
    )

    if subject:

        if scope:
            return (
                f"您想查询{scope}的"
                f"{subject}活动。"
            )

        return (
            f"您想查询{subject}活动。"
        )


    if scope:

        return (
            f"您想查询{scope}的活动。"
        )


    return "您有查询社区活动的需求。"


def build_decision_message(
    result,
    user_text,
):

    action = result.get(
        "action"
    )

    selected = result.get(
        "selected"
    )

    name = (
        selected.get(
            "name"
        )
        if selected
        else None
    )


    if action in {
        "recommend",
        "single_result",
    }:
        return describe_activity_query(
            user_text
        )


    if action == "selected":

        if name:
            return (
                f"您选择了{name}活动。"
            )

        return "您已经选择了一个活动。"


    if action == "detail_time":

        if name:
            return (
                f"您正在询问{name}的活动时间。"
            )

        return "您正在询问活动时间。"


    if action == "detail_location":

        if name:
            return (
                f"您正在询问{name}的活动地点。"
            )

        return "您正在询问活动地点。"


    if action == "detail_availability":

        if name:
            return (
                f"您正在询问{name}的参与名额。"
            )

        return "您正在询问活动参与名额。"


    if action == "detail_registration":

        if name:
            return (
                f"您正在询问{name}是否需要报名。"
            )

        return "您正在询问活动报名要求。"


    if action == "confirm_join":

        if name:
            return (
                f"您有参加{name}活动的意愿。"
            )

        return "您有参加活动的意愿。"


    if action == "confirm_waitlist":

        if name:
            return (
                f"您希望参加{name}，"
                "但当前活动已经满员。"
            )

        return (
            "您希望参加该活动，"
            "但当前活动已经满员。"
        )


    if action == "confirm_late_inquiry":

        if name:
            return (
                f"您希望参加{name}，"
                "但当前报名已经截止。"
            )

        return (
            "您希望参加该活动，"
            "但当前报名已经截止。"
        )


    if action == "interest_recorded":

        return (
            "您的活动参与意愿"
            "已经确认并记录。"
        )


    if action == "already_recorded":

        return (
            "您之前已经登记过这个活动。"
        )


    if action == "cancelled":

        return (
            "您选择的活动当前已经取消。"
        )


    if action == "join_cancelled":

        return (
            "您取消了本次活动登记。"
        )


    if action == "end":

        return (
            "您暂时不想继续参加活动。"
        )


    if action == "not_found":

        return (
            "当前没有找到符合条件的活动。"
        )


    return None


_ACTIVE_ACTIVITY_NEED = ContextVar(
    "active_activity_need",
    default=None,
)


def _finalize_activity_need_flow(func):
    """Cancel only an unanswered registration intent on scene exit."""

    @wraps(func)
    def wrapped(*args, **kwargs):
        previous_need = _ACTIVE_ACTIVITY_NEED.get()

        try:
            return func(*args, **kwargs)

        except KeyboardInterrupt:
            needs = _ACTIVE_ACTIVITY_NEED.get()
            if needs is not None:
                needs.close(outcome="scene_interrupted")
            raise

        except Exception:
            needs = _ACTIVE_ACTIVITY_NEED.get()
            if needs is not None:
                needs.close(outcome="scene_interrupted")
            raise

        finally:
            needs = _ACTIVE_ACTIVITY_NEED.get()
            if needs is not None:
                needs.close(outcome="scene_interrupted")
            _ACTIVE_ACTIVITY_NEED.set(previous_need)

    return wrapped


@_finalize_activity_need_flow
def run_scene(
    *,
    elder_id,
    elder_name,
    dialect,
    listen_seconds,
    announce_decisions,
    record_elder_needs=True,
):

    print()
    print(
        "=" * 72
    )
    print(
        "SOCIAL_ACTIVITY_SUPPORT"
        " 社交活动协助"
    )
    print(
        "=" * 72
    )

    print(
        "老人:",
        elder_name,
        f"(ID={elder_id})",
    )

    speech = SpeechClient()

    controller = (
        ActivityController(
            elder_id=elder_id,
            elder_name=elder_name,
        )
    )

    needs = ActivityNeedSession(
        elderly_id=elder_id,
        record=record_elder_needs,
    )
    _ACTIVE_ACTIVITY_NEED.set(needs)
    controller.preference_ranker = needs.rank_recommendations

    try:

        intent_llm = (
            ActivityIntentLLM()
        )

        log(
            "活动意图识别",
            "Qwen LLM",
        )

    except Exception as exc:

        intent_llm = None

        log(
            "活动意图识别",
            "本地规则",
        )

        log(
            "LLM初始化失败",
            repr(exc),
        )

    empty_count = 0

    while controller.active:

        try:

            text = listen(
                speech,
                seconds=listen_seconds,
            )

        except KeyboardInterrupt:

            print()
            print(
                "用户中断场景"
            )
            recording_mark_interrupted()
            break

        except Exception as exc:

            print(
                "语音识别失败:",
                repr(exc),
            )
            recording_mark_failed(exc)

            speak(
                speech,
                "语音识别暂时出现问题，这次活动咨询先结束。",
                dialect=dialect,
            )

            break


        if not text:

            empty_count += 1

            if empty_count == 2:

                speak(
                    speech,
                    (
                        "我没有听清。"
                        "您可以问今天有什么活动，"
                        "或者有没有唱歌、聊天、"
                        "讲座和观影活动。"
                    ),
                    dialect=dialect,
                )

            elif empty_count >= 4:

                speak(
                    speech,
                    (
                        "这次活动咨询先结束。"
                        "需要的时候再叫我。"
                    ),
                    dialect=dialect,
                )

                break

            continue


        empty_count = 0

        # -------------------------------------------------
        # 优先使用 Qwen 理解老人意图。
        #
        # Qwen 不可用、超时、输出异常或置信度过低时，
        # 自动回退到原来的本地 activity_intent.py。
        # -------------------------------------------------

        llm_result = None

        if intent_llm is not None:

            try:

                selected_name = None

                if controller.selected:

                    selected_name = (
                        controller
                        .selected
                        .get(
                            "name"
                        )
                    )


                llm_result = (
                    intent_llm.classify(
                        text,

                        selected_name=
                            selected_name,

                        awaiting_confirmation=
                            controller
                            .awaiting_join_confirmation,

                        pending_join_mode=
                            controller
                            .pending_join_mode,
                    )
                )


                log(
                    "意图来源",
                    "Qwen LLM",
                )

                log(
                    "意图置信度",
                    (
                        f"{llm_result.get('confidence', 0):.2f}"
                    ),
                )

                log(
                    "意图识别耗时",
                    (
                        f"{llm_result.get('llm_ms', 0):.0f} ms"
                    ),
                )

                log(
                    "意图结果",
                    str(
                        {
                            "action":
                                llm_result.get(
                                    "action"
                                ),

                            "date":
                                llm_result.get(
                                    "date"
                                ),

                            "period":
                                llm_result.get(
                                    "period"
                                ),

                            "keyword":
                                llm_result.get(
                                    "keyword"
                                ),
                        }
                    ),
                )


            except Exception as exc:

                log(
                    "LLM意图识别失败",
                    repr(exc),
                )

                llm_result = None


        use_llm = (
            llm_result is not None

            and llm_result.get(
                "action"
            ) != "unknown"

            and llm_result.get(
                "confidence",
                0.0,
            ) >= 0.60
        )


        if use_llm:

            action = (
                llm_result[
                    "action"
                ]
            )

            normalized_text = (
                llm_result.get(
                    "normalized_text"
                )
                or text
            )

            # select / join 需要保留老人原话里的
            # “第一个、第二个、唱歌那个”等选择信息。
            if action in {
                "select",
                "join",
            }:
                action_text = text
            else:
                action_text = normalized_text

            result = (
                controller
                .handle_action(
                    action,
                    action_text,

                    filters_override=(
                        llm_result.get(
                            "filters"
                        )
                        if action == "query"
                        else None
                    ),
                )
            )


        else:

            log(
                "意图来源",
                "本地规则兜底",
            )

            result = (
                controller
                .handle_text(
                    text
                )
            )

        log(
            "动作",
            result[
                "action"
            ],
        )

        # 只记录控制器已经接受的业务动作；ASR 噪声、低置信度
        # 以及无关输入不会进入跨场景需求库。
        needs.record_result(
            raw_text=text,
            result=result,
            controller=controller,
        )

        selected = result.get(
            "selected"
        )

        if selected:

            log(
                "当前活动",
                (
                    f"{selected['name']} "
                    f"{selected['activity_date']} "
                    f"{selected['start_time']}"
                ),
            )


        decision_message = (
            build_decision_message(
                result,
                text,
            )
        )

        if decision_message:

            announce_decision(
                speech,
                decision_message,
                enabled=
                    announce_decisions,
                dialect=dialect,
                prepared_prompts=PREPARED_PROMPTS,
            )


        reply = result.get(
            "reply"
        )

        if reply:

            speak(
                speech,
                reply,
                dialect=dialect,
            )


        if not result.get(
            "active",
            True,
        ):
            break


    print()
    print(
        "SOCIAL_ACTIVITY_SUPPORT 场景结束"
    )


def main():

    parser = (
        argparse.ArgumentParser()
    )

    parser.add_argument(
        "--elder-id",
        "--elderly-id",
        dest="elder_id",
        type=int,
        default=None,
    )

    parser.add_argument(
        "--elder-name",
        default="王大爷",
    )

    parser.add_argument(
        "--dialect",
        default="mandarin",
        choices=[
            "mandarin",
            "shaanxi",
        ],
    )

    # 老人说完整句子需要稍微长一点的录音时间
    parser.add_argument(
        "--listen-seconds",
        type=float,
        default=6.0,
    )

    parser.add_argument(
        "--announce-decisions",
        action="store_true",
        help="播报关键业务判断结果",
    )

    parser.add_argument(
        "--no-need-write",
        action="store_true",
        help="只读取历史活动偏好，不向共享老人需求库写入新记录",
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

    if args.record_log is not None and args.elder_id is None:
        parser.error("--record-log requires explicit --elderly-id")
    elder_id = args.elder_id if args.elder_id is not None else 1
    try:
        validate_elderly_id(elder_id)
    except ValueError as error:
        parser.error(str(error))

    def runner():
        return run_scene(
            elder_id=elder_id,
            elder_name=args.elder_name,
            dialect=args.dialect,
            listen_seconds=args.listen_seconds,
            announce_decisions=args.announce_decisions,
            record_elder_needs=not args.no_need_write,
        )

    run_recorded_scene(
        runner,
        record_log=args.record_log,
        elderly_id=elder_id,
        record_mode=args.record_mode,
        source_scene="social_activity_support",
        stderr=sys.stderr,
    )


if __name__ == "__main__":
    main()

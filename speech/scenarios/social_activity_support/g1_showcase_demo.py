#!/usr/bin/env python3

from __future__ import annotations

import argparse
import sys
import time
from datetime import (
    date,
    timedelta,
)
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
from decision_announcer import (
    announce_decision,
)

from robot_actions import (
    RobotActionClient,
)

from showcase_controller import (
    ShowcaseController,
)

from showcase_activity_matcher import (
    ActivitySemanticMatcher,
)

from showcase_recent_query import (
    RecentActivityQueryResolver,
)

from showcase_intent import (
    SocialActivityIntentLLM,
    classify_showcase_intent,
)

from showcase_protocol import (
    ASK_AVAILABILITY,
    ASK_LOCATION,
    ASK_REGISTRATION,
    ASK_TIME,
    CONFIRM_NO,
    CONFIRM_YES,
    END,
    JOIN,
    OPENING,
    OTHER,
    QUERY,
    REPEAT_DETAILS,
    SELECT,
)

from activity_need_integration import (
    ActivityNeedSession,
)


ANNOUNCER_DIALECT = "mandarin"

PREPARED_PROMPTS = PreparedPromptCatalog(
    SCENE_DIR / "prepared_prompts.json"
)


def log(
    name,
    value="",
):
    if value:
        print(
            f"{name}: {value}",
            flush=True,
        )
    else:
        print(
            name,
            flush=True,
        )


def speak(
    speech,
    text,
    *,
    dialect,
):
    if not text:
        return

    log(
        "机器人",
        text,
    )

    result = PREPARED_PROMPTS.play_or_speak(
        speech,
        text,
        style="companion",
        dialect=dialect,
    )

    log(
        "语音来源",
        result.get("audio_source", "runtime_tts"),
    )

    # 避免机器人刚说完，
    # 麦克风马上把尾音重新录进去。
    time.sleep(
        0.4
    )


def listen_once(
    speech,
    *,
    seconds,
    silence_timeout,
):
    log(
        "等待老人开口",
        (
            f"检测到说话后最多录音 {seconds:.1f} 秒；"
            f"静音 {silence_timeout:.1f} 秒结束"
        ),
    )

    result = (
        speech.listen_g1(
            seconds=seconds,
            wait_for_speech=True,
            silence_timeout=silence_timeout,
            delete_audio_after_transcribe=True,
        )
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

    emotion = (
        result.get(
            "emotion"
        )
    )

    if emotion:
        log(
            "情绪",
            str(
                emotion
            ),
        )

    return text

def preflight_activity_data(
    controller,
):
    """
    只读检查。

    比赛前确保数据库里至少还有今天或明天
    可以查询的活动，避免使用过期的 seed 数据。
    """

    today = (
        date.today()
        .isoformat()
    )

    tomorrow = (
        (
            date.today()
            + timedelta(
                days=1
            )
        )
        .isoformat()
    )

    today_items = (
        controller.repo
        .query_sessions(
            activity_date=today,
            include_cancelled=False,
            limit=50,
        )
    )

    tomorrow_items = (
        controller.repo
        .query_sessions(
            activity_date=tomorrow,
            include_cancelled=False,
            limit=50,
        )
    )

    log(
        "今日可查询活动",
        str(
            len(
                today_items
            )
        ),
    )

    log(
        "明日可查询活动",
        str(
            len(
                tomorrow_items
            )
        ),
    )

    if (
        not today_items
        and not tomorrow_items
    ):
        raise RuntimeError(
            "活动数据库中没有今天或明天的有效活动。"
            "请检查 seed 数据日期。"
        )


def build_decision_message(
    intent,
    result,
):
    selected = (
        result.get(
            "selected"
        )
    )

    selected_name = (
        selected.get(
            "name"
        )
        if selected
        else None
    )

    if intent == QUERY:
        return (
            "您希望查询社区集体活动。"
        )

    if intent == SELECT:
        if selected_name:
            return (
                f"您对{selected_name}"
                "感兴趣。"
            )

        return (
            "您对刚才介绍的一个活动感兴趣。"
        )

    if intent == ASK_TIME:
        return (
            "您正在询问当前活动的时间。"
        )

    if intent == ASK_LOCATION:
        return (
            "您正在询问当前活动的地点。"
        )

    if intent == ASK_AVAILABILITY:
        return (
            "您正在询问当前活动的人数情况。"
        )

    if intent == ASK_REGISTRATION:
        return (
            "您正在询问当前活动是否需要报名。"
        )

    if intent == REPEAT_DETAILS:
        return (
            "您希望再次了解当前活动的信息。"
        )

    if intent == JOIN:
        if selected_name:
            return (
                f"您表示希望参加"
                f"{selected_name}。"
            )

        return (
            "您表示希望参加当前活动。"
        )

    if intent == CONFIRM_YES:
        return (
            "您确认登记参加当前活动。"
        )

    if intent == CONFIRM_NO:
        return (
            "您暂时不登记当前活动。"
        )

    if intent == END:
        return (
            "您希望结束这次活动咨询。"
        )

    return None


def run_scene(
    *,
    elder_id,
    elder_name,
    dialect,
    listen_seconds,
    silence_timeout,
    state_timeout,
    announce_decisions,
    no_llm,
    robot_actions,
    confirm_g1_actions,
    record_elder_needs=False,
):
    print()
    print(
        "=" * 72
    )
    print(
        "SOCIAL_ACTIVITY_SUPPORT"
        " 社区集体活动比赛演示"
    )
    print(
        "=" * 72
    )

    log(
        "老人",
        (
            f"{elder_name} "
            f"(ID={elder_id})"
        ),
    )

    controller = (
        ShowcaseController(
            elder_id=elder_id,
            elder_name=elder_name,
        )
    )

    # 比赛版默认只读，避免演示录音污染正式需求历史。
    # 明确传入 --record-elder-needs 时才写入。
    needs = ActivityNeedSession(
        elderly_id=elder_id,
        record=record_elder_needs,
    )
    controller.preference_ranker = needs.rank_recommendations

    preflight_activity_data(
        controller
    )

    speech = (
        SpeechClient()
    )

    actions = (
        RobotActionClient(
            mode=robot_actions,
            confirm_writes=
                confirm_g1_actions,
        )
    )

    log(
        "机器人动作",
        robot_actions,
    )

    intent_llm = None

    if not no_llm:
        try:
            intent_llm = (
                SocialActivityIntentLLM()
            )

            log(
                "意图识别",
                "规则 + Qwen fallback",
            )

        except Exception as exc:
            log(
                "Qwen意图识别不可用",
                repr(
                    exc
                ),
            )

            log(
                "意图识别",
                "仅规则",
            )

    else:
        log(
            "意图识别",
            "仅规则",
        )

    # -----------------------------------------------------
    # 增强活动查询：
    # 老人可以使用自然语言询问最近活动，
    # 例如“有没有打牌的”“那唱歌呢”。
    #
    # Qwen 只负责把自然表达匹配到
    # SQLite 中真实存在的活动，
    # 时间、地点、状态仍全部来自数据库。
    # -----------------------------------------------------

    if intent_llm is not None:

        try:

            controller.recent_resolver = (
                RecentActivityQueryResolver(
                    controller.repo,
                    ActivitySemanticMatcher(),
                )
            )

            log(
                "活动语义匹配",
                "Qwen + SQLite候选约束",
            )

        except Exception as exc:

            log(
                "活动语义匹配不可用",
                repr(
                    exc
                ),
            )

            # 不影响原来的今天 / 明天
            # 精确查询流程。
            controller.recent_resolver = None


    log(
        "交互方言",
        dialect,
    )

    log(
        "决策播报方言",
        ANNOUNCER_DIALECT,
    )

    log(
        "初始状态",
        controller.state,
    )

    actions.play(
        "greeting",
        source=(
            "social_activity_support:"
            "opening"
        ),
        blocking=False,
    )

    speak(
        speech,
        OPENING,
        dialect=dialect,
    )

    state_started = (
        time.monotonic()
    )

    try:

        while not (
            controller.done
        ):

            if (
                state_timeout
                > 0
                and (
                    time.monotonic()
                    - state_started
                )
                >= state_timeout
            ):
                log(
                    "状态超时",
                    controller.state,
                )

                speak(
                    speech,
                    (
                        "这次活动咨询先到这里。"
                        "需要的时候您再告诉我。"
                    ),
                    dialect=dialect,
                )

                break

            text = (
                listen_once(
                    speech,
                    seconds=
                        listen_seconds,
                    silence_timeout=
                        silence_timeout,
                )
            )

            # 没听到内容：
            # 比赛版保持安静，继续监听。
            if not text:
                continue

            intent_result = (
                classify_showcase_intent(
                    text,
                    state=
                        controller.state,
                    llm=
                        intent_llm,
                )
            )

            intent = (
                intent_result[
                    "intent"
                ]
            )

            source = (
                intent_result.get(
                    "source",
                    "",
                )
            )

            confidence = float(
                intent_result.get(
                    "confidence",
                    0.0,
                )
                or 0.0
            )

            log(
                "意图",
                (
                    f"{intent} "
                    f"source={source} "
                    f"confidence="
                    f"{confidence:.2f}"
                ),
            )

            llm_ms = (
                intent_result.get(
                    "llm_ms"
                )
            )

            if llm_ms is not None:
                log(
                    "Qwen耗时",
                    f"{llm_ms:.0f} ms",
                )

            # 任何流程外输入：
            # 不说话、不改状态。
            if intent == OTHER:
                log(
                    "流程动作",
                    "ignore",
                )

                log(
                    "当前状态",
                    controller.state,
                )

                continue

            previous_state = (
                controller.state
            )

            result = (
                controller.handle(
                    intent,
                    text,
                )
            )

            action = (
                result.get(
                    "action"
                )
            )

            log(
                "流程动作",
                str(
                    action
                ),
            )

            selected = (
                result.get(
                    "selected"
                )
            )

            if selected:
                log(
                    "当前活动",
                    (
                        f"{selected['name']} | "
                        f"{selected['activity_date']} | "
                        f"{selected['start_time']} | "
                        f"{selected['location']}"
                    ),
                )

            log(
                "下一状态",
                controller.state,
            )

            # controller 二次门禁仍可能拒绝，
            # 被拒绝时必须完全静默。
            if action in {
                "ignore",
                "done",
            }:
                continue

            needs.record_result(
                raw_text=text,
                result=result,
                controller=controller,
            )

            if action == "recommend":
                actions.play(
                    "present",
                    source=(
                        "social_activity_support:"
                        "recommend"
                    ),
                    blocking=False,
                )

            elif action == "end":
                actions.play(
                    "goodbye",
                    source=(
                        "social_activity_support:"
                        "end"
                    ),
                    blocking=False,
                )

            decision_message = (
                build_decision_message(
                    intent,
                    result,
                )
            )

            if decision_message:
                announce_decision(
                    speech,
                    decision_message,
                    enabled=
                        announce_decisions,
                    dialect=
                        ANNOUNCER_DIALECT,
                    prepared_prompts=PREPARED_PROMPTS,
                )

            reply = (
                result.get(
                    "reply"
                )
            )

            if reply:
                speak(
                    speech,
                    reply,
                    dialect=dialect,
                )

            if (
                controller.state
                != previous_state
            ):
                state_started = (
                    time.monotonic()
                )

    except KeyboardInterrupt:
        print()
        log(
            "用户中断场景"
        )

    finally:
        # 语音、动作或数据库读取异常时，也要撤销尚未得到确认的
        # 报名意愿，避免控制台留下永久 in_progress 记录。
        needs.close(outcome="scene_interrupted")

    print()
    log(
        "场景结束",
        controller.state,
    )


def main():
    parser = (
        argparse.ArgumentParser()
    )

    parser.add_argument(
        "--elder-id",
        type=int,
        default=1,
    )

    parser.add_argument(
        "--elder-name",
        default="王大爷",
    )

    parser.add_argument(
        "--dialect",
        default="mandarin",
    )

    parser.add_argument(
        "--listen-seconds",
        type=float,
        default=4.5,
    )

    parser.add_argument(
        "--silence-timeout",
        type=float,
        default=0.5,
        help=(
            "老人说话后的静音结束阈值；"
            "默认 0.5 秒"
        ),
    )

    parser.add_argument(
        "--state-timeout",
        type=float,
        default=0.0,
        help=(
            "单状态最大等待秒数；"
            "0 表示不自动超时"
        ),
    )

    parser.add_argument(
        "--announce-decisions",
        action="store_true",
    )

    parser.add_argument(
        "--no-llm",
        action="store_true",
    )

    parser.add_argument(
        "--record-elder-needs",
        action="store_true",
        help="明确允许比赛展示版写入共享老人需求库",
    )

    parser.add_argument(
        "--robot-actions",
        choices=(
            "off",
            "dry-run",
            "execute",
        ),
        default="dry-run",
        help=(
            "机器人手臂动作模式；"
            "默认 dry-run，不向 G1 写入"
        ),
    )

    parser.add_argument(
        "--confirm-g1-actions",
        action="store_true",
        help=(
            "确认允许执行 G1 手臂动作；"
            "仅与 --robot-actions execute 一起使用"
        ),
    )

    args = (
        parser.parse_args()
    )

    if (
        args.robot_actions
        == "execute"
        and not args.confirm_g1_actions
    ):
        parser.error(
            "--robot-actions execute "
            "requires --confirm-g1-actions"
        )

    if (
        args.confirm_g1_actions
        and args.robot_actions
        != "execute"
    ):
        parser.error(
            "--confirm-g1-actions requires "
            "--robot-actions execute"
        )

    run_scene(
        elder_id=
            args.elder_id,

        elder_name=
            args.elder_name,

        dialect=
            args.dialect,

        listen_seconds=
            args.listen_seconds,

        silence_timeout=
            args.silence_timeout,

        state_timeout=
            args.state_timeout,

        announce_decisions=
            args.announce_decisions,

        no_llm=
            args.no_llm,

        robot_actions=
            args.robot_actions,

        confirm_g1_actions=
            args.confirm_g1_actions,

        record_elder_needs=
            args.record_elder_needs,
    )


if __name__ == "__main__":
    main()

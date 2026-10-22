#!/usr/bin/env python3

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path


SCENE_DIR = Path(__file__).resolve().parent
SPEECH_ROOT = SCENE_DIR.parents[1]

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
    record_receipt,
    record_speech_receipt,
    record_speech_request,
    recording_mark_interrupted,
    run_recorded_scene,
    validate_elderly_id,
)

from g1_audio.g1_live_asr import (
    G1RollingASR,
)

from robot_actions import (
    RobotActionClient,
)

from robot_leds import (
    RobotLedClient,
    add_robot_led_arguments,
    validate_robot_led_arguments,
)

from entertainment_controller import (
    EntertainmentController,
)

from entertainment_intent import (
    classify_command,
)

from entertainment_llm_intent import (
    EntertainmentIntentLLM,
)

from g1_media_player import (
    G1MediaPlayer,
)

from local_media_library import (
    CATEGORY_LABELS,
)

from speech.reply.companion_entertainment import (
    generate_reply,
    append_led_notice,
)


PREPARED_PROMPTS = PreparedPromptCatalog(
    SCENE_DIR / "prepared_prompts.json"
)


PRESENT_LEAD_SECONDS = 1.5


from entertainment_need_integration import EntertainmentNeedSession

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
    """
    娱乐场景统一动作入口。

    动作层只负责非语言表现。
    即使动作请求失败，
    也不能阻断语音、媒体或业务状态。
    """
    try:
        result = actions.play(
            action_name,
            source=source,
            blocking=False,
        )
        record_receipt({'kind':'entertainment_action_return','action':action_name,'source':source,'result':result,'physical_completed':'unknown'})
        return result

    except Exception as exc:
        record_receipt({'kind':'entertainment_action_error','action':action_name,'error':str(exc)[:2000]})
        log(
            "机器人动作异常",
            repr(exc),
        )

        return None


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

    record_speech_request("companion_entertainment", text, source="speak")
    try:
        result = PREPARED_PROMPTS.play_or_speak(
            speech,
            text,
            style="companion",
            dialect=dialect,
        )
    except BaseException as error:
        record_speech_receipt(
            "companion_entertainment",
            text,
            source="speak",
            error=error,
        )
        raise
    record_speech_receipt(
        "companion_entertainment",
        text,
        result=result,
        source="speak",
    )

    time.sleep(0.4)


def listen(
    speech,
    *,
    seconds,
):

    log(
        "正在听",
        f"{seconds:.1f} 秒",
    )

    result = speech.listen_g1(
        seconds=seconds,
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
        "companion_entertainment",
        text,
        source="listen",
        result=result,
    )

    return text


def build_opening_text(
    dialect,
):
    if dialect == "shaanxi":
        return (
            "您好，想听点啥？"
            "您跟我说一声，我给您放。"
        )

    return (
        "您好，您想听音乐、"
        "新闻还是戏曲？"
        "也可以直接告诉我想听什么。"
    )


def build_spoken_reply(
    command,
    result,
    dialect,
):
    """
    Controller负责业务结果，
    这里仅负责把正常版回复变得更适合口语/TTS。
    """

    original = result.get(
        "reply"
    )

    if dialect != "shaanxi":
        return original

    command_action = command.get(
        "action"
    )

    result_action = result.get(
        "action"
    )

    category = (
        command.get(
            "category"
        )
        or result.get(
            "category"
        )
    )

    play_item = result.get(
        "play_item"
    )

    title = (
        play_item.get(
            "title"
        )
        if play_item
        else None
    )

    if result_action == "ask_category":
        return (
            "想听点啥？"
            "音乐、新闻、戏曲都行，"
            "您跟我说一声。"
        )

    if result_action == "play":

        if category == "music":

            if command_action == "next":
                return (
                    "好嘞，给您换一首，"
                    "咱接着听。"
                )

            if (
                command_action == "play_query"
                and title
            ):
                return (
                    f"成，给您找着了，"
                    f"咱就听{title}。"
                )

            return (
                "好嘞，给您放点音乐，"
                "咱慢慢听。"
            )

        if category == "news":
            return (
                "成，咱听听新闻，"
                "看看有啥新消息。"
            )

        if category == "opera":

            if (
                command_action == "play_query"
                and title
            ):
                return (
                    f"好嘞，给您找着了，"
                    f"咱听听{title}。"
                )

            return (
                "好嘞，咱听段戏。"
            )

    if result_action == "not_found":
        return (
            "这个我这儿暂时没有，"
            "咱换个别的听。"
        )

    if result_action == "empty":
        return (
            "这个我这儿暂时没准备好，"
            "咱换个别的听。"
        )

    if result_action == "continue":
        return None

    if result_action == "stop":
        return (
            "好嘞，那咱今儿就先听到这儿。"
            "您啥时候想听了，再叫我就成。"
        )

    return original


def build_decision_message(
    command,
    result,
):

    command_action = command.get(
        "action"
    )

    result_action = result.get(
        "action"
    )

    category = (
        command.get(
            "category"
        )
        or result.get(
            "category"
        )
    )

    label = (
        CATEGORY_LABELS.get(
            category,
            "",
        )
        if category
        else ""
    )

    play_item = result.get(
        "play_item"
    )


    if command_action == "ask_category":

        return (
            "您有娱乐陪伴需求，"
            "但还没有选择音乐、新闻或戏曲。"
        )


    if command_action == "play_category":

        if label:

            return (
                f"您想听{label}。"
            )

        return (
            "您选择了一个娱乐内容类别。"
        )


    if command_action == "play_query":

        if play_item:

            return (
                f"您指定了"
                f"{play_item['title']}。"
            )

        query = command.get(
            "query"
        )

        if query:

            return (
                f"您想播放{query}。"
            )

        return (
            "您指定了想播放的内容。"
        )


    if command_action == "next":

        return (
            "您希望切换当前播放内容。"
        )


    if command_action == "continue":

        return (
            "您希望继续播放同类内容。"
        )


    if command_action == "stop":

        return (
            "您希望停止当前播放。"
        )


    if result_action == "empty":

        if label:

            return (
                f"您想听{label}，"
                "但当前没有准备好相关内容。"
            )

        return (
            "当前类别没有准备好可播放内容。"
        )


    if result_action == "not_found":

        return (
            "本地媒体库中没有匹配到"
            "您指定的内容。"
        )


    return None


def apply_result(
    *,
    speech,
    player,
    command,
    result,
    announce_decisions,
    dialect,
    announcer_dialect="mandarin",
    led_announcement=False,
):

    # 需要切换、停止或开始新内容时，
    # 先停止原来的媒体，避免和语音反馈重叠。
    if result.get(
        "stop_playback"
    ):

        stopped=player.stop()
        record_receipt({'kind':'entertainment_media_stop_return','result':stopped})


    decision_message = (
        build_decision_message(
            command,
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
                announcer_dialect,
            prepared_prompts=PREPARED_PROMPTS,
        )


    reply = generate_reply(
        command,
        result,
        dialect=dialect,
    )

    if result.get("action") == "play" and command.get("action") != "next":
        reply = append_led_notice(
            reply, result.get("category"), enabled=led_announcement,
        )

    if reply:

        speak(
            speech,
            reply,
            dialect=dialect,
        )


    play_item = result.get(
        "play_item"
    )

    if play_item:

        log(
            "播放内容",
            play_item[
                "title"
            ],
        )

        log(
            "播放文件",
            play_item[
                "path"
            ],
        )

        played=player.play(
            play_item[
                "path"
            ]
        )
        record_receipt({'kind':'entertainment_media_start_return','title':play_item['title'],'path':str(play_item['path']),'result':played,'physical_heard':'unknown'})


def run_scene(
    *,
    dialect,
    request_seconds,
    control_seconds,
    announce_decisions,
    robot_actions,
    confirm_g1_actions,
    elderly_id=None,
    record_elder_needs=True,
    robot_leds="off",
    confirm_g1_led_demo=False,
):
    # request_seconds / control_seconds
    # 暂时保留CLI兼容性。
    # 正常版现已统一使用持续滚动ASR。
    del request_seconds
    del control_seconds

    print()
    print(
        "=" * 72
    )
    print(
        "COMPANION_ENTERTAINMENT"
        " 娱乐陪伴"
    )
    print(
        "=" * 72
    )

    speech = SpeechClient()

    controller = (
        EntertainmentController()
    )

    needs = EntertainmentNeedSession(
        elderly_id=elderly_id,
        library=controller.library,
        record=record_elder_needs,
    )

    controller.preferred_item_lookup = needs.preferred_item

    player = G1MediaPlayer()

    actions = RobotActionClient(
        mode=robot_actions,
        confirm_writes=
            confirm_g1_actions,
    )

    log(
        "机器人动作",
        robot_actions,
    )

    leds = RobotLedClient(
        mode=robot_leds,
        confirm_writes=confirm_g1_led_demo,
    )

    log(
        "机器人灯光",
        robot_leds,
    )

    try:

        intent_llm = (
            EntertainmentIntentLLM()
        )

        log(
            "娱乐意图识别",
            "Qwen主识别 + 本地规则故障降级",
        )

    except Exception as exc:

        intent_llm = None

        log(
            "娱乐意图识别",
            "Qwen不可用，使用本地规则故障降级",
        )

        log(
            "初始化原因",
            repr(exc),
        )

    # -----------------------------------------------------
    # 持续ASR
    # -----------------------------------------------------

    def create_live_asr():

        return G1RollingASR(
            speech,
            window_seconds=4.5,
            startup_min_window_seconds=2.0,
            hop_seconds=0.5,
            worker_count=2,
            buffer_seconds=12.0,
            speech_rms_threshold=450,
            min_voiced_seconds=0.12,
        )

    live = None

    # open_palm_invite 动作较长，
    # 整个娱乐场景最多展示一次。
    presented_once = False

    def start_live():

        nonlocal live

        # 每次重新创建实例。
        #
        # 这样不会残留上一轮的result queue，
        # 也不会把机器人刚才自己的TTS结果
        # 留到下一轮业务处理中。
        live = create_live_asr()

        live.start()

        # Background ASR may listen while a media-specific LED stays visible.
        if not player.is_playing():
            leds.show(
                "listening",
                source="companion_entertainment:live_listen",
            )

        log(
            "持续监听",
            (
                "已启动；"
                "启动窗口=2.0→4.5秒，"
                "滚动窗口=4.5秒，"
                "更新步长=0.5秒，"
                "ASR并行=2"
            ),
        )

    def stop_live():

        nonlocal live

        if live is None:
            return

        try:
            live.stop()

        except Exception as exc:

            log(
                "持续监听停止异常",
                repr(exc),
            )

        live = None

    # -----------------------------------------------------
    # 开场
    # -----------------------------------------------------

    trigger_robot_action(
        actions,
        "greeting",
        source=
            "companion_entertainment:opening",
    )

    speak(
        speech,
        build_opening_text(
            dialect
        ),
        dialect=dialect,
    )

    start_live()
    media_led_event = None

    try:

        while controller.active:

            # Release media LED when the bridge finishes naturally.
            if media_led_event and not player.is_playing():
                media_led_event = None
                leds.show(
                    "listening",
                    source="companion_entertainment:media_finished",
                )

            event = live.get_event(
                timeout=0.5
            )

            if event is None:
                continue

            kind = event.get(
                "kind"
            )

            # ---------------------------------------------
            # 麦克风 / ASR异常
            # ---------------------------------------------

            if kind in {
                "snapshot_error",
                "asr_error",
            }:

                log(
                    "实时录音错误",
                    event.get(
                        "error",
                        kind,
                    ),
                )

                continue

            if kind != "transcript":
                continue

            text = str(
                event.get(
                    "text",
                    "",
                )
            ).strip()

            if not text:
                continue

            # 短预热窗口只在老人已经出现停顿后才参与意图判断，
            # 防止长句的前半段被当成完整控制命令。
            if event.get("phase") == "bootstrap":

                trailing_silence = float(
                    (
                        event.get("vad")
                        or {}
                    ).get(
                        "trailing_silence_seconds",
                        0.0,
                    )
                    or 0.0
                )

                if trailing_silence < 0.45:

                    log(
                        "预热识别",
                        "老人可能仍在说话，等待下一窗口",
                    )

                    continue

            record_asr(
                "companion_entertainment",
                text,
                source="rolling_asr",
                result=event,
            )

            # ASR结果在队列里等待业务主循环的时间。
            ready_monotonic = (
                event.get(
                    "ready_monotonic"
                )
            )

            if ready_monotonic is None:
                result_wait_ms = 0.0
            else:
                result_wait_ms = (
                    time.monotonic()
                    - float(
                        ready_monotonic
                    )
                ) * 1000

            log(
                "实时ASR",
                (
                    f"{text} "
                    f"(ASR="
                    f"{event.get('asr_ms', 0):.0f}ms, "
                    f"queue="
                    f"{event.get('queue_ms', 0):.0f}ms, "
                    f"result_wait="
                    f"{result_wait_ms:.0f}ms, "
                    f"asr_total="
                    f"{event.get('total_ms', 0):.0f}ms)"
                ),
            )

            # ---------------------------------------------
            # 本地规则只提前算好，作为Qwen故障时兜底。
            # 正常路径绝不使用规则抢先决定语义。
            # ---------------------------------------------

            rule_command = classify_command(
                text,
                current_category=
                    controller.current_category,
            )

            classify_started = (
                time.perf_counter()
            )

            if intent_llm is not None:

                try:

                    command = (
                        intent_llm.classify(
                            text,
                            current_category=
                                controller.current_category,
                        )
                    )

                    source = "llm"

                except Exception as exc:

                    log(
                        "LLM意图识别失败",
                        repr(exc),
                    )

                    command = rule_command
                    source = "rule_fallback"

            else:

                command = rule_command
                source = "rule_only"

            classify_ms = (
                time.perf_counter()
                - classify_started
            ) * 1000

            confidence = float(
                command.get(
                    "confidence",
                    (
                        1.0
                        if source.startswith(
                            "rule"
                        )
                        else 0.0
                    ),
                )
                or 0.0
            )

            # Qwen低置信度时宁可静默，
            # 不允许猜测控制动作。
            if (
                source == "llm"
                and confidence < 0.82
            ):

                command = {
                    "action": "unknown",
                    "category": None,
                    "query": None,
                    "confidence":
                        confidence,
                }

                source = (
                    "llm_low_confidence"
                )

            log(
                "意图",
                (
                    f"{command.get('action')} "
                    f"source={source} "
                    f"confidence="
                    f"{confidence:.2f} "
                    f"classify="
                    f"{classify_ms:.0f}ms"
                ),
            )

            action = command.get(
                "action",
                "unknown",
            )

            # ---------------------------------------------
            # OTHER / 媒体正文 / ASR幻觉
            #
            # 完全静默，不停媒体，不重启ASR。
            # ---------------------------------------------

            if action == "unknown":

                log(
                    "控制判断",
                    "未知或无关输入，静默忽略",
                )

                continue

            # ---------------------------------------------
            # continue:
            # 正在播放时什么都不切换。
            # ---------------------------------------------

            if (
                action == "continue"
                and player.is_playing()
            ):

                log(
                    "控制判断",
                    "当前内容继续播放",
                )

                continue

            # ---------------------------------------------
            # 明确业务指令
            # ---------------------------------------------

            result = (
                controller
                .handle_command(
                    command
                )
            )

            log(
                "动作",
                result[
                    "action"
                ],
            )

            # Controller仍可能因为参数不完整
            # 返回unknown。
            if (
                result[
                    "action"
                ] == "unknown"
            ):

                log(
                    "控制判断",
                    "无法形成有效动作，静默忽略",
                )

                continue

            # 接下来会执行机器人反馈、动作或媒体控制。
            #
            # 必须先停止持续ASR，
            # 避免机器人TTS以及未来真实手臂动作的
            # 扬声器声 / 机械声重新进入识别链路。
            stop_live()

            leds.show(
                "processing",
                source="companion_entertainment:accepted_command",
            )

            # 有效需求已经通过业务检查，先写共享库，再播报。
            need_id = needs.begin(
                raw_text=text,
                command=command,
                result=result,
            )

            execution_succeeded = False

            try:
                # ---------------------------------------------
                # 非语言动作
                #
                # 动作只跟随已经确定的业务结果，
                # 不参与业务状态判断。
                # ---------------------------------------------

                if (
                    result.get("action")
                    == "play"
                    and result.get(
                        "play_item"
                    )
                    and not presented_once
                ):

                    trigger_robot_action(
                        actions,
                        "present",
                        source=(
                            "companion_entertainment:"
                            "play"
                        ),
                    )

                    # present 录制动作起势较慢。
                    # 先让手臂提前运动一段时间，
                    # 再开始判断播报和机器人回复。
                    time.sleep(
                        PRESENT_LEAD_SECONDS
                    )

                    presented_once = True

                if (
                    result.get("action")
                    == "stop"
                ):

                    trigger_robot_action(
                        actions,
                        "goodbye",
                        source=(
                            "companion_entertainment:"
                            "end"
                        ),
                    )

                apply_result(
                    speech=speech,
                    player=player,
                    command=command,
                    result=result,
                    announce_decisions=
                        announce_decisions,
                    dialect=dialect,
                    led_announcement=(robot_leds == "execute"),
                )

                execution_succeeded = (
                    result.get("action") not in (
                        "empty",
                        "not_found",
                    )
                )

                if result.get("action") == "stop":
                    media_led_event = None
                    leds.show(
                        "farewell",
                        source="companion_entertainment:stop",
                    )
                elif player.is_playing():
                    if result.get("action") == "play":
                        category = result.get("category") or command.get("category")
                        media_led_event = {
                            "music": "media_music",
                            "news": "media_news",
                            "opera": "media_opera",
                        }.get(category)
                    leds.show(
                        media_led_event or "acknowledged",
                        source="companion_entertainment:media_playing",
                    )
                else:
                    media_led_event = None
                    leds.show(
                        "acknowledged",
                        source="companion_entertainment:response",
                    )

            finally:
                # 播放、TTS 或动作发生异常时，不能把需求一直留在
                # in_progress；finish 本身是非阻塞的。
                needs.finish(
                    need_id,
                    succeeded=execution_succeeded,
                )

            if controller.active:

                start_live()

    except KeyboardInterrupt:

        print()

        log(
            "运行状态",
            "用户中断",
        )
        recording_mark_interrupted()

    finally:

        stop_live()

        player.stop()

        leds.show(
            "farewell",
            source="companion_entertainment:scene_end",
        )

    print()

    print(
        "COMPANION_ENTERTAINMENT 场景结束"
    )


def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--dialect",
        default="mandarin",
        choices=[
            "mandarin",
            "shaanxi",
        ],
    )

    parser.add_argument(
        "--request-seconds",
        type=float,
        default=5.0,
        help="首次娱乐需求监听时间",
    )

    parser.add_argument(
        "--control-seconds",
        type=float,
        default=3.0,
        help="播放期间控制指令监听时间",
    )

    parser.add_argument(
        "--announce-decisions",
        action="store_true",
        help="播报关键业务判断结果",
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
            "默认dry-run，不向G1写入"
        ),
    )

    parser.add_argument(
        "--confirm-g1-actions",
        action="store_true",
        help=(
            "仅与 --robot-actions execute "
            "同时使用"
        ),
    )

    add_robot_led_arguments(parser)

    parser.add_argument(
        "--elder-id",
        "--elderly-id",
        dest="elder_id",
        type=int,
        default=None,
        help="共享数据库中的老人ID",
    )

    parser.add_argument(
        "--no-need-write",
        action="store_true",
        help="只读历史需求，不新增正式记录",
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

    if (
        args.robot_actions == "execute"
        and not args.confirm_g1_actions
    ):
        parser.error(
            "--robot-actions execute "
            "requires --confirm-g1-actions"
        )

    if (
        args.confirm_g1_actions
        and args.robot_actions != "execute"
    ):
        parser.error(
            "--confirm-g1-actions requires "
            "--robot-actions execute"
        )

    validate_robot_led_arguments(parser, args)


    if args.record_log is not None and args.elder_id is None:
        parser.error("--record-log requires explicit --elderly-id")
    elderly_id = args.elder_id if args.elder_id is not None else 1
    try:
        validate_elderly_id(elderly_id)
    except ValueError as error:
        parser.error(str(error))

    def runner():
        return run_scene(
            elderly_id=elderly_id,
            record_elder_needs=not args.no_need_write,
            dialect=args.dialect,
            request_seconds=args.request_seconds,
            control_seconds=args.control_seconds,
            announce_decisions=args.announce_decisions,
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
        source_scene="companion_entertainment",
        stderr=sys.stderr,
    )


if __name__ == "__main__":
    main()

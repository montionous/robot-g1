#!/usr/bin/env python3

from __future__ import annotations

import argparse
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


from decision_announcer import (
    announce_decision,
)

from speech_client import (
    SpeechClient,
)

from speech.prepared_audio import (
    PreparedPromptCatalog,
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

from demo_controller import (
    ShowcaseController,
)

from demo_intent import (
    ShowcaseIntentLLM,
    classify_showcase_intent,
)

from demo_protocol import (
    ANNOUNCER_DIALECT,
    DECISION_MESSAGES,
    END,
    INTERACTION_DIALECT,
    INTERACTION_REPLIES,
    NEXT_MUSIC,
    OTHER,
    PLAY_MUSIC,
    SWITCH_NEWS,
    SWITCH_OPERA,
    TIMEOUT_REPLY,
    OPENING,
)

from entertainment_controller import (
    EntertainmentController,
)

from g1_media_player import (
    G1MediaPlayer,
)

from speech.reply.companion_entertainment import (
    generate_reply,
    append_led_notice as append_category_led_notice,
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
            f"{name}: {value}",
            flush=True,
        )
    else:
        print(
            name,
            flush=True,
        )


def trigger_robot_action(
    actions,
    action_name,
    *,
    source,
):
    """
    展示版统一动作入口。

    动作只负责非语言表现。
    动作失败不得影响原展示流程。
    """
    try:
        return actions.play(
            action_name,
            source=source,
            blocking=False,
        )

    except Exception as exc:
        log(
            "机器人动作异常",
            repr(exc),
        )

        return None


def speak_interaction(
    speech,
    text,
):
    log(
        "机器人",
        text,
    )

    result = PREPARED_PROMPTS.play_or_speak(
        speech,
        text,
        style="companion",
        dialect=
            INTERACTION_DIALECT,
    )

    log(
        "语音来源",
        result.get(
            "audio_source",
            "runtime_tts",
        ),
    )

    time.sleep(0.4)


def listen_once(
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

    return text


def looks_like_live_control_candidate(
    text,
    state,
):
    """
    实时ASR会同时听到老人和媒体。

    这里只做非常宽松的候选过滤，
    最终意图仍然由规则 + Qwen + 状态机决定。
    """

    value = (
        str(text or "")
        .strip()
        .lower()
        .replace(" ", "")
    )

    if not value:
        return False

    # 实机测试中媒体容易产生这些短幻觉。
    obvious_noise = {
        "hmm.",
        "hmm",
        "oh.",
        "oh",
        "good.",
        "good",
        "good.good.",
        "thankyou.",
        "thankyou",
        "嗯。",
        "嗯",
        "嗯嗯。",
        "嗯嗯",
        "嗯嗯嗯嗯。",
        "嗯嗯嗯嗯",
    }

    if value in obvious_noise:
        return False

    # 任意阶段都可以主动结束。
    end_hints = (
        "不想听",
        "不想再听",
        "不听",
        "别放",
        "停一下",
        "停了",
        "停止",
        "关掉",
        "结束",
        "算了",
        "行了",
        "够了",
        "先这样",
        "可以了",
    )

    if any(
        hint in value
        for hint in end_hints
    ):
        return True

    # 当前比赛流程是固定状态机。
    # 候选过滤也跟随当前状态，
    # 避免把所有歌词/新闻正文都送给LLM。
    hints_by_state = {
        "wait_music_request": (
            "音乐",
            "歌曲",
            "歌",
            "听点",
            "放点",
            "来点",
        ),

        "playing_music_first": (
            "换",
            "下一",
            "下一个",
            "下一首",
            "另一",
            "别的",
            "不好听",
            "来一首",
        ),

        "playing_music_second": (
            "新闻",
            "消息",
            "时事",
            "今天有什么",
            "今天都",
            "发生了什么",
            "新消息",
        ),

        "playing_news": (
            "戏曲",
            "唱戏",
            "听戏",
            "戏",
        ),

        "playing_opera": (
            "不听",
            "停止",
            "停",
            "结束",
            "算了",
        ),
    }

    hints = hints_by_state.get(
        state,
        (),
    )

    return any(
        hint in value
        for hint in hints
    )


def start_live_asr(
    speech,
    *,
    window_seconds,
):
    startup_window = min(
        2.0,
        float(window_seconds),
    )

    live = G1RollingASR(
        speech,

        # 这是滚动窗口长度，
        # 不是“等这么久才听一次”。
        window_seconds=
            window_seconds,

        # 首句不再强制等满4.5秒：同一条持续PCM缓冲会依次
        # 生成 2.0、2.5……秒的预热窗口，之后仍是完整滑动窗。
        startup_min_window_seconds=
            startup_window,

        # 每0.5秒产生一个新的4.5秒完整窗口。
        hop_seconds=0.5,

        # 两个ASR worker并行处理，
        # 避免0.5秒窗口产生速度超过识别速度。
        worker_count=2,

        # 静音和短促噪声不送云端；媒体声与老人声仍由下面的
        # 状态机和意图候选过滤区分。
        speech_rms_threshold=450,
        min_voiced_seconds=0.12,

        buffer_seconds=max(
            10.0,
            window_seconds + 4.0,
        ),
    )

    live.start()

    log(
        "持续监听",
        (
            "已启动；"
            f"启动窗口={startup_window:.1f}"
            f"→{window_seconds:.1f}秒，"
            f"滚动窗口={window_seconds:.1f}秒，"
            "更新步长=0.5秒，"
            "ASR并行=2"
        ),
    )

    return live


def preflight_media(
    entertainment,
):
    music = (
        entertainment.library
        .list_items(
            "music"
        )
    )

    news = (
        entertainment.library
        .list_items(
            "news"
        )
    )

    opera = (
        entertainment.library
        .list_items(
            "opera"
        )
    )

    log(
        "音乐数量",
        len(music),
    )

    log(
        "新闻数量",
        len(news),
    )

    log(
        "戏曲数量",
        len(opera),
    )

    if len(music) < 2:
        raise RuntimeError(
            "比赛展示至少需要两首音乐"
        )

    if not news:
        raise RuntimeError(
            "比赛展示至少需要一条新闻"
        )

    if not opera:
        raise RuntimeError(
            "比赛展示至少需要一段戏曲"
        )


def announce(
    speech,
    intent,
    *,
    enabled,
):
    message = (
        DECISION_MESSAGES
        .get(
            intent
        )
    )

    if not message:
        return

    announce_decision(
        speech,
        message,
        enabled=enabled,
        dialect=
            ANNOUNCER_DIALECT,
        prepared_prompts=PREPARED_PROMPTS,
    )


def append_led_notice(reply, intent, *, enabled):
    """在真实灯光模式下，把主动调灯说明融入原回复。"""
    category = {PLAY_MUSIC: "music", SWITCH_NEWS: "news", SWITCH_OPERA: "opera"}.get(intent)
    return append_category_led_notice(reply, category, enabled=enabled)


def start_media_result(
    *,
    speech,
    player,
    intent,
    result,
    announce_decisions,
    led_announcement=False,
):
    # 切换内容时，
    # 先关闭旧媒体。
    if result.get(
        "stop_playback"
    ):
        player.stop()

    announce(
        speech,
        intent,
        enabled=
            announce_decisions,
    )

    reply_command = {
        PLAY_MUSIC: {
            "action": "play_category",
            "category": "music",
        },

        NEXT_MUSIC: {
            "action": "next",
            "category": "music",
        },

        SWITCH_NEWS: {
            "action": "play_category",
            "category": "news",
        },

        SWITCH_OPERA: {
            "action": "play_category",
            "category": "opera",
        },
    }.get(
        intent,
    )


    reply = None

    if reply_command:
        reply = generate_reply(
            reply_command,
            result,
            dialect=INTERACTION_DIALECT,
        )

    if reply is None:
        reply = INTERACTION_REPLIES.get(
            intent
        )

    # 仅在成功播放时补充主动灯光说明。
    if result.get("action") == "play":
        reply = append_led_notice(
            reply,
            intent,
            enabled=led_announcement,
        )

    if reply:
        speak_interaction(
            speech,
            reply,
        )

    play_item = result.get(
        "play_item"
    )

    if not play_item:
        raise RuntimeError(
            "当前媒体操作没有获得"
            "可播放内容"
        )

    log(
        "播放内容",
        play_item["title"],
    )

    log(
        "播放文件",
        play_item["path"],
    )

    player.play(
        play_item["path"]
    )


def execute_action(
    *,
    action,
    speech,
    entertainment,
    player,
    announce_decisions,
    led_announcement=False,
):
    if action == PLAY_MUSIC:

        result = (
            entertainment
            .handle_command(
                {
                    "action":
                        "play_category",

                    "category":
                        "music",

                    "query":
                        None,
                }
            )
        )

        start_media_result(
            speech=speech,
            player=player,
            intent=PLAY_MUSIC,
            result=result,
            announce_decisions=
                announce_decisions,
            led_announcement=led_announcement,
        )

        return

    if action == NEXT_MUSIC:

        result = (
            entertainment
            .handle_command(
                {
                    "action":
                        "next",

                    "category":
                        "music",

                    "query":
                        None,
                }
            )
        )

        start_media_result(
            speech=speech,
            player=player,
            intent=NEXT_MUSIC,
            result=result,
            announce_decisions=
                announce_decisions,
            led_announcement=led_announcement,
        )

        return

    if action == SWITCH_NEWS:

        result = (
            entertainment
            .handle_command(
                {
                    "action":
                        "play_category",

                    "category":
                        "news",

                    "query":
                        None,
                }
            )
        )

        start_media_result(
            speech=speech,
            player=player,
            intent=SWITCH_NEWS,
            result=result,
            announce_decisions=
                announce_decisions,
            led_announcement=led_announcement,
        )

        return

    if action == SWITCH_OPERA:

        result = (
            entertainment
            .handle_command(
                {
                    "action":
                        "play_category",

                    "category":
                        "opera",

                    "query":
                        None,
                }
            )
        )

        start_media_result(
            speech=speech,
            player=player,
            intent=SWITCH_OPERA,
            result=result,
            announce_decisions=
                announce_decisions,
            led_announcement=led_announcement,
        )

        return

    if action == END:

        player.stop()

        announce(
            speech,
            END,
            enabled=
                announce_decisions,
        )

        end_reply = INTERACTION_REPLIES[END]
        if led_announcement:
            end_reply += " 我把灯光也收一收。"
        speak_interaction(
            speech,
            end_reply,
        )

        return

    raise RuntimeError(
        f"未知展示动作: {action}"
    )


def run_scene(
    *,
    listen_seconds,
    state_timeout,
    announce_decisions,
    use_llm,
    robot_actions,
    confirm_g1_actions,
    elderly_id=None,
    record_elder_needs=True,
    robot_leds="off",
    confirm_g1_led_demo=False,
):
    speech = SpeechClient()

    entertainment = (
        EntertainmentController()
    )

    needs = EntertainmentNeedSession(
        elderly_id=elderly_id,
        library=entertainment.library,
        record=record_elder_needs,
    )

    entertainment.preferred_item_lookup = needs.preferred_item

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

    showcase = (
        ShowcaseController()
    )

    # 展示 / 邀请动作较长，
    # 整个娱乐展示流程只触发一次。
    presented_once = False

    preflight_media(
        entertainment
    )

    intent_llm = None

    if use_llm:
        try:
            intent_llm = (
                ShowcaseIntentLLM()
            )

            log(
                "意图识别",
                "Qwen主识别 + 规则故障降级",
            )

        except Exception as exc:

            log(
                "意图识别",
                (
                    "Qwen不可用，"
                    "仅使用规则: "
                    f"{exc}"
                ),
            )

    else:
        log(
            "意图识别",
            "仅规则",
        )

    log(
        "交互方言",
        INTERACTION_DIALECT,
    )

    log(
        "决策播报方言",
        ANNOUNCER_DIALECT,
    )

    log(
        "初始状态",
        showcase.state,
    )

    trigger_robot_action(
        actions,
        "greeting",
        source=(
            "companion_entertainment_showcase:"
            "opening"
        ),
    )

    opening_reply = OPENING
    if robot_leds == "execute":
        opening_reply += (
            " 您说话时我会亮起倾听灯光，"
            "换节目我也会自己调整。"
        )
    speak_interaction(
        speech,
        opening_reply,
    )

    state_started = (
        time.monotonic()
    )

    # 麦克风持续接收G1 PCM，
    # 实时ASR在后台处理重叠窗口。
    live = start_live_asr(
        speech,
        window_seconds=
            listen_seconds,
    )

    leds.show(
        "listening",
        source="companion_entertainment_showcase:live_listen",
    )
    media_led_event = None

    try:


        while not showcase.done:

            if media_led_event and not player.is_playing():
                media_led_event = None
                leds.show(
                    "listening",
                    source="companion_entertainment_showcase:media_finished",
                )

            if (
                state_timeout > 0
                and
                (
                    time.monotonic()
                    - state_started
                )
                >= state_timeout
            ):
                log(
                    "状态超时",
                    showcase.state,
                )

                live.stop()

                player.stop()

                speak_interaction(
                    speech,
                    TIMEOUT_REPLY,
                )

                leds.show(
                    "farewell",
                    source="companion_entertainment_showcase:timeout",
                )

                break

            event = live.get_event(
                timeout=0.25,
            )

            if event is None:
                continue

            kind = event.get(
                "kind"
            )

            if kind == "asr_error":

                log(
                    "实时ASR错误",
                    event.get(
                        "error",
                        "unknown",
                    ),
                )

                continue

            if kind == "snapshot_error":

                log(
                    "实时录音错误",
                    event.get(
                        "error",
                        "unknown",
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

            # 预热窗口只在老人已经停顿时参与控制判断，避免把
            # 正在说的长句前半段当成完整命令。
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

            # 媒体正文和环境声不进入LLM意图识别，减少误触发。
            if not looks_like_live_control_candidate(
                text,
                showcase.state,
            ):

                log(
                    "控制判断",
                    "不是当前阶段的控制候选，静默忽略",
                )

                continue

            asr_ms = event.get(
                "asr_ms"
            )

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

            if asr_ms is None:

                log(
                    "实时ASR",
                    text,
                )

            else:

                log(
                    "实时ASR",
                    (
                        f"{text} "
                        f"(ASR="
                        f"{float(asr_ms):.0f}ms, "
                        f"queue="
                        f"{float(event.get('queue_ms', 0)):.0f}ms, "
                        f"result_wait="
                        f"{result_wait_ms:.0f}ms, "
                        f"asr_total="
                        f"{float(event.get('total_ms', asr_ms)):.0f}ms)"
                    ),
                )


            classify_started = (
                time.perf_counter()
            )

            classification = (
                classify_showcase_intent(
                    text,
                    state=
                        showcase.state,
                    llm=
                        intent_llm,
                )
            )

            classify_ms = (
                time.perf_counter()
                - classify_started
            ) * 1000

            intent = classification.get(
                "intent",
                OTHER,
            )

            source = classification.get(
                "source",
                "unknown",
            )

            confidence = float(
                classification.get(
                    "confidence",
                    0.0,
                )
            )

            llm_ms = (
                classification.get(
                    "llm_ms"
                )
            )

            pipeline_ms = (
                float(
                    event.get(
                        "total_ms",
                        asr_ms or 0.0,
                    )
                )
                + result_wait_ms
                + classify_ms
            )

            intent_log = (
                f"{intent} "
                f"source={source} "
                f"confidence="
                f"{confidence:.2f} "
                f"classify="
                f"{classify_ms:.0f}ms "
                f"pipeline="
                f"{pipeline_ms:.0f}ms"
            )

            if llm_ms is not None:
                intent_log += (
                    " llm="
                    f"{float(llm_ms):.0f}ms"
                )

            log(
                "意图",
                intent_log,
            )

            transition = (
                showcase.handle(
                    intent
                )
            )

            action = transition.get(
                "action",
                "ignore",
            )

            if action == "ignore":

                log(
                    "流程",
                    (
                        "当前状态不接受"
                        "该输入，静默忽略；"
                        f"state="
                        f"{showcase.state}"
                    ),
                )

                # 不说话
                # 不停媒体
                # 不改变状态
                continue

            # 已确认是一条合法控制。
            # 暂停实时ASR，避免录入接下来的
            # 判断播报和机器人回复。
            live.stop()

            leds.show(
                "processing",
                source="companion_entertainment_showcase:accepted_command",
            )

            # 只发布固定状态机已经接受的有效老人需求。
            # 展示版记录有效老人指令；模拟偏好单独由初始化脚本维护。
            need_command = {
                PLAY_MUSIC: {
                    "action": "play_category",
                    "category": "music",
                },
                NEXT_MUSIC: {
                    "action": "next",
                    "category": "music",
                },
                SWITCH_NEWS: {
                    "action": "play_category",
                    "category": "news",
                },
                SWITCH_OPERA: {
                    "action": "play_category",
                    "category": "opera",
                },
                END: {
                    "action": "stop",
                    "category": None,
                },
            }.get(action)

            need_id = needs.begin(
                raw_text=text,
                command=need_command,
                result={
                    "action": "stop" if action == END else "play",
                    "category": (
                        need_command.get("category")
                        if need_command
                        else None
                    ),
                },
            )

            log(
                "流程动作",
                action,
            )

            log(
                "下一状态",
                showcase.state,
            )

            execution_succeeded = False

            try:
                # ---------------------------------------------
                # 非语言动作
                #
                # 只有状态机已经确认的合法动作
                # 才允许触发手势。
                # ---------------------------------------------

                if (
                    action == PLAY_MUSIC
                    and not presented_once
                ):

                    trigger_robot_action(
                        actions,
                        "present",
                        source=(
                            "companion_entertainment_showcase:"
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

                if action == END:

                    trigger_robot_action(
                        actions,
                        "goodbye",
                        source=(
                            "companion_entertainment_showcase:"
                            "end"
                        ),
                    )

                execute_action(
                    action=action,
                    speech=speech,
                    entertainment=
                        entertainment,
                    player=player,
                    announce_decisions=
                        announce_decisions,
                    led_announcement=(robot_leds == "execute"),
                )

                execution_succeeded = True

                if action == END:
                    media_led_event = None
                    leds.show(
                        "farewell",
                        source="companion_entertainment_showcase:end",
                    )
                elif player.is_playing():
                    media_led_event = {
                        PLAY_MUSIC: "media_music",
                        NEXT_MUSIC: "media_music",
                        SWITCH_NEWS: "media_news",
                        SWITCH_OPERA: "media_opera",
                    }.get(action, media_led_event)
                    leds.show(
                        media_led_event or "acknowledged",
                        source="companion_entertainment_showcase:media_playing",
                    )
                else:
                    media_led_event = None
                    leds.show(
                        "acknowledged",
                        source="companion_entertainment_showcase:response",
                    )

            finally:
                needs.finish(
                    need_id,
                    succeeded=execution_succeeded,
                )

            # 新的媒体已经启动以后，
            # 再重新打开持续ASR。
            #
            # END动作已经进入done，
            # 不再继续监听。
            if not showcase.done:

                live = start_live_asr(
                    speech,
                    window_seconds=
                        listen_seconds,
                )

                if not player.is_playing():
                    leds.show(
                        "listening",
                        source="companion_entertainment_showcase:resume_listen",
                    )

            # 只有合法控制真正执行后，
            # 才重置当前阶段的超时计时。
            state_started = (
                time.monotonic()
            )

    except KeyboardInterrupt:
        print()

        log(
            "人工停止"
        )

    finally:

        try:
            live.stop()
        except Exception:
            pass

        player.stop(
            quiet=True
        )

        leds.show(
            "farewell",
            source="companion_entertainment_showcase:scene_end",
        )

    log(
        "COMPANION_ENTERTAINMENT "
        "SHOWCASE 场景结束"
    )


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--listen-seconds",
        type=float,
        default=4.5,
        help=(
            "实时滚动ASR窗口长度；"
            "麦克风本身会持续监听"
        ),
    )

    parser.add_argument(
        "--state-timeout",
        type=float,
        default=60.0,
        help=(
            "单个流程阶段最长等待时间；"
            "0表示不自动超时"
        ),
    )

    parser.add_argument(
        "--announce-decisions",
        action="store_true",
        help=(
            "播报普通话的决策说明"
        ),
    )

    parser.add_argument(
        "--no-llm",
        action="store_true",
        help=(
            "只使用规则意图识别"
        ),
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
        type=int,
        default=1,
        help="当前服务对象档案ID（默认1，为预先绑定，不是身份识别）",
    )

    record_mode = parser.add_mutually_exclusive_group()
    record_mode.add_argument(
        "--record-elder-needs",
        dest="record_elder_needs",
        action="store_true",
        help="兼容旧参数：显式开启写入（演示版目前默认开启）",
    )
    record_mode.add_argument(
        "--no-need-write",
        dest="record_elder_needs",
        action="store_false",
        help="本次演示只读共享库，不记录新需求",
    )
    parser.set_defaults(record_elder_needs=True)

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

    run_scene(
        elderly_id=args.elder_id,
        record_elder_needs=args.record_elder_needs,
        listen_seconds=
            max(
                1.0,
                args.listen_seconds,
            ),

        state_timeout=
            max(
                0.0,
                args.state_timeout,
            ),

        announce_decisions=
            args.announce_decisions,

        use_llm=
            not args.no_llm,

        robot_actions=
            args.robot_actions,

        confirm_g1_actions=
            args.confirm_g1_actions,
        robot_leds=args.robot_leds,
        confirm_g1_led_demo=args.confirm_g1_led_demo,
    )


if __name__ == "__main__":
    main()

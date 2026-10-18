#!/usr/bin/env python3

from __future__ import annotations

import argparse
from contextvars import ContextVar
from functools import wraps
import math
import struct
import subprocess
import sys
import time
import wave
from pathlib import Path


# =========================================================
# 路径
# =========================================================

SCENE_DIR = Path(__file__).resolve().parent
SPEECH_ROOT = SCENE_DIR.parents[1]

sys.path.insert(
    0,
    str(SPEECH_ROOT),
)


from speech_client import SpeechClient
from speech.prepared_audio import PreparedPromptCatalog
from decision_announcer import announce_decision as _announce_decision
from companion_recording import (
    record_asr,
    record_receipt,
    record_speech_receipt,
    record_speech_request,
    run_recorded_scene,
    validate_elderly_id,
)

from call_service import (
    MockCallService,
)

from contact_family_logic import (
    ContactFamilySession,
)

from contact_need_integration import (
    ContactFamilyNeedSession,
)

from call_backend import (
    ContactCallBackend,
)


from phone_binding import (
    binding_summary,
)

from db_access import (
    create_call_log,
    get_elderly,
)


AUDIO_DIR = (
    SCENE_DIR
    / "audio"
)

RINGTONE_PATH = (
    AUDIO_DIR
    / "phone_ringtone.wav"
)

PREPARED_PROMPTS = PreparedPromptCatalog(
    SCENE_DIR / "prepared_prompts.json"
)


def announce_decision(
    speech,
    text,
    *,
    enabled=False,
    dialect="mandarin",
):
    """Use the contact-family prompt catalog for fixed decision notices."""

    return _announce_decision(
        speech,
        text,
        enabled=enabled,
        dialect=dialect,
        prepared_prompts=PREPARED_PROMPTS,
    )


# =========================================================
# 展示
# =========================================================

def banner(text):
    print()
    print("=" * 72)
    print(f"  {text}")
    print("=" * 72)


def stage(
    icon,
    title,
    value="",
):
    # icon 参数保留用于兼容现有代码，
    # SSH终端展示时不输出任何图标。
    if value:
        print(
            f"{title}: {value}"
        )
    else:
        print(
            f"{title}"
        )


# =========================================================
# G1 说
# =========================================================

def say(
    speech: SpeechClient,
    text: str,
    *,
    dialect: str,
    style: str = "companion",
):
    print()

    stage(
        "🤖",
        "G1",
        text,
    )

    record_speech_request("contact_family", text, source="say")
    try:
        result = PREPARED_PROMPTS.play_or_speak(
            speech,
            text,
            style=style,
            dialect=dialect,
        )
    except BaseException as error:
        record_speech_receipt(
            "contact_family",
            text,
            source="say",
            error=error,
        )
        raise
    record_speech_receipt(
        "contact_family",
        text,
        result=result,
        source="say",
    )

    if result.get("tts_total_ms") is not None:
        stage(
            "⏱",
            "TTS耗时",
            f"{result['tts_total_ms']:.0f} ms",
        )

    # 避免刚播完就开始录音，
    # 把扬声器最后一点声音重新录进去。
    time.sleep(0.35)

    return result


# =========================================================
# G1 听
# =========================================================

def listen(
    speech: SpeechClient,
    *,
    seconds: float,
    prompt: str,
):
    print()

    stage(
        "🎤",
        "G1正在听",
        prompt,
    )

    result = speech.listen_g1(
        seconds=seconds,
        # 普通语音指令等待老人开口并在说完后收尾；真实通话的
        # 原始录音链路在下面的 call 流程中保持独立。
        wait_for_speech=True,
        start_timeout=15.0,
        silence_timeout=1.0,
        speech_rms_threshold=450,
        delete_audio_after_transcribe=True,
    )

    text = (
        result
        .get(
            "text",
            "",
        )
        .strip()
    )

    stage(
        "📝",
        "ASR",
        text or "(未识别到文字)",
    )

    if result.get("emotion"):
        stage(
            "🎭",
            "语音情绪",
            (
                f"{result.get('emotion')} / "
                f"{result.get('emotion_zh')}"
            ),
        )

    if result.get("asr_ms") is not None:
        stage(
            "⏱",
            "ASR耗时",
            f"{result['asr_ms']:.0f} ms",
        )

    record_asr(
        "contact_family",
        text,
        source="listen",
        result=result,
    )

    return text


# =========================================================
# 电话铃声
# =========================================================

def create_ringtone():
    if RINGTONE_PATH.exists():
        return

    AUDIO_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    sample_rate = 16000
    duration = 3.0

    samples = []

    for i in range(
        int(sample_rate * duration)
    ):
        t = i / sample_rate

        # 0.8秒响，0.7秒停
        cycle = t % 1.5

        if cycle < 0.8:
            signal = (
                0.30
                * math.sin(
                    2
                    * math.pi
                    * 440
                    * t
                )
                +
                0.20
                * math.sin(
                    2
                    * math.pi
                    * 480
                    * t
                )
            )
        else:
            signal = 0.0

        signal = max(
            -1.0,
            min(
                1.0,
                signal,
            ),
        )

        samples.append(
            int(
                signal
                * 32767
            )
        )

    with wave.open(
        str(RINGTONE_PATH),
        "wb",
    ) as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(
            sample_rate
        )

        f.writeframes(
            b"".join(
                struct.pack(
                    "<h",
                    sample,
                )
                for sample
                in samples
            )
        )


def play_ringtone(
    speech: SpeechClient,
):
    create_ringtone()

    stage(
        "☎️",
        "呼叫状态",
        "正在呼叫……",
    )

    try:
        result = speech.play_g1(
            RINGTONE_PATH
        )
    except BaseException as error:
        record_receipt(
            {
                "kind": "contact_family_ringtone_receipt",
                "status": "unknown",
                "physical_heard": "unknown",
                "error": repr(error),
            }
        )
        raise
    record_receipt(
        {
            "kind": "contact_family_ringtone_receipt",
            "status": result.get("status", "returned") if isinstance(result, dict) else "unknown",
            "physical_heard": "unknown",
            "result": result,
        }
    )


# =========================================================
# 联系人信息
# =========================================================

def mask_phone(phone):
    phone = str(
        phone or ""
    )

    digits = "".join(
        ch
        for ch in phone
        if ch.isdigit()
    )

    if len(digits) >= 7:
        return (
            digits[:3]
            + "****"
            + digits[-4:]
        )

    return "已保存"


# =========================================================
# 未接通后的处理
# =========================================================

def classify_no_answer_action(
    text,
):
    text = (
        str(text)
        .replace(" ", "")
    )

    retry_words = [
        "稍后",
        "等会",
        "等一会",
        "过会",
        "过一会",
        "再联系",
        "再打",
        "一会再",
    ]

    message_words = [
        "留言",
        "留个言",
        "转告",
        "告诉她",
        "告诉他",
        "捎句话",
        "带句话",
    ]

    if any(
        word in text
        for word in message_words
    ):
        return "message"

    if any(
        word in text
        for word in retry_words
    ):
        return "retry"

    return None


def handle_no_answer(
    speech,
    contact,
    *,
    dialect,
    followup_seconds,
):
    relation = contact["relation"]

    say(
        speech,
        (
            f"{relation}暂时没有接通。"
            "您想稍后再联系，还是给家人留个言？"
        ),
        dialect=dialect,
    )

    followup_text = listen(
        speech,
        seconds=followup_seconds,
        prompt=(
            "请说“稍后再联系”"
            "或“给她留言”"
        ),
    )

    action = classify_no_answer_action(
        followup_text
    )

    # -----------------------------------------------------
    # 稍后联系
    # -----------------------------------------------------

    if action == "retry":
        say(
            speech,
            (
                "好的，我已经记录您"
                "稍后再次联系的意向。"
            ),
            dialect=dialect,
        )

        return {
            "status":
                "no_answer_retry_requested",

            "followup_text":
                followup_text,
        }

    # -----------------------------------------------------
    # 留言
    # -----------------------------------------------------

    if action == "message":
        say(
            speech,
            "好的，您想让我转告什么？",
            dialect=dialect,
        )

        message_text = listen(
            speech,
            seconds=6,
            prompt="请说留言内容",
        )

        if message_text:
            stage(
                "💬",
                "留言内容",
                message_text,
            )

            say(
                speech,
                "好的，我已经记下这条留言。",
                dialect=dialect,
            )

            return {
                "status":
                    "no_answer_message_recorded",

                "followup_text":
                    followup_text,

                "message_text":
                    message_text,
            }

        say(
            speech,
            "我没有听清留言内容，先不继续操作。",
            dialect=dialect,
        )

        return {
            "status":
                "no_answer_message_unclear",

            "followup_text":
                followup_text,
        }

    # -----------------------------------------------------
    # 没听懂
    # -----------------------------------------------------

    say(
        speech,
        (
            "好的，我先不继续操作。"
            "需要的时候您再告诉我。"
        ),
        dialect=dialect,
    )

    return {
        "status":
            "no_answer_no_followup",

        "followup_text":
            followup_text,
    }


# =========================================================
# 真实模拟语音通话
# =========================================================

def record_g1_call_audio(
    output_path,
    *,
    seconds,
):
    output_path = Path(
        output_path
    )

    recorder = (
        SPEECH_ROOT
        / "g1_audio"
        / "g1_mic_recorder.py"
    )

    if not recorder.exists():
        raise RuntimeError(
            f"找不到 G1 麦克风录音器: {recorder}"
        )

    command = [
        sys.executable,
        str(recorder),
        "--seconds",
        str(seconds),
        "--output",
        str(output_path),
    ]

    stage(
        "",
        "G1正在听",
        (
            f"通话语音录制 {seconds:.1f} 秒"
        ),
    )

    subprocess.run(
        command,
        check=True,
    )

    if not output_path.exists():
        raise RuntimeError(
            "G1 通话录音文件没有生成"
        )

    return output_path


def run_simple_voice_call(
    speech,
    call_service,
    call,
    *,
    dialect,
    call_rounds,
    elder_turn_seconds,
    family_turn_timeout,
    announce_decisions,
):
    call_id = call["id"]

    last_family_audio_id = 0

    say(
        speech,
        (
            "电话已经接通。"
            "现在可以和您的家人说话了。"
        ),
        dialect=dialect,
    )

    stage(
        "",
        "呼叫状态",
        "真实语音通话已接通",
    )

    for round_index in range(
        1,
        call_rounds + 1,
    ):
        current_call = (
            call_service.get_call(
                call_id
            )
        )

        if (
            current_call["status"]
            != "answered"
        ):
            stage(
                "",
                "呼叫状态",
                current_call["status"],
            )

            return {
                "status":
                    current_call["status"],
            }

        banner(
            (
                "CONTACT FAMILY · VOICE "
                f"{round_index}/{call_rounds}"
            )
        )

        stage(
            "",
            "通话状态",
            "现在请老人讲话",
        )

        elder_wav = Path(
            "/tmp"
        ) / (
            f"g1_call_"
            f"{call_id}_"
            f"{round_index}.wav"
        )

        try:
            record_g1_call_audio(
                elder_wav,
                seconds=
                    elder_turn_seconds,
            )

            message = (
                call_service
                .upload_elderly_audio(
                    call_id,
                    elder_wav,
                )
            )
            record_receipt({'kind':'contact_audio_upload_return','call_id':str(call_id),'round_no':round_index,'audio_id':str(message['id']),'content_transcription':'not_available'})

            stage(
                "",
                "通话状态",
                (
                    "老人语音已发送到手机 "
                    f"audio_id={message['id']}"
                ),
            )

        finally:
            try:
                elder_wav.unlink()
            except FileNotFoundError:
                pass

        stage(
            "",
            "通话状态",
            "等待家属手机端回复",
        )

        family_result = (
            call_service
            .wait_for_family_audio(
                call_id,
                after=
                    last_family_audio_id,
                timeout=
                    family_turn_timeout,
            )
        )

        family_status = (
            family_result[
                "status"
            ]
        )
        record_receipt({'kind':'contact_family_audio_response','call_id':str(call_id),'round_no':round_index,'status':family_status})

        if family_status == "completed":
            stage(
                "",
                "呼叫状态",
                "家属已挂断",
            )

            return {
                "status":
                    "completed",
            }

        if family_status != "audio":
            stage(
                "",
                "通话状态",
                (
                    "没有收到家属语音，状态="
                    f"{family_status}"
                ),
            )

            try:
                call_service.hangup(
                    call_id
                )
            except Exception:
                pass

            say(
                speech,
                (
                    "暂时没有收到家人的回应，"
                    "本次通话先结束。"
                ),
                dialect=dialect,
            )

            return {
                "status":
                    "completed",
            }

        family_message = (
            family_result[
                "message"
            ]
        )

        last_family_audio_id = (
            family_message[
                "id"
            ]
        )

        family_wav = (
            call_service
            .download_audio(
                family_message
            )
        )

        try:
            stage(
                "",
                "通话状态",
                (
                    "正在通过 G1 播放家属原声 "
                    f"audio_id={last_family_audio_id}"
                ),
            )

            playback=speech.play_g1(
                family_wav
            )
            record_receipt({'kind':'contact_family_audio_playback_return','call_id':str(call_id),'round_no':round_index,'audio_id':str(last_family_audio_id),'result':playback,'physical_heard':'unknown','content_transcription':'not_available'})

            time.sleep(
                0.35
            )

        finally:
            try:
                family_wav.unlink()
            except FileNotFoundError:
                pass

    stage(
        "",
        "呼叫状态",
        "已完成预设通话轮次",
    )

    try:
        call_service.hangup(
            call_id
        )
    except Exception:
        pass

    say(
        speech,
        "好的，本次通话先到这里。",
        dialect=dialect,
    )

    return {
        "status":
            "completed",
    }


def perform_mock_call(
    speech,
    elderly,
    contact,
    *,
    dialect,
    followup_seconds,
    call_timeout,
    call_rounds,
    elder_turn_seconds,
    family_turn_timeout,
):
    relation = contact["relation"]

    call_service = MockCallService()

    health = call_service.health()

    stage(
        "",
        "Mock Call Server",
        health.get(
            "service",
            "online",
        ),
    )

    say(
        speech,
        (
            f"好的，正在为您联系"
            f"{relation}。"
        ),
        dialect=dialect,
    )

    banner(
        "CONTACT FAMILY · CALL"
    )

    stage(
        "",
        "联系人",
        (
            f"{relation} / "
            f"{contact['name']}"
        ),
    )

    stage(
        "",
        "号码",
        mask_phone(
            contact["phone"]
        ),
    )

    stage(
        "",
        "授权状态",
        "已授权",
    )

    call = call_service.start_call(
        elderly_id=
            elderly["id"],

        elderly_name=
            elderly["name"],

        contact_id=
            contact["id"],

        contact_name=
            contact["name"],

        relation=
            relation,

        phone_masked=
            mask_phone(
                contact["phone"]
            ),
    )

    stage(
        "",
        "呼叫状态",
        (
            "手机端已收到模拟来电 "
            f"call_id={call['id']}"
        ),
    )

    play_ringtone(
        speech
    )

    result = (
        call_service
        .wait_for_answer(
            call["id"],
            timeout=
                call_timeout,
        )
    )

    status = result[
        "status"
    ]

    stage(
        "",
        "呼叫状态",
        status,
    )

    if status == "answered":
        return run_simple_voice_call(
            speech,
            call_service,
            result,
            dialect=dialect,
            call_rounds=
                call_rounds,
            elder_turn_seconds=
                elder_turn_seconds,
            family_turn_timeout=
                family_turn_timeout,
            announce_decisions=False,
        )

    if status == "rejected":
        say(
            speech,
            (
                f"{relation}暂时不方便接听。"
            ),
            dialect=dialect,
        )

        return {
            "status":
                "rejected",
        }

    if status == "completed":
        return {
            "status":
                "completed",
        }

    return handle_no_answer(
        speech,
        contact,
        dialect=dialect,
        followup_seconds=
            followup_seconds,
    )


# =========================================================
# 场景主流程
# =========================================================



_ACTIVE_CONTACT_NEED = ContextVar(
    "active_contact_need",
    default=None,
)


def _finalize_contact_need_flow(func):
    """Close only a request left unfinished by this scene invocation."""

    @wraps(func)
    def wrapped(*args, **kwargs):
        previous_need = _ACTIVE_CONTACT_NEED.get()

        try:
            return func(*args, **kwargs)

        except KeyboardInterrupt:
            needs = _ACTIVE_CONTACT_NEED.get()
            if needs is not None:
                needs.close(outcome="scene_interrupted")
            raise

        except Exception:
            needs = _ACTIVE_CONTACT_NEED.get()
            if needs is not None:
                # 错误详情不进入共享需求库；只保留受控的高层结果。
                needs.finish(
                    status="failed",
                    outcome="scene_failed",
                )
            raise

        finally:
            needs = _ACTIVE_CONTACT_NEED.get()
            if needs is not None:
                needs.close(outcome="scene_interrupted")
            _ACTIVE_CONTACT_NEED.set(previous_need)

    return wrapped
@_finalize_contact_need_flow
def run_scene(
    *,
    elderly_id,
    dialect,
    announce_decisions,
    call_backend,
    request_seconds,
    target_seconds,
    confirm_seconds,
    followup_seconds,
    call_timeout,
    call_rounds,
    elder_turn_seconds,
    family_turn_timeout,
    record_elder_needs=True,
):
    banner(
        "CONTACT_FAMILY · G1 全语音演示"
    )

    speech = SpeechClient()

    # -----------------------------------------------------
    # 服务健康检查
    # -----------------------------------------------------

    health = speech.health()

    stage(
        "🟢",
        "Speech Server",
        health.get(
            "service",
            "online",
        ),
    )

    stage(
        "🟢",
        "G1 PCM Bridge",
        str(
            speech.g1_pcm_bridge
        ),
    )

    # -----------------------------------------------------
    # 当前老人
    # -----------------------------------------------------

    elderly = get_elderly(
        elderly_id
    )

    if elderly is None:
        raise RuntimeError(
            f"找不到老人 elderly_id={elderly_id}"
        )

    stage(
        "👴",
        "当前老人",
        (
            f"{elderly['name']} "
            f"(ID={elderly_id})"
        ),
    )

    needs = ContactFamilyNeedSession(
        elderly_id=elderly_id,
        record=record_elder_needs,
    )

    _ACTIVE_CONTACT_NEED.set(needs)

    # -----------------------------------------------------
    # 1. 老人提出联系需求
    # -----------------------------------------------------

    print()
    print(
        "示例说法："
        "“我想和女儿说说话”"
    )

    request_text = listen(
        speech,
        seconds=request_seconds,
        prompt="请提出联系家人的需求",
    )

    if not request_text:
        say(
            speech,
            "抱歉，我没有听清，请稍后再试。",
            dialect=dialect,
        )
        return

    session = ContactFamilySession(
        elderly_id
    )

    result = session.handle_request(
        request_text
    )

    # -----------------------------------------------------
    # 2. 判断 CONTACT_FAMILY
    # -----------------------------------------------------

    if (
        result["state"]
        == "NOT_CONTACT_FAMILY"
    ):
        stage(
            "❌",
            "场景识别",
            "NOT_CONTACT_FAMILY",
        )

        say(
            speech,
            "我目前没有识别到联系家人的需求。",
            dialect=dialect,
        )

        return

    stage(
        "✅",
        "场景识别",
        "CONTACT_FAMILY",
    )

    announce_decision(
        speech,
        "您有联系家人的需求。",
        enabled=
            announce_decisions,
        dialect=dialect,
    )

    # -----------------------------------------------------
    # 3. 没说清楚联系人
    # -----------------------------------------------------

    if (
        result["state"]
        == "CONTACT_NOT_FOUND"
    ):

        announce_decision(
            speech,
            (
                "您有联系家人的需求，"
                "但还没有确定具体联系人。"
            ),
            enabled=
                announce_decisions,
            dialect=dialect,
        )

        say(
            speech,
            result["reply"],
            dialect=dialect,
        )

        target_text = listen(
            speech,
            seconds=target_seconds,
            prompt="请说要联系哪位家人",
        )

        # 原句保留“联系”意图，
        # 第二句补联系人。
        combined_text = (
            request_text
            + " "
            + target_text
        )

        result = session.handle_request(
            combined_text
        )

    # -----------------------------------------------------
    # 4. 联系人仍然不存在
    # -----------------------------------------------------

    if (
        result["state"]
        != "AWAITING_CONFIRMATION"
    ):

        # 已确认“联系家人”的意图，但没有找到授权联系人。
        # 共享记录不写电话号码或后续拨号授权语音。
        needs.begin(
            raw_text=request_text,
            contact=None,
        )
        needs.finish(
            status="failed",
            outcome="contact_not_found",
        )

        announce_decision(
            speech,
            "当前没有匹配到对应的授权联系人。",
            enabled=
                announce_decisions,
            dialect=dialect,
        )

        stage(
            "❌",
            "数据库查询",
            "没有找到匹配的授权联系人",
        )

        say(
            speech,
            (
                "抱歉，我没有找到对应的"
                "授权联系人。"
            ),
            dialect=dialect,
        )

        create_call_log(
            elderly_id=elderly_id,
            contact_id=None,
            recognized_text=request_text,
            requested_relation=None,
            confirmed=False,
            call_status=
                "contact_not_found",
        )

        return

    # -----------------------------------------------------
    # 5. 数据库联系人匹配成功
    # -----------------------------------------------------

    needs.begin(
        raw_text=request_text,
        contact=session.contact,
    )

    stage(
        "🔍",
        "数据库查询",
        "已找到授权联系人",
    )

    stage(
        "👤",
        "联系人",
        (
            f"{result['relation']} / "
            f"{result['contact_name']}"
        ),
    )

    stage(
        "📞",
        "电话",
        result["phone_masked"],
    )

    stage(
        "🔐",
        "授权状态",
        "通过",
    )

    announce_decision(
        speech,
        (
            "已经匹配到授权联系人，"
            f"您想联系的是您的"
            f"{result['relation']}"
            f"{result['contact_name']}。"
        ),
        enabled=
            announce_decisions,
        dialect=dialect,
    )

    # -----------------------------------------------------
    # 6. G1 二次确认
    # -----------------------------------------------------

    say(
        speech,
        result["reply"],
        dialect=dialect,
    )

    confirmation = None
    confirmation_text = ""

    # 最多两次确认机会
    for attempt in range(
        1,
        3,
    ):
        confirmation_text = listen(
            speech,
            seconds=confirm_seconds,
            prompt=(
                "请回答“对 / 是的”"
                "或“算了”"
            ),
        )

        confirm = (
            session
            .handle_confirmation(
                confirmation_text
            )
        )

        confirmation = (
            confirm.get(
                "confirmed"
            )
        )

        if confirmation is not None:
            break

        if attempt < 2:
            say(
                speech,
                confirm["reply"],
                dialect=dialect,
            )

    # -----------------------------------------------------
    # 7. 老人拒绝
    # -----------------------------------------------------

    if confirmation is False:

        needs.finish(
            status="cancelled",
            outcome="contact_confirmation_cancelled",
            contact=session.contact,
        )

        announce_decision(
            speech,
            "您取消了本次联系家人的操作。",
            enabled=
                announce_decisions,
            dialect=dialect,
        )

        stage(
            "🛑",
            "确认结果",
            "老人取消联系",
        )

        say(
            speech,
            confirm["reply"],
            dialect=dialect,
        )

        create_call_log(
            elderly_id=elderly_id,
            contact_id=
                session.contact["id"],
            recognized_text=
                request_text,
            requested_relation=
                session.contact["relation"],
            confirmed=False,
            call_status=
                "cancelled",
        )

        banner(
            "场景结束 · 未拨号"
        )

        return

    # -----------------------------------------------------
    # 8. 两次都没听清
    # -----------------------------------------------------

    if confirmation is not True:

        needs.finish(
            status="failed",
            outcome="contact_confirmation_unclear",
            contact=session.contact,
        )

        announce_decision(
            speech,
            (
                "当前没有获得明确的联系确认，"
                "因此不会执行呼叫。"
            ),
            enabled=
                announce_decisions,
            dialect=dialect,
        )

        stage(
            "⚠️",
            "确认结果",
            "无法获得明确确认",
        )

        say(
            speech,
            (
                "我没有听到明确确认，"
                "所以不会帮您拨打电话。"
            ),
            dialect=dialect,
        )

        create_call_log(
            elderly_id=elderly_id,
            contact_id=
                session.contact["id"],
            recognized_text=
                request_text,
            requested_relation=
                session.contact["relation"],
            confirmed=False,
            call_status=
                "confirmation_unclear",
        )

        banner(
            "场景结束 · 安全终止"
        )

        return

    # -----------------------------------------------------
    # 9. 联系人确认成功
    # -----------------------------------------------------

    stage(
        "",
        "联系人确认",
        "已确认目标联系人",
    )

    announce_decision(
        speech,
        (
            "联系人已经确认。"
            "接下来进行拨号前准备。"
        ),
        enabled=
            announce_decisions,
        dialect=dialect,
    )

    # -----------------------------------------------------
    # 10. 电话准备
    #
    # 当前开发阶段固定使用 safe_stub。
    # 不访问手机、不读取 token、不调用真实拨号脚本。
    # -----------------------------------------------------

    say(
        speech,
        "我先检查一下联系流程是否已经准备好。",
        dialect=dialect,
    )

    backend = ContactCallBackend(
        mode=call_backend
    )

    if call_backend == "real":

        binding = binding_summary(
            session.contact
        )

        stage(
            "",
            "真实电话联系人绑定",
            (
                "通过"
                if binding["available"]
                else binding["reason"]
            ),
        )

        if not binding["available"]:

            needs.finish(
                status="failed",
                outcome="real_phone_binding_blocked",
                contact=session.contact,
            )

            say(
                speech,
                (
                    "当前联系人还没有配置真实电话绑定，"
                    "所以不会发起拨号。"
                ),
                dialect=dialect,
            )

            create_call_log(
                elderly_id=elderly_id,
                contact_id=
                    session.contact["id"],
                recognized_text=
                    request_text,
                requested_relation=
                    session.contact["relation"],
                confirmed=False,
                call_status=
                    "real_phone_binding_blocked",
            )

            return

    phone_prepare = (
        backend.prepare()
    )

    stage(
        "",
        "电话准备",
        phone_prepare[
            "display_state"
        ],
    )

    stage(
        "",
        "真实外拨请求",
        str(
            phone_prepare[
                "external_dial_requested"
            ]
        ),
    )

    if not phone_prepare["ready"]:

        needs.finish(
            status="failed",
            outcome="phone_prepare_failed",
            contact=session.contact,
        )

        announce_decision(
            speech,
            (
                "联系流程当前没有准备完成，"
                "不会继续执行拨号。"
            ),
            enabled=
                announce_decisions,
            dialect=dialect,
        )

        say(
            speech,
            (
                "现在暂时不能继续联系家人，"
                "我们稍后再试。"
            ),
            dialect=dialect,
        )

        create_call_log(
            elderly_id=elderly_id,
            contact_id=
                session.contact["id"],
            recognized_text=
                request_text,
            requested_relation=
                session.contact["relation"],
            confirmed=False,
            call_status=
                "phone_prepare_failed",
        )

        return

    announce_decision(
        speech,
        (
            "联系流程检查完成，"
            "现在进入最终拨号确认。"
        ),
        enabled=
            announce_decisions,
        dialect=dialect,
    )

    # -----------------------------------------------------
    # 11. 最终拨号授权
    # -----------------------------------------------------

    authorization_start = (
        session
        .begin_dial_authorization()
    )

    if not authorization_start["ok"]:
        raise RuntimeError(
            "无法进入最终拨号授权阶段: "
            + str(
                authorization_start
            )
        )

    say(
        speech,
        authorization_start[
            "reply"
        ],
        dialect=dialect,
    )

    dial_authorized = None
    dial_auth = None

    # 最多两次最终授权机会
    for attempt in range(
        1,
        3,
    ):

        dial_text = listen(
            speech,
            seconds=confirm_seconds,
            prompt=(
                "确定拨打请完整说"
                "“确认拨号”；"
                "不拨打请说“取消”"
            ),
        )

        dial_auth = (
            session
            .handle_dial_authorization(
                dial_text
            )
        )

        dial_authorized = (
            dial_auth.get(
                "authorized"
            )
        )

        if dial_authorized is not None:
            break

        if attempt < 2:
            say(
                speech,
                dial_auth["reply"],
                dialect=dialect,
            )

    # -----------------------------------------------------
    # 12A. 最终授权取消
    # -----------------------------------------------------

    if dial_authorized is False:

        needs.finish(
            status="cancelled",
            outcome="dial_authorization_cancelled",
            contact=session.contact,
        )

        stage(
            "",
            "拨号授权",
            "CANCELLED",
        )

        announce_decision(
            speech,
            "最终拨号授权已取消，不会拨打电话。",
            enabled=
                announce_decisions,
            dialect=dialect,
        )

        say(
            speech,
            dial_auth["reply"],
            dialect=dialect,
        )

        create_call_log(
            elderly_id=elderly_id,
            contact_id=
                session.contact["id"],
            recognized_text=
                request_text,
            requested_relation=
                session.contact["relation"],
            confirmed=False,
            call_status=
                "dial_cancelled",
        )

        banner(
            "场景结束 · 未拨号"
        )

        return

    # -----------------------------------------------------
    # 12B. 最终授权仍不明确
    # -----------------------------------------------------

    if dial_authorized is not True:

        needs.finish(
            status="failed",
            outcome="dial_authorization_unclear",
            contact=session.contact,
        )

        stage(
            "",
            "拨号授权",
            "UNCLEAR",
        )

        announce_decision(
            speech,
            (
                "没有获得明确的最终拨号授权，"
                "因此不会执行拨号。"
            ),
            enabled=
                announce_decisions,
            dialect=dialect,
        )

        say(
            speech,
            (
                "我没有听到完整的确认拨号，"
                "所以不会拨打电话。"
            ),
            dialect=dialect,
        )

        create_call_log(
            elderly_id=elderly_id,
            contact_id=
                session.contact["id"],
            recognized_text=
                request_text,
            requested_relation=
                session.contact["relation"],
            confirmed=False,
            call_status=
                "dial_authorization_unclear",
        )

        banner(
            "场景结束 · 安全终止"
        )

        return

    # -----------------------------------------------------
    # 12C. 最终授权通过
    # -----------------------------------------------------

    stage(
        "",
        "拨号授权",
        "DIAL_AUTHORIZED",
    )

    if call_backend == "safe_stub":

        announce_decision(
            speech,
            (
                "最终拨号授权已经通过。"
                "本次处于安全测试模式，"
                "不会发起真实外拨。"
            ),
            enabled=
                announce_decisions,
            dialect=dialect,
        )

    else:

        announce_decision(
            speech,
            (
                "最终拨号授权已经通过，"
                "正在发起联系请求。"
            ),
            enabled=
                announce_decisions,
            dialect=dialect,
        )

    call_result_data = (
        backend.dial()
    )

    # safe_stub 是硬安全边界：
    # 永远不能产生真实外拨。
    if (
        call_backend == "safe_stub"
        and
        call_result_data.get(
            "external_dial_requested"
        )
        is not False
    ):
        raise RuntimeError(
            "安全模式出现真实拨号请求，"
            "立即停止场景"
        )

    stage(
        "",
        "拨号结果",
        call_result_data[
            "display_state"
        ],
    )

    stage(
        "",
        "真实外拨请求",
        str(
            call_result_data[
                "external_dial_requested"
            ]
        ),
    )

    if call_backend == "safe_stub":

        say(
            speech,
            (
                "好的，拨号确认已经完成。"
                "本次是安全测试，"
                "不会真正拨出电话。"
            ),
            dialect=dialect,
        )

        call_status = (
            "dial_authorized_safe_stub"
        )

    else:

        operation_state = (
            call_result_data.get(
                "operation_state"
            )
        )

        if (
            call_result_data.get("ok")
            and
            operation_state == "accepted"
        ):
            say(
                speech,
                (
                    "好的，正在为您联系家人，"
                    "请稍候。"
                ),
                dialect=dialect,
            )

            call_status = "accepted"

        else:
            say(
                speech,
                (
                    "抱歉，这次没有成功发起联系，"
                    "请稍后再试。"
                ),
                dialect=dialect,
            )

            # operation_state 来自外部调用结果，不能把其原文（可能
            # 包含后端诊断或敏感字段）写进场景/共享记录。
            call_status = "dial_failed"

    # 不把最终授权语句写进日志。
    log_text = request_text

    # -----------------------------------------------------
    # 13. 写服务日志
    # -----------------------------------------------------

    log_id = create_call_log(
        elderly_id=elderly_id,
        contact_id=
            session.contact["id"],
        recognized_text=log_text,
        requested_relation=
            session.contact["relation"],
        confirmed=True,
        call_status=
            call_status,
    )

    # “请求已接受”不等于家属已经接通；保留 in_progress 让
    # 工作人员可以从共享需求库继续跟进。safe_stub 同样不能冒充
    # 已完成的真实联络。
    needs.finish(
        status=(
            "in_progress"
            if call_status in {
                "accepted",
                "dial_authorized_safe_stub",
            }
            else "failed"
        ),
        outcome=call_status,
        contact=session.contact,
    )

    stage(
        "💾",
        "服务记录",
        f"log_id={log_id}",
    )

    banner(
        "CONTACT_FAMILY 场景完成"
    )

    print(
        "G1听"
        " → ASR"
        " → CONTACT_FAMILY"
        " → SQLite"
        " → G1确认"
        " → 老人确认"
        " → 呼叫"
        " → 数据库记录"
    )


# =========================================================
# main
# =========================================================

def main():
    parser = argparse.ArgumentParser(
        description=(
            "CONTACT_FAMILY "
            "G1全语音演示"
        )
    )

    parser.add_argument(
        "--elderly-id",
        "--elder-id",
        dest="elderly_id",
        type=int,
        default=None,
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
        "--request-seconds",
        type=float,
        default=5.0,
    )

    parser.add_argument(
        "--target-seconds",
        type=float,
        default=3.0,
    )

    parser.add_argument(
        "--confirm-seconds",
        type=float,
        default=3.0,
    )

    parser.add_argument(
        "--followup-seconds",
        type=float,
        default=4.0,
    )

    parser.add_argument(
        "--call-timeout",
        type=float,
        default=30.0,
        help=(
            "等待家属接听的秒数"
        ),
    )

    parser.add_argument(
        "--call-rounds",
        type=int,
        default=3,
        help=(
            "真实语音通话轮数"
        ),
    )

    parser.add_argument(
        "--elder-turn-seconds",
        type=float,
        default=5.0,
        help=(
            "老人每轮讲话录音秒数"
        ),
    )

    parser.add_argument(
        "--family-turn-timeout",
        type=float,
        default=60.0,
        help=(
            "每轮等待家属发送语音的秒数"
        ),
    )

    # 为旧 run_g1_demo.sh 暂时保留兼容，
    # 但该参数已经完全不会控制呼叫结果。
    parser.add_argument(
        "--call-result",
        choices=[
            "connected",
            "no_answer",
        ],
        default=None,
        help=argparse.SUPPRESS,
    )

    parser.add_argument(
        "--announce-decisions",
        action="store_true",
        help="播报关键业务判断结果",
    )

    parser.add_argument(
        "--no-need-write",
        action="store_true",
        help="不向共享老人需求库写入联系家人需求",
    )

    parser.add_argument(
        "--call-backend",
        choices=[
            "safe_stub",
            "real",
        ],
        default="safe_stub",
        help=(
            "电话后端。默认 safe_stub "
            "绝不真实外拨；"
            "real 才允许使用 Android 电话。"
        ),
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
            dialect=args.dialect,
            request_seconds=args.request_seconds,
            target_seconds=args.target_seconds,
            confirm_seconds=args.confirm_seconds,
            followup_seconds=args.followup_seconds,
            call_timeout=args.call_timeout,
            call_rounds=args.call_rounds,
            elder_turn_seconds=args.elder_turn_seconds,
            family_turn_timeout=args.family_turn_timeout,
            announce_decisions=args.announce_decisions,
            call_backend=args.call_backend,
            record_elder_needs=not args.no_need_write,
        )

    run_recorded_scene(
        runner,
        record_log=args.record_log,
        elderly_id=elderly_id,
        record_mode=args.record_mode,
        source_scene="contact_family",
        stderr=sys.stderr,
    )


if __name__ == "__main__":
    main()

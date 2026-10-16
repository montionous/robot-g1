#!/usr/bin/env python3
"""Turn one emotion strategy event into one bounded G1 companion dialogue."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import json
import math
import os
from pathlib import Path
from queue import Empty, Full, Queue
import re
import subprocess
import sys
import threading
import time
from typing import Any, Callable, TextIO
import wave

import requests

from emotion_interaction import (
    INTERACTIONS,
    _iter_events,
    _validate_event,
)
from scenarios.elder_companion.elder_chat_client import ElderChatClient
from scenarios.elder_companion.end_request import is_explicit_end_request
from speech.presets import STYLE_PRESETS
from speech.tts_cloud import resolve_tts_identity
from speech_client import SpeechClient
from g1_audio.entertainment_interrupt import play_interruptible_wav
from companion_recording import (
    CompanionRecorder,
    RecordingError,
    open_recorder,
    record_console,
    record_receipt,
    recording_context,
    validate_elderly_id,
)


MAX_DIALOGUE_EVENTS = 1
DEFAULT_LISTEN_SECONDS = 20.0
DEFAULT_SILENCE_TIMEOUT = 1.2
CLOSING_REPLIES = {
    "happy": "好的，很高兴和您聊这些开心的事。我们下次再聊。",
    "sad": "好的，今天就聊到这里。您好好休息。",
    "angry": "好的，我先不打扰您了。等您想聊时再叫我。",
}
WATER_NEED_MARKERS = (
    "口渴",
    "渴了",
    "想喝水",
    "喝点水",
    "喝口水",
    "给我水",
    "拿水",
    "一杯水",
)
WATER_DECLINE_MARKERS = (
    "不渴",
    "不用",
    "不需要",
    "不喝水",
    "不要喝水",
    "不想喝水",
    "别给我水",
    "别拿水",
)
WATER_CONFIRMATIONS = (
    "好",
    "好的",
    "好啊",
    "好呀",
    "要",
    "要的",
    "需要",
    "麻烦",
    "麻烦你",
    "行",
    "可以",
)
WATER_CONFIRMATION_SUFFIXES = ("了", "谢谢", "谢谢您", "谢谢你", "麻烦", "麻烦你", "麻烦您")
WATER_CONFIRMATION_PATTERN = re.compile(
    rf"^(?:{'|'.join(map(re.escape, WATER_CONFIRMATIONS))})(?:{'|'.join(map(re.escape, WATER_CONFIRMATION_SUFFIXES))})*$"
)
SAD_HYDRATION_CUES = ("口干", "嘴干", "嗓子干", "喉咙干", "没怎么喝水")
WATER_OFFER = "您需要喝点水吗？"
WATER_ACKNOWLEDGEMENT = "好的，我已经收到您的饮水需求。"
MOTION_OFFERS = {
    "celebrate_once": {
        "action_id": 17,
        "cue": "clap_two_hands",
        "action_zh": "鼓掌",
    },
    "reply_wave_once": {
        "action_id": 25,
        "cue": "wave_open_palm",
        "action_zh": "挥手",
    },
}
MOTION_CONFIRMATIONS = ("好", "好的", "好啊", "好呀", "可以", "行", "愿意", "当然", "没问题", "来吧")
MOTION_CONFIRMATION_SUFFIXES = ("呀", "啊", "的", "了", "谢谢", "请", "您")
MOTION_CONFIRMATION_PATTERN = re.compile(
    rf"^(?:{'|'.join(map(re.escape, MOTION_CONFIRMATIONS))})(?:{'|'.join(map(re.escape, MOTION_CONFIRMATION_SUFFIXES))})*(?:挥手|鼓掌|拍手)?$"
)
MOTION_CONFIRMATION_LEAD = re.compile(r"^(?:嗯+|啊+|哦+|额+|哎+|唔+)")
_MOTION_CONFIRMATION_PREFIXES = tuple(
    sorted(MOTION_CONFIRMATIONS, key=len, reverse=True)
)
MOTION_CONFIRMATION_FILLERS = tuple(
    sorted(
        (
            *MOTION_CONFIRMATIONS,
            *MOTION_CONFIRMATION_SUFFIXES,
            "差不多",
            "吧",
            "嗯",
            "挥手",
            "鼓掌",
            "拍手",
        ),
        key=len,
        reverse=True,
    )
)
MOTION_DECLINE_MARKERS = (
    "不用",
    "不要",
    "不可以",
    "不行",
    "不好",
    "不想",
    "算了",
    "不能",
    "不愿意",
    "不需要",
    "别挥手",
    "别鼓掌",
    "别拍手",
)
MOTION_NON_DECLINE_BEI_WORDS = ("特别", "别人", "别的")
EMOTION_ZH = {"happy": "高兴", "sad": "悲伤", "angry": "生气"}
INFERENCE_ZH = {
    "stable_face": "稳定面部表情",
    "action_face": "动作触发时的当前开心表情",
    "possible": "动作线索（面部未稳定）",
}
EVIDENCE_ZH = {
    "face": "面部表情",
    "behavior": "动作/手势",
    "face_and_behavior": "面部表情+动作/手势",
}
CUE_ZH = {
    "wave_open_palm": "挥手",
    "clap_two_hands": "鼓掌",
    "thumb_up": "点赞",
    "closed_fist": "握拳",
    "rapid_downward_fist_lower_frame": "向下捶",
    "hand_near_eye_head_down": "手靠近眼睛",
    "cover_face_head_down": "捂脸",
}
OPENING_CUE_PRIORITY = (
    "clap_two_hands",
    "wave_open_palm",
    "thumb_up",
    "cover_face_head_down",
    "hand_near_eye_head_down",
    "rapid_downward_fist_lower_frame",
    "closed_fist",
)
SAD_POSTURE_CUE_PRIORITY = (
    "cover_face_head_down",
    "hand_near_eye_head_down",
)
STABLE_FACE_ONLY_OPENING = {
    "happy": "检测到您笑了，看起来非常开心",
    "sad": "看到您好像心情有些低落",
    "angry": "检测到您好像有些生气",
}
HEDGED_EMOTION = {
    "happy": "貌似您很高兴",
    "sad": "貌似您有些难过",
    "angry": "貌似您有些生气",
}
SAD_POSTURE_OPENINGS = {
    "cover_face_head_down": "看到您低着头捂着脸，好像心情有些低落",
    "hand_near_eye_head_down": "看到您低着头、手靠近眼睛，好像心情有些低落",
}
DIALOGUE_OPENING_FOLLOWS = {
    "happy": "有什么开心的事，也跟我分享一下吧。",
    "angry": "如果您愿意，可以跟我说说发生了什么，我在听。",
}
LISTEN_INVITE_PHRASE = "您愿意和我聊一聊吗？"
SAD_DIALOGUE_FOLLOWS = {
    "face": "如果您愿意，可以和我说说发生了什么，我会认真听。",
    "cover_possible": f"{LISTEN_INVITE_PHRASE}我可以陪着您。",
    "cover_stable": "如果您愿意，可以跟我说说，我会认真听。",
    "hand_near_eye": "您愿意的话，可以慢慢跟我说。",
}
DEMO_SCENE_DIALOGUE = "现在演示多轮对话场景"
DEMO_SCENE_MOTION = "现在演示动作交互场景"
DEMO_SCENE_SESSION_EVENT_ID = "session"
DEMO_SCENE_LABELS = {
    "dialogue": "多轮对话",
    "motion": "动作交互",
}
DEMO_SCENE_TEXTS = {
    "dialogue": DEMO_SCENE_DIALOGUE,
    "motion": DEMO_SCENE_MOTION,
}
LISTEN_HOLD_MOTION_ID = "listen_hold"
LISTEN_INVITE_ACTION_NAME = "open_palm_invite"
LISTEN_INVITE_SEQUENCE = "with_detection_opening"
DEFAULT_ELDER_CHAT_URL = "http://127.0.0.1:8810"
PCM_BRIDGE_MIN_TIMEOUT_SECONDS = 20.0
PCM_BRIDGE_RPC_MARGIN_SECONDS = 10.0
PCM_BRIDGE_MAX_TIMEOUT_SECONDS = 20.0 * 60.0
JOKE_TRANSITION_GRACE_SECONDS = 0.25
ELDER_CHAT_SERVICE = "elder-companion-unified"


def _motion_intent(payload: dict[str, Any], interaction: dict[str, Any]) -> tuple[str, str]:
    offer = _motion_offer(payload)
    if offer is not None:
        return offer["motion_id"], offer["cue"]
    return interaction["motion_id"], "emotion_strategy"


def _motion_offer(payload: dict[str, Any]) -> dict[str, Any] | None:
    if payload["emotion"] != "happy":
        return None
    behavior_cues = payload.get("behavior_cues", [])
    for motion_id in ("celebrate_once", "reply_wave_once"):
        offer = MOTION_OFFERS[motion_id]
        if offer["cue"] in behavior_cues:
            return {"motion_id": motion_id, **offer}
    return None


def _first_known_cue(payload: dict[str, Any], priority: tuple[str, ...]) -> str | None:
    cues = payload.get("behavior_cues") or []
    if not isinstance(cues, list):
        return None
    known = {cue for cue in cues if isinstance(cue, str)}
    for cue in priority:
        if cue in known:
            return cue
    return None


def _selected_opening_cue(payload: dict[str, Any]) -> str | None:
    return _first_known_cue(payload, OPENING_CUE_PRIORITY)


def _selected_sad_posture_cue(payload: dict[str, Any]) -> str | None:
    return _first_known_cue(payload, SAD_POSTURE_CUE_PRIORITY)


def _sad_detection_opening(payload: dict[str, Any]) -> str:
    """Companion-tone sad detection. Stable face plus cover is named separately."""
    cue = _selected_sad_posture_cue(payload)
    if cue is None:
        return STABLE_FACE_ONLY_OPENING["sad"]
    if cue == "cover_face_head_down" and payload.get("inference_level") == "stable_face":
        return "看到您好像心情有些低落，并且在捂脸"
    return SAD_POSTURE_OPENINGS[cue]


def _sad_dialogue_follow(payload: dict[str, Any]) -> str:
    """Companionship invite. Distinct from angry's listen-without-provoking follow."""
    cue = _selected_sad_posture_cue(payload)
    if cue == "cover_face_head_down":
        if payload.get("inference_level") == "stable_face":
            return SAD_DIALOGUE_FOLLOWS["cover_stable"]
        return SAD_DIALOGUE_FOLLOWS["cover_possible"]
    if cue == "hand_near_eye_head_down":
        return SAD_DIALOGUE_FOLLOWS["hand_near_eye"]
    return SAD_DIALOGUE_FOLLOWS["face"]


def _detection_opening(payload: dict[str, Any]) -> str:
    """Deterministic detection+emotion opening. Never action-only; never random."""
    emotion = str(payload.get("emotion", ""))
    if emotion == "sad":
        return _sad_detection_opening(payload)
    cue = _selected_opening_cue(payload)
    cue_zh = CUE_ZH[cue] if cue is not None else ""
    hedged = HEDGED_EMOTION.get(emotion, "貌似您情绪有变化")
    if payload.get("inference_level") in {"stable_face", "action_face"}:
        if cue is None:
            return STABLE_FACE_ONLY_OPENING.get(emotion, f"检测到您的表情有变化，{hedged}")
        if emotion == "happy":
            return f"检测到您笑了，并向我{cue_zh}"
        return f"检测到您好像有些生气，并且在{cue_zh}"
    if cue is None:
        return f"检测到一些动作线索，{hedged}"
    return f"检测到您在{cue_zh}，{hedged}"


def _spoken_opening(payload: dict[str, Any], motion_offer: dict[str, Any] | None) -> str:
    opening = _detection_opening(payload)
    if motion_offer is not None:
        return f"{opening.rstrip('。')}。我也想{motion_offer['action_zh']}回应，可以吗？"
    emotion = str(payload.get("emotion", ""))
    if emotion == "sad":
        return f"{opening.rstrip('。')}。{_sad_dialogue_follow(payload)}"
    follow = DIALOGUE_OPENING_FOLLOWS.get(emotion)
    if follow:
        return f"{opening.rstrip('。')}。{follow}"
    return opening


class DialogueError(RuntimeError):
    """Stable error code for the emotion-to-natural-dialogue boundary."""


@dataclass
class DialogueMemory:
    """Lock one dialogue to its opening emotion, except its sad-joke close."""

    initial_emotion: str
    last_companion_action: str | None = None
    announced_transitions: set[tuple[str, str, str | None]] = field(default_factory=set)

    def remember_completed_reply(self, transcript: str, entertainment_kind: str | None = None) -> None:
        self.last_companion_action = "joke" if (
            entertainment_kind == "joke" or (entertainment_kind is None and "笑话" in transcript)
        ) else None

    def observe(self, payload: dict[str, Any]) -> tuple[str, str, str | None] | None:
        if payload.get("inference_level") != "stable_face":
            return None
        next_emotion = str(payload.get("emotion", ""))
        transition = (self.initial_emotion, next_emotion, self.last_companion_action)
        if transition != ("sad", "happy", "joke") or transition in self.announced_transitions:
            return None
        self.announced_transitions.add(transition)
        return transition


def _dialogue_pcm_timeout(audio_path: str) -> float:
    try:
        with wave.open(audio_path, "rb") as audio:
            frame_rate = audio.getframerate()
            byte_rate = frame_rate * audio.getnchannels() * audio.getsampwidth()
            duration = min(
                audio.getnframes() / frame_rate,
                os.path.getsize(audio_path) / byte_rate,
            )
    except (OSError, wave.Error, ZeroDivisionError):
        return PCM_BRIDGE_MIN_TIMEOUT_SECONDS
    if not math.isfinite(duration) or duration < 0.0:
        return PCM_BRIDGE_MIN_TIMEOUT_SECONDS
    return min(
        PCM_BRIDGE_MAX_TIMEOUT_SECONDS,
        max(PCM_BRIDGE_MIN_TIMEOUT_SECONDS, duration + PCM_BRIDGE_RPC_MARGIN_SECONDS),
    )


def _run_dialogue_pcm_bridge(bridge_path: str, audio_path: str) -> dict[str, Any]:
    try:
        result = subprocess.run(
            [bridge_path, "--confirm-g1-companion-pcm", audio_path],
            capture_output=True,
            check=False,
            text=True,
            timeout=_dialogue_pcm_timeout(audio_path),
        )
    except FileNotFoundError as error:
        raise DialogueError("g1_pcm_bridge_not_found") from error
    except subprocess.TimeoutExpired as error:
        raise DialogueError("g1_pcm_bridge_timeout") from error
    if result.returncode != 0:
        raise DialogueError(f"g1_pcm_bridge_failed:exit={result.returncode}")
    try:
        bridge_result = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise DialogueError("g1_pcm_bridge_response_invalid") from error
    if (
        not isinstance(bridge_result, dict)
        or bridge_result.get("kind") != "g1_companion_pcm_bridge"
        or bridge_result.get("status") != "completed"
        or bridge_result.get("wav_path") != audio_path
    ):
        raise DialogueError("g1_pcm_bridge_response_invalid")
    return bridge_result


def _emotion_confidence(payload: dict[str, Any]) -> float | None:
    score = payload.get("match_score")
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        return None
    value = float(score)
    if not math.isfinite(value) or value < 0.0 or value > 1.0:
        return None
    return value


def _visual_context(payload: dict[str, Any]) -> dict[str, Any]:
    context: dict[str, Any] = {}
    for key in ("inference_level", "evidence_source", "behavior_cues"):
        if key in payload:
            context[key] = payload[key]
    return context


def _chat_result_metadata(result: dict[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for key in ("mode", "transfer_to", "caregiver_strategy", "question_opportunity", "reply_action", "chat_wall_ms", "llm_ms"):
        value = result.get(key)
        if value is not None:
            metadata[key] = value
    validation = result.get("reply_validation")
    if isinstance(validation, dict):
        metadata["reply_validation"] = {
            key: validation[key]
            for key in ("validation_ok", "validation_errors", "repair_attempted",
                        "repair_validation_errors", "intent_validation_errors", "normalizations", "final_source")
            if key in validation
        }
    if result.get("should_end"):
        metadata["should_end"] = True
    return metadata


def _require_elder_chat_health(base_url: str, *, timeout: float = 5.0) -> None:
    url = f"{base_url.rstrip('/')}/health"
    try:
        response = requests.get(url, timeout=timeout)
    except requests.RequestException as error:
        raise DialogueError("elder_chat_service_unreachable") from error
    try:
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as error:
        raise DialogueError("elder_chat_service_unhealthy") from error
    if (
        not isinstance(payload, dict)
        or payload.get("ok") is not True
        or payload.get("service") != ELDER_CHAT_SERVICE
    ):
        raise DialogueError("elder_chat_service_unhealthy")


def _elder_chat(
    chat_client: ElderChatClient,
    transcript: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    started_at = time.monotonic()
    try:
        result = chat_client.chat(
            transcript,
            emotion=payload.get("emotion"),
            emotion_confidence=_emotion_confidence(payload),
            visual_context=_visual_context(payload),
            mode_hint="auto",
        )
    except DialogueError:
        raise
    except (requests.RequestException, ValueError, KeyError, TypeError) as error:
        raise DialogueError("elder_chat_request_failed") from error
    if not isinstance(result, dict):
        raise DialogueError("elder_chat_request_failed")
    result["chat_wall_ms"] = (time.monotonic() - started_at) * 1000
    return result


def _elder_visual_transition(
    chat_client: ElderChatClient,
    *,
    from_emotion: str,
    to_emotion: str,
    companion_action: str | None,
    payload: dict[str, Any],
) -> dict[str, Any]:
    try:
        result = chat_client.visual_transition(
            from_emotion=from_emotion,
            to_emotion=to_emotion,
            companion_action=companion_action,
            visual_context=_visual_context(payload),
        )
    except DialogueError:
        raise
    except (requests.RequestException, ValueError, KeyError, TypeError) as error:
        raise DialogueError("elder_visual_transition_request_failed") from error
    if not isinstance(result, dict):
        raise DialogueError("elder_visual_transition_request_failed")
    return result


def _take_visual_transition(
    memory: DialogueMemory,
    visual_updates: Queue[dict[str, Any]] | None,
) -> tuple[dict[str, Any], tuple[str, str, str | None]] | None:
    if visual_updates is None:
        return None
    transition: tuple[dict[str, Any], tuple[str, str, str | None]] | None = None
    while True:
        try:
            payload = (
                visual_updates.get(timeout=JOKE_TRANSITION_GRACE_SECONDS)
                if transition is None and memory.last_companion_action == "joke"
                else visual_updates.get_nowait()
            )
        except Empty:
            return transition
        try:
            _validate_event(payload)
        except (KeyError, TypeError, ValueError):
            continue
        observed = memory.observe(payload)
        if observed is not None:
            transition = (payload, observed)


def _queue_visual_update(visual_updates: Queue[dict[str, Any]], payload: dict[str, Any]) -> None:
    try:
        visual_updates.put_nowait(payload)
    except Full:
        try:
            visual_updates.get_nowait()
        except Empty:
            pass
        visual_updates.put_nowait(payload)


def _forward_visual_updates(events: Any, visual_updates: Queue[dict[str, Any]]) -> None:
    for payload in events:
        _queue_visual_update(visual_updates, payload)


def _voice_options(interaction: dict[str, Any], dialect: str) -> dict[str, Any]:
    options = {
        "style": interaction["style"],
        "emotion": interaction["emotion_style"],
        "dialect": dialect,
        "play_on_host": False,
    }
    for name in ("speed", "volume", "pitch"):
        if name in interaction:
            options[name] = interaction[name]
    return options


def _tts_settings(interaction: dict[str, Any], dialect: str) -> dict[str, Any]:
    options = _voice_options(interaction, dialect)
    preset = STYLE_PRESETS[options["style"]]
    model, voice = resolve_tts_identity()
    return {
        "style": options["style"],
        "dialect": options["dialect"],
        "speed": options.get("speed", preset["speed"]),
        "pitch": options.get("pitch", preset["pitch"]),
        "volume": options.get("volume", preset["volume"]),
        "emotion": options.get("emotion", preset["emotion"]),
        "voice": voice,
        "model": model,
        "play_on_host": options["play_on_host"],
    }


def _speak_on_g1(
    client: SpeechClient,
    text: str,
    interaction: dict[str, Any],
    *,
    bridge_path: str,
    dialect: str,
    play_audio: Callable[[str, str], dict[str, Any]],
    speech_end_monotonic: float | None = None,
) -> dict[str, Any]:
    started_at = time.monotonic()
    response = client.speak(text, cache=True, **_voice_options(interaction, dialect))
    if not isinstance(response, dict) or response.get("ok") is not True:
        raise DialogueError("speech_service_response_invalid")
    audio_path = response.get("audio_path")
    if not isinstance(audio_path, str) or not audio_path:
        raise DialogueError("speech_service_audio_path_invalid")
    playback_started_at = time.monotonic()
    playback = play_audio(bridge_path, audio_path)
    if not isinstance(playback, dict):
        raise DialogueError("g1_pcm_bridge_response_invalid")
    timing = {
        "tts_wall_ms": (playback_started_at - started_at) * 1000,
        "playback_wall_ms": (time.monotonic() - playback_started_at) * 1000,
        "tts_cache_hit": response.get("tts_cache_hit") is True,
    }
    for key in ("tts_api_ms", "tts_download_ms", "tts_total_ms"):
        value = response.get(key)
        if isinstance(value, (int, float)) and math.isfinite(value):
            timing[key] = value
    if speech_end_monotonic is not None:
        # Dispatch is measurable here; actual first sound still requires field observation.
        timing["estimated_speech_end_to_playback_dispatch_ms"] = (playback_started_at - speech_end_monotonic) * 1000
    return {**playback, "speech_timing": timing}


def _playback_metadata(playback: dict[str, Any]) -> dict[str, Any]:
    return {key: playback.get(key) for key in (
        "pcm_bytes", "duration_milliseconds", "speech_timing", "pcm_bytes_sent", "stop_result",
        "interrupt_monitor_error", "app_name", "stream_id", "play_result",
    )}


def _announce_demo_scene(
    client: SpeechClient,
    scene: str,
    interaction: dict[str, Any],
    *,
    event_id: str,
    bridge_path: str,
    dialect: str,
    play_audio: Callable[[str, str], dict[str, Any]],
    output: TextIO,
    console: TextIO,
    round_no: int | None = None,
) -> dict[str, Any]:
    text = DEMO_SCENE_TEXTS[scene]
    playback = _speak_on_g1(
        client,
        text,
        interaction,
        bridge_path=bridge_path,
        dialect=dialect,
        play_audio=play_audio,
    )
    console_payload: dict[str, Any] = {
        "event_id": event_id,
        "scene": scene,
        "text": text,
    }
    if round_no is not None:
        console_payload["round_no"] = round_no
    _console(console, "演示场景", **console_payload)
    record: dict[str, Any] = {
        "kind": "emotion_dialogue_scene_announce",
        "event_id": event_id,
        "scene": scene,
        "text": text,
        "g1_played": True,
        **_playback_metadata(playback),
    }
    if round_no is not None:
        record["round_no"] = round_no
    _emit(output, record)
    return playback


def _is_quiet_request(text: str) -> bool:
    return is_explicit_end_request(text)


def _is_water_need(text: str) -> bool:
    normalized = text.replace(" ", "")
    return not any(marker in normalized for marker in WATER_DECLINE_MARKERS) and any(
        marker in normalized for marker in WATER_NEED_MARKERS
    )


def _is_water_decline(text: str) -> bool:
    normalized = text.replace(" ", "")
    return any(marker in normalized for marker in WATER_DECLINE_MARKERS)


def _normalize_spoken(text: str) -> str:
    return re.sub(r"[\s，。！？、,.!?]", "", text)


def _is_water_confirmation(text: str) -> bool:
    normalized = _normalize_spoken(text)
    return not _is_water_decline(normalized) and bool(
        WATER_CONFIRMATION_PATTERN.fullmatch(normalized)
    )


def _confirmation_rest_is_filler(rest: str) -> bool:
    while rest:
        filler = next(
            (item for item in MOTION_CONFIRMATION_FILLERS if rest.startswith(item)),
            None,
        )
        if filler is None:
            return False
        rest = rest[len(filler) :]
    return True


def _is_motion_confirmation(text: str) -> bool:
    if _is_motion_decline(text):
        return False
    for candidate in (text, re.split(r"[，。！？、,.!?]", text, maxsplit=1)[0]):
        normalized = MOTION_CONFIRMATION_LEAD.sub("", _normalize_spoken(candidate))
        if MOTION_CONFIRMATION_PATTERN.fullmatch(normalized):
            return True
        if any(
            normalized.startswith(prefix)
            and _confirmation_rest_is_filler(normalized[len(prefix) :])
            for prefix in _MOTION_CONFIRMATION_PREFIXES
        ):
            return True
    return False


def _is_motion_decline(text: str) -> bool:
    normalized = _normalize_spoken(text)
    remaining_beis = normalized
    for word in MOTION_NON_DECLINE_BEI_WORDS:
        remaining_beis = remaining_beis.replace(word, "")
    return any(marker in normalized for marker in MOTION_DECLINE_MARKERS) or bool(
        "别" in remaining_beis
    )


def _is_sad_hydration_cue(payload: dict[str, Any], text: str) -> bool:
    return (
        payload["emotion"] == "sad"
        and payload["inference_level"] == "stable_face"
        and any(marker in text.replace(" ", "") for marker in SAD_HYDRATION_CUES)
    )


def _listen_once(
    client: SpeechClient,
    *,
    seconds: float,
    audio_path: Path,
    silence_timeout: float = DEFAULT_SILENCE_TIMEOUT,
    speech_rms_threshold: int = 450,
) -> tuple[str, float | None, dict[str, Any]]:
    started_at = time.monotonic()
    try:
        response = client.listen_g1(
            seconds=seconds, output_path=str(audio_path), wait_for_speech=True,
            silence_timeout=silence_timeout, speech_rms_threshold=speech_rms_threshold,
        )
        if not isinstance(response, dict):
            raise DialogueError("speech_listen_response_invalid")
        text = response.get("text")
        if not isinstance(text, str):
            raise DialogueError("speech_transcript_invalid")
        asr_ms = response.get("asr_ms")
        if not isinstance(asr_ms, (int, float)) or not math.isfinite(asr_ms):
            asr_ms = None
        recording = response.get("recording")
        recording = recording if isinstance(recording, dict) else {}
        timing = {key: recording[key] for key in (
            "recording_wall_ms", "speech_start_offset_ms", "endpoint_reason", "endpoint_delay_ms",
            "speech_end_monotonic", "speech_end_estimated", "speech_detected", "audio_seconds",
        ) if key in recording}
        timing["listen_wall_ms"] = (time.monotonic() - started_at) * 1000
        timing["asr_wall_ms"] = response.get("asr_wall_ms")
        return text.strip(), float(asr_ms) if asr_ms is not None else None, timing
    finally:
        audio_path.unlink(missing_ok=True)


def _emit(output: TextIO, payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), file=output, flush=True)
    record_receipt(payload)


def _cue_zh(cues: Any) -> str:
    if not isinstance(cues, list) or not cues:
        return "无"
    return "、".join(CUE_ZH.get(str(cue), str(cue)) for cue in cues)


def _console_line(stage: str, payload: dict[str, Any]) -> str | None:
    if stage == "检测到情绪策略":
        emotion = EMOTION_ZH.get(str(payload.get("emotion", "")), str(payload.get("emotion", "")))
        inference = INFERENCE_ZH.get(
            str(payload.get("inference_level", "")), str(payload.get("inference_level", ""))
        )
        evidence = EVIDENCE_ZH.get(
            str(payload.get("evidence_source", "")), str(payload.get("evidence_source") or "未标注")
        )
        return (
            f"[现场] 情绪={emotion} 依据={inference} 来源={evidence} "
            f"动作线索={_cue_zh(payload.get('behavior_cues'))} "
            f"分数={payload.get('match_score')} 稳定={payload.get('stability_ratio')} "
            f"策略={payload.get('strategy_id')}"
        )
    if stage == "演示场景":
        label = DEMO_SCENE_LABELS.get(str(payload.get("scene")), str(payload.get("scene")))
        spoken = _console_line("G1开场", payload)
        return f"[现场] 演示场景={label}\n{spoken}"
    if stage in ("G1开场", "G1回复"):
        return f"[现场] G1说：{payload.get('text')}"
    if stage == "动作提议":
        if payload.get("status") == "awaiting_confirmation":
            return (
                f"[现场] 动作提议={payload.get('action_zh')} 官方ID={payload.get('action_id')} "
                "等待口头确认"
            )
        return "[现场] 动作提议=无（本轮不挥手/鼓掌）"
    if stage == "检测到老人说的内容":
        text = payload.get("text") or "（未识别到内容）"
        asr_ms = payload.get("asr_ms")
        asr = f"ASR={asr_ms}ms" if asr_ms is not None else "ASR=未知"
        return f"[现场] 老人说：{text}  {asr} 轮次={payload.get('round_no')}"
    if stage == "对话判定":
        return f"[现场] 判定：{payload.get('decision')}"
    if stage == "情绪转变":
        from_emotion = EMOTION_ZH.get(
            str(payload.get("from_emotion", "")), str(payload.get("from_emotion", ""))
        )
        to_emotion = EMOTION_ZH.get(
            str(payload.get("to_emotion", "")), str(payload.get("to_emotion", ""))
        )
        action = "刚才的笑话" if payload.get("companion_action") == "joke" else "前面的陪伴交流"
        return f"[现场] 情绪转变={from_emotion}→{to_emotion}，由LLM接续{action}"
    if stage == "模型输出":
        extras = []
        if payload.get("mode"):
            extras.append(f"mode={payload.get('mode')}")
        if payload.get("question_opportunity"):
            extras.append(f"轻问机会={payload['question_opportunity']}")
        if payload.get("reply_action"):
            extras.append(f"动作={payload['reply_action']}")
        extra = f"  {' '.join(extras)}" if extras else ""
        return f"[现场] LLM说：{payload.get('text')}{extra}"
    return None


def _console(console: TextIO, stage: str, **payload: Any) -> None:
    record = {"kind": "emotion_dialogue_console", "stage": stage, **payload}
    print(
        json.dumps(
            record,
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        file=console,
        flush=True,
    )
    record_console(record)
    line = _console_line(stage, payload)
    if line:
        print(line, file=console, flush=True)


def _run_dialogue(
    payload: dict[str, Any],
    client: SpeechClient,
    output: TextIO,
    *,
    bridge_path: str,
    audio_dir: Path,
    dialect: str,
    listen_seconds: float,
    silence_timeout: float,
    speech_rms_threshold: int,
    chat_client: ElderChatClient | None,
    play_audio: Callable[[str, str], dict[str, Any]],
    console: TextIO,
    demo_scene: str,
    enable_listen_invite: bool = False,
    enable_entertainment_interrupts: bool = False,
    visual_updates: Queue[dict[str, Any]] | None = None,
) -> str:
    event_id, interaction = _validate_event(payload)
    memory = DialogueMemory(initial_emotion=payload["emotion"])
    current_payload = payload
    strategy = payload["strategy"]
    evidence_source = payload.get("evidence_source")
    behavior_cues = payload.get("behavior_cues", [])
    _console(
        console,
        "检测到情绪策略",
        event_id=event_id,
        source_run_id=payload.get("source_run_id"),
        observed_at=payload.get("observed_at"),
        emotion=payload["emotion"],
        inference_level=payload["inference_level"],
        evidence_source=evidence_source,
        behavior_cues=behavior_cues,
        match_score=payload.get("match_score"),
        stability_ratio=payload.get("stability_ratio"),
        strategy_id=strategy["strategy_id"],
        goal=strategy["goal"],
        tone=strategy["tone"],
        do=strategy["do"],
        avoid=strategy["avoid"],
        tts=_tts_settings(interaction, dialect),
    )
    visual_offer = _motion_offer(payload)
    motion_offer = visual_offer if demo_scene == "motion" else None
    motion_id, motion_trigger = _motion_intent(payload, interaction)
    opening = _spoken_opening(payload, motion_offer)
    phrase_id = (
        f"motion_offer_{motion_offer['motion_id']}"
        if motion_offer is not None
        else "detection_opening"
    )
    if enable_listen_invite and motion_id == LISTEN_HOLD_MOTION_ID:
        _emit(
            output,
            {
                "kind": "emotion_dialogue_custom_action_request",
                "event_id": event_id,
                "status": "confirmed",
                "action_name": LISTEN_INVITE_ACTION_NAME,
                "sequence": LISTEN_INVITE_SEQUENCE,
                "physical_actions_emitted": False,
            },
        )
    opening_playback = _speak_on_g1(
        client,
        opening,
        interaction,
        bridge_path=bridge_path,
        dialect=dialect,
        play_audio=play_audio,
    )
    _console(
        console,
        "G1开场",
        event_id=event_id,
        phrase_id=phrase_id,
        text=opening,
    )
    _emit(
        output,
        {
            "kind": "emotion_dialogue_opening",
            "event_id": event_id,
            "phrase_id": phrase_id,
            "inference_level": payload["inference_level"],
            "style": interaction["style"],
            "dialect": dialect,
            "status": "completed",
            "g1_played": True,
            **_playback_metadata(opening_playback),
        },
    )
    _emit(
        output,
        {
            "kind": "emotion_dialogue_motion_intent",
            "event_id": event_id,
            "strategy_id": strategy["strategy_id"],
            "motion_id": motion_id,
            "trigger": motion_trigger,
            "status": "awaiting_confirmation" if motion_offer is not None else "not_applicable",
            "execution": "intent_only",
            "physical_actions_emitted": False,
        },
    )
    _console(
        console,
        "动作提议",
        event_id=event_id,
        motion_id=motion_id,
        trigger=motion_trigger,
        status="awaiting_confirmation" if motion_offer is not None else "not_applicable",
        action_id=None if motion_offer is None else motion_offer["action_id"],
        action_zh=None if motion_offer is None else motion_offer["action_zh"],
    )

    water_offer_made = False
    water_offer_pending = False
    round_no = 0
    pending_input: str | None = None
    pending_input_source = 'interrupt_asr'
    while True:
        round_no += 1
        if pending_input is not None:
            transcript, asr_ms, listen_timing = pending_input, None, {"source": pending_input_source}
            pending_input = None
        else:
            transcript, asr_ms, listen_timing = _listen_once(
                client,
                seconds=listen_seconds,
                audio_path=audio_dir / f"turn-{round_no}.wav",
                silence_timeout=silence_timeout,
                speech_rms_threshold=speech_rms_threshold,
            )
        _console(
            console,
            "检测到老人说的内容",
            input_source=listen_timing.get('source','g1_asr'),
            event_id=event_id,
            round_no=round_no,
            text=transcript,
            asr_ms=asr_ms,
            listen_timing=listen_timing,
        )
        if not transcript:
            _console(
                console,
                "对话判定",
                event_id=event_id,
                round_no=round_no,
                decision="未识别到内容，继续等待，不挥手不鼓掌",
            )
            _emit(
                output,
                {
                    "kind": "emotion_dialogue_turn",
                    "event_id": event_id,
                    "round_no": round_no,
                    "status": "no_response",
                    "asr_ms": asr_ms,
                    "listen_timing": listen_timing,
                },
            )
            continue
        if _is_quiet_request(transcript):
            closing_playback = None
            if demo_scene == "dialogue":
                closing_reply = CLOSING_REPLIES[current_payload["emotion"]]
                closing_playback = _speak_on_g1(
                    client,
                    closing_reply,
                    interaction,
                    bridge_path=bridge_path,
                    dialect=dialect,
                    play_audio=play_audio,
                )
                _console(
                    console,
                    "G1回复",
                    event_id=event_id,
                    round_no=round_no,
                    text=closing_reply,
                )
            _console(
                console,
                "对话判定",
                event_id=event_id,
                round_no=round_no,
                decision="老人要求安静/结束/退下/关闭，停止对话，不挥手不鼓掌",
            )
            _emit(
                output,
                {
                    "kind": "emotion_dialogue_turn",
                    "event_id": event_id,
                    "round_no": round_no,
                    "status": "quiet_requested",
                    "asr_ms": asr_ms,
                    "listen_timing": listen_timing,
                    "g1_played": closing_playback is not None,
                    **(
                        {
                            "reply_characters": len(closing_reply),
                            **_playback_metadata(closing_playback),
                        }
                        if closing_playback is not None
                        else {}
                    ),
                },
            )
            return "completed"

        if (demo_scene == "dialogue" and transcript[0] in "，,、。"
                and len(transcript.strip("，,、。！？!? ")) <= 3):
            _console(
                console,
                "对话判定",
                event_id=event_id,
                round_no=round_no,
                decision="识别到残句，静默继续听",
            )
            _emit(
                output,
                {
                    "kind": "emotion_dialogue_turn",
                    "event_id": event_id,
                    "round_no": round_no,
                    "status": "unclear_input",
                    "asr_ms": asr_ms,
                    "listen_timing": listen_timing,
                },
            )
            continue

        if demo_scene == "motion":
            # 达到录音上限的残句可能漏掉后续否定，不能授权动作。
            if (listen_timing.get("endpoint_reason") == "max_duration"
                    and not _is_motion_decline(transcript)):
                _emit(output, {
                    "kind": "emotion_dialogue_turn", "event_id": event_id,
                    "round_no": round_no, "status": "incomplete_confirmation",
                    "asr_ms": asr_ms, "listen_timing": listen_timing,
                })
                continue
            if motion_offer is not None and _is_motion_confirmation(transcript):
                _console(
                    console,
                    "对话判定",
                    event_id=event_id,
                    round_no=round_no,
                    decision=(
                        f"肯定，记录{motion_offer['action_zh']}请求 "
                        f"官方ID={motion_offer['action_id']}，停止听答"
                    ),
                )
                _emit(
                    output,
                    {
                        "kind": "emotion_dialogue_motion_request",
                        "event_id": event_id,
                        "round_no": round_no,
                        "motion_id": motion_offer["motion_id"],
                        "action_id": motion_offer["action_id"],
                        "trigger": motion_offer["cue"],
                        "status": "confirmed",
                        "execution": "intent_only",
                        "physical_actions_emitted": False,
                    },
                )
                return "motion_confirmed"
            if motion_offer is not None and _is_motion_decline(transcript):
                _console(
                    console,
                    "对话判定",
                    event_id=event_id,
                    round_no=round_no,
                    decision=f"拒绝{motion_offer['action_zh']}，本轮不再授权该动作",
                )
                _emit(
                    output,
                    {
                        "kind": "emotion_dialogue_motion_offer",
                        "event_id": event_id,
                        "round_no": round_no,
                        "motion_id": motion_offer["motion_id"],
                        "status": "declined",
                    },
                )
                return "completed"
            _console(
                console,
                "对话判定",
                event_id=event_id,
                round_no=round_no,
                decision="未明确肯定或拒绝，继续等待，不陪聊",
            )
            _emit(
                output,
                {
                    "kind": "emotion_dialogue_turn",
                    "event_id": event_id,
                    "round_no": round_no,
                    "status": "awaiting_confirmation",
                    "asr_ms": asr_ms,
                    "listen_timing": listen_timing,
                },
            )
            continue

        if water_offer_pending:
            if _is_water_confirmation(transcript) or _is_water_need(transcript):
                _console(
                    console,
                    "对话判定",
                    event_id=event_id,
                    round_no=round_no,
                    decision="确认饮水需求，只记录不递水",
                )
                playback = _speak_on_g1(
                    client,
                    WATER_ACKNOWLEDGEMENT,
                    interaction,
                    bridge_path=bridge_path,
                    dialect=dialect,
                    play_audio=play_audio,
                )
                _console(
                    console,
                    "G1回复",
                    event_id=event_id,
                    round_no=round_no,
                    text=WATER_ACKNOWLEDGEMENT,
                )
                _emit(
                    output,
                    {
                        "kind": "emotion_dialogue_care_request",
                        "event_id": event_id,
                        "round_no": round_no,
                        "need": "water",
                        "status": "confirmed",
                        "delivery_started": False,
                        "g1_played": True,
                        **_playback_metadata(playback),
                    },
                )
                water_offer_pending = False
                continue
            if _is_water_decline(transcript):
                _console(
                    console,
                    "对话判定",
                    event_id=event_id,
                    round_no=round_no,
                    decision="拒绝喝水，继续陪聊",
                )
                _emit(
                    output,
                    {
                        "kind": "emotion_dialogue_care_offer",
                        "event_id": event_id,
                        "round_no": round_no,
                        "offer": "water",
                        "status": "declined",
                    },
                )
            water_offer_pending = False

        water_offer_trigger = None
        if not water_offer_made:
            water_offer_trigger = "explicit_request" if _is_water_need(transcript) else None
            if (
                water_offer_trigger is None
                and not _is_water_decline(transcript)
                and _is_sad_hydration_cue(payload, transcript)
            ):
                water_offer_trigger = "sad_hydration_cue"
        if water_offer_trigger is not None:
            _console(
                console,
                "对话判定",
                event_id=event_id,
                round_no=round_no,
                decision="询问是否需要喝水，等待确认",
            )
            playback = _speak_on_g1(
                client,
                WATER_OFFER,
                interaction,
                bridge_path=bridge_path,
                dialect=dialect,
                play_audio=play_audio,
            )
            _console(
                console,
                "G1回复",
                event_id=event_id,
                round_no=round_no,
                text=WATER_OFFER,
            )
            _emit(
                output,
                {
                    "kind": "emotion_dialogue_care_offer",
                    "event_id": event_id,
                    "round_no": round_no,
                    "offer": "water",
                    "status": "offered",
                    "trigger": water_offer_trigger,
                    "g1_played": True,
                    **_playback_metadata(playback),
                },
            )
            water_offer_made = True
            water_offer_pending = True
            continue

        if chat_client is None:
            raise DialogueError("elder_chat_client_missing")
        _console(
            console,
            "对话判定",
            event_id=event_id,
            round_no=round_no,
            decision="继续陪聊",
        )
        result = _elder_chat(chat_client, transcript, current_payload)
        record_receipt({
            'kind':'elder_chat_api_context','event_id':event_id,'round_no':round_no,
            'base_url':getattr(chat_client,'base_url',None),
            'requested_elderly_id':str(getattr(chat_client,'elderly_id','unknown')),
            **{key:result[key] for key in ('session_id','elderly_id','care_session_id') if key in result},
        })
        raw_reply = result.get("reply")
        reply = raw_reply.strip() if isinstance(raw_reply, str) else ""
        should_end = bool(result.get("should_end"))
        if not reply:
            if should_end:
                _console(
                    console,
                    "模型输出",
                    event_id=event_id,
                    round_no=round_no,
                    text="",
                    **_chat_result_metadata(result),
                )
                _emit(
                    output,
                    {
                        "kind": "emotion_dialogue_turn",
                        "event_id": event_id,
                        "round_no": round_no,
                        "status": "session_ended",
                        "asr_ms": asr_ms,
                        "listen_timing": listen_timing,
                        "g1_played": False,
                        **_chat_result_metadata(result),
                    },
                )
                return "completed"
            raise DialogueError("elder_chat_reply_invalid")
        _console(
            console,
            "模型输出",
            event_id=event_id,
            round_no=round_no,
            text=reply,
            **{**_chat_result_metadata(result),
               **({"reply_validation": result["reply_validation"]}
                  if isinstance(result.get("reply_validation"), dict) else {})},
            **({"reason": result["reason"]} if isinstance(result.get("reason"), str) and result["reason"] else {}),
        )
        entertainment_kind = result.get("entertainment_kind")
        reply_player = play_audio
        if enable_entertainment_interrupts and entertainment_kind in {"story", "joke"} and not should_end:
            memory.last_companion_action = None

            def reply_player(bridge, audio):
                return play_interruptible_wav(
                    bridge, audio, client=client, narration=reply, audio_dir=audio_dir,
                    speech_rms_threshold=speech_rms_threshold, timeout=_dialogue_pcm_timeout(audio),
                )

        playback = _speak_on_g1(
            client,
            reply,
            interaction,
            bridge_path=bridge_path,
            dialect=dialect,
            play_audio=reply_player,
            speech_end_monotonic=listen_timing.get("speech_end_monotonic"),
        )
        _emit(
            output,
            {
                "kind": "emotion_dialogue_turn",
                "event_id": event_id,
                "round_no": round_no,
                "status": "interrupted" if playback.get("status") == "interrupted" else (
                    "session_ended" if should_end else "completed"
                ),
                "asr_ms": asr_ms,
                "listen_timing": listen_timing,
                "transcript_characters": len(transcript),
                "reply_characters": len(reply),
                "g1_played": True,
                **_playback_metadata(playback),
                **_chat_result_metadata(result),
            },
        )
        if should_end:
            return "completed"
        if playback.get("status") == "interrupted":
            command = playback["interrupt"]
            memory.last_companion_action = None
            if visual_updates is not None:
                while True:
                    try:
                        visual_updates.get_nowait()
                    except Empty:
                        break
            # The public stdout receipt keeps the transcript-free contract.  The
            # private journal retains the exact interruption command so the
            # operator can distinguish stop/replace/end-session decisions.
            record_console(
                {
                    "kind": "emotion_dialogue_interrupt_command",
                    "event_id": event_id,
                    "round_no": round_no,
                    "action": command["action"],
                    "entertainment_kind": entertainment_kind,
                    "text": command["text"],
                    "stop_result": playback.get("stop_result"),
                }
            )
            _emit(output, {
                "kind": "emotion_dialogue_entertainment_interrupt", "event_id": event_id,
                "round_no": round_no, "status": "stopped", "action": command["action"],
                "entertainment_kind": entertainment_kind,
                "command_characters": len(command["text"]), "stop_result": playback.get("stop_result"),
            })
            if command["action"] == "replace":
                next_kind = "joke" if "笑话" in command["text"] else (
                    "story" if "故事" in command["text"] else entertainment_kind
                )
                pending_input = "换一个笑话" if next_kind == "joke" else "换一个故事"
                pending_input_source = 'derived_interrupt_instruction'
            elif command["action"] == "end_session":
                pending_input = command["text"]
                pending_input_source = 'interrupt_asr'
            else:
                stop_text = "好的，先停下来。"
                record_console(
                    {
                        "kind": "emotion_dialogue_stop_confirmation",
                        "event_id": event_id,
                        "round_no": round_no,
                        "text": stop_text,
                    }
                )
                try:
                    stop_playback = _speak_on_g1(
                        client, stop_text, interaction, bridge_path=bridge_path,
                        dialect=dialect, play_audio=play_audio,
                    )
                except BaseException as error:
                    record_receipt(
                        {
                            "kind": "emotion_dialogue_stop_confirmation_playback",
                            "event_id": event_id,
                            "round_no": round_no,
                            "status": "unknown",
                            "playback_observation": "software_return",
                            "physical_heard": "unknown",
                            "error": repr(error),
                        }
                    )
                    raise
                record_receipt(
                    {
                        "kind": "emotion_dialogue_stop_confirmation_playback",
                        "event_id": event_id,
                        "round_no": round_no,
                        "status": stop_playback.get("status", "returned"),
                        "playback_observation": "software_return",
                        "physical_heard": "unknown",
                        **_playback_metadata(stop_playback),
                    }
                )
            continue
        memory.remember_completed_reply(
            transcript,
            entertainment_kind if entertainment_kind in {"story", "joke"} else (
                "none" if enable_entertainment_interrupts else None
            ),
        )
        pending_transition = _take_visual_transition(memory, visual_updates)
        if pending_transition is None:
            continue
        transition_payload, (from_emotion, to_emotion, companion_action) = pending_transition
        current_payload = transition_payload
        _, interaction = _validate_event(transition_payload)
        transition_result = _elder_visual_transition(
            chat_client,
            from_emotion=from_emotion,
            to_emotion=to_emotion,
            companion_action=companion_action,
            payload=transition_payload,
        )
        transition_raw_reply = transition_result.get("reply")
        transition_reply = (
            transition_raw_reply.strip() if isinstance(transition_raw_reply, str) else ""
        )
        if not transition_reply:
            raise DialogueError("elder_visual_transition_reply_invalid")
        _console(
            console,
            "情绪转变",
            event_id=event_id,
            transition_event_id=transition_payload.get("event_id"),
            from_emotion=from_emotion,
            to_emotion=to_emotion,
            companion_action=companion_action,
        )
        _console(
            console,
            "模型输出",
            event_id=event_id,
            round_no=round_no,
            text=transition_reply,
            **_chat_result_metadata(transition_result),
        )
        transition_playback = _speak_on_g1(
            client,
            transition_reply,
            INTERACTIONS["SHARE_POSITIVE"],
            bridge_path=bridge_path,
            dialect=dialect,
            play_audio=play_audio,
        )
        _emit(
            output,
            {
                "kind": "emotion_dialogue_visual_transition",
                "event_id": event_id,
                "transition_event_id": transition_payload.get("event_id"),
                "from_emotion": from_emotion,
                "to_emotion": to_emotion,
                "companion_action": companion_action,
                "status": "completed",
                "g1_played": True,
                "reply_characters": len(transition_reply),
                **_playback_metadata(transition_playback),
                **_chat_result_metadata(transition_result),
            },
        )


def consume_g1_dialogue_events(
    stream: TextIO,
    client: SpeechClient,
    output: TextIO,
    *,
    bridge_path: str,
    audio_dir: Path,
    dialect: str = "mandarin",
    listen_seconds: float = DEFAULT_LISTEN_SECONDS,
    silence_timeout: float = DEFAULT_SILENCE_TIMEOUT,
    speech_rms_threshold: int = 450,
    chat_client: ElderChatClient | None = None,
    play_audio: Callable[[str, str], dict[str, Any]] = _run_dialogue_pcm_bridge,
    console: TextIO | None = None,
    demo_scene: str = "dialogue",
    enable_listen_invite: bool = False,
    enable_entertainment_interrupts: bool = False,
    elder_chat_url: str = DEFAULT_ELDER_CHAT_URL,
    elder_chat_timeout: float = 90.0,
    elderly_id: int | None = None,
    visual_updates: Queue[dict[str, Any]] | None = None,
    accept_visual_transitions: bool = False,
) -> dict[str, int]:
    if demo_scene not in DEMO_SCENE_TEXTS:
        raise DialogueError("demo_scene_invalid")
    if not 1.0 <= listen_seconds <= 60.0:
        raise DialogueError("listen_seconds_invalid")
    if not 0.2 <= silence_timeout <= 5.0:
        raise DialogueError("silence_timeout_invalid")
    if not isinstance(speech_rms_threshold, int) or not 1 <= speech_rms_threshold <= 32767:
        raise DialogueError("speech_rms_threshold_invalid")
    audio_dir.mkdir(parents=True, exist_ok=True)
    if console is None:
        console = sys.stderr
    if chat_client is None and demo_scene == "dialogue":
        _require_elder_chat_health(
            elder_chat_url,
            timeout=min(elder_chat_timeout, 10.0),
        )
        chat_options: dict[str, Any] = {
            "base_url": elder_chat_url,
            "timeout": elder_chat_timeout,
        }
        if elderly_id is not None:
            chat_options["elderly_id"] = elderly_id
        chat_client = ElderChatClient(**chat_options)

    _announce_demo_scene(
        client,
        demo_scene,
        INTERACTIONS["SHARE_POSITIVE"],
        event_id=DEMO_SCENE_SESSION_EVENT_ID,
        bridge_path=bridge_path,
        dialect=dialect,
        play_audio=play_audio,
        output=output,
        console=console,
    )

    seen_event_ids: set[str] = set()
    received = completed = duplicates = ignored = 0
    for payload in _iter_events(stream):
        received += 1
        event_id, _ = _validate_event(payload)
        if event_id in seen_event_ids:
            duplicates += 1
            _console(
                console,
                "对话判定",
                event_id=event_id,
                decision="重复事件已忽略",
            )
            _emit(
                output,
                {"kind": "emotion_dialogue_receipt", "event_id": event_id, "status": "duplicate_ignored"},
            )
            continue
        seen_event_ids.add(event_id)
        if completed == MAX_DIALOGUE_EVENTS:
            ignored += 1
            _console(
                console,
                "对话判定",
                event_id=event_id,
                decision="已完成一条对话，后续事件忽略",
            )
            _emit(
                output,
                {"kind": "emotion_dialogue_receipt", "event_id": event_id, "status": "event_limit_reached"},
            )
            continue
        if demo_scene == "motion" and _motion_offer(payload) is None:
            ignored += 1
            _console(
                console,
                "对话判定",
                event_id=event_id,
                decision="非高兴挥手/鼓掌事件已忽略，继续等待",
            )
            _emit(
                output,
                {
                    "kind": "emotion_dialogue_receipt",
                    "event_id": event_id,
                    "status": "ignored_not_motion_cue",
                },
            )
            continue
        active_visual_updates = visual_updates
        visual_reader_started = False
        if demo_scene == "dialogue" and accept_visual_transitions and active_visual_updates is None:
            active_visual_updates = Queue(maxsize=4)
            threading.Thread(
                target=_forward_visual_updates,
                args=(_iter_events(stream), active_visual_updates),
                daemon=True,
            ).start()
            visual_reader_started = True
        outcome = _run_dialogue(
            payload,
            client,
            output,
            bridge_path=bridge_path,
            audio_dir=audio_dir,
            dialect=dialect,
            listen_seconds=listen_seconds,
            silence_timeout=silence_timeout,
            speech_rms_threshold=speech_rms_threshold,
            chat_client=chat_client,
            play_audio=play_audio,
            console=console,
            demo_scene=demo_scene,
            enable_listen_invite=enable_listen_invite,
            enable_entertainment_interrupts=enable_entertainment_interrupts,
            visual_updates=active_visual_updates,
        )
        completed += 1
        if outcome == "motion_confirmed" or visual_reader_started:
            break
    return {"received": received, "completed": completed, "duplicates": duplicates, "ignored": ignored}


def parse_arguments(arguments: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.getenv("SPEECH_BASE_URL", "http://127.0.0.1:8780"))
    parser.add_argument("--g1-pcm-bridge")
    parser.add_argument("--confirm-g1-companion-pcm", action="store_true")
    parser.add_argument(
        "--audio-dir",
        type=Path,
    )
    parser.add_argument("--dialect", default="mandarin")
    parser.add_argument("--listen-seconds", type=float, default=DEFAULT_LISTEN_SECONDS)
    parser.add_argument("--silence-timeout", type=float, default=DEFAULT_SILENCE_TIMEOUT)
    parser.add_argument("--speech-rms-threshold", type=int, default=450)
    parser.add_argument(
        "--demo-scene",
        choices=("dialogue", "motion"),
        default="dialogue",
    )
    parser.add_argument(
        "--enable-listen-invite",
        action="store_true",
        help="悲伤 listen_hold 在检测开场开口前请求一次 open_palm_invite；默认关闭",
    )
    parser.add_argument(
        "--enable-entertainment-interrupts",
        action="store_true",
        help="仅故事/笑话播报期间监听明确停止或换一个指令；普通回复仍等待播放完成",
    )
    parser.add_argument(
        "--accept-visual-transitions",
        action="store_true",
        help="只在伤心对话讲完笑话后处理一次稳定开心视觉转变",
    )
    parser.add_argument("--record-log", type=Path, help="care_session_record_v1 journal path")
    parser.add_argument("--elderly-id", type=int, help="positive elderly ID (1..2^63-1)")
    parser.add_argument("--record-mode", choices=("live", "replay"), default="live")
    parser.add_argument(
        "--elder-chat-url",
        default=os.getenv("ELDER_CHAT_BASE_URL", DEFAULT_ELDER_CHAT_URL),
        help="Elder Companion Unified API base URL; ignored in motion scene",
    )
    parser.add_argument("--timeout", type=float, default=90.0)
    args = parser.parse_args(arguments)
    if args.elderly_id is not None:
        try:
            validate_elderly_id(args.elderly_id)
        except ValueError as error:
            parser.error(str(error))
    if args.record_log is not None and args.elderly_id is None:
        parser.error("--record-log requires explicit --elderly-id")
    if not args.g1_pcm_bridge:
        parser.error("live control requires --g1-pcm-bridge")
    if not args.confirm_g1_companion_pcm:
        parser.error("--g1-pcm-bridge requires --confirm-g1-companion-pcm")
    if args.audio_dir is None:
        parser.error("the following arguments are required: --audio-dir")
    if not 1.0 <= args.timeout <= 120.0:
        parser.error("--timeout must be between 1 and 120 seconds")
    return args


def main(arguments: list[str]) -> int:
    args = parse_arguments(arguments)
    elderly_id = args.elderly_id if args.elderly_id is not None else 1
    recorder: CompanionRecorder | None = None
    summary: dict[str, int] | None = None
    status = "failed"
    error_text: str | None = None
    try:
        if args.record_log is not None:
            try:
                recorder = open_recorder(
                    args.record_log,
                    elderly_id=elderly_id,
                    mode=args.record_mode,
                    scene=args.demo_scene,
                    stderr=sys.stderr,
                )
            except (RecordingError, OSError, ValueError) as error:
                print(f"care_session_recording_disabled: {error}", file=sys.stderr, flush=True)
        with recording_context(recorder):
            client = SpeechClient(base_url=args.base_url, timeout=args.timeout)
            health = client.health()
            if not isinstance(health, dict) or health.get("ok") is not True:
                raise DialogueError("speech_service_unhealthy")
            chat_client = None
            if args.demo_scene == "dialogue":
                _require_elder_chat_health(args.elder_chat_url, timeout=min(args.timeout, 10.0))
                chat_options: dict[str, Any] = {
                    "base_url": args.elder_chat_url,
                    "timeout": args.timeout,
                }
                if args.elderly_id is not None:
                    chat_options["elderly_id"] = elderly_id
                chat_client = ElderChatClient(**chat_options)
            play_audio = _run_dialogue_pcm_bridge
            summary = consume_g1_dialogue_events(
                sys.stdin,
                client,
                sys.stdout,
                bridge_path=args.g1_pcm_bridge or "",
                audio_dir=args.audio_dir,
                dialect=args.dialect,
                listen_seconds=args.listen_seconds,
                silence_timeout=args.silence_timeout,
                speech_rms_threshold=args.speech_rms_threshold,
                chat_client=chat_client,
                play_audio=play_audio,
                demo_scene=args.demo_scene,
                enable_listen_invite=args.enable_listen_invite,
                enable_entertainment_interrupts=args.enable_entertainment_interrupts,
                elder_chat_url=args.elder_chat_url,
                elder_chat_timeout=args.timeout,
                elderly_id=elderly_id,
                accept_visual_transitions=args.accept_visual_transitions,
            )
            _emit(
                sys.stdout,
                {"kind": "emotion_g1_dialogue_summary", **summary, "robot_motion_commands_emitted": 0},
            )
        status = "no_event" if summary is not None and summary.get("received", 0) == 0 else "completed"
        return_code = 0
    except KeyboardInterrupt:
        status = "interrupted"
        error_text = "keyboard_interrupt"
        print(
            json.dumps({"kind": "emotion_dialogue_error", "error_code": error_text}, separators=(",", ":")),
            file=sys.stderr,
            flush=True,
        )
        print("[现场] 中断：keyboard_interrupt", file=sys.stderr, flush=True)
        return_code = 70
    except Exception as error:
        status = "failed"
        error_text = str(error)
        print(
            json.dumps(
                {"kind": "emotion_dialogue_error", "error_code": error_text},
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            file=sys.stderr,
            flush=True,
        )
        print(f"[现场] 错误：{error}", file=sys.stderr, flush=True)
        return_code = 70
    finally:
        if recorder is not None:
            recorder.finish(status, summary, error=error_text)
    return return_code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

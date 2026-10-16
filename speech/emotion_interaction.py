#!/usr/bin/env python3
"""Consume emotion_strategy_v1 JSONL and hand approved replies to the speech service."""

from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
from typing import Any, Iterator, TextIO

from speech_client import SpeechClient


MAX_EVENT_BYTES = 64 * 1024
MAX_G1_PHRASES = 3
G1_PCM_BRIDGE_TIMEOUT_SECONDS = 20.0
G1_TTS_BRIDGE_TIMEOUT_SECONDS = 15.0
# ponytail: symbolic motion only; bind these IDs to a verified, confirmed G1 executor later.
INTERACTIONS = {
    "SHARE_POSITIVE": {
        "emotion": "happy",
        "phrases": {
            "stable_face": (
                ("companion_share_positive", "这会儿看着您心情不错，愿意跟我说说发生了啥吗？"),
                ("companion_share_positive_2", "您这会儿挺高兴的。要是愿意，我很想听听这好心情从哪来。"),
                ("companion_share_positive_3", "看着有啥让您高兴了；愿意跟我唠两句不？"),
            ),
            "possible": (
                ("companion_share_positive_possible", "您这会儿看着兴致还行，要是我看走眼了您就说一声。"),
                ("companion_share_positive_possible_2", "我感觉您这会儿心情还不错，愿意的话跟我随便聊聊？"),
                ("companion_share_positive_possible_3", "您看着像心情还行，想说就说，不想说也没事。"),
            ),
        },
        "style": "happy",
        "emotion_style": "cheerful",
        "motion_id": "no_motion",
        "speed": 1.05,
    },
    "EMPATHIZE_AND_INVITE": {
        "emotion": "sad",
        "phrases": {
            "stable_face": (
                ("companion_empathize_and_invite", "您这会儿看着有些难过。我陪着您；想聊就聊，想静一静也行。"),
                ("companion_empathize_and_invite_2", "我注意到您可能有点难受。我就在这；想说就说，不想说也没关系。"),
                ("companion_empathize_and_invite_3", "您看着有些低落。愿意的话我听着；不想说我也不追问。"),
            ),
            "possible": (
                ("companion_empathize_and_invite_possible", "您这会儿看着有点不自在，我先陪着；想说就说，不想说也行。"),
                ("companion_empathize_and_invite_possible_2", "我可能看错了，您要是心里不舒服，跟我吭一声就中。"),
                ("companion_empathize_and_invite_possible_3", "您看着像有点难受，我先不打扰；需要我听着您再说。"),
            ),
        },
        "style": "comfort",
        "emotion_style": "gentle",
        "motion_id": "listen_hold",
        "speed": 0.82,
    },
    "DEESCALATE_AND_GIVE_SPACE": {
        "emotion": "angry",
        "phrases": {
            "stable_face": (
                ("companion_deescalate_and_give_space", "您这会儿看着不太舒服。我先不吵您；需要帮忙您吭一声。"),
                ("companion_deescalate_and_give_space_2", "我先放慢、不跟您争。您要帮忙还是想先静一静？"),
                ("companion_deescalate_and_give_space_3", "您看着心里不太痛快。我先给您留空；需要我做啥您说。"),
            ),
            "possible": (
                ("companion_deescalate_and_give_space_possible", "您这会儿看着不太痛快，我先不靠近、也不多问。"),
                ("companion_deescalate_and_give_space_possible_2", "我可能看走眼了；要是心里不舒服，我先安静陪着。"),
                ("companion_deescalate_and_give_space_possible_3", "您看着像有点不耐烦。我先不吵；需要帮忙再说。"),
            ),
        },
        "style": "normal",
        "emotion_style": "calm",
        "motion_id": "return_to_neutral",
        "speed": 0.70,
        "pitch": 0.94,
        "volume": 62,
    },
}


class InteractionError(RuntimeError):
    """Stable error code for the emotion-to-speech boundary."""


def _validate_event(payload: Any) -> tuple[str, dict[str, Any]]:
    if not isinstance(payload, dict) or payload.get("schema_version") != "emotion_strategy_v1":
        raise InteractionError("emotion_event_schema_invalid")
    event_id = payload.get("event_id")
    emotion = payload.get("emotion")
    inference_level = payload.get("inference_level")
    behavior_cues = payload.get("behavior_cues", [])
    strategy = payload.get("strategy")
    if not isinstance(event_id, str) or not event_id.strip() or len(event_id) > 128:
        raise InteractionError("emotion_event_id_invalid")
    if inference_level not in {"stable_face", "action_face", "possible"}:
        raise InteractionError("emotion_inference_level_invalid")
    if (
        not isinstance(behavior_cues, list)
        or len(behavior_cues) > 16
        or any(
            not isinstance(cue, str) or not cue or len(cue) > 64 for cue in behavior_cues
        )
    ):
        raise InteractionError("emotion_behavior_cues_invalid")
    if inference_level == "action_face" and (
        emotion != "happy"
        or not {"wave_open_palm", "clap_two_hands"}.intersection(behavior_cues)
    ):
        raise InteractionError("emotion_action_face_invalid")
    if not isinstance(strategy, dict):
        raise InteractionError("emotion_strategy_invalid")
    strategy_id = strategy.get("strategy_id")
    if not isinstance(strategy_id, str):
        raise InteractionError("emotion_strategy_id_invalid")
    interaction = INTERACTIONS.get(strategy_id)
    if interaction is None:
        raise InteractionError("emotion_strategy_id_invalid")
    if emotion != interaction["emotion"]:
        raise InteractionError("strategy_emotion_mismatch")
    if not all(isinstance(strategy.get(field), str) and strategy[field] for field in ("goal", "tone")):
        raise InteractionError("emotion_strategy_text_invalid")
    if not all(
        isinstance(strategy.get(field), list)
        and strategy[field]
        and all(isinstance(item, str) and item for item in strategy[field])
        for field in ("do", "avoid")
    ):
        raise InteractionError("emotion_strategy_rules_invalid")
    return event_id, interaction


def _choose_phrase(interaction: dict[str, Any], inference_level: str) -> tuple[str, str]:
    banks = interaction["phrases"]
    if inference_level == "action_face":
        inference_level = "stable_face"
    if not isinstance(banks, dict) or inference_level not in banks:
        raise InteractionError("emotion_phrase_bank_invalid")
    phrase = random.choice(banks[inference_level])
    if not isinstance(phrase, tuple) or len(phrase) != 2:
        raise InteractionError("emotion_phrase_invalid")
    phrase_id, text = phrase
    if not isinstance(phrase_id, str) or not isinstance(text, str):
        raise InteractionError("emotion_phrase_invalid")
    return phrase_id, text


def dispatch_event(
    payload: Any,
    client: SpeechClient,
    seen_event_ids: set[str],
    *,
    play_on_host: bool,
    dialect: str = "mandarin",
) -> dict[str, Any]:
    event_id, interaction = _validate_event(payload)
    strategy_id = payload["strategy"]["strategy_id"]
    if event_id in seen_event_ids:
        return {
            "kind": "emotion_interaction_receipt",
            "event_id": event_id,
            "strategy_id": strategy_id,
            "status": "duplicate_ignored",
        }

    seen_event_ids.add(event_id)
    inference_level = payload["inference_level"]
    phrase_id, text = _choose_phrase(interaction, inference_level)
    options = {
        "style": interaction["style"],
        "emotion": interaction["emotion_style"],
        "dialect": dialect,
        "play_on_host": play_on_host,
    }
    for name in ("speed", "volume", "pitch"):
        if name in interaction:
            options[name] = interaction[name]
    response = client.speak(text, **options)
    if not isinstance(response, dict) or response.get("ok") is not True:
        raise InteractionError("speech_service_response_invalid")

    return {
        "kind": "emotion_interaction_receipt",
        "event_id": event_id,
        "strategy_id": strategy_id,
        "inference_level": inference_level,
        "phrase_id": phrase_id,
        "status": "delivered",
        "request_id": response.get("request_id"),
        "audio_path": response.get("audio_path"),
        "played": bool(response.get("played")),
        "g1_played": bool(response.get("g1_played")),
    }


def phrase_event(payload: Any, seen_event_ids: set[str]) -> dict[str, str] | None:
    """Map one valid strategy event to the only payload accepted by the G1 bridge."""
    event_id, interaction = _validate_event(payload)
    if event_id in seen_event_ids:
        return None
    seen_event_ids.add(event_id)
    phrase_id, _ = _choose_phrase(interaction, payload["inference_level"])
    return {
        "schema_version": "g1_companion_phrase_v1",
        "event_id": event_id,
        "phrase_id": phrase_id,
    }


def _iter_events(stream: TextIO) -> Iterator[Any]:
    line_number = 0
    while True:
        line = stream.readline()
        if line == "":
            return
        line_number += 1
        if not line.strip():
            continue
        if len(line.encode("utf-8")) > MAX_EVENT_BYTES:
            raise InteractionError(f"emotion_event_too_large:line={line_number}")
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as error:
            raise InteractionError(f"emotion_event_json_invalid:line={line_number}") from error
        if isinstance(payload, dict) and payload.get("kind") == "emotion_demo_summary":
            continue
        yield payload


def consume_events(
    stream: TextIO,
    client: SpeechClient,
    output: TextIO,
    *,
    play_on_host: bool,
    dialect: str = "mandarin",
) -> dict[str, int]:
    seen_event_ids: set[str] = set()
    received = delivered = duplicates = 0
    for payload in _iter_events(stream):
        received += 1
        receipt = dispatch_event(
            payload, client, seen_event_ids, play_on_host=play_on_host, dialect=dialect
        )
        delivered += receipt["status"] == "delivered"
        duplicates += receipt["status"] == "duplicate_ignored"
        print(json.dumps(receipt, ensure_ascii=False, separators=(",", ":")), file=output, flush=True)
    return {"received": received, "delivered": delivered, "duplicates": duplicates}


def consume_phrase_events(stream: TextIO, output: TextIO) -> dict[str, int]:
    """Emit pure JSONL for the separate fixed-phrase G1 playback bridge."""
    seen_event_ids: set[str] = set()
    received = emitted = duplicates = 0
    for payload in _iter_events(stream):
        received += 1
        phrase = phrase_event(payload, seen_event_ids)
        if phrase is None:
            duplicates += 1
            continue
        emitted += 1
        print(json.dumps(phrase, ensure_ascii=False, separators=(",", ":")), file=output, flush=True)
    return {"received": received, "emitted": emitted, "duplicates": duplicates}


def _run_g1_bridge(bridge_path: str, phrase_id: str) -> dict[str, Any]:
    try:
        result = subprocess.run(
            [bridge_path, "--confirm-g1-companion-tts", phrase_id],
            capture_output=True,
            check=False,
            text=True,
            timeout=G1_TTS_BRIDGE_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as error:
        raise InteractionError("g1_tts_bridge_not_found") from error
    except subprocess.TimeoutExpired as error:
        raise InteractionError("g1_tts_bridge_timeout") from error
    if result.returncode != 0:
        raise InteractionError(f"g1_tts_bridge_failed:exit={result.returncode}")
    try:
        bridge_result = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise InteractionError("g1_tts_bridge_response_invalid") from error
    if (
        not isinstance(bridge_result, dict)
        or bridge_result.get("kind") != "g1_companion_tts_phrase_bridge"
        or bridge_result.get("status") != "completed"
        or bridge_result.get("phrase_id") != phrase_id
    ):
        raise InteractionError("g1_tts_bridge_response_invalid")
    return bridge_result


def _run_g1_pcm_bridge(bridge_path: str, audio_path: str) -> dict[str, Any]:
    try:
        result = subprocess.run(
            [bridge_path, "--confirm-g1-companion-pcm", audio_path],
            capture_output=True,
            check=False,
            text=True,
            timeout=G1_PCM_BRIDGE_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as error:
        raise InteractionError("g1_pcm_bridge_not_found") from error
    except subprocess.TimeoutExpired as error:
        raise InteractionError("g1_pcm_bridge_timeout") from error
    if result.returncode != 0:
        raise InteractionError(f"g1_pcm_bridge_failed:exit={result.returncode}")
    try:
        bridge_result = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise InteractionError("g1_pcm_bridge_response_invalid") from error
    if (
        not isinstance(bridge_result, dict)
        or bridge_result.get("kind") != "g1_companion_pcm_bridge"
        or bridge_result.get("status") != "completed"
        or bridge_result.get("wav_path") != audio_path
    ):
        raise InteractionError("g1_pcm_bridge_response_invalid")
    return bridge_result


def consume_g1_bridge_events(
    stream: TextIO, output: TextIO, *, bridge_path: str
) -> dict[str, int]:
    """Play at most three reviewed phrases through the separately confirmed bridge."""
    seen_event_ids: set[str] = set()
    received = completed = duplicates = 0
    for payload in _iter_events(stream):
        received += 1
        phrase = phrase_event(payload, seen_event_ids)
        if phrase is None:
            duplicates += 1
            continue
        if completed == MAX_G1_PHRASES:
            raise InteractionError("g1_tts_phrase_limit_reached")
        bridge_result = _run_g1_bridge(bridge_path, phrase["phrase_id"])
        completed += 1
        print(
            json.dumps(
                {
                    "kind": "emotion_g1_tts_receipt",
                    "event_id": phrase["event_id"],
                    "phrase_id": phrase["phrase_id"],
                    "status": "completed",
                    "playback_started": bridge_result.get("playback_started"),
                    "playback_stopped": bridge_result.get("playback_stopped"),
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            file=output,
            flush=True,
        )
    return {"received": received, "completed": completed, "duplicates": duplicates}


def consume_g1_pcm_bridge_events(
    stream: TextIO, client: SpeechClient, output: TextIO, *, bridge_path: str, dialect: str
) -> dict[str, int]:
    """Generate reviewed speech locally, then play its bounded PCM on G1."""
    seen_event_ids: set[str] = set()
    received = completed = duplicates = 0
    for payload in _iter_events(stream):
        received += 1
        receipt = dispatch_event(
            payload, client, seen_event_ids, play_on_host=False, dialect=dialect
        )
        if receipt["status"] == "duplicate_ignored":
            duplicates += 1
            continue
        if completed == MAX_G1_PHRASES:
            raise InteractionError("g1_pcm_phrase_limit_reached")
        audio_path = receipt.get("audio_path")
        if not isinstance(audio_path, str) or not audio_path:
            raise InteractionError("speech_service_audio_path_invalid")
        bridge_result = _run_g1_pcm_bridge(bridge_path, audio_path)
        completed += 1
        print(
            json.dumps(
                {
                    "kind": "emotion_g1_pcm_receipt",
                    "event_id": receipt["event_id"],
                    "phrase_id": receipt["phrase_id"],
                    "inference_level": receipt.get("inference_level"),
                    "style": INTERACTIONS[receipt["strategy_id"]]["style"],
                    "dialect": dialect,
                    "status": "completed",
                    "g1_played": True,
                    "pcm_bytes": bridge_result.get("pcm_bytes"),
                    "duration_milliseconds": bridge_result.get("duration_milliseconds"),
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            file=output,
            flush=True,
        )
    return {"received": received, "completed": completed, "duplicates": duplicates}


def parse_arguments(arguments: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.getenv("SPEECH_BASE_URL", "http://127.0.0.1:8780"),
    )
    g1_mode = parser.add_mutually_exclusive_group()
    g1_mode.add_argument(
        "--g1-phrase-jsonl",
        action="store_true",
        help="仅输出固定 phrase_id JSONL；不请求本机语音服务，也不播放",
    )
    g1_mode.add_argument(
        "--g1-bridge",
        help="已构建的 g1_companion_tts_phrase_bridge；必须同时显式确认",
    )
    g1_mode.add_argument(
        "--g1-pcm-bridge",
        help="已构建的 g1_companion_pcm_bridge；生成 WAV 后必须同时显式确认",
    )
    parser.add_argument("--confirm-g1-companion-tts", action="store_true")
    parser.add_argument("--confirm-g1-companion-pcm", action="store_true")
    parser.add_argument("--dialect", default="mandarin")
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument(
        "--play-on-host",
        action="store_true",
        help="在语音服务所在主机播放；默认只生成 WAV",
    )
    args = parser.parse_args(arguments)
    if not 1.0 <= args.timeout <= 120.0:
        parser.error("--timeout must be between 1 and 120 seconds")
    if args.g1_bridge and not args.confirm_g1_companion_tts:
        parser.error("--g1-bridge requires --confirm-g1-companion-tts")
    if args.confirm_g1_companion_tts and not args.g1_bridge:
        parser.error("--confirm-g1-companion-tts requires --g1-bridge")
    if args.g1_pcm_bridge and not args.confirm_g1_companion_pcm:
        parser.error("--g1-pcm-bridge requires --confirm-g1-companion-pcm")
    if args.confirm_g1_companion_pcm and not args.g1_pcm_bridge:
        parser.error("--confirm-g1-companion-pcm requires --g1-pcm-bridge")
    return args


def main(arguments: list[str]) -> int:
    args = parse_arguments(arguments)
    try:
        if args.g1_phrase_jsonl:
            summary = consume_phrase_events(sys.stdin, sys.stdout)
        elif args.g1_bridge:
            summary = consume_g1_bridge_events(
                sys.stdin, sys.stdout, bridge_path=args.g1_bridge
            )
        else:
            client = SpeechClient(
                base_url=args.base_url,
                timeout=args.timeout,
            )
            health = client.health()
            if not isinstance(health, dict) or health.get("ok") is not True:
                raise InteractionError("speech_service_unhealthy")
            if args.g1_pcm_bridge:
                summary = consume_g1_pcm_bridge_events(
                    sys.stdin, client, sys.stdout, bridge_path=args.g1_pcm_bridge,
                    dialect=args.dialect
                )
            else:
                summary = consume_events(
                    sys.stdin, client, sys.stdout, play_on_host=args.play_on_host,
                    dialect=args.dialect,
                )
    except Exception as error:
        print(
            json.dumps(
                {"kind": "emotion_interaction_error", "error_code": str(error)},
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            file=sys.stderr,
        )
        return 70
    if args.g1_phrase_jsonl:
        result = {"kind": "emotion_g1_phrase_summary", **summary, "physical_actions_emitted": 0}
    elif args.g1_bridge:
        result = {"kind": "emotion_g1_tts_summary", **summary, "robot_motion_commands_emitted": 0}
    elif args.g1_pcm_bridge:
        result = {"kind": "emotion_g1_pcm_summary", **summary, "robot_motion_commands_emitted": 0}
    else:
        result = {"kind": "emotion_interaction_summary", **summary, "physical_actions_emitted": 0}
    print(
        json.dumps(
            result,
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        file=sys.stderr if args.g1_phrase_jsonl else sys.stdout,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

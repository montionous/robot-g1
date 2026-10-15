#!/usr/bin/env python3
"""Run one explicit G1 announcement, owner-only phone call, and local ringback."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import re
import stat
import struct
import subprocess
import sys
from typing import Any, Callable
import wave


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import g1_phone_dial


SCHEMA_VERSION = "g1_contact_family_call_v1"
CONFIRM = "--confirm-g1-contact-family-call"
RINGBACK_SECONDS = 12
VOICE_CONFIRMATION_SECONDS = 7.0


class ContactCallError(RuntimeError):
    """A safe, operator-readable reason why the call sequence stopped."""


def is_voice_confirmation(value: str) -> bool:
    return re.sub(r"[\s，。！？、,.!?]", "", value) == "确认拨号"


def write_ringback_wav(path: Path, *, seconds: int = RINGBACK_SECONDS) -> None:
    if not 1 <= seconds <= 15:
        raise ContactCallError("ringback_duration_invalid")
    path.parent.mkdir(parents=True, exist_ok=True)
    sample_rate = 16000
    samples: list[int] = []
    for index in range(sample_rate * seconds):
        elapsed = index / sample_rate
        if elapsed % 1.5 < 0.8:
            value = 0.30 * math.sin(2 * math.pi * 440 * elapsed)
            value += 0.20 * math.sin(2 * math.pi * 480 * elapsed)
        else:
            value = 0.0
        samples.append(int(max(-1.0, min(1.0, value)) * 32767))
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(sample_rate)
        audio.writeframes(b"".join(struct.pack("<h", sample) for sample in samples))


def validate_pcm_bridge(bridge: Path, wav_path: Path) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            [str(bridge), "--dry-run", str(wav_path)],
            capture_output=True,
            check=False,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ContactCallError("g1_pcm_bridge_unavailable") from error
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise ContactCallError("g1_pcm_bridge_invalid_response") from error
    if (
        completed.returncode != 0
        or payload.get("kind") != "g1_companion_pcm_bridge"
        or payload.get("status") != "dry_run"
    ):
        raise ContactCallError("g1_pcm_bridge_preflight_failed")
    return payload


def _read_token(path: Path) -> str:
    try:
        mode = path.stat().st_mode
        if not path.is_file() or mode & (stat.S_IRWXG | stat.S_IRWXO):
            raise ContactCallError("phone_token_file_permissions_invalid")
        token = path.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise ContactCallError("phone_token_file_unavailable") from error
    if len(token) < 32 or any(character.isspace() for character in token):
        raise ContactCallError("phone_token_invalid")
    return token


def _phone_arguments(
    arguments: argparse.Namespace, *, mode: str, token: str | None = None
) -> argparse.Namespace:
    return argparse.Namespace(
        phone_url=arguments.phone_url,
        token=token,
        output_dir=arguments.output_dir / f"phone-{mode}",
        dry_run=False,
        preflight=mode == "preflight",
        confirmed=mode == "dial",
    )


def _speech_factory() -> Any:
    speech_directory = ROOT / "speech"
    if str(speech_directory) not in sys.path:
        sys.path.insert(0, str(speech_directory))
    from speech_client import SpeechClient

    return SpeechClient()


def _call_speech(method: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    try:
        return method(*args, **kwargs)
    except Exception as error:
        raise ContactCallError("g1_speech_failed") from error


def listen_for_voice_confirmation(speech: Any, audio_path: Path) -> str:
    try:
        response = _call_speech(
            speech.listen_g1,
            seconds=VOICE_CONFIRMATION_SECONDS,
            output_path=str(audio_path),
        )
    finally:
        audio_path.unlink(missing_ok=True)
    if not isinstance(response, dict) or not isinstance(response.get("text"), str):
        raise ContactCallError("g1_speech_invalid_response")
    transcript = response["text"].strip()
    print(f"[现场] G1识别：{transcript or '（未识别到内容）'}", file=sys.stderr)
    return transcript


def _result(mode: str, state: str, *, dial_requested: bool) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "mode": mode,
        "contact_id": "owner",
        "operation_state": state,
        "external_dial_requested": dial_requested,
    }


def _write_result(output_directory: Path, result: dict[str, Any]) -> None:
    (output_directory / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
    )


def run(
    arguments: argparse.Namespace,
    *,
    speech_factory: Callable[[], Any] = _speech_factory,
    phone_runner: Callable[[argparse.Namespace], dict[str, Any]] = g1_phone_dial.run,
    pcm_validator: Callable[[Path, Path], dict[str, Any]] = validate_pcm_bridge,
) -> dict[str, Any]:
    mode = "dry_run" if arguments.dry_run else "preflight" if arguments.preflight else "dial"
    dial_requested = False
    arguments.output_dir.mkdir(parents=True, exist_ok=False)
    if arguments.dry_run:
        result = _result(mode, "planned", dial_requested=False)
        _write_result(arguments.output_dir, result)
        return result

    try:
        speech = speech_factory()
        health = _call_speech(speech.health)
        if not isinstance(health, dict) or health.get("ok") is not True:
            raise ContactCallError("speech_service_unhealthy")
        ringback_path = arguments.output_dir / "ringback.wav"
        write_ringback_wav(ringback_path)
        pcm_validator(arguments.g1_pcm_bridge, ringback_path)
        preflight = phone_runner(_phone_arguments(arguments, mode="preflight"))
        if preflight.get("operation_state") != "preflight_ok":
            raise ContactCallError("phone_preflight_failed")

        if arguments.preflight:
            result = _result(mode, "preflight_ok", dial_requested=False)
        else:
            _call_speech(
                speech.speak_g1,
                "即将联系您的儿子。要拨打电话，请说确认拨号；不拨打请说取消。",
                style="companion",
                dialect="mandarin",
            )
            transcript = listen_for_voice_confirmation(
                speech, arguments.output_dir / "voice-confirmation.wav"
            )
            if not is_voice_confirmation(transcript):
                _call_speech(
                    speech.speak_g1,
                    "没有听到确认拨号，本次不会拨打电话。",
                    style="companion",
                    dialect="mandarin",
                )
                result = _result(mode, "voice_not_confirmed", dial_requested=False)
            else:
                token = _read_token(arguments.token_file)
                dial_requested = True
                dial = phone_runner(_phone_arguments(arguments, mode="dial", token=token))
                if dial.get("operation_state") != "accepted":
                    raise ContactCallError("phone_dial_rejected")
                _call_speech(
                    speech.speak_g1,
                    "正在联系您的儿子，请稍候。",
                    style="companion",
                    dialect="mandarin",
                )
                _call_speech(speech.play_g1, ringback_path)
                result = _result(mode, "accepted", dial_requested=True)
    except (ContactCallError, g1_phone_dial.DialError) as error:
        result = _result(mode, "failed", dial_requested=dial_requested)
        result["error_code"] = str(error)
        _write_result(arguments.output_dir, result)
        raise
    _write_result(arguments.output_dir, result)
    return result


def parse_arguments(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phone-url", required=True)
    parser.add_argument("--token-file", type=Path)
    parser.add_argument("--g1-pcm-bridge", type=Path, default=ROOT / "build" / "g1_companion_pcm_bridge")
    parser.add_argument("--output-dir", required=True, type=Path)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--dry-run", action="store_true")
    action.add_argument("--preflight", action="store_true")
    action.add_argument(CONFIRM, dest="confirmed", action="store_true")
    arguments = parser.parse_args(argv)
    if arguments.confirmed and arguments.token_file is None:
        parser.error("--confirm-g1-contact-family-call requires --token-file")
    return arguments


def main(argv: list[str] | None = None) -> int:
    try:
        result = run(parse_arguments(sys.argv[1:] if argv is None else argv))
    except (ContactCallError, g1_phone_dial.DialError) as error:
        print(json.dumps({"schema_version": SCHEMA_VERSION, "operation_state": "failed", "error_code": str(error)}))
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

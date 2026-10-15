from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
import dashscope
from dashscope.audio.http_tts.http_speech_synthesizer import HttpSpeechSynthesizer

from .presets import STYLE_PRESETS, build_instruction, delivery_instruction

DEFAULT_TTS_MODEL = "qwen-audio-3.0-tts-flash"
DEFAULT_TTS_VOICE = "longanfengyue"
QWEN3_TTS_ENDPOINT = os.getenv(
    "QWEN3_TTS_ENDPOINT",
    "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation",
)

DEFAULT_MODEL = os.getenv("TTS_MODEL", DEFAULT_TTS_MODEL)
DEFAULT_VOICE = os.getenv("TTS_VOICE", DEFAULT_TTS_VOICE)


def configure_dashscope():
    api_key = os.getenv("DASHSCOPE_API_KEY")
    workspace_id = os.getenv("DASHSCOPE_WORKSPACE_ID")
    if not api_key:
        raise RuntimeError("缺少 DASHSCOPE_API_KEY")
    if not workspace_id:
        raise RuntimeError("缺少 DASHSCOPE_WORKSPACE_ID")
    dashscope.base_http_api_url = (
        f"https://{workspace_id}.cn-beijing.maas.aliyuncs.com/api/v1"
    )
    return api_key


def resolve_tts_identity(
    model: str | None = None,
    voice: str | None = None,
) -> tuple[str, str]:
    resolved_model = str(model or DEFAULT_MODEL).strip() or DEFAULT_TTS_MODEL
    resolved_voice = str(voice or DEFAULT_VOICE).strip() or DEFAULT_TTS_VOICE
    return resolved_model, resolved_voice


def _is_qwen3_tts(model: str) -> bool:
    return "qwen3-tts" in model


def _language_type(dialect: str) -> str:
    dialect = dialect.strip().lower()
    if dialect in {"mandarin", "putonghua", "chinese", "zh"}:
        return "Chinese"
    return "Chinese"


def _format_tts_failure(status: object, payload: object) -> str:
    code = ""
    message = ""
    if isinstance(payload, dict):
        code = str(payload.get("code") or "")
        message = str(payload.get("message") or "")
        if not message:
            message = json.dumps(payload, ensure_ascii=False)
    elif payload:
        message = str(payload)
    parts = [f"status={status}"]
    if code:
        parts.append(f"code={code}")
    if message:
        parts.append(f"message={message}")
    return " ".join(parts)


def _post_qwen3_tts(
    *,
    api_key: str,
    model: str,
    text: str,
    voice: str,
    dialect: str,
    instruction: str,
    timeout: float,
) -> dict:
    body: dict[str, object] = {
        "text": text,
        "voice": voice,
        "language_type": _language_type(dialect),
    }
    if "instruct" in model and instruction:
        body["instructions"] = instruction
    payload = {"model": model, "input": body}
    request = urllib.request.Request(
        QWEN3_TTS_ENDPOINT,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            status = getattr(response, "status", 200)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(detail) if detail else {}
        except json.JSONDecodeError:
            parsed = detail
        raise RuntimeError(_format_tts_failure(exc.code, parsed)) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"status=network message={exc.reason}") from exc

    try:
        result = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(_format_tts_failure(status, raw[:300])) from exc
    if not isinstance(result, dict):
        raise RuntimeError(_format_tts_failure(status, result))
    if result.get("code") and str(result.get("code")).lower() not in {"", "success", "none"}:
        raise RuntimeError(_format_tts_failure(status, result))
    audio = (result.get("output") or {}).get("audio") if isinstance(result.get("output"), dict) else None
    audio_url = audio.get("url") if isinstance(audio, dict) else None
    if not audio_url:
        raise RuntimeError(_format_tts_failure(status, result))
    return {
        "audio_url": str(audio_url),
        "audio_id": audio.get("id") if isinstance(audio, dict) else None,
        "raw": result,
    }


def _resample_wav_16k_mono(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(source),
        "-ar",
        "16000",
        "-ac",
        "1",
        "-c:a",
        "pcm_s16le",
        str(destination),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "ffmpeg failed").strip()
        raise RuntimeError(f"status=ffmpeg message={detail}")


def _synthesize_cosyvoice(
    *,
    api_key: str,
    model: str,
    text: str,
    voice: str,
    speed: float,
    pitch: float,
    volume: int,
    instruction: str,
) -> dict:
    result = HttpSpeechSynthesizer.call(
        model=model,
        text=text,
        voice=voice,
        audio_format="wav",
        sample_rate=16000,
        stream=False,
        api_key=api_key,
        volume=volume,
        rate=speed,
        pitch=pitch,
        language_hints=["zh"],
        instruction=instruction,
    )
    status = getattr(result, "status_code", None)
    audio_url = getattr(result, "audio_url", None)
    if status != 200 or not audio_url:
        raise RuntimeError(
            _format_tts_failure(
                status,
                {
                    "code": getattr(result, "code", "") or "",
                    "message": getattr(result, "message", "") or "",
                },
            )
        )
    return {
        "audio_url": str(audio_url),
        "audio_id": getattr(result, "audio_id", None),
    }


def synthesize_to_file(
    text: str,
    output_path,
    *,
    style="normal",
    dialect="mandarin",
    speed=None,
    pitch=None,
    volume=None,
    emotion=None,
    voice=DEFAULT_VOICE,
    model=DEFAULT_MODEL,
):
    text = str(text).strip()
    if not text:
        raise ValueError("text不能为空")

    style = style.strip().lower()
    if style not in STYLE_PRESETS:
        raise ValueError(f"不支持的style: {style}")

    preset = STYLE_PRESETS[style]
    if speed is None:
        speed = preset["speed"]
    if pitch is None:
        pitch = preset["pitch"]
    if volume is None:
        volume = preset["volume"]
    if emotion is None:
        emotion = preset["emotion"]

    speed = max(0.5, min(2.0, float(speed)))
    pitch = max(0.5, min(2.0, float(pitch)))
    volume = max(0, min(100, int(volume)))
    model, voice = resolve_tts_identity(model, voice)

    api_key = configure_dashscope()
    instruction = build_instruction(dialect=dialect, emotion=emotion)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print(
        "[HostTTS]",
        f"style={style}",
        f"dialect={dialect}",
        f"speed={speed}",
        f"emotion={emotion}",
        f"model={model}",
        f"voice={voice}",
        flush=True,
    )

    start = time.perf_counter()
    if _is_qwen3_tts(model):
        instruction = instruction + delivery_instruction(
            speed=speed,
            pitch=pitch,
            volume=volume,
        )
        result = _post_qwen3_tts(
            api_key=api_key,
            model=model,
            text=text,
            voice=voice,
            dialect=dialect,
            instruction=instruction,
            timeout=90.0,
        )
        api_done = time.perf_counter()
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp:
            temp_path = Path(temp.name)
        try:
            urllib.request.urlretrieve(result["audio_url"], str(temp_path))
            _resample_wav_16k_mono(temp_path, output_path)
        finally:
            temp_path.unlink(missing_ok=True)
    else:
        result = _synthesize_cosyvoice(
            api_key=api_key,
            model=model,
            text=text,
            voice=voice,
            speed=speed,
            pitch=pitch,
            volume=volume,
            instruction=instruction,
        )
        api_done = time.perf_counter()
        urllib.request.urlretrieve(result["audio_url"], str(output_path))

    download_done = time.perf_counter()
    return {
        "audio_path": str(output_path.resolve()),
        "audio_url": result["audio_url"],
        "audio_id": result["audio_id"],
        "api_ms": (api_done - start) * 1000,
        "download_ms": (download_done - api_done) * 1000,
        "tts_total_ms": (download_done - start) * 1000,
        "model": model,
        "voice": voice,
    }

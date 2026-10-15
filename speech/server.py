from __future__ import annotations

import os
import shutil
import subprocess
import time
import uuid
from collections import OrderedDict
from pathlib import Path
from threading import Lock

from fastapi import (
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    Request,
    UploadFile,
)

from fastapi.responses import (
    FileResponse,
)

from pydantic import BaseModel

from speech.asr_cloud import (
    transcribe_file,
)

from speech.tts_cloud import (
    resolve_tts_identity,
    synthesize_to_file,
)


ROOT = Path(
    __file__
).resolve().parent

OUTPUT_DIR = (
    ROOT
    / "output"
)

INPUT_DIR = (
    ROOT
    / "input"
)

OUTPUT_DIR.mkdir(
    parents=True,
    exist_ok=True,
)

INPUT_DIR.mkdir(
    parents=True,
    exist_ok=True,
)


SERVER_VERSION = "1.1.0"
TTS_CACHE_LIMIT = 32
TTS_CACHE: OrderedDict[tuple, dict] = OrderedDict()
TTS_CACHE_LOCK = Lock()


app = FastAPI(
    title="Elder Companion Speech Service",
    version=SERVER_VERSION,
)


# =========================================================
# 可选鉴权
# =========================================================

def check_token(
    token: str | None,
):

    expected = os.getenv(
        "SPEECH_API_TOKEN"
    )

    # 没配置 token 时，
    # 允许局域网内部直接使用。
    if not expected:
        return

    if token != expected:
        raise HTTPException(
            status_code=401,
            detail="Invalid speech API token",
        )


# =========================================================
# Models
# =========================================================

class SpeakRequest(BaseModel):

    text: str
    cache: bool = False

    style: str = "normal"

    dialect: str = "mandarin"

    speed: float | None = None

    pitch: float | None = None

    volume: int | None = None

    emotion: str | None = None

    # 当前中间主机如果有扬声器，
    # 可以设 true。
    #
    # 没有则只生成 WAV。
    play_on_host: bool = False


# =========================================================
# Health
# =========================================================

@app.get("/health")
def health():
    tts_model, tts_voice = resolve_tts_identity()

    return {
        "ok": True,

        "service":
            "elder-companion-speech",

        "version":
            SERVER_VERSION,

        "tts_model": tts_model,
        "tts_voice": tts_voice,
        "tts_cache": {"supported": True, "max_entries": TTS_CACHE_LIMIT},

        "asr_model":
            os.getenv(
                "ASR_MODEL",
                "qwen3-asr-flash",
            ),

        "g1_playback":
            False,
    }


# =========================================================
# TTS / Speak
# =========================================================

@app.post("/speak")
def speak(
    req: SpeakRequest,
    request: Request,
    x_speech_token: str | None = Header(
        default=None
    ),
):

    check_token(
        x_speech_token
    )

    text = req.text.strip()

    if not text:
        raise HTTPException(
            status_code=400,
            detail="text不能为空",
        )

    request_id = (
        uuid.uuid4()
        .hex[:12]
    )

    filename = (
        f"tts_{request_id}.wav"
    )

    output_path = (
        OUTPUT_DIR
        / filename
    )

    total_start = (
        time.perf_counter()
    )
    tts_cache_hit = False
    model, voice = resolve_tts_identity()
    cache_key = (model, voice, text, req.style, req.dialect, req.speed, req.pitch, req.volume, req.emotion)
    result = None
    if req.cache:
        with TTS_CACHE_LOCK:
            cached = TTS_CACHE.get(cache_key)
            if cached is not None and Path(cached["audio_path"]).is_file():
                TTS_CACHE.move_to_end(cache_key)
                result = dict(cached)
                output_path = Path(result["audio_path"])
                filename = output_path.name
                result.update(api_ms=0.0, download_ms=0.0, tts_total_ms=0.0)
                tts_cache_hit = True

    try:

        if result is None:
            result = synthesize_to_file(
                text,
                output_path,

                style=req.style,
                dialect=req.dialect,

                speed=req.speed,
                pitch=req.pitch,
                volume=req.volume,
                emotion=req.emotion,
            )
            if req.cache:
                with TTS_CACHE_LOCK:
                    TTS_CACHE[cache_key] = {**result, "audio_path": str(output_path.resolve())}
                    TTS_CACHE.move_to_end(cache_key)
                    while len(TTS_CACHE) > TTS_CACHE_LIMIT:
                        TTS_CACHE.popitem(last=False)

    except Exception as exc:

        raise HTTPException(
            status_code=500,
            detail=f"TTS失败: {exc}",
        )

    played = False
    host_play_ms = None

    if req.play_on_host:

        player = shutil.which(
            "aplay"
        )

        if not player:

            raise HTTPException(
                status_code=500,
                detail=(
                    "play_on_host=true，"
                    "但主机没有aplay"
                ),
            )

        play_start = (
            time.perf_counter()
        )

        subprocess.run(
            [
                player,
                str(output_path),
            ],
            check=True,
        )

        play_done = (
            time.perf_counter()
        )

        played = True

        host_play_ms = (
            play_done
            - play_start
        ) * 1000

    done = time.perf_counter()

    base_url = str(
        request.base_url
    ).rstrip("/")

    return {
        "ok": True,

        "request_id":
            request_id,

        "text":
            text,

        "style":
            req.style,

        "dialect":
            req.dialect,

        "audio_path":
            str(
                output_path.resolve()
            ),

        "audio_url":
            (
                f"{base_url}"
                f"/audio/{filename}"
            ),

        "played":
            played,

        "g1_played":
            False,
        "tts_cache_hit": tts_cache_hit,

        "tts_api_ms":
            result.get(
                "api_ms"
            ),

        "tts_download_ms":
            result.get(
                "download_ms"
            ),

        "tts_total_ms":
            result.get(
                "tts_total_ms"
            ),

        "host_play_ms":
            host_play_ms,

        "server_total_ms":
            (
                done
                - total_start
            ) * 1000,
    }


# =========================================================
# Audio download
# =========================================================

@app.get("/audio/{filename}")
def get_audio(
    filename: str,
):

    # 防路径穿越
    safe_name = Path(
        filename
    ).name

    if safe_name != filename:
        raise HTTPException(
            status_code=400,
            detail="Invalid filename",
        )

    path = (
        OUTPUT_DIR
        / safe_name
    )

    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail="Audio not found",
        )

    return FileResponse(
        path=str(path),

        media_type="audio/wav",

        filename=safe_name,
    )


# =========================================================
# ASR
# =========================================================

@app.post("/asr")
async def asr(
    file: UploadFile = File(...),

    language: str | None = Form(
        default=None
    ),

    enable_itn: bool = Form(
        default=True
    ),

    x_speech_token: str | None = Header(
        default=None
    ),
):

    check_token(
        x_speech_token
    )

    request_id = (
        uuid.uuid4()
        .hex[:12]
    )

    original_name = (
        Path(
            file.filename
            or "audio.wav"
        ).name
    )

    suffix = (
        Path(
            original_name
        ).suffix
        or ".wav"
    )

    input_path = (
        INPUT_DIR
        /
        f"asr_{request_id}{suffix}"
    )

    try:

        data = await file.read()

        # qwen3-asr-flash
        # 单文件官方限制10MB。
        if len(data) > (
            10 * 1024 * 1024
        ):
            raise HTTPException(
                status_code=413,
                detail=(
                    "音频超过10MB，"
                    "请缩短录音"
                ),
            )

        input_path.write_bytes(
            data
        )

        result = transcribe_file(
            input_path,

            language=language,

            enable_itn=enable_itn,
        )

        return {
            "ok": True,

            "request_id":
                request_id,

            "text":
                result[
                    "text"
                ],

            "language":
                result[
                    "language"
                ],

            "emotion":
                result[
                    "emotion"
                ],

            "asr_ms":
                result[
                    "asr_ms"
                ],

            "model":
                result[
                    "model"
                ],
        }

    except HTTPException:
        raise

    except Exception as exc:

        raise HTTPException(
            status_code=500,
            detail=f"ASR失败: {exc}",
        )

    finally:

        # 临时ASR文件识别结束就删掉。
        try:
            input_path.unlink(
                missing_ok=True
            )
        except Exception:
            pass


if __name__ == "__main__":

    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",

        port=int(
            os.getenv(
                "SPEECH_SERVER_PORT",
                "8780",
            )
        ),
    )

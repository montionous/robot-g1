from __future__ import annotations

import base64
import mimetypes
import os
import time
from pathlib import Path

from openai import OpenAI


DEFAULT_MODEL = os.getenv(
    "ASR_MODEL",
    "qwen3-asr-flash",
)

MAX_AUDIO_BYTES = 10 * 1024 * 1024


def _create_client() -> OpenAI:

    api_key = os.getenv(
        "DASHSCOPE_API_KEY"
    )

    workspace_id = os.getenv(
        "DASHSCOPE_WORKSPACE_ID"
    )

    if not api_key:
        raise RuntimeError(
            "缺少 DASHSCOPE_API_KEY"
        )

    if not workspace_id:
        raise RuntimeError(
            "缺少 DASHSCOPE_WORKSPACE_ID"
        )

    base_url = (
        f"https://{workspace_id}."
        "cn-beijing.maas.aliyuncs.com/"
        "compatible-mode/v1"
    )

    return OpenAI(
        api_key=api_key,
        base_url=base_url,
    )


def transcribe_file(
    audio_path,
    *,
    language=None,
    enable_itn=True,
    model=DEFAULT_MODEL,
):

    audio_path = Path(
        audio_path
    ).resolve()

    if not audio_path.exists():
        raise FileNotFoundError(
            audio_path
        )

    size = audio_path.stat().st_size

    if size > MAX_AUDIO_BYTES:
        raise ValueError(
            "qwen3-asr-flash 单文件不能超过10MB"
        )

    mime_type, _ = mimetypes.guess_type(
        str(audio_path)
    )

    if not mime_type:
        mime_type = "audio/wav"

    audio_base64 = base64.b64encode(
        audio_path.read_bytes()
    ).decode("ascii")

    data_uri = (
        f"data:{mime_type};base64,"
        f"{audio_base64}"
    )

    asr_options = {
        "enable_itn": bool(
            enable_itn
        )
    }

    if language:
        asr_options["language"] = (
            language
        )

    client = _create_client()

    start = time.perf_counter()

    completion = (
        client.chat.completions.create(
            model=model,

            messages=[
                {
                    "role": "user",

                    "content": [
                        {
                            "type":
                                "input_audio",

                            "input_audio": {
                                "data":
                                    data_uri
                            },
                        }
                    ],
                }
            ],

            stream=False,

            extra_body={
                "asr_options":
                    asr_options
            },
        )
    )

    done = time.perf_counter()

    # 转成普通 dict，
    # 避免不同 openai SDK 版本对象访问方式不同。
    payload = completion.model_dump()

    choices = payload.get(
        "choices",
        []
    )

    if not choices:
        raise RuntimeError(
            f"ASR没有返回choices: {payload}"
        )

    message = (
        choices[0]
        .get("message", {})
    )

    text = (
        message.get(
            "content",
            ""
        )
        or ""
    )

    annotations = (
        message.get(
            "annotations",
            []
        )
        or []
    )

    detected_language = None
    emotion = None

    for item in annotations:

        if (
            item.get("type")
            == "audio_info"
        ):

            detected_language = (
                item.get("language")
            )

            emotion = (
                item.get("emotion")
            )

            break

    usage = payload.get(
        "usage",
        {}
    )

    return {
        "text":
            str(text).strip(),

        "language":
            detected_language,

        "emotion":
            emotion,

        "asr_ms":
            (
                done
                - start
            ) * 1000,

        "model":
            model,

        "usage":
            usage,
    }

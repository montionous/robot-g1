#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import urllib.request
from pathlib import Path


SCENE_DIR = Path(__file__).resolve().parent

SCRIPT_PATH = (
    SCENE_DIR
    / "news_scripts.json"
)

OUTPUT_DIR = (
    SCENE_DIR
    / "content"
    / "news"
)

OUTPUT_DIR.mkdir(
    parents=True,
    exist_ok=True,
)


API_KEY = os.environ.get(
    "DASHSCOPE_API_KEY"
)

if not API_KEY:
    raise RuntimeError(
        "DASHSCOPE_API_KEY 未加载。"
        "请先 source ~/.config/elder_companion/cloud.env"
    )


# 默认使用百炼北京区域 Qwen3-TTS HTTP 接口。
# 如果以后需要切换区域，可以通过环境变量覆盖。
ENDPOINT = os.environ.get(
    "QWEN3_TTS_ENDPOINT",
    (
        "https://dashscope.aliyuncs.com"
        "/api/v1/services/aigc/"
        "multimodal-generation/generation"
    ),
)


MODEL = "qwen3-tts-flash"

# 阿闻：专业新闻主持人男声
VOICE = "Neil"


def synthesize(
    text: str,
    output_path: Path,
):
    payload = {
        "model": MODEL,
        "input": {
            "text": text,
            "voice": VOICE,
            "language_type": "Chinese",
        },
    }

    body = json.dumps(
        payload,
        ensure_ascii=False,
    ).encode("utf-8")

    request = urllib.request.Request(
        ENDPOINT,
        data=body,
        method="POST",
        headers={
            "Authorization":
                f"Bearer {API_KEY}",

            "Content-Type":
                "application/json",
        },
    )

    with urllib.request.urlopen(
        request,
        timeout=120,
    ) as response:
        result = json.loads(
            response
            .read()
            .decode("utf-8")
        )

    try:
        audio_url = (
            result["output"]
            ["audio"]
            ["url"]
        )
    except Exception:
        print(
            "TTS 返回内容：",
            json.dumps(
                result,
                ensure_ascii=False,
                indent=2,
            ),
        )

        raise RuntimeError(
            "返回结果中没有音频 URL"
        )

    with tempfile.NamedTemporaryFile(
        suffix=".wav",
        delete=False,
    ) as temp:
        temp_path = Path(
            temp.name
        )

    print(
        "下载临时音频:",
        audio_url,
    )

    urllib.request.urlretrieve(
        audio_url,
        temp_path,
    )

    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(temp_path),
        "-ar",
        "16000",
        "-ac",
        "1",
        "-c:a",
        "pcm_s16le",
        str(output_path),
    ]

    subprocess.run(
        command,
        check=True,
    )

    temp_path.unlink(
        missing_ok=True
    )


def main():
    scripts = json.loads(
        SCRIPT_PATH.read_text(
            encoding="utf-8"
        )
    )

    print(
        "新闻音色:",
        VOICE,
    )

    print(
        "模型:",
        MODEL,
    )

    print()

    for index, item in enumerate(
        scripts,
        start=1,
    ):
        output_path = (
            OUTPUT_DIR
            / f"{item['id']}.wav"
        )

        print(
            f"[{index}/{len(scripts)}]"
            f" {item['title']}"
        )

        synthesize(
            item["text"],
            output_path,
        )

        print(
            "生成完成:",
            output_path,
        )

        print()

    print(
        "全部新闻音频生成完成。"
    )


if __name__ == "__main__":
    main()

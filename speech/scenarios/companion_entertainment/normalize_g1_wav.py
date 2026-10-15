#!/usr/bin/env python3

from __future__ import annotations

import subprocess
import sys
import tempfile
import wave
from pathlib import Path


SAMPLE_RATE = 16000
CHANNELS = 1
SAMPLE_WIDTH = 2


def normalize(path: Path):
    path = path.resolve()

    if not path.exists():
        raise FileNotFoundError(path)

    print(f"处理: {path}")

    with tempfile.NamedTemporaryFile(
        suffix=".raw",
        delete=False,
    ) as temp_raw:
        raw_path = Path(temp_raw.name)

    with tempfile.NamedTemporaryFile(
        suffix=".wav",
        delete=False,
    ) as temp_wav:
        wav_path = Path(temp_wav.name)

    try:
        subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(path),

                # 先输出纯 PCM 裸数据，
                # 避免 ffmpeg 自己生成复杂 WAV 头
                "-f",
                "s16le",

                "-acodec",
                "pcm_s16le",

                "-ar",
                str(SAMPLE_RATE),

                "-ac",
                str(CHANNELS),

                str(raw_path),
            ],
            check=True,
        )

        pcm_data = raw_path.read_bytes()

        # 用 Python wave 模块重新封装。
        # 这样生成的 WAV 与项目里已验证的铃声结构一致。
        with wave.open(
            str(wav_path),
            "wb",
        ) as wav:
            wav.setnchannels(
                CHANNELS
            )

            wav.setsampwidth(
                SAMPLE_WIDTH
            )

            wav.setframerate(
                SAMPLE_RATE
            )

            wav.setcomptype(
                "NONE",
                "not compressed",
            )

            wav.writeframes(
                pcm_data
            )

        # 再读取一次做严格验证
        with wave.open(
            str(wav_path),
            "rb",
        ) as wav:
            assert (
                wav.getnchannels()
                == CHANNELS
            )

            assert (
                wav.getsampwidth()
                == SAMPLE_WIDTH
            )

            assert (
                wav.getframerate()
                == SAMPLE_RATE
            )

            assert (
                wav.getcomptype()
                == "NONE"
            )

        wav_path.replace(
            path
        )

        print(
            "完成: "
            "PCM s16le / "
            "16000 Hz / "
            "mono / "
            "16 bit"
        )

    finally:
        raw_path.unlink(
            missing_ok=True
        )

        wav_path.unlink(
            missing_ok=True
        )


def main():
    if len(sys.argv) < 2:
        print(
            "用法: normalize_g1_wav.py file.wav [file2.wav ...]"
        )
        raise SystemExit(2)

    for filename in sys.argv[1:]:
        normalize(
            Path(filename)
        )


if __name__ == "__main__":
    main()

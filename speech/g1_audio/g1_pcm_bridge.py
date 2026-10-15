from __future__ import annotations

import json
import subprocess
from pathlib import Path


class G1PlaybackError(RuntimeError):
    pass


def play_wav_on_g1(
    bridge_path,
    wav_path,
    *,
    timeout=30.0,
):
    """
    使用已经构建好的 g1_companion_pcm_bridge
    将 WAV 播放到 G1 扬声器。
    """

    bridge_path = (
        Path(bridge_path)
        .expanduser()
        .resolve()
    )

    wav_path = (
        Path(wav_path)
        .expanduser()
        .resolve()
    )

    if not bridge_path.exists():
        raise FileNotFoundError(
            f"G1 PCM bridge 不存在: {bridge_path}"
        )

    if not wav_path.exists():
        raise FileNotFoundError(
            f"WAV 文件不存在: {wav_path}"
        )

    try:
        result = subprocess.run(
            [
                str(bridge_path),
                "--confirm-g1-companion-pcm",
                str(wav_path),
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )

    except subprocess.TimeoutExpired as exc:
        raise G1PlaybackError(
            "G1 PCM 播放超时"
        ) from exc

    if result.returncode != 0:
        raise G1PlaybackError(
            "G1 PCM bridge 播放失败\n"
            f"exit={result.returncode}\n"
            f"stdout={result.stdout}\n"
            f"stderr={result.stderr}"
        )

    try:
        response = json.loads(
            result.stdout
        )

    except json.JSONDecodeError as exc:
        raise G1PlaybackError(
            "G1 PCM bridge 返回的不是合法 JSON\n"
            f"stdout={result.stdout}"
        ) from exc

    if response.get("status") != "completed":
        raise G1PlaybackError(
            "G1 PCM bridge 未完成播放: "
            f"{response}"
        )

    return response

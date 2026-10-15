from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path


def play_wav(path: str | Path) -> None:
    wav_path = Path(path).resolve()
    if not wav_path.exists():
        raise FileNotFoundError(wav_path)

    system = platform.system().lower()

    if system == "windows":
        import winsound
        winsound.PlaySound(str(wav_path), winsound.SND_FILENAME)
        return

    g1_player = os.getenv(
        "G1_WAV_PLAYER",
        "/home/unitree/medication_robot/bin/g1_play_wav",
    )

    if Path(g1_player).exists():
        subprocess.run([g1_player, str(wav_path)], check=True)
        return

    for command in ("aplay", "paplay"):
        try:
            subprocess.run([command, str(wav_path)], check=True)
            return
        except (FileNotFoundError, subprocess.CalledProcessError):
            continue

    raise RuntimeError(
        "当前系统没有可用的 WAV 播放器。机器人端需要实现/配置 G1_WAV_PLAYER。"
    )

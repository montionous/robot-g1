#!/usr/bin/env python3

from __future__ import annotations

import subprocess
import tempfile
import time
import wave
from pathlib import Path


SCENE_DIR = Path(__file__).resolve().parent

SPEECH_ROOT = SCENE_DIR.parents[1]

PROJECT_ROOT = SPEECH_ROOT.parent

BRIDGE = (
    PROJECT_ROOT
    / "build"
    / "g1_companion_pcm_bridge"
)

RUNTIME_DIR = (
    SPEECH_ROOT
    / "runtime"
    / "companion_entertainment"
)

RUNTIME_DIR.mkdir(
    parents=True,
    exist_ok=True,
)

SAMPLE_RATE = 16000
CHANNELS = 1
SAMPLE_WIDTH = 2

MAX_PCM_BYTES = (
    32
    * 1024
    * 1024
)


class G1MediaPlayer:

    def __init__(self):

        self.process = None
        self.current_source = None
        self.current_wav = None
        self._bridge_log = None


    def _cleanup_wav(self):

        if self.current_wav is not None:

            try:
                Path(
                    self.current_wav
                ).unlink(
                    missing_ok=True
                )

            except Exception:
                pass

        self.current_wav = None


    def _prepare_wav(
        self,
        source,
    ):
        source = Path(
            source
        ).resolve()

        if not source.exists():
            raise FileNotFoundError(
                source
            )

        print(
            "媒体转换:",
            source.name,
        )

        raw_file = (
            tempfile.NamedTemporaryFile(
                prefix="g1_media_",
                suffix=".raw",
                dir=RUNTIME_DIR,
                delete=False,
            )
        )

        raw_file.close()

        raw_path = Path(
            raw_file.name
        )

        wav_file = (
            tempfile.NamedTemporaryFile(
                prefix="g1_media_",
                suffix=".wav",
                dir=RUNTIME_DIR,
                delete=False,
            )
        )

        wav_file.close()

        wav_path = Path(
            wav_file.name
        )

        try:

            subprocess.run(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",

                    "-i",
                    str(source),

                    # MP4 等文件只取音频
                    "-vn",

                    "-f",
                    "s16le",

                    "-acodec",
                    "pcm_s16le",

                    "-ar",
                    str(
                        SAMPLE_RATE
                    ),

                    "-ac",
                    str(
                        CHANNELS
                    ),

                    str(
                        raw_path
                    ),
                ],
                check=True,
            )

            pcm = raw_path.read_bytes()

            if not pcm:
                raise RuntimeError(
                    "ffmpeg 没有产生 PCM 数据"
                )

            if len(pcm) > MAX_PCM_BYTES:

                seconds = (
                    len(pcm)
                    / (
                        SAMPLE_RATE
                        * CHANNELS
                        * SAMPLE_WIDTH
                    )
                )

                raise RuntimeError(
                    "媒体文件过长："
                    f"{seconds:.1f} 秒，"
                    f"PCM={len(pcm)} bytes"
                )

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
                    pcm
                )

            seconds = (
                len(pcm)
                / (
                    SAMPLE_RATE
                    * CHANNELS
                    * SAMPLE_WIDTH
                )
            )

            print(
                "媒体准备完成:",
                f"{seconds:.1f} 秒",
            )

            return wav_path

        finally:

            raw_path.unlink(
                missing_ok=True
            )


    def is_playing(self):

        return (
            self.process is not None
            and self.process.poll() is None
        )


    def play(
        self,
        source,
    ):
        self.stop(
            quiet=True
        )

        wav_path = self._prepare_wav(
            source
        )

        self.current_source = (
            Path(source).resolve()
        )

        self.current_wav = wav_path

        print(
            "开始后台播放:",
            self.current_source.name,
        )

        log_path = (
            RUNTIME_DIR
            / "g1_media_bridge.log"
        )

        self._bridge_log = log_path.open(
            "ab"
        )

        self.process = subprocess.Popen(
            [
                str(BRIDGE),
                "--confirm-g1-companion-pcm",
                str(wav_path),
            ],
            stdout=self._bridge_log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

        # 给 bridge 一点时间完成初始化。
        # 如果它立即退出，就不能把状态报告成 playing。
        time.sleep(0.35)

        return_code = self.process.poll()

        if return_code is not None:
            self._bridge_log.flush()
            self._bridge_log.close()
            self._bridge_log = None

            try:
                detail = (
                    log_path
                    .read_text(
                        encoding="utf-8",
                        errors="replace",
                    )
                    [-2000:]
                )
            except Exception:
                detail = ""

            self.process = None

            raise RuntimeError(
                "G1媒体播放 bridge 启动失败，"
                f"returncode={return_code}\n"
                f"{detail}"
            )

        return {
            "status": "playing",
            "source": str(
                self.current_source
            ),
        }


    def stop(
        self,
        *,
        quiet=False,
    ):

        if (
            self.process is not None
            and self.process.poll() is None
        ):

            if not quiet:
                print(
                    "停止当前媒体"
                )

            self.process.terminate()

            try:
                self.process.wait(
                    timeout=2.0
                )

            except subprocess.TimeoutExpired:

                self.process.kill()

                self.process.wait(
                    timeout=2.0
                )

        self.process = None
        self.current_source = None

        if self._bridge_log is not None:
            try:
                self._bridge_log.flush()
                self._bridge_log.close()
            except Exception:
                pass

            self._bridge_log = None

        self._cleanup_wav()

        time.sleep(
            0.15
        )


    def wait(self):

        if self.process is None:
            return

        self.process.wait()

        self.process = None

        self._cleanup_wav()


    def status(self):

        return {
            "playing":
                self.is_playing(),

            "source":
                (
                    str(
                        self.current_source
                    )
                    if self.current_source
                    else None
                ),
        }


if __name__ == "__main__":

    print(
        "G1MediaPlayer 模块加载正常"
    )

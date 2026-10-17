#!/usr/bin/env python3

from __future__ import annotations

import os
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests


# =========================================================
# 路径
# =========================================================

SPEECH_ROOT = (
    Path(__file__).resolve().parent
)

PROJECT_ROOT = (
    SPEECH_ROOT.parent
)

DEFAULT_G1_PCM_BRIDGE = (
    PROJECT_ROOT
    / "build"
    / "g1_companion_pcm_bridge"
)

DEFAULT_INPUT_DIR = (
    SPEECH_ROOT
    / "input"
)


# =========================================================
# 情绪中文名称
# =========================================================

EMOTION_ZH = {
    "neutral": "平静",
    "happy": "开心",
    "sad": "悲伤",
    "angry": "生气",
    "fearful": "恐惧",
    "surprised": "惊讶",
    "disgusted": "厌恶",
}


class SpeechClientError(RuntimeError):
    pass


class SpeechClient:
    """
    老年陪伴机器人统一语音接口。

    对队友提供：

    1. health()
       检查语音服务

    2. speak(...)
       云TTS，兼容旧接口

    3. transcribe(...)
       识别已有音频文件

    4. listen_g1(...)
       G1麦克风录音 + ASR

    5. speak_g1(...)
       云TTS + G1扬声器播放

    6. play_g1(...)
       播放已有WAV到G1

    队友不需要直接调用：
    - DashScope
    - UDP multicast
    - g1_companion_pcm_bridge
    """

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8780",
        *,
        timeout: float = 90.0,
        g1_pcm_bridge: Optional[str] = None,
    ):
        self.base_url = (
            base_url.rstrip("/")
        )

        self.timeout = timeout

        if g1_pcm_bridge:
            self.g1_pcm_bridge = Path(
                g1_pcm_bridge
            ).expanduser()
        else:
            env_bridge = os.getenv(
                "G1_PCM_BRIDGE"
            )

            if env_bridge:
                self.g1_pcm_bridge = Path(
                    env_bridge
                ).expanduser()
            else:
                self.g1_pcm_bridge = (
                    DEFAULT_G1_PCM_BRIDGE
                )

        token = os.getenv(
            "SPEECH_API_TOKEN"
        )

        self.headers = {}

        if token:
            self.headers[
                "X-Speech-Token"
            ] = token

    # =====================================================
    # 健康检查
    # =====================================================

    def health(self) -> dict:
        response = requests.get(
            f"{self.base_url}/health",
            headers=self.headers,
            timeout=5,
        )

        response.raise_for_status()

        return response.json()

    # =====================================================
    # TTS
    # =====================================================

    def speak(
        self,
        text: str,
        *,
        style: str = "normal",
        dialect: str = "mandarin",
        speed: Optional[float] = None,
        pitch: Optional[float] = None,
        volume: Optional[int] = None,
        emotion: Optional[str] = None,
        play_on_host: bool = False,
        cache: bool = False,
    ) -> dict:
        """
        生成TTS语音。

        play_on_host=True:
            在中间主机播放。

        play_on_host=False:
            只生成WAV。

        注意：
        要让G1直接说，请优先使用 speak_g1()。
        """

        if not isinstance(text, str):
            raise TypeError(
                "text 必须是字符串"
            )

        text = text.strip()

        if not text:
            raise ValueError(
                "text 不能为空"
            )

        payload = {
            "text": text,
            "style": style,
            "dialect": dialect,
            "play_on_host":
                play_on_host,
            "cache": cache,
        }

        if speed is not None:
            payload["speed"] = speed

        if pitch is not None:
            payload["pitch"] = pitch

        if volume is not None:
            payload["volume"] = volume

        if emotion is not None:
            payload["emotion"] = emotion

        response = requests.post(
            f"{self.base_url}/speak",
            headers=self.headers,
            json=payload,
            timeout=self.timeout,
        )

        response.raise_for_status()

        result = response.json()

        if (
            not isinstance(result, dict)
            or result.get("ok") is not True
        ):
            raise SpeechClientError(
                f"TTS服务返回异常: {result}"
            )

        return result

    # =====================================================
    # ASR：识别已有文件
    # =====================================================

    def transcribe(
        self,
        audio_path,
        *,
        language: Optional[str] = None,
        enable_itn: bool = True,
    ) -> dict:
        """
        识别已有音频文件。
        """

        path = Path(
            audio_path
        ).expanduser()

        if not path.exists():
            raise FileNotFoundError(
                f"音频文件不存在: {path}"
            )

        data = {
            "enable_itn":
                str(
                    enable_itn
                ).lower(),
        }

        if language:
            data["language"] = language

        with path.open(
            "rb"
        ) as audio_file:

            response = requests.post(
                f"{self.base_url}/asr",

                headers=self.headers,

                files={
                    "file": (
                        path.name,
                        audio_file,
                        "application/octet-stream",
                    )
                },

                data=data,

                timeout=self.timeout,
            )

        response.raise_for_status()

        result = response.json()

        if not isinstance(
            result,
            dict,
        ):
            raise SpeechClientError(
                "ASR服务返回格式错误"
            )

        emotion = result.get(
            "emotion"
        )

        result["emotion_zh"] = (
            EMOTION_ZH.get(
                emotion,
                emotion,
            )
        )

        return result

    # =====================================================
    # ASR：内存音频
    # =====================================================

    def transcribe_bytes(
        self,
        audio_data: bytes,
        *,
        filename: str = "audio.wav",
        language: Optional[str] = None,
        enable_itn: bool = True,
    ) -> dict:

        if not isinstance(
            audio_data,
            bytes,
        ):
            raise TypeError(
                "audio_data 必须是 bytes"
            )

        data = {
            "enable_itn":
                str(
                    enable_itn
                ).lower(),
        }

        if language:
            data["language"] = language

        response = requests.post(
            f"{self.base_url}/asr",

            headers=self.headers,

            files={
                "file": (
                    filename,
                    audio_data,
                    "application/octet-stream",
                )
            },

            data=data,

            timeout=self.timeout,
        )

        response.raise_for_status()

        result = response.json()

        emotion = result.get(
            "emotion"
        )

        result["emotion_zh"] = (
            EMOTION_ZH.get(
                emotion,
                emotion,
            )
        )

        return result

    # =====================================================
    # G1：录音
    # =====================================================

    def record_g1(
        self,
        *,
        seconds: float = 5.0,
        output_path=None,
        interface_ip: Optional[str] = None,
    ) -> dict:
        """
        从G1麦克风录制音频。

        只负责录音，不做ASR。
        """

        from g1_audio.g1_mic_recorder import (
            record_g1_wav,
        )

        if seconds <= 0:
            raise ValueError(
                "seconds 必须大于0"
            )

        if output_path is None:

            DEFAULT_INPUT_DIR.mkdir(
                parents=True,
                exist_ok=True,
            )

            timestamp = (
                datetime.now()
                .strftime(
                    "%Y%m%d_%H%M%S_%f"
                )
            )

            output_path = (
                DEFAULT_INPUT_DIR
                / (
                    "g1_mic_"
                    + timestamp
                    + ".wav"
                )
            )

        return record_g1_wav(
            output_path,
            seconds=seconds,
            interface_ip=
                interface_ip,
        )

    # =====================================================
    # G1：听 + ASR
    # =====================================================

    def listen_g1(
        self,
        *,
        seconds: float = 5.0,
        output_path=None,
        interface_ip: Optional[str] = None,
        language: Optional[str] = None,
        enable_itn: bool = True,
        wait_for_speech: bool = False,
        start_timeout: float = 12.0,
        silence_timeout: float = 1.8,
        speech_rms_threshold: int = 450,
        delete_audio_after_transcribe: bool = False,
    ) -> dict:
        """
        队友最常用的“机器人听”。

        默认保持原有固定时长录音行为。

        wait_for_speech=True 时：
        先等待检测到老人开口，
        再开始计算 seconds，
        并支持说完后的静音自动结束。

        delete_audio_after_transcribe=True 时，只删除本次自动创建的
        临时录音。显式传入 output_path 的调用仍由调用方保留和管理。
        """

        auto_output_path = output_path is None
        recording = None
        result = None

        try:
            if wait_for_speech:

                from g1_audio.g1_mic_recorder import (
                    record_g1_wav,
                )

                if output_path is None:

                    import tempfile

                    DEFAULT_INPUT_DIR.mkdir(
                        parents=True,
                        exist_ok=True,
                    )

                    temp = (
                        tempfile.NamedTemporaryFile(
                            prefix="g1_mic_",
                            suffix=".wav",
                            dir=DEFAULT_INPUT_DIR,
                            delete=False,
                        )
                    )

                    temp.close()

                    output_path = (
                        temp.name
                    )

                recording = record_g1_wav(
                    output_path,
                    seconds=seconds,
                    interface_ip=
                        interface_ip,
                    wait_for_speech=True,
                    start_timeout=
                        start_timeout,
                    silence_timeout=
                        silence_timeout,
                    speech_rms_threshold=
                        speech_rms_threshold,
                )

            else:

                recording = self.record_g1(
                    seconds=seconds,
                    output_path=output_path,
                    interface_ip=
                        interface_ip,
                )

            # 等待超时但老人没有开口时，
            # 不把环境静音送给 ASR。
            if (
                wait_for_speech
                and not recording.get(
                    "speech_detected",
                    False,
                )
            ):

                result = {
                    "text":
                        "",

                    "audio_path":
                        recording[
                            "path"
                        ],

                    "recording":
                        recording,

                    "source":
                        "g1",

                    "speech_detected":
                        False,
                }

                return result

            asr_started_at = time.monotonic()
            result = self.transcribe(
                recording["path"],
                language=language,
                enable_itn=enable_itn,
            )

            result["asr_wall_ms"] = (
                time.monotonic()
                - asr_started_at
            ) * 1000

            result["audio_path"] = (
                recording["path"]
            )

            result["recording"] = (
                recording
            )

            result["source"] = "g1"

            result["speech_detected"] = (
                recording.get(
                    "speech_detected",
                    True,
                )
            )

            return result

        finally:
            if (
                delete_audio_after_transcribe
                and auto_output_path
            ):
                cleanup_path = (
                    recording.get(
                        "path"
                    )
                    if recording is not None
                    else output_path
                )

                deleted = False

                if cleanup_path:
                    try:
                        Path(cleanup_path).unlink(
                            missing_ok=True
                        )
                        deleted = True
                    except OSError:
                        pass

                if result is not None and deleted:
                    result["audio_path"] = None
                    result["audio_deleted"] = True

                    cleaned_recording = dict(
                        recording
                    )
                    cleaned_recording["path"] = None
                    cleaned_recording["audio_deleted"] = True
                    result["recording"] = cleaned_recording


    # =====================================================
    # G1：播放已有WAV
    # =====================================================

    def play_g1(
        self,
        audio_path,
        *,
        bridge_path=None,
        timeout: float = 30.0,
    ) -> dict:
        """
        将已有WAV播放到G1扬声器。
        """

        from g1_audio.g1_pcm_bridge import (
            play_wav_on_g1,
        )

        path = Path(
            audio_path
        ).expanduser()

        if not path.is_absolute():

            candidate = (
                SPEECH_ROOT
                / path
            )

            if candidate.exists():
                path = candidate

        if not path.exists():
            raise FileNotFoundError(
                f"WAV不存在: {path}"
            )

        bridge = (
            Path(
                bridge_path
            ).expanduser()
            if bridge_path
            else self.g1_pcm_bridge
        )

        if not bridge.exists():
            raise FileNotFoundError(
                "找不到G1 PCM bridge: "
                f"{bridge}"
            )

        return play_wav_on_g1(
            bridge,
            path,
            timeout=timeout,
        )

    # =====================================================
    # G1：TTS + 播放
    # =====================================================

    def speak_g1(
        self,
        text: str,
        *,
        style: str = "normal",
        dialect: str = "mandarin",
        speed: Optional[float] = None,
        pitch: Optional[float] = None,
        volume: Optional[int] = None,
        emotion: Optional[str] = None,
        bridge_path=None,
        cache: bool = False,
    ) -> dict:
        """
        队友最常用的“机器人说”。

        text
          ↓
        云TTS
          ↓
        WAV
          ↓
        G1 PCM bridge
          ↓
        G1扬声器
        """

        tts_result = self.speak(
            text,

            style=style,
            dialect=dialect,

            speed=speed,
            pitch=pitch,
            volume=volume,
            emotion=emotion,

            # G1播放时，中间主机不要同时播。
            play_on_host=False,

            # 动态回复仍可使用服务端的短期缓存；
            # 赛前已准备好的固定话术由 prepared_audio.py
            # 直接播放本地WAV，不会走这里。
            cache=cache,
        )

        audio_path = (
            tts_result.get(
                "audio_path"
            )
        )

        if not audio_path:
            raise SpeechClientError(
                "TTS成功但没有返回 audio_path"
            )

        playback = self.play_g1(
            audio_path,
            bridge_path=
                bridge_path,
        )

        result = dict(
            tts_result
        )

        result[
            "g1_played"
        ] = True

        result[
            "g1_playback"
        ] = playback

        return result


if __name__ == "__main__":

    speech = SpeechClient()

    print(
        speech.health()
    )

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .playback import play_wav
from .presets import STYLE_PRESETS
from .tts_cloud import synthesize_to_file


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT / "output"


def speak_to_file(
    text: str,
    *,
    style: str = "normal",
    dialect: str = "mandarin",
    speed: float | None = None,
    pitch: float | None = None,
    volume: int | None = None,
    emotion: str | None = None,
    output_path: str | Path | None = None,
    voice: str | None = None,
) -> dict:
    style_key = str(style).strip().lower()
    if style_key not in STYLE_PRESETS:
        raise ValueError(
            f"不支持的 style={style!r}，可选：{', '.join(STYLE_PRESETS)}"
        )

    preset = STYLE_PRESETS[style_key]
    final_speed = preset["speed"] if speed is None else speed
    final_pitch = preset["pitch"] if pitch is None else pitch
    final_volume = preset["volume"] if volume is None else volume
    final_emotion = preset["emotion"] if emotion is None else emotion

    if output_path is None:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        output_path = OUTPUT_DIR / f"tts_{stamp}.wav"

    kwargs = {}
    if voice:
        kwargs["voice"] = voice

    return synthesize_to_file(
        text,
        output_path,
        dialect=dialect,
        emotion=final_emotion,
        speed=final_speed,
        pitch=final_pitch,
        volume=final_volume,
        **kwargs,
    )


def speak(
    text: str,
    *,
    style: str = "normal",
    dialect: str = "mandarin",
    speed: float | None = None,
    pitch: float | None = None,
    volume: int | None = None,
    emotion: str | None = None,
    voice: str | None = None,
) -> dict:
    result = speak_to_file(
        text,
        style=style,
        dialect=dialect,
        speed=speed,
        pitch=pitch,
        volume=volume,
        emotion=emotion,
        voice=voice,
    )
    play_wav(result["audio_path"])
    return result


def listen(
    *,
    output_path: str | None = None,
    **record_kwargs,
) -> dict:
    """
    机器人项目中的统一听取接口。

    依赖已有项目模块：
        asr.recorder.record_until_silence
        asr.recognize.recognize_audio

    Windows 独立 TTS 测试包没有这两个模块，因此该函数主要
    用于将本 speech/ 目录复制进 medication_robot 后调用。
    """
    try:
        from asr.recorder import record_until_silence
        from asr.recognize import recognize_audio
    except ImportError as exc:
        raise RuntimeError(
            "listen() 需要运行在现有机器人项目中，"
            "并确保 asr.recorder / asr.recognize 可导入。"
        ) from exc

    if output_path is None:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        output_path = str(
            PROJECT_ROOT
            / "audio"
            / "input"
            / f"speech_service_{stamp}.wav"
        )

    audio_path = record_until_silence(
        output_path=output_path,
        **record_kwargs,
    )

    if not audio_path:
        return {
            "text": "",
            "emotion": None,
            "audio_path": None,
            "ok": False,
        }

    text = recognize_audio(audio_path)

    return {
        "text": str(text).strip(),
        # 现有 ASR 暂未统一输出 emotion。
        # 后续切换 qwen3-asr-flash-realtime 后在这里填真实情绪。
        "emotion": None,
        "audio_path": str(audio_path),
        "ok": bool(str(text).strip()),
    }

from __future__ import annotations

import audioop

from .g1_mic_recorder import (
    CHANNELS,
    SAMPLE_RATE,
    SAMPLE_WIDTH,
)


def analyze_pcm16(
    pcm: bytes,
    *,
    sample_rate: int = SAMPLE_RATE,
    channels: int = CHANNELS,
    sample_width: int = SAMPLE_WIDTH,
    threshold_rms: int = 450,
    frame_ms: int = 20,
    min_consecutive_frames: int = 3,
) -> dict:
    """Return deterministic RMS/VAD metadata for mono PCM16 audio.

    This deliberately matches the lightweight rule used by ``record_g1_wav``:
    a voice starts after three consecutive 20 ms frames reach the RMS threshold.
    It is an audio gate, not a speaker-identification mechanism, so scene-level
    intent and state checks must still decide whether a transcript is actionable.
    """

    if not isinstance(pcm, (bytes, bytearray, memoryview)):
        raise TypeError("pcm must be bytes-like")

    if (
        not isinstance(sample_rate, int)
        or sample_rate <= 0
        or not isinstance(channels, int)
        or channels <= 0
        or not isinstance(sample_width, int)
        or sample_width != 2
    ):
        raise ValueError("PCM16 format must use positive sample_rate/channels and sample_width=2")

    if (
        not isinstance(threshold_rms, int)
        or not 1 <= threshold_rms <= 32767
    ):
        raise ValueError("threshold_rms must be an integer in [1, 32767]")

    if not isinstance(frame_ms, int) or not 1 <= frame_ms <= 1000:
        raise ValueError("frame_ms must be an integer in [1, 1000]")

    if (
        not isinstance(min_consecutive_frames, int)
        or min_consecutive_frames < 1
    ):
        raise ValueError("min_consecutive_frames must be at least 1")

    data = bytes(pcm)

    if len(data) % sample_width:
        data = data[:-(len(data) % sample_width)]

    bytes_per_second = (
        sample_rate
        * channels
        * sample_width
    )

    frame_bytes = int(
        bytes_per_second
        * frame_ms
        / 1000
    )

    frame_bytes -= frame_bytes % sample_width

    if frame_bytes <= 0:
        raise ValueError("frame_ms produced an empty PCM frame")

    frame_count = len(data) // frame_bytes
    max_rms = 0
    voiced_frames = 0
    consecutive = 0
    max_consecutive = 0
    trailing_silence_frames = 0

    for offset in range(
        0,
        frame_count * frame_bytes,
        frame_bytes,
    ):
        level = audioop.rms(
            data[offset:offset + frame_bytes],
            sample_width,
        )

        max_rms = max(max_rms, level)

        if level >= threshold_rms:
            voiced_frames += 1
            consecutive += 1
            max_consecutive = max(
                max_consecutive,
                consecutive,
            )
            trailing_silence_frames = 0
        else:
            consecutive = 0
            trailing_silence_frames += 1

    audio_seconds = len(data) / bytes_per_second
    voiced_seconds = voiced_frames * frame_ms / 1000
    trailing_silence_seconds = (
        trailing_silence_frames
        * frame_ms
        / 1000
    )

    speech_detected = (
        max_consecutive
        >= min_consecutive_frames
    )

    if not frame_count:
        reason = "empty"
    elif speech_detected:
        reason = "accepted"
    else:
        reason = "insufficient_consecutive_voice"

    return {
        "enabled": True,
        "speech_detected": speech_detected,
        "reason": reason,
        "threshold_rms": threshold_rms,
        "frame_ms": frame_ms,
        "frame_count": frame_count,
        "voiced_frames": voiced_frames,
        "voiced_ratio": (
            voiced_frames / frame_count
            if frame_count
            else 0.0
        ),
        "voiced_seconds": voiced_seconds,
        "max_consecutive_voiced_frames": max_consecutive,
        "max_rms": max_rms,
        "trailing_silence_seconds": trailing_silence_seconds,
        "audio_seconds": audio_seconds,
    }

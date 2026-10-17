"""Persistent, scene-owned audio for short fixed robot prompts.

The speech server has an in-memory TTS cache, but that cache is empty after a
restart and still has to synthesize the first request.  This module keeps the
small set of stable prompts that a scene can prepare before a demonstration
separate from dynamic replies that must be synthesized at runtime.

Prepared audio is matched by the complete spoken specification: text, style,
dialect and voice controls.  A Mandarin file can therefore never be used for a
Shaanxi-dialect reply just because the written text happens to be identical.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SPEECH_ROOT = Path(__file__).resolve().parents[1]
_IDENTIFIER_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")


def _normalise_text(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError("预生成话术 text 不能为空")
    return text


def _normalise_name(value: object, *, field: str) -> str:
    name = str(value or "").strip().lower()
    if not _IDENTIFIER_RE.fullmatch(name):
        raise ValueError(
            f"预生成话术 {field} 只能使用小写字母、数字、点、下划线或短横线: {value!r}"
        )
    return name


def _normalise_style(value: object) -> str:
    style = str(value or "").strip().lower()
    if not style:
        raise ValueError("预生成话术 style 不能为空")
    return style


def _normalise_dialect(value: object) -> str:
    dialect = str(value or "").strip().lower()
    if not dialect:
        raise ValueError("预生成话术 dialect 不能为空")
    return dialect


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    return float(value)


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    return int(value)


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


@dataclass(frozen=True)
class PreparedPrompt:
    """One immutable prompt declared by a scene manifest."""

    scene: str
    prompt_id: str
    text: str
    style: str
    dialect: str
    voice_profile: str
    speed: float | None = None
    pitch: float | None = None
    volume: int | None = None
    emotion: str | None = None

    def specification(self) -> dict[str, Any]:
        return {
            "scene": self.scene,
            "id": self.prompt_id,
            "text": self.text,
            "style": self.style,
            "dialect": self.dialect,
            "voice_profile": self.voice_profile,
            "speed": self.speed,
            "pitch": self.pitch,
            "volume": self.volume,
            "emotion": self.emotion,
        }

    @property
    def fingerprint(self) -> str:
        encoded = json.dumps(
            self.specification(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @property
    def signature(self) -> tuple[object, ...]:
        return (
            self.text,
            self.style,
            self.dialect,
            self.speed,
            self.pitch,
            self.volume,
            self.emotion,
        )


def resolve_prepared_audio_root(audio_root: str | Path | None = None) -> Path:
    """Return the deployment-local directory for generated prompt WAVs.

    The default is deliberately under ``speech/runtime`` so generated audio,
    metadata and voice recordings stay out of Git.  A deployment may set
    ``G1_PREPARED_AUDIO_DIR`` when it keeps prepared assets on another disk.
    """

    raw = audio_root or os.getenv("G1_PREPARED_AUDIO_DIR")
    if raw:
        return Path(raw).expanduser().resolve()
    return (SPEECH_ROOT / "runtime" / "prepared_audio").resolve()


def prepared_audio_path(prompt: PreparedPrompt, audio_root: str | Path | None = None) -> Path:
    root = resolve_prepared_audio_root(audio_root)
    return root / prompt.scene / f"{prompt.prompt_id}-{prompt.fingerprint[:16]}.wav"


def prepared_metadata_path(audio_path: str | Path) -> Path:
    return Path(audio_path).with_suffix(".json")


def validate_prepared_wav(audio_path: str | Path) -> str | None:
    """Return ``None`` for a G1-compatible WAV, otherwise a short reason."""

    path = Path(audio_path)
    if not path.is_file():
        return "missing"

    try:
        with wave.open(str(path), "rb") as audio:
            if audio.getnchannels() != 1:
                return "not_mono"
            if audio.getsampwidth() != 2:
                return "not_pcm16"
            if audio.getframerate() != 16000:
                return "not_16khz"
            if audio.getcomptype() != "NONE":
                return "compressed"
            if audio.getnframes() <= 0:
                return "empty"
    except (EOFError, OSError, wave.Error):
        return "invalid_wav"

    return None


class PreparedPromptCatalog:
    """Load one scene's prepared-prompt manifest and play exact matches."""

    def __init__(
        self,
        manifest_path: str | Path,
        *,
        audio_root: str | Path | None = None,
    ) -> None:
        self.manifest_path = Path(manifest_path).expanduser().resolve()
        self.audio_root = resolve_prepared_audio_root(audio_root)
        data = self._load_manifest()

        if data.get("schema_version") != 1:
            raise ValueError(
                f"不支持的预生成话术清单版本: {data.get('schema_version')!r}"
            )

        self.scene = _normalise_name(data.get("scene"), field="scene")
        self.voice_profile = str(data.get("voice_profile") or "default").strip()
        if not self.voice_profile:
            raise ValueError("预生成话术 voice_profile 不能为空")

        raw_prompts = data.get("prompts")
        if not isinstance(raw_prompts, list) or not raw_prompts:
            raise ValueError("预生成话术清单 prompts 必须是非空列表")

        prompts: list[PreparedPrompt] = []
        ids: set[str] = set()
        signatures: set[tuple[object, ...]] = set()
        for index, raw in enumerate(raw_prompts, start=1):
            if not isinstance(raw, dict):
                raise ValueError(f"预生成话术第 {index} 项必须是对象")

            prompt = PreparedPrompt(
                scene=self.scene,
                prompt_id=_normalise_name(raw.get("id"), field="id"),
                text=_normalise_text(raw.get("text")),
                style=_normalise_style(raw.get("style", "companion")),
                dialect=_normalise_dialect(raw.get("dialect", "mandarin")),
                voice_profile=self.voice_profile,
                speed=_optional_float(raw.get("speed")),
                pitch=_optional_float(raw.get("pitch")),
                volume=_optional_int(raw.get("volume")),
                emotion=_optional_text(raw.get("emotion")),
            )

            if prompt.prompt_id in ids:
                raise ValueError(f"预生成话术 id 重复: {prompt.prompt_id}")
            if prompt.signature in signatures:
                raise ValueError(
                    "预生成话术的文本、风格、方言和参数组合重复: "
                    f"{prompt.prompt_id}"
                )

            ids.add(prompt.prompt_id)
            signatures.add(prompt.signature)
            prompts.append(prompt)

        self.prompts = tuple(prompts)
        self._by_signature = {
            prompt.signature: prompt
            for prompt in self.prompts
        }

    def _load_manifest(self) -> dict[str, Any]:
        try:
            raw = self.manifest_path.read_text(encoding="utf-8")
        except OSError as error:
            raise RuntimeError(f"无法读取预生成话术清单: {self.manifest_path}") from error

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as error:
            raise ValueError(f"预生成话术清单不是有效 JSON: {self.manifest_path}") from error

        if not isinstance(data, dict):
            raise ValueError("预生成话术清单根节点必须是对象")
        return data

    def find(
        self,
        text: str,
        *,
        style: str = "companion",
        dialect: str = "mandarin",
        speed: float | None = None,
        pitch: float | None = None,
        volume: int | None = None,
        emotion: str | None = None,
    ) -> PreparedPrompt | None:
        signature = (
            _normalise_text(text),
            _normalise_style(style),
            _normalise_dialect(dialect),
            _optional_float(speed),
            _optional_float(pitch),
            _optional_int(volume),
            _optional_text(emotion),
        )
        return self._by_signature.get(signature)

    def audio_path_for(self, prompt: PreparedPrompt) -> Path:
        return prepared_audio_path(prompt, self.audio_root)

    def prepared_status(self, prompt: PreparedPrompt) -> tuple[Path, str | None]:
        path = self.audio_path_for(prompt)
        return path, validate_prepared_wav(path)

    def play_or_speak(
        self,
        speech: Any,
        text: str,
        *,
        style: str = "companion",
        dialect: str = "mandarin",
        speed: float | None = None,
        pitch: float | None = None,
        volume: int | None = None,
        emotion: str | None = None,
        bridge_path: str | Path | None = None,
    ) -> dict[str, Any]:
        """Play a valid prepared WAV, or synthesize only when no file fits.

        Playback errors deliberately propagate.  Falling back after a bridge
        failure can make the robot repeat a whole sentence after it already
        played part of it.  Only a missing or invalid file falls back to TTS.
        """

        clean_text = _normalise_text(text)
        prompt = self.find(
            clean_text,
            style=style,
            dialect=dialect,
            speed=speed,
            pitch=pitch,
            volume=volume,
            emotion=emotion,
        )

        fallback_reason = "not_registered"
        if prompt is not None:
            audio_path, invalid_reason = self.prepared_status(prompt)
            if invalid_reason is None:
                playback = speech.play_g1(
                    audio_path,
                    bridge_path=bridge_path,
                )
                return {
                    "ok": True,
                    "text": clean_text,
                    "style": _normalise_style(style),
                    "dialect": _normalise_dialect(dialect),
                    "audio_path": str(audio_path),
                    "audio_source": "prepared",
                    "prepared_prompt_id": prompt.prompt_id,
                    "prepared_prompt_fingerprint": prompt.fingerprint,
                    "tts_cache_hit": False,
                    "tts_total_ms": 0.0,
                    "g1_played": True,
                    "g1_playback": playback,
                }
            fallback_reason = invalid_reason

        result = speech.speak_g1(
            clean_text,
            style=style,
            dialect=dialect,
            speed=speed,
            pitch=pitch,
            volume=volume,
            emotion=emotion,
            bridge_path=bridge_path,
            cache=True,
        )
        response = dict(result or {})
        response["audio_source"] = "runtime_tts"
        response["prepared_prompt_id"] = (
            prompt.prompt_id
            if prompt is not None
            else None
        )
        response["prepared_audio_reason"] = fallback_reason
        return response


def prepared_metadata(
    prompt: PreparedPrompt,
    *,
    tts_result: dict[str, Any],
) -> dict[str, Any]:
    """Metadata written next to a generated WAV for review and regeneration."""

    return {
        "schema_version": 1,
        "prepared_prompt_id": prompt.prompt_id,
        "fingerprint": prompt.fingerprint,
        "specification": prompt.specification(),
        "tts_model": tts_result.get("model"),
        "tts_voice": tts_result.get("voice"),
    }

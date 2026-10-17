#!/usr/bin/env python3

"""Generate persistent WAVs for fixed scene prompts.

Run this on the robot-side host while the local speech service is running.  It
uses the same service, TTS model, voice and dialect instructions as live
speech, then atomically publishes G1-compatible WAVs under
``speech/runtime/prepared_audio`` (or ``G1_PREPARED_AUDIO_DIR``).

Examples:

    python3 tools/generate_prepared_prompts.py --check
    python3 tools/generate_prepared_prompts.py
    python3 tools/generate_prepared_prompts.py --force
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


SPEECH_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SPEECH_ROOT))


from speech.prepared_audio import (  # noqa: E402
    PreparedPrompt,
    PreparedPromptCatalog,
    prepared_metadata,
    prepared_metadata_path,
    resolve_prepared_audio_root,
    validate_prepared_wav,
)
from speech_client import SpeechClient  # noqa: E402


def default_manifest_paths() -> list[Path]:
    return sorted(
        (SPEECH_ROOT / "scenarios").glob("*/prepared_prompts.json")
    )


def load_catalogs(
    manifest_paths: Iterable[str | Path],
    *,
    audio_root: str | Path | None,
) -> list[PreparedPromptCatalog]:
    catalogs: list[PreparedPromptCatalog] = []
    for raw_path in manifest_paths:
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = (Path.cwd() / path).resolve()
        catalogs.append(
            PreparedPromptCatalog(
                path,
                audio_root=audio_root,
            )
        )
    return catalogs


def _write_json_atomically(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        suffix=".json",
        prefix=f".{path.stem}.",
        dir=path.parent,
        delete=False,
    ) as temp:
        json.dump(data, temp, ensure_ascii=False, indent=2, sort_keys=True)
        temp.write("\n")
        temporary_path = Path(temp.name)
    os.replace(temporary_path, path)


def generate_prompt(
    *,
    speech: SpeechClient,
    catalog: PreparedPromptCatalog,
    prompt: PreparedPrompt,
    tts_identity: dict | None = None,
) -> Path:
    """Synthesize one prompt, validate it, then publish it atomically."""

    target = catalog.audio_path_for(prompt)
    target.parent.mkdir(parents=True, exist_ok=True)

    result = speech.speak(
        prompt.text,
        style=prompt.style,
        dialect=prompt.dialect,
        speed=prompt.speed,
        pitch=prompt.pitch,
        volume=prompt.volume,
        emotion=prompt.emotion,
        play_on_host=False,
        cache=True,
    )

    source_value = result.get("audio_path")
    if not source_value:
        raise RuntimeError(f"TTS没有返回音频路径: {prompt.prompt_id}")
    source = Path(str(source_value)).expanduser()
    source_reason = validate_prepared_wav(source)
    if source_reason is not None:
        raise RuntimeError(
            f"TTS产物不是G1兼容WAV ({source_reason}): {source}"
        )

    with tempfile.NamedTemporaryFile(
        suffix=".wav",
        prefix=f".{target.stem}.",
        dir=target.parent,
        delete=False,
    ) as temp:
        temporary_audio = Path(temp.name)

    try:
        shutil.copyfile(source, temporary_audio)
        target_reason = validate_prepared_wav(temporary_audio)
        if target_reason is not None:
            raise RuntimeError(
                f"复制后的预生成音频无效 ({target_reason}): {prompt.prompt_id}"
            )
        os.replace(temporary_audio, target)
    finally:
        temporary_audio.unlink(missing_ok=True)

    metadata = prepared_metadata(prompt, tts_result=result)
    metadata["generated_at"] = datetime.now(timezone.utc).isoformat()
    metadata["audio_path"] = str(target)
    if tts_identity:
        metadata["tts_model"] = (
            metadata.get("tts_model")
            or tts_identity.get("tts_model")
        )
        metadata["tts_voice"] = (
            metadata.get("tts_voice")
            or tts_identity.get("tts_voice")
        )
    _write_json_atomically(prepared_metadata_path(target), metadata)
    return target


def check_catalog(catalog: PreparedPromptCatalog) -> list[tuple[PreparedPrompt, Path, str | None]]:
    return [
        (prompt, *catalog.prepared_status(prompt))
        for prompt in catalog.prompts
    ]


def _format_manifest(path: Path) -> str:
    try:
        return str(path.relative_to(SPEECH_ROOT))
    except ValueError:
        return str(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="为固定机器人话术生成可直接播放的 G1 WAV",
    )
    parser.add_argument(
        "--manifest",
        action="append",
        type=Path,
        help="只处理一个清单；可重复指定。默认处理全部场景清单。",
    )
    parser.add_argument(
        "--audio-root",
        type=Path,
        help="覆盖 G1_PREPARED_AUDIO_DIR，仅用于本次命令。",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="只检查哪些提示音缺失或格式不合格，不调用TTS。",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="即使已有有效WAV也重新生成。",
    )
    args = parser.parse_args(argv)

    if args.check and args.force:
        parser.error("--check 不能和 --force 一起使用")

    manifest_paths = args.manifest or default_manifest_paths()
    if not manifest_paths:
        parser.error("没有找到 prepared_prompts.json")

    audio_root = resolve_prepared_audio_root(args.audio_root)
    catalogs = load_catalogs(manifest_paths, audio_root=audio_root)

    print(f"预生成音频目录: {audio_root}")
    print(f"场景清单数量: {len(catalogs)}")

    if args.check:
        missing = 0
        for catalog in catalogs:
            print(f"\n[{catalog.scene}] {_format_manifest(catalog.manifest_path)}")
            for prompt, path, reason in check_catalog(catalog):
                if reason is None:
                    print(f"  OK      {prompt.prompt_id} -> {path.name}")
                else:
                    missing += 1
                    print(f"  MISSING {prompt.prompt_id} ({reason}) -> {path.name}")
        if missing:
            print(f"\n检查完成：{missing} 条提示音需要生成。")
            return 1
        print("\n检查完成：所有预生成提示音都有效。")
        return 0

    speech = SpeechClient()
    identity = speech.health()
    print(
        "TTS身份: "
        f"model={identity.get('tts_model', 'unknown')} "
        f"voice={identity.get('tts_voice', 'unknown')}"
    )

    generated = 0
    skipped = 0
    for catalog in catalogs:
        print(f"\n[{catalog.scene}] {_format_manifest(catalog.manifest_path)}")
        for prompt in catalog.prompts:
            target, reason = catalog.prepared_status(prompt)
            if reason is None and not args.force:
                skipped += 1
                print(f"  KEEP    {prompt.prompt_id} -> {target.name}")
                continue

            print(
                f"  BUILD   {prompt.prompt_id} "
                f"(dialect={prompt.dialect})"
            )
            output = generate_prompt(
                speech=speech,
                catalog=catalog,
                prompt=prompt,
                tts_identity=identity,
            )
            generated += 1
            print(f"  READY   {prompt.prompt_id} -> {output.name}")

    print(f"\n完成：新生成 {generated} 条，保留 {skipped} 条。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

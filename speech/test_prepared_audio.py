from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
import wave
from pathlib import Path


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


from speech.prepared_audio import (  # noqa: E402
    PreparedPromptCatalog,
    prepared_metadata_path,
    validate_prepared_wav,
)


def write_wav(
    path: Path,
    *,
    sample_rate: int = 16000,
    channels: int = 1,
    frames: int = 160,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(channels)
        audio.setsampwidth(2)
        audio.setframerate(sample_rate)
        audio.writeframes(b"\x00\x00" * frames * channels)


class FakeSpeech:
    def __init__(self, *, play_error: Exception | None = None) -> None:
        self.play_error = play_error
        self.play_calls: list[tuple[Path, object]] = []
        self.speak_calls: list[dict] = []

    def play_g1(self, audio_path, *, bridge_path=None):
        self.play_calls.append((Path(audio_path), bridge_path))
        if self.play_error is not None:
            raise self.play_error
        return {"played": str(audio_path)}

    def speak_g1(self, text, **kwargs):
        self.speak_calls.append({"text": text, **kwargs})
        return {"ok": True, "audio_path": "/tmp/runtime.wav"}


class FakeGeneratorSpeech:
    def __init__(self, source: Path) -> None:
        self.source = source
        self.calls: list[dict] = []

    def speak(self, text, **kwargs):
        self.calls.append({"text": text, **kwargs})
        return {
            "ok": True,
            "audio_path": str(self.source),
            "model": "fake-model",
            "voice": "fake-voice",
        }


class PreparedAudioTest(unittest.TestCase):
    def make_catalog(self, directory: Path) -> PreparedPromptCatalog:
        manifest = directory / "prepared_prompts.json"
        manifest.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "scene": "test_scene",
                    "voice_profile": "test-voice-v1",
                    "prompts": [
                        {
                            "id": "hello_shaanxi",
                            "text": "您好，想听点啥？",
                            "style": "companion",
                            "dialect": "shaanxi",
                        },
                        {
                            "id": "hello_mandarin",
                            "text": "您好，想听点啥？",
                            "style": "companion",
                            "dialect": "mandarin",
                        },
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return PreparedPromptCatalog(
            manifest,
            audio_root=directory / "audio",
        )

    def test_valid_exact_match_plays_prepared_wav(self):
        with tempfile.TemporaryDirectory() as directory:
            catalog = self.make_catalog(Path(directory))
            prompt = catalog.find(
                "您好，想听点啥？",
                dialect="shaanxi",
            )
            self.assertIsNotNone(prompt)
            path = catalog.audio_path_for(prompt)
            write_wav(path)

            speech = FakeSpeech()
            result = catalog.play_or_speak(
                speech,
                "您好，想听点啥？",
                dialect="shaanxi",
            )

            self.assertEqual(result["audio_source"], "prepared")
            self.assertEqual(result["prepared_prompt_id"], "hello_shaanxi")
            self.assertEqual(speech.play_calls, [(path, None)])
            self.assertEqual(speech.speak_calls, [])

    def test_missing_or_dialect_mismatch_falls_back_to_tts(self):
        with tempfile.TemporaryDirectory() as directory:
            catalog = self.make_catalog(Path(directory))
            speech = FakeSpeech()

            missing = catalog.play_or_speak(
                speech,
                "您好，想听点啥？",
                dialect="shaanxi",
            )
            self.assertEqual(missing["audio_source"], "runtime_tts")
            self.assertEqual(missing["prepared_audio_reason"], "missing")
            self.assertTrue(speech.speak_calls[-1]["cache"])

            shaanxi = catalog.find("您好，想听点啥？", dialect="shaanxi")
            write_wav(catalog.audio_path_for(shaanxi))
            mismatch = catalog.play_or_speak(
                speech,
                "您好，想听点啥？",
                dialect="mandarin",
            )
            self.assertEqual(mismatch["audio_source"], "runtime_tts")
            self.assertEqual(mismatch["prepared_audio_reason"], "missing")

            style_mismatch = catalog.play_or_speak(
                speech,
                "您好，想听点啥？",
                style="normal",
                dialect="shaanxi",
            )
            self.assertEqual(style_mismatch["audio_source"], "runtime_tts")
            self.assertEqual(style_mismatch["prepared_audio_reason"], "not_registered")
            self.assertEqual(speech.play_calls, [])

    def test_invalid_wav_falls_back_without_playing(self):
        with tempfile.TemporaryDirectory() as directory:
            catalog = self.make_catalog(Path(directory))
            prompt = catalog.find("您好，想听点啥？", dialect="shaanxi")
            write_wav(catalog.audio_path_for(prompt), sample_rate=8000)

            speech = FakeSpeech()
            result = catalog.play_or_speak(
                speech,
                "您好，想听点啥？",
                dialect="shaanxi",
            )

            self.assertEqual(result["prepared_audio_reason"], "not_16khz")
            self.assertEqual(speech.play_calls, [])
            self.assertEqual(len(speech.speak_calls), 1)

    def test_playback_error_does_not_repeat_with_tts(self):
        with tempfile.TemporaryDirectory() as directory:
            catalog = self.make_catalog(Path(directory))
            prompt = catalog.find("您好，想听点啥？", dialect="shaanxi")
            write_wav(catalog.audio_path_for(prompt))
            speech = FakeSpeech(play_error=RuntimeError("bridge unavailable"))

            with self.assertRaisesRegex(RuntimeError, "bridge unavailable"):
                catalog.play_or_speak(
                    speech,
                    "您好，想听点啥？",
                    dialect="shaanxi",
                )

            self.assertEqual(len(speech.play_calls), 1)
            self.assertEqual(speech.speak_calls, [])

    def test_entertainment_catalog_covers_static_dialect_prompts_only(self):
        catalog = PreparedPromptCatalog(
            ROOT
            / "scenarios"
            / "companion_entertainment"
            / "prepared_prompts.json",
            audio_root=ROOT / "runtime" / "test_prepared_audio",
        )

        for text in (
            "您好，想听点啥？您跟我说一声，我给您放。",
            "好嘞，给您放点音乐，咱慢慢听。",
            "成，咱听听新闻，看看有啥新消息。",
            "好嘞，那咱今儿就先听到这儿。您啥时候想听了，再叫我就成。",
        ):
            with self.subTest(text=text):
                self.assertIsNotNone(
                    catalog.find(
                        text,
                        style="companion",
                        dialect="shaanxi",
                    )
                )

        self.assertIsNone(
            catalog.find(
                "成，给您找着了，咱就听甜蜜蜜。",
                style="companion",
                dialect="shaanxi",
            )
        )

    def test_all_scene_catalogs_are_valid(self):
        scenes = (
            "care_consultation_support",
            "companion_entertainment",
            "social_activity_support",
            "contact_family",
        )
        for scene in scenes:
            with self.subTest(scene=scene):
                catalog = PreparedPromptCatalog(
                    ROOT / "scenarios" / scene / "prepared_prompts.json",
                    audio_root=ROOT / "runtime" / "test_prepared_audio",
                )
                self.assertEqual(catalog.scene, scene)
                self.assertGreater(len(catalog.prompts), 0)

    def test_generator_publishes_valid_wav_and_metadata(self):
        script_path = ROOT / "tools" / "generate_prepared_prompts.py"
        spec = importlib.util.spec_from_file_location(
            "generate_prepared_prompts",
            script_path,
        )
        generator = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(generator)

        with tempfile.TemporaryDirectory() as directory:
            directory_path = Path(directory)
            catalog = self.make_catalog(directory_path)
            prompt = catalog.find("您好，想听点啥？", dialect="shaanxi")
            source = directory_path / "tts_source.wav"
            write_wav(source)

            output = generator.generate_prompt(
                speech=FakeGeneratorSpeech(source),
                catalog=catalog,
                prompt=prompt,
                tts_identity={
                    "tts_model": "health-model",
                    "tts_voice": "health-voice",
                },
            )

            self.assertIsNone(validate_prepared_wav(output))
            metadata = json.loads(
                prepared_metadata_path(output).read_text(encoding="utf-8")
            )
            self.assertEqual(metadata["prepared_prompt_id"], "hello_shaanxi")
            self.assertEqual(metadata["fingerprint"], prompt.fingerprint)
            self.assertEqual(metadata["tts_model"], "fake-model")
            self.assertEqual(metadata["tts_voice"], "fake-voice")


if __name__ == "__main__":
    unittest.main()

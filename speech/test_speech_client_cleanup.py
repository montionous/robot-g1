from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import speech_client
from speech_client import SpeechClient


class SpeechClientCleanupTest(
    unittest.TestCase,
):

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.client = SpeechClient()

    @staticmethod
    def record(
        output_path,
        **_kwargs,
    ):
        path = Path(output_path)
        path.write_bytes(b"fake wav")
        return {
            "path": str(path),
            "speech_detected": True,
        }

    def test_auto_created_input_is_removed_after_successful_asr(self):
        self.client.transcribe = lambda *_args, **_kwargs: {
            "text": "播放音乐",
        }

        with patch.object(
            speech_client,
            "DEFAULT_INPUT_DIR",
            self.root,
        ), patch(
            "g1_audio.g1_mic_recorder.record_g1_wav",
            side_effect=self.record,
        ):
            result = self.client.listen_g1(
                wait_for_speech=True,
                delete_audio_after_transcribe=True,
            )

        self.assertEqual(result["text"], "播放音乐")
        self.assertIsNone(result["audio_path"])
        self.assertTrue(result["audio_deleted"])
        self.assertIsNone(result["recording"]["path"])
        self.assertEqual(list(self.root.glob("g1_mic_*.wav")), [])

    def test_auto_created_input_is_removed_when_no_speech_is_detected(self):
        def no_speech(
            output_path,
            **_kwargs,
        ):
            path = Path(output_path)
            path.write_bytes(b"ambient audio")
            return {
                "path": str(path),
                "speech_detected": False,
            }

        with patch.object(
            speech_client,
            "DEFAULT_INPUT_DIR",
            self.root,
        ), patch(
            "g1_audio.g1_mic_recorder.record_g1_wav",
            side_effect=no_speech,
        ):
            result = self.client.listen_g1(
                wait_for_speech=True,
                delete_audio_after_transcribe=True,
            )

        self.assertEqual(result["text"], "")
        self.assertFalse(result["speech_detected"])
        self.assertTrue(result["audio_deleted"])
        self.assertEqual(list(self.root.glob("g1_mic_*.wav")), [])

    def test_auto_created_input_is_removed_when_asr_raises(self):
        def fail(*_args, **_kwargs):
            raise RuntimeError("asr unavailable")

        self.client.transcribe = fail

        with patch.object(
            speech_client,
            "DEFAULT_INPUT_DIR",
            self.root,
        ), patch(
            "g1_audio.g1_mic_recorder.record_g1_wav",
            side_effect=self.record,
        ), self.assertRaisesRegex(
            RuntimeError,
            "asr unavailable",
        ):
            self.client.listen_g1(
                wait_for_speech=True,
                delete_audio_after_transcribe=True,
            )

        self.assertEqual(list(self.root.glob("g1_mic_*.wav")), [])

    def test_explicit_output_path_is_never_deleted(self):
        output = self.root / "keep.wav"
        self.client.transcribe = lambda *_args, **_kwargs: {
            "text": "好的",
        }

        with patch(
            "g1_audio.g1_mic_recorder.record_g1_wav",
            side_effect=self.record,
        ):
            result = self.client.listen_g1(
                output_path=output,
                wait_for_speech=True,
                delete_audio_after_transcribe=True,
            )

        self.assertTrue(output.exists())
        self.assertEqual(result["audio_path"], str(output))
        self.assertNotIn("audio_deleted", result)

    def test_speak_g1_forwards_cache_to_tts_request(self):
        calls = []

        def speak(text, **kwargs):
            calls.append((text, kwargs))
            return {
                "ok": True,
                "audio_path": str(self.root / "speech.wav"),
            }

        self.client.speak = speak
        self.client.play_g1 = lambda audio_path, **_kwargs: {
            "played": str(audio_path),
        }

        result = self.client.speak_g1(
            "固定回复",
            style="companion",
            dialect="shaanxi",
            cache=True,
        )

        self.assertTrue(calls[0][1]["cache"])
        self.assertFalse(calls[0][1]["play_on_host"])
        self.assertTrue(result["g1_played"])


if __name__ == "__main__":
    unittest.main()

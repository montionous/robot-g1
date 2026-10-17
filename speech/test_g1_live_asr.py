from __future__ import annotations

import struct
import tempfile
import threading
import unittest
from pathlib import Path

from g1_audio.g1_continuous_recorder import BYTE_RATE
from g1_audio.g1_live_asr import (
    G1RollingASR,
    WindowSpec,
    build_startup_plan,
)
from g1_audio.g1_mic_recorder import (
    SAMPLE_RATE,
)
from g1_audio.g1_vad import analyze_pcm16


def pcm_frame(
    level,
    *,
    milliseconds=20,
):
    samples = int(SAMPLE_RATE * milliseconds / 1000)
    return struct.pack(
        "<h",
        level,
    ) * samples


class FakeRecorder:

    def __init__(
        self,
        pcm,
    ):
        self.pcm = pcm
        self.snapshots = []
        self.started = 0
        self.stopped = 0

    def start(self):
        self.started += 1

    def stop(self):
        self.stopped += 1

    def snapshot_pcm(
        self,
        *,
        seconds,
    ):
        self.snapshots.append(seconds)
        wanted = int(BYTE_RATE * seconds)
        return self.pcm[-wanted:]


class FakeBytesSpeech:

    def __init__(
        self,
        *,
        text="播放音乐",
    ):
        self.text = text
        self.calls = []

    def transcribe_bytes(
        self,
        audio_data,
        *,
        filename,
    ):
        self.calls.append(
            {
                "audio_data": audio_data,
                "filename": filename,
            }
        )
        return {
            "text": self.text,
        }


class FakePathSpeech:

    def __init__(
        self,
        *,
        fail=False,
    ):
        self.fail = fail
        self.paths = []

    def transcribe(
        self,
        path,
    ):
        path = Path(path)
        self.paths.append(path)
        assert path.exists()

        if self.fail:
            raise RuntimeError("expected fallback failure")

        return {
            "text": "播放音乐",
        }


class RollingASRTest(
    unittest.TestCase,
):

    def setUp(self):
        self.voiced_pcm = pcm_frame(
            2200,
            milliseconds=4500,
        )

    def create_live(
        self,
        speech,
        recorder,
        directory,
        **kwargs,
    ):
        return G1RollingASR(
            speech,
            recorder=recorder,
            runtime_dir=directory,
            window_seconds=4.5,
            startup_min_window_seconds=2.0,
            min_voiced_seconds=0.12,
            **kwargs,
        )

    def test_startup_plan_has_progressive_windows_without_duplicate_full_window(self):
        plan = build_startup_plan(
            window_seconds=4.5,
            hop_seconds=0.5,
            startup_from_seconds=2.0,
        )

        self.assertEqual(
            [
                (
                    spec.due_seconds,
                    spec.duration_seconds,
                    spec.phase,
                )
                for spec in plan
            ],
            [
                (2.0, 2.0, "bootstrap"),
                (2.5, 2.5, "bootstrap"),
                (3.0, 3.0, "bootstrap"),
                (3.5, 3.5, "bootstrap"),
                (4.0, 4.0, "bootstrap"),
                (4.5, 4.5, "steady"),
            ],
        )

    def test_vad_rejects_silence_and_short_noise_but_accepts_three_voice_frames(self):
        silence = pcm_frame(0, milliseconds=120)
        short_noise = pcm_frame(2200, milliseconds=40)
        voice = pcm_frame(2200, milliseconds=60)

        self.assertFalse(
            analyze_pcm16(
                silence,
                threshold_rms=450,
            )["speech_detected"]
        )
        self.assertFalse(
            analyze_pcm16(
                short_noise,
                threshold_rms=450,
            )["speech_detected"]
        )

        accepted = analyze_pcm16(
            voice + b"x",
            threshold_rms=450,
        )

        self.assertTrue(accepted["speech_detected"])
        self.assertEqual(
            accepted["max_consecutive_voiced_frames"],
            3,
        )
        self.assertEqual(accepted["reason"], "accepted")

    def test_capture_uses_one_recorder_and_rejects_silence_without_writing_files(self):
        with tempfile.TemporaryDirectory() as directory:
            recorder = FakeRecorder(
                pcm_frame(0, milliseconds=4500),
            )
            live = self.create_live(
                FakeBytesSpeech(),
                recorder,
                directory,
            )

            item = live._capture_window(
                WindowSpec(2.0, 2.0, "bootstrap"),
                captured_monotonic=100.0,
            )

            self.assertIsNone(item)
            self.assertEqual(recorder.snapshots, [2.0])
            self.assertEqual(
                list(Path(directory).rglob("*.wav")),
                [],
            )

    def test_bytes_transport_emits_vad_metadata_without_snapshot_files(self):
        with tempfile.TemporaryDirectory() as directory:
            recorder = FakeRecorder(self.voiced_pcm)
            speech = FakeBytesSpeech()
            live = self.create_live(
                speech,
                recorder,
                directory,
            )

            item = live._capture_window(
                WindowSpec(2.0, 2.0, "bootstrap"),
                captured_monotonic=100.0,
            )

            self.assertIsNotNone(item)
            self.assertEqual(item["phase"], "bootstrap")
            self.assertTrue(item["vad"]["speech_detected"])

            live._running = True
            worker = threading.Thread(
                target=live._asr_loop,
                args=(0,),
            )
            worker.start()

            event = live.get_event(timeout=1.0)
            live._running = False
            worker.join(timeout=1.0)

            self.assertEqual(event["kind"], "transcript")
            self.assertEqual(event["audio_transport"], "bytes")
            self.assertEqual(event["audio_path"], None)
            self.assertEqual(event["phase"], "bootstrap")
            self.assertTrue(event["vad"]["speech_detected"])
            self.assertEqual(len(speech.calls), 1)
            self.assertTrue(
                speech.calls[0]["audio_data"].startswith(b"RIFF")
            )
            self.assertEqual(
                list(Path(directory).rglob("*.wav")),
                [],
            )

    def test_path_fallback_always_removes_its_private_wav(self):
        for fail in (False, True):
            with self.subTest(fail=fail), tempfile.TemporaryDirectory() as directory:
                recorder = FakeRecorder(self.voiced_pcm)
                speech = FakePathSpeech(fail=fail)
                live = self.create_live(
                    speech,
                    recorder,
                    directory,
                )
                item = live._capture_window(
                    WindowSpec(2.0, 2.0, "bootstrap"),
                    captured_monotonic=100.0,
                )

                if fail:
                    with self.assertRaisesRegex(
                        RuntimeError,
                        "expected fallback failure",
                    ):
                        live._transcribe_item(item)
                else:
                    result, transport = live._transcribe_item(item)
                    self.assertEqual(result["text"], "播放音乐")
                    self.assertEqual(transport, "path_fallback")

                self.assertEqual(
                    list(Path(directory).rglob("*.wav")),
                    [],
                )
                live.stop()
                self.assertEqual(
                    list(Path(directory).glob("g1-live-asr-*")),
                    [],
                )

    def test_each_instance_cleans_only_its_own_session_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            first = self.create_live(
                FakePathSpeech(),
                FakeRecorder(self.voiced_pcm),
                directory,
            )
            second = self.create_live(
                FakePathSpeech(),
                FakeRecorder(self.voiced_pcm),
                directory,
            )

            first_dir = first._ensure_session_dir()
            second_dir = second._ensure_session_dir()

            self.assertNotEqual(first_dir, second_dir)
            first.stop()

            self.assertFalse(first_dir.exists())
            self.assertTrue(second_dir.exists())

            second.stop()


if __name__ == "__main__":
    unittest.main()

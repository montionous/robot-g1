"""Explicit entertainment interruption, with fake PCM and microphone owners only."""

import json
import multiprocessing
from pathlib import Path
import sys
import tempfile
from threading import Event
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from g1_audio.entertainment_interrupt import parse_interrupt_command, play_interruptible_wav
from g1_audio.entertainment_interrupt import _listen_for_interrupt
from g1_audio.g1_mic_recorder import record_g1_wav


def fake_listener(command, mode, audio_dir, done, results):
    Path(audio_dir, "listener.wav").write_bytes(b"fake recording")
    if mode in {"late", "none"}:
        done.wait(10)
    elif mode == "stalled":
        import time
        time.sleep(10)
    if command is not None:
        results.put(command)


class InterruptCommandTest(unittest.TestCase):
    def test_explicit_stop_and_replacement(self):
        for text in ("停一下", "别讲了。", "请先停一下吧", "不要讲了", "暂停"):
            with self.subTest(text=text):
                self.assertEqual(parse_interrupt_command(text, "故事正文")["action"], "stop")
        for text in ("换一个", "换个笑话", "停一下，换一个", "麻烦你换一个故事吧"):
            with self.subTest(text=text):
                self.assertEqual(parse_interrupt_command(text, "故事正文")["action"], "replace")

    def test_negation_reported_speech_and_acknowledgement_do_not_interrupt(self):
        for text in ("不要停", "别停", "不要换一个", "他说停一下", "故事里的孩子说别讲了",
                     "嗯", "好的", "哈哈", "我今天心情不错", "别讲了这句话是什么意思"):
            with self.subTest(text=text):
                self.assertIsNone(parse_interrupt_command(text, "故事正文"))

    def test_known_narration_echo_is_rejected(self):
        self.assertIsNone(parse_interrupt_command("停一下", "老人说：停一下，我先歇会儿。"))
        self.assertIsNone(parse_interrupt_command("请停一下吧", "他小声说，请停一下吧。"))


class InterruptPlaybackTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.bridge = self.root / "fake-bridge"
        self.workers = []

    def play(self, command=None, *, listener_mode="normal", normal_finish=False, stop_result=0):
        self.bridge.write_text(f"#!{sys.executable}\n" + """
import json, os, signal, sys, time
stopped = False
def stop(signum, frame):
    global stopped
    stopped = True
signal.signal(signal.SIGUSR1, stop)
row = dict(kind='g1_companion_pcm_bridge', app_name='companion_pcm_fake_'+str(os.getpid()),
           wav_path=sys.argv[-1], pcm_bytes=32000, pcm_bytes_sent=16000,
           play_result=0, stop_result=STOP_RESULT)
print(json.dumps(dict(row, status='ready')), flush=True)
deadline = time.monotonic() + (0.15 if NORMAL_FINISH else 3)
while not stopped and time.monotonic() < deadline:
    time.sleep(0.005)
print(json.dumps(dict(row, status='interrupted' if stopped else 'completed')), flush=True)
sys.exit(0 if STOP_RESULT == 0 else 2)
""".replace("STOP_RESULT", str(stop_result)).replace("NORMAL_FINISH", str(normal_finish)))
        self.bridge.chmod(0o700)

        def start(client, narration, audio_dir, rms):
            context = multiprocessing.get_context("spawn")
            done, results = context.Event(), context.Queue(maxsize=1)
            worker = context.Process(target=fake_listener,
                                     args=(command, listener_mode, str(audio_dir), done, results))
            worker.start()
            self.workers.append(worker)
            return worker, done, results

        with patch("g1_audio.entertainment_interrupt._start_listener", side_effect=start):
            try:
                return play_interruptible_wav(
                    str(self.bridge), str(self.root / "fake.wav"),
                    client=SimpleNamespace(base_url="http://unused", headers={}),
                    narration="故事正文", audio_dir=self.root, speech_rms_threshold=450, timeout=5,
                )
            finally:
                self.assertTrue(all(not worker.is_alive() for worker in self.workers))
                self.assertEqual(list(self.root.glob("interrupt-*")), [])

    def test_explicit_command_returns_only_after_stream_stops(self):
        for action in ("stop", "replace", "end_session"):
            result = self.play({"action": action, "text": "明确口令"})
            self.assertEqual(result["status"], "interrupted")
            self.assertEqual(result["interrupt"]["action"], action)
            self.assertEqual(result["stop_result"], 0)

    def test_failed_stop_never_returns_replacement(self):
        with self.assertRaisesRegex(RuntimeError, "play_or_stop_failed"):
            self.play({"action": "replace", "text": "换一个"}, stop_result=17)

    def test_late_command_does_not_interrupt_next_reply(self):
        result = self.play({"action": "replace", "text": "换一个"},
                           listener_mode="late", normal_finish=True)
        self.assertEqual(result["status"], "completed")
        self.assertNotIn("interrupt", result)


    def test_normal_completion_releases_stalled_listener_and_recording(self):
        result = self.play(listener_mode="stalled", normal_finish=True)
        self.assertEqual(result["status"], "completed")

    def test_listener_failure_is_reported_without_interrupting_narration(self):
        result = self.play({"error": "ASR_failure"}, normal_finish=True)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["interrupt_monitor_error"], "ASR_failure")
        self.assertNotIn("interrupt", result)

    def test_listener_directory_failure_does_not_stop_narration(self):
        with patch("g1_audio.entertainment_interrupt.tempfile.TemporaryDirectory", side_effect=OSError):
            result = self.play(normal_finish=True)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["interrupt_monitor_error"], "OSError")
        self.assertNotIn("interrupt", result)

    def test_fast_completion_still_checks_ready_identity(self):
        from unittest.mock import Mock
        process = Mock(returncode=0)
        process.poll.return_value = 0
        rows = [
            {"kind": "g1_companion_pcm_bridge", "status": "ready", "wav_path": "wrong.wav",
             "app_name": "unrelated_owner"},
            {"kind": "g1_companion_pcm_bridge", "status": "completed", "wav_path": "expected.wav",
             "app_name": "unrelated_owner", "play_result": 0, "stop_result": 0},
        ]
        with patch("g1_audio.entertainment_interrupt.subprocess.Popen", return_value=process), \
             patch("g1_audio.entertainment_interrupt._receipts", return_value=rows):
            with self.assertRaisesRegex(RuntimeError, "ready_invalid"):
                play_interruptible_wav(
                    "unused", "expected.wav", client=SimpleNamespace(base_url="unused", headers={}),
                    narration="故事正文", audio_dir=self.root, speech_rms_threshold=450, timeout=5,
                )

    def test_listener_start_failure_does_not_stop_narration(self):
        # Inject a failure before worker creation; the old stream must finish naturally.
        self.bridge.write_text(f"#!{sys.executable}\nimport sys\n")
        with patch("g1_audio.entertainment_interrupt.multiprocessing.get_context", side_effect=OSError):
            result = self.play(normal_finish=True)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["interrupt_monitor_error"], "OSError")


class InterruptRecordingTest(unittest.TestCase):
    def test_cancel_without_packets_closes_socket_and_is_not_a_stream_error(self):
        from unittest.mock import MagicMock
        socket = MagicMock()
        done = Event()
        done.set()
        with tempfile.TemporaryDirectory() as directory:
            with patch("g1_audio.g1_mic_recorder.socket.socket", return_value=socket):
                result = record_g1_wav(
                    Path(directory) / "cancel.wav", wait_for_speech=True,
                    interface_ip="192.168.123.99", cancel_event=done,
                )
        self.assertEqual(result["endpoint_reason"], "cancelled")
        socket.recvfrom.assert_not_called()
        socket.close.assert_called_once()

    def test_worker_accepts_only_clear_command_and_deletes_its_wav(self):
        from queue import Queue
        for transcript, expected in (("换一个", "replace"), ("不要停", None),
                                     ("嗯", None), ("停一下", None)):
            with self.subTest(transcript=transcript), tempfile.TemporaryDirectory() as directory:
                done, results = Event(), Queue(maxsize=1)
                calls = []

                def record(*args, **kwargs):
                    calls.append(args[0])
                    if len(calls) > 1:
                        done.set()
                    return {"speech_detected": True}

                fake_client = SimpleNamespace(transcribe=lambda *a, **kw: {"text": transcript})
                with patch("g1_audio.entertainment_interrupt.record_g1_wav", side_effect=record), \
                     patch("g1_audio.entertainment_interrupt.SpeechClient", return_value=fake_client), \
                     patch("g1_audio.entertainment_interrupt.signal.signal"):
                    _listen_for_interrupt("http://unused", {}, "他喊停一下。", directory, 450, done, results)
                self.assertEqual(list(Path(directory).glob("*.wav")), [])
                if expected:
                    self.assertEqual(results.get_nowait()["action"], expected)
                else:
                    self.assertTrue(results.empty())

if __name__ == "__main__":
    unittest.main()

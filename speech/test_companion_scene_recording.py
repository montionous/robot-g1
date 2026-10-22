"""Offline journal wiring tests for the four independent companion scenes."""

from __future__ import annotations

import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent
SCENES = {
    "entertainment": ROOT / "scenarios/companion_entertainment/g1_voice_demo.py",
    "social": ROOT / "scenarios/social_activity_support/g1_voice_demo.py",
    "contact": ROOT / "scenarios/contact_family/g1_voice_demo.py",
    "care": ROOT / "scenarios/care_consultation_support/g1_voice_demo.py",
}


def _load_scene(name: str):
    path = SCENES[name]
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(f"recording_{name}", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Speech:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def speak_g1(self, text: str, **options):
        self.calls.append(("speak", text))
        return {"status": "completed", "g1_played": True, "play_result": 0}

    def listen_g1(self, **options):
        self.calls.append(("listen", options))
        return {
            "text": "老人原话",
            "asr_ms": 3.0,
            "recording": {"speech_detected": True},
        }


def _rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


class CompanionSceneRecordingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.modules = {name: _load_scene(name) for name in SCENES}

    def _argv(self, name: str, path: Path) -> list[str]:
        id_flag = "--elder-id" if name in {"entertainment", "social"} else "--elderly-id"
        return [
            "g1_voice_demo.py",
            id_flag,
            "42",
            "--record-log",
            str(path),
            "--record-mode",
            "replay",
        ]

    def _fake_runner(self, name: str, module, captured: dict):
        def runner(**kwargs):
            captured.update(kwargs)
            speech = _Speech()
            if name == "contact":
                module.say(speech, "系统回复", dialect="mandarin")
                module.listen(speech, seconds=1.0, prompt="请说")
            elif name == "entertainment":
                module.speak(speech, "系统回复", dialect="mandarin")
                module.listen(speech, seconds=1.0)
            else:
                module.speak(speech, "系统回复", dialect="mandarin")
                module.listen(speech, seconds=1.0)
            return {"received": 1, "completed": 1}

        return runner

    def test_each_entry_records_asr_speech_and_external_id(self) -> None:
        for name, module in self.modules.items():
            with self.subTest(scene=name), tempfile.TemporaryDirectory() as temp:
                path = Path(temp) / "care-session.jsonl"
                captured: dict = {}
                with patch.object(module, "run_scene", self._fake_runner(name, module, captured)), patch.object(
                    module.time, "sleep", return_value=None
                ), patch.object(sys, "argv", self._argv(name, path)):
                    module.main()

                rows = _rows(path)
                self.assertEqual(rows[0]["kind"], "session_start")
                self.assertEqual(rows[0]["payload"]["source_scene"], {
                    "entertainment": "companion_entertainment",
                    "social": "social_activity_support",
                    "contact": "contact_family",
                    "care": "care_consultation_support",
                }[name])
                self.assertEqual({row["elderly_id"] for row in rows}, {"42"})
                self.assertEqual({row["mode"] for row in rows}, {"replay"})
                self.assertTrue(any(row["payload"].get("text") == "老人原话" for row in rows))
                self.assertTrue(any(row["payload"].get("text") == "系统回复" for row in rows))
                receipts = [row for row in rows if row["kind"] == "receipt"]
                self.assertTrue(receipts)
                self.assertTrue(all(row["payload"].get("physical_heard") == "unknown" for row in receipts))
                self.assertEqual(rows[-1]["kind"], "session_end")
                self.assertEqual(rows[-1]["payload"]["status"], "completed")
                self.assertEqual(captured.get("elderly_id", captured.get("elder_id")), 42)

    def test_recording_requires_explicit_id_without_running_scene(self) -> None:
        for name, module in self.modules.items():
            with self.subTest(scene=name), tempfile.TemporaryDirectory() as temp:
                path = Path(temp) / "care-session.jsonl"
                with patch.object(module, "run_scene", side_effect=AssertionError("scene must not run")), patch.object(
                    sys, "argv", ["g1_voice_demo.py", "--record-log", str(path)]
                ):
                    with self.assertRaises(SystemExit) as raised:
                        module.main()
                self.assertEqual(raised.exception.code, 2)
                self.assertFalse(path.exists())

    def test_each_entry_keeps_interrupted_terminal_status(self) -> None:
        for name, module in self.modules.items():
            with self.subTest(scene=name), tempfile.TemporaryDirectory() as temp:
                path = Path(temp) / "care-session.jsonl"
                with patch.object(module, "run_scene", side_effect=KeyboardInterrupt), patch.object(
                    sys, "argv", self._argv(name, path)
                ):
                    with self.assertRaises(KeyboardInterrupt):
                        module.main()
                rows = _rows(path)
                self.assertEqual(rows[-1]["kind"], "session_end")
                self.assertEqual(rows[-1]["payload"]["status"], "interrupted")
                self.assertEqual(rows[-1]["payload"]["error"], "keyboard_interrupt")

    def test_speech_failure_receipt_does_not_claim_heard(self) -> None:
        module = self.modules["social"]

        class BrokenSpeech(_Speech):
            def speak_g1(self, text: str, **options):
                raise RuntimeError("fake bridge failure")

        from companion_recording import CompanionRecorder, recording_context

        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "care-session.jsonl"
            recorder = CompanionRecorder(path, elderly_id=42, mode="replay", stderr=io.StringIO())
            recorder.start("dialogue", source_scene="social_activity_support")
            with recording_context(recorder):
                with self.assertRaises(RuntimeError):
                    module.speak(BrokenSpeech(), "系统回复", dialect="mandarin")
            recorder.finish("failed", {}, error="fake bridge failure")
            rows = _rows(path)
        self.assertTrue(any(row["payload"].get("text") == "系统回复" for row in rows))
        receipt = next(row for row in rows if row["kind"] == "receipt")
        self.assertEqual(receipt["payload"]["physical_heard"], "unknown")
        self.assertIn("fake bridge failure", receipt["payload"]["error"])

    def test_decision_announcements_are_recorded_with_separate_receipts(self) -> None:
        from companion_recording import CompanionRecorder,recording_context
        from decision_announcer import announce_decision
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'care-session.jsonl'
            recorder=CompanionRecorder(path,elderly_id=42,mode='replay',stderr=io.StringIO())
            recorder.start('dialogue')
            with recording_context(recorder),patch('decision_announcer.time.sleep',return_value=None):
                announce_decision(_Speech(),'护理需求',enabled=True)
            recorder.finish('completed')
            rows=_rows(path)
        self.assertEqual(rows[1]['payload']['text'],'检测到护理需求')
        self.assertEqual(rows[2]['kind'],'receipt')
        self.assertEqual(rows[2]['payload']['physical_heard'],'unknown')

    @unittest.skipUnless(os.name == "posix", "requires POSIX shell paths")
    def test_shell_recording_setup_has_no_device_calls_and_requires_valid_identity(self) -> None:
        helper=ROOT/'companion_recording_env.sh'
        # Execute only the environment helper; never execute any scene launcher.
        for value in ('', '0', str(2**63), '7'):
            with self.subTest(id=value),tempfile.TemporaryDirectory() as temp:
                speech=Path(temp)/'speech';speech.mkdir()
                result=subprocess.run(['bash','-c','source "$1" test-scene','bash',str(helper)],
                    env={**os.environ,'SPEECH_ROOT':str(speech),'G1_ELDERLY_ID':value},capture_output=True,text=True,timeout=5)
                self.assertEqual(result.returncode,0 if value=='7' else 64)
                if value=='7':
                    self.assertIn('care-session.jsonl',result.stdout)
                else:
                    self.assertFalse((Path(temp)/'runs').exists())
        for path in SCENES.values():
            launcher=path.parent/'run_g1_demo.sh'
            text=launcher.read_text()
            self.assertIn('companion_recording_env.sh',text)
            self.assertIn('--record-log "$CARE_SESSION_LOG"',text)
            self.assertIn('--elderly-id "$G1_ELDERLY_ID"',text)


if __name__ == "__main__":
    unittest.main()

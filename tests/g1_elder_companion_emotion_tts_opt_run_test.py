"""Opt camera launcher remains a compatibility alias of the promoted live path."""

from __future__ import annotations

from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
LIVE = ROOT / "scripts" / "g1_elder_companion_emotion_camera_tts_run.sh"
OPT = ROOT / "scripts" / "g1_elder_companion_emotion_camera_tts_opt_run.sh"


class ElderCompanionEmotionTtsOptRunTest(unittest.TestCase):
    def test_live_camera_script_is_the_promoted_mandarin_path(self) -> None:
        text = LIVE.read_text(encoding="utf-8")
        self.assertIn("--confirm-g1-companion-camera-tts", text)
        self.assertIn("speech/emotion_interaction.py", text)
        self.assertIn("--dialect mandarin", text)
        self.assertNotIn("emotion_interaction_opt.py", text)
        self.assertNotIn("--dialect shaanxi", text)
        self.assertNotIn("--confirm-g1-companion-camera-tts-opt", text)

    def test_opt_runner_refuses_without_its_exact_confirmation(self) -> None:
        missing = subprocess.run(
            ["bash", str(OPT)],
            capture_output=True,
            check=False,
            text=True,
        )
        self.assertEqual(missing.returncode, 64)
        self.assertIn("--confirm-g1-companion-camera-tts-opt", missing.stderr)

        live_flag = subprocess.run(
            ["bash", str(OPT), "--confirm-g1-companion-camera-tts"],
            capture_output=True,
            check=False,
            text=True,
        )
        self.assertEqual(live_flag.returncode, 64)
        self.assertIn("--confirm-g1-companion-camera-tts-opt", live_flag.stderr)

    def test_opt_runner_aliases_the_same_consumer_with_a_separate_log_root(self) -> None:
        text = OPT.read_text(encoding="utf-8")
        self.assertIn("--confirm-g1-companion-camera-tts-opt", text)
        self.assertIn("speech/emotion_interaction.py", text)
        self.assertIn("elder-companion-emotion-tts-opt", text)
        self.assertIn("--g1-pcm-bridge", text)
        self.assertIn("g1_companion_pcm_bridge", text)
        self.assertIn("--dialect mandarin", text)
        self.assertIn("--input 0", text)
        self.assertIn("--display", text)
        self.assertIn("--max-seconds 60", text)
        self.assertNotIn("emotion_interaction_opt.py", text)
        self.assertNotIn("--dialect shaanxi", text)
        self.assertNotIn("g1_competition_audio_vla_visual", text)


if __name__ == "__main__":
    unittest.main()

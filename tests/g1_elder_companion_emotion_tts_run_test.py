"""陪伴情绪播报 launcher 的无硬件契约测试。"""

from __future__ import annotations

from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
PREFLIGHT = ROOT / "scripts" / "g1_elder_companion_emotion_preflight.sh"
VIDEO = ROOT / "scripts" / "g1_elder_companion_emotion_video_tts_run.sh"
CAMERA = ROOT / "scripts" / "g1_elder_companion_emotion_camera_tts_run.sh"
DIALOGUE = ROOT / "scripts" / "g1_elder_companion_emotion_camera_dialogue_run.sh"
MOTION = ROOT / "scripts" / "g1_elder_companion_emotion_camera_dialogue_motion_run.sh"


class ElderCompanionEmotionTtsRunTest(unittest.TestCase):
    def test_preflight_stays_local_and_checks_the_fixed_handoff(self) -> None:
        text = PREFLIGHT.read_text(encoding="utf-8")

        self.assertIn("g1_companion_pcm_bridge", text)
        self.assertIn("g1_companion_pcm_test", text)
        self.assertIn("--g1-phrase-jsonl", text)
        self.assertIn("--dry-run", text)
        self.assertNotIn("--g1-bridge", text)
        self.assertNotIn("g1_competition_audio_vla_visual", text)

    def test_tts_runners_refuse_without_their_exact_confirmation(self) -> None:
        cases = (
            (VIDEO, "--confirm-g1-companion-known-video-tts"),
            (CAMERA, "--confirm-g1-companion-camera-tts"),
        )
        for script, confirmation in cases:
            with self.subTest(script=script.name):
                result = subprocess.run(
                    ["bash", str(script)],
                    capture_output=True,
                    check=False,
                    text=True,
                )
                self.assertEqual(result.returncode, 64)
                self.assertIn(confirmation, result.stderr)

    def test_tts_runners_keep_inputs_and_g1_boundary_fixed(self) -> None:
        video = VIDEO.read_text(encoding="utf-8")
        camera = CAMERA.read_text(encoding="utf-8")

        for text, confirmation in (
            (video, "--confirm-g1-companion-known-video-tts"),
            (camera, "--confirm-g1-companion-camera-tts"),
        ):
            self.assertIn(confirmation, text)
            self.assertIn("--g1-pcm-bridge", text)
            self.assertIn("--confirm-g1-companion-pcm", text)
            self.assertIn("g1_companion_pcm_bridge", text)
            self.assertIn("--dialect mandarin", text)
            self.assertIn("--max-seconds 60", text)
            self.assertIn("tee", text)
            self.assertNotIn("g1_competition_audio_vla_visual", text)

        self.assertIn("vedio/happy_1.mp4", video)
        self.assertIn("--input 0", camera)
        self.assertIn("--display", camera)

    def test_dialogue_runner_confirms_and_enables_wake_mode_before_camera(self) -> None:
        result = subprocess.run(
            ["bash", str(DIALOGUE)], capture_output=True, check=False, text=True
        )
        self.assertEqual(result.returncode, 64)
        self.assertIn("--confirm-g1-companion-camera-dialogue", result.stderr)

        text = DIALOGUE.read_text(encoding="utf-8")
        self.assertIn("emotion_dialogue.py", text)
        self.assertIn("--input 0", text)
        self.assertIn("--max-seconds 60", text)
        self.assertIn("--continue-after-first-event", text)
        self.assertIn("mkfifo", text)
        self.assertIn("stop_emotion_demo", text)
        self.assertIn("--g1-pcm-bridge", text)
        self.assertIn("--confirm-g1-companion-pcm", text)
        self.assertIn("--audio-dir", text)
        self.assertIn("g1_voice_wake_mode.sh", text)
        self.assertIn("--confirm-g1-voice-wake-mode", text)
        self.assertIn("--confirm-g1-voice-mode-restore", text)
        self.assertIn("trap cleanup EXIT", text)
        self.assertIn('console=%s', text)
        self.assertIn('custom_action_log=%s', text)
        self.assertIn("tee -a \"$CONSOLE\"", text)
        self.assertIn('CLOUD_ENV="$HOME/.config/elder_companion/cloud.env"', text)
        self.assertIn('source "$CLOUD_ENV"', text)
        self.assertLess(
            text.index('source "$CLOUD_ENV"'),
            text.index("g1_voice_wake_mode.sh"),
        )
        self.assertLess(
            text.index("g1_voice_wake_mode.sh"),
            text.index('"$EMOTION_PY" "$ROOT/scripts/g1_elder_companion_emotion_demo.py"'),
        )
        self.assertIn("--demo-scene dialogue", text)
        self.assertIn("--enable-listen-invite", text)
        self.assertIn("g1_elder_companion_custom_action_executor.py", text)
        self.assertIn("--confirm-g1-companion-listen-invite-executor", text)
        self.assertIn('tee "$EXECUTOR_LOG"', text)
        self.assertNotIn('--jsonl-output "$LOG"', text)
        self.assertIn("open_palm_invite", text)
        self.assertIn("/home/user/miniconda3/envs/tv/bin/python", text)
        self.assertIn("regular sport standing and small idle posture stay allowed", text)
        self.assertIn("intent_only", text)
        self.assertIn("ELDER_CHAT_URL=http://127.0.0.1:8811", text)
        self.assertIn('--elder-chat-url "$ELDER_CHAT_URL"', text)
        self.assertLess(
            text.index("_require_elder_chat_health"),
            text.index('"$ROOT/scripts/g1_voice_wake_mode.sh" --confirm-g1-voice-wake-mode'),
        )
        self.assertIn("Elder Companion Unified API", text)
        self.assertNotIn("最多三轮", text)
        self.assertNotIn("short companion", text)
        self.assertNotIn("g1_elder_companion_motion_executor.py", text)
        self.assertNotIn("现在演示动作交互场景", text)
        self.assertNotIn("rt/dex3", text)
        self.assertNotIn("rt/lowcmd", text)
        self.assertNotIn("无动作", text)
        self.assertNotIn("零动作", text)
        self.assertNotIn("never move", text)
        self.assertNotIn("冻住", text)
        self.assertNotIn("no joint, Dex3, or VLA command is issued", text)

    def test_listen_invite_branch_has_a_separate_confirmation_and_executor(self) -> None:
        result = subprocess.run(
            ["bash", str(DIALOGUE)],
            capture_output=True,
            check=False,
            text=True,
        )
        self.assertEqual(result.returncode, 64)
        self.assertIn("--confirm-g1-companion-camera-listen-invite", result.stderr)
        reused = subprocess.run(
            ["bash", str(DIALOGUE), "--confirm-g1-companion-camera-dialogue-motion"],
            capture_output=True,
            check=False,
            text=True,
        )
        self.assertEqual(reused.returncode, 64)
        self.assertIn("--confirm-g1-companion-camera-listen-invite", reused.stderr)

        text = DIALOGUE.read_text(encoding="utf-8")
        self.assertIn("--confirm-g1-companion-camera-listen-invite", text)
        self.assertIn("--confirm-g1-companion-camera-dialogue", text)
        self.assertIn('"$DIALOGUE_CONFIRM"|"$LISTEN_INVITE_CONFIRM"', text)
        self.assertIn("g1_elder_companion_custom_action_executor.py", text)
        self.assertIn("--confirm-g1-companion-listen-invite-executor", text)
        self.assertIn("--enable-listen-invite", text)
        self.assertIn("open_palm_invite", text)
        self.assertNotIn("g1_elder_companion_motion_executor.py", text)
        self.assertNotIn("LISTEN_INVITE=0", text)

    def test_motion_dialogue_runner_requires_its_own_confirmation(self) -> None:
        result = subprocess.run(
            ["bash", str(MOTION)], capture_output=True, check=False, text=True
        )
        self.assertEqual(result.returncode, 64)
        self.assertIn("--confirm-g1-companion-camera-dialogue-motion", result.stderr)
        reused = subprocess.run(
            ["bash", str(MOTION), "--confirm-g1-companion-camera-dialogue"],
            capture_output=True,
            check=False,
            text=True,
        )
        self.assertEqual(reused.returncode, 64)
        self.assertIn("--confirm-g1-companion-camera-dialogue-motion", reused.stderr)

        text = MOTION.read_text(encoding="utf-8")
        self.assertIn("g1_elder_companion_motion_executor.py", text)
        self.assertIn("--confirm-g1-companion-motion-executor", text)
        self.assertIn("/home/user/miniconda3/envs/tv/bin/python", text)
        self.assertIn("--interface enp3s0", text)
        self.assertIn("--from-stdin", text)
        self.assertIn("stdbuf -oL tee", text)
        self.assertIn('"$SPEECH_PY" -u', text)
        self.assertNotIn("--from-jsonl", text)
        self.assertIn("emotion_dialogue.py", text)
        self.assertIn("--demo-scene motion", text)
        self.assertIn("g1_voice_wake_mode.sh", text)
        self.assertIn('console=%s', text)
        self.assertIn("tee -a \"$CONSOLE\"", text)
        self.assertNotIn("no joint, Dex3, or VLA command is issued", text)
        self.assertNotIn("rt/lowcmd", text)
        self.assertNotIn("ServiceSwitch", text)
        self.assertIn("finishes on its own", text)
        self.assertNotIn("press q or Esc to end the camera so the confirmed", text)
        self.assertIn("not a prerequisite", text)
        self.assertNotIn("现在演示多轮对话场景", text)
        self.assertNotIn("run_elder_api.sh", text)
        self.assertNotIn("8810", text)
        self.assertIn("现在演示动作交互场景", text)
        self.assertIn("operator then waves or claps", text)
        self.assertIn("after the arms leave the torso", text)
        self.assertIn("never at hip rest", text)
        self.assertIn("do not cancel ArmAction", text)
        self.assertNotIn("voice yes plays 现在演示动作交互场景", text)
        self.assertNotIn("a confirmed voice yes plays", text)
        self.assertNotIn("open_palm_invite", text)
        self.assertNotIn("g1_elder_companion_custom_action_executor.py", text)
        self.assertNotIn("--enable-listen-invite", text)


if __name__ == "__main__":
    unittest.main()

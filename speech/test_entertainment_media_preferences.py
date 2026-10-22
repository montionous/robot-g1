"""Offline regression: no SDK, cloud ASR/TTS, shared DB or media subprocess."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import math
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parent
SCENE = ROOT / "scenarios/companion_entertainment"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SCENE))

import robot_leds
from entertainment_controller import EntertainmentController
from entertainment_need_integration import EntertainmentNeedSession
from local_media_library import MediaItem
from speech.reply.companion_entertainment import generate_reply
from speech.prepared_audio import PreparedPromptCatalog


def load_scene(name):
    spec = importlib.util.spec_from_file_location(f"offline_media_{name}", SCENE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Library:
    def __init__(self):
        self.items = {
            category: [MediaItem(category, Path(f"/{category}{i}.wav"), f"{category}{i}") for i in (1, 2)]
            for category in ("music", "news", "opera")
        }

    def list_items(self, category):
        return self.items[category]

    def first(self, category):
        return self.items[category][0]

    def next_item(self, category, current):
        items = self.items[category]
        return items[(next(i for i, item in enumerate(items) if item.path == current) + 1) % len(items)]


class OfflineMediaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.showcase = load_scene("g1_showcase_demo")
        cls.voice = load_scene("g1_voice_demo")

    def setUp(self):
        self.library = Library()
        # Accidental external calls fail the test, even if a fake was missed.
        for target in ("subprocess.Popen", "requests.sessions.Session.request", "socket.create_connection"):
            guard = patch(target, side_effect=AssertionError(f"offline test attempted {target}"))
            guard.start()
            self.addCleanup(guard.stop)

    def controller(self):
        with patch("entertainment_controller.LocalMediaLibrary", return_value=self.library):
            return EntertainmentController()

    def test_selection_and_narration_share_one_history_snapshot(self):
        controller = self.controller()
        lookup = Mock(side_effect=[self.library.items["music"][1], RuntimeError("history changed")])
        controller.preferred_item_lookup = lookup
        result = controller.play_category("music")
        with patch.object(self.showcase, "speak_interaction") as speak:
            self.showcase.start_media_result(
                speech=Mock(), player=Mock(), intent="play_music", result=result,
                announce_decisions=False, led_announcement=True,
            )
        lookup.assert_called_once_with("music")
        reply = speak.call_args.args[1]
        self.assertIn("《music2》", reply)
        self.assertIn("点播偏好", reply)
        self.assertIn("灯光", reply)

    def test_default_next_and_news_do_not_claim_history(self):
        controller = self.controller()
        controller.preferred_item_lookup = Mock(return_value=None)
        default = controller.play_category("opera")
        self.assertEqual(default["selection_reason"], "default")
        for command, result in [
            ({"action": "play_category", "category": "opera"}, default),
            ({"action": "next", "category": "opera"}, controller.next_item()),
            ({"action": "play_category", "category": "news"}, controller.play_category("news")),
        ]:
            self.assertNotIn("偏好", generate_reply(command, result))
        controller.preferred_item_lookup.assert_called_once_with("opera")

    def test_history_failure_falls_back_to_default(self):
        controller = self.controller()
        controller.preferred_item_lookup = Mock(side_effect=RuntimeError("offline"))
        result = controller.play_category("music")
        self.assertEqual(result["play_item"]["title"], "music1")
        self.assertEqual(result["selection_reason"], "default")

    def test_preference_uses_only_explicit_available_titles_and_counts_then_recency(self):
        history = [
            {"details": {"request_mode": "category", "title": "music1"}},
            {"details": {"request_mode": "next", "title": "music1"}},
            {"details": {"request_mode": "explicit", "title": "missing"}},
            {"details": {"request_mode": "explicit", "title": "music2"}},
            {"details": {"request_mode": "explicit", "title": "music1"}},
        ]
        with patch("entertainment_need_integration.elderly_is_enabled", return_value=True), patch(
            "entertainment_need_integration.get_elder_need_history", return_value=history
        ) as query:
            needs = EntertainmentNeedSession(elderly_id=7, library=self.library, record=False)
            self.assertEqual(needs.preferred_item("music").title, "music2")
            history.append({"details": {"request_mode": "explicit", "title": "music1"}})
            self.assertEqual(needs.preferred_item("music").title, "music1")
        self.assertEqual(query.call_args.args, (7,))
        self.assertEqual(query.call_args.kwargs["status"], "completed")
        self.assertEqual(query.call_args.kwargs["limit"], 100)

    def test_normal_reply_uses_shaanxi_and_describes_only_enabled_leds(self):
        controller = self.controller()
        controller.preferred_item_lookup = Mock(return_value=self.library.items["music"][1])
        result = controller.play_category("music")
        for enabled in (False, True):
            with patch.object(self.voice, "speak") as speak:
                self.voice.apply_result(
                    speech=Mock(), player=Mock(), command={"action": "play_category", "category": "music"},
                    result=result, announce_decisions=False, dialect="shaanxi", led_announcement=enabled,
                )
            self.assertEqual(speak.call_args.kwargs["dialect"], "shaanxi")
            self.assertEqual("灯光" in speak.call_args.args[1], enabled)
            self.assertIn("《music2》", speak.call_args.args[1])

    def test_fixed_led_replies_are_available_for_shaanxi_preparation(self):
        catalog = PreparedPromptCatalog(SCENE / "prepared_prompts.json")
        controller = self.controller()
        for category in ("music", "news", "opera"):
            result = controller.play_category(category)
            command = {"action": "play_category", "category": category}
            from speech.reply.companion_entertainment import append_led_notice
            text = append_led_notice(generate_reply(command, result), category, enabled=True)
            self.assertIsNotNone(catalog.find(text, style="companion", dialect="shaanxi"))
            self.assertIsNone(catalog.find(text, style="companion", dialect="mandarin"))

    def test_media_led_mapping_and_timeout_do_not_launch_hardware(self):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "fake.sh"
            script.touch()
            runner = Mock(return_value=SimpleNamespace(returncode=0, stdout=""))
            client = robot_leds.RobotLedClient(mode="execute", confirm_writes=True, script_path=script, runner=runner)
            for category, effect in (("music", 12), ("news", 10), ("opera", 6)):
                result = client.show(f"media_{category}")
                self.assertEqual(result["status"], "started")
                self.assertTrue(client.wait_for_idle(1))
                self.assertEqual(runner.call_args.args[0][-2:], [str(effect), "--media"])
                self.assertEqual(runner.call_args.kwargs["timeout"], robot_leds.MEDIA_LED_COMMAND_TIMEOUT)
            client.show("listening")
            self.assertTrue(client.wait_for_idle(1))
            self.assertNotIn("--media", runner.call_args.args[0])
            self.assertEqual(runner.call_args.kwargs["timeout"], client.command_timeout)
            self.assertTrue(client.close())

    def test_led_deadlines_reject_non_finite_values(self):
        for value in ("nan", "inf", "-inf", "0", "-1", "bad"):
            with self.subTest(value=value), patch.dict(os.environ, {"OFFLINE_TIMEOUT": value}):
                self.assertEqual(robot_leds._seconds_from_environment("OFFLINE_TIMEOUT", 30), 30)
        for value in (math.nan, math.inf, -math.inf, 0, -1):
            with self.subTest(value=value), self.assertRaises(ValueError):
                robot_leds.RobotLedClient(command_timeout=value)

    def test_both_scene_loops_keep_media_leds_until_natural_finish(self):
        for scene in (self.showcase, self.voice):
            with self.subTest(scene=scene.__name__):
                self.run_fake_scene(scene)

    def run_fake_scene(self, scene):
        controller = self.controller()
        player = Mock()
        player.playing = False
        player.is_playing.side_effect = lambda: player.playing
        player.play.side_effect = lambda *_: setattr(player, "playing", True)
        player.stop.side_effect = lambda **_: setattr(player, "playing", False)
        observations = []
        leds = Mock()
        leds.show.side_effect = lambda event, **_: observations.append((event, player.playing))
        inputs = iter(["机器人，放点音乐", "机器人，换一首", "机器人，换成新闻", "机器人，换成戏曲", None, "机器人，不听了"])

        def next_event(**_):
            text = next(inputs)  # Exhaustion fails instead of hanging.
            if text is None:
                player.playing = False
                return None
            return {"kind": "transcript", "text": text}

        live = Mock()
        live.get_event.side_effect = next_event
        needs = Mock()
        needs.preferred_item.return_value = None
        with contextlib.ExitStack() as stack:
            for name, value in {
                "SpeechClient": Mock(), "EntertainmentController": controller,
                "EntertainmentNeedSession": needs, "G1MediaPlayer": player,
                "RobotActionClient": Mock(), "RobotLedClient": leds,
            }.items():
                stack.enter_context(patch.object(scene, name, return_value=value))
            stack.enter_context(patch.object(scene, "trigger_robot_action"))
            stack.enter_context(patch.object(scene.time, "sleep"))
            stack.enter_context(patch.object(scene.PREPARED_PROMPTS, "play_or_speak", return_value={}))
            if scene is self.showcase:
                stack.enter_context(patch.object(scene, "preflight_media"))
                stack.enter_context(patch.object(scene, "start_live_asr", return_value=live))
                scene.run_scene(listen_seconds=4.5, state_timeout=60, announce_decisions=False,
                    use_llm=False, robot_actions="off", confirm_g1_actions=False,
                    elderly_id=7, record_elder_needs=False, robot_leds="dry-run")
            else:
                stack.enter_context(patch.object(scene, "G1RollingASR", return_value=live))
                stack.enter_context(patch.object(scene, "EntertainmentIntentLLM", side_effect=RuntimeError("offline")))
                scene.run_scene(dialect="shaanxi", request_seconds=5, control_seconds=3,
                    announce_decisions=False, robot_actions="off", confirm_g1_actions=False,
                    elderly_id=7, record_elder_needs=False, robot_leds="dry-run")
        self.assertFalse(any(event == "listening" and playing for event, playing in observations))
        self.assertEqual([event for event, _ in observations if event.startswith("media_")],
            ["media_music", "media_music", "media_news", "media_opera"])
        self.assertEqual([event for event, _ in observations].count("listening"), 2)
        self.assertIn(("farewell", False), observations)
        self.assertEqual(needs.begin.call_count, 5)


if __name__ == "__main__":
    unittest.main()

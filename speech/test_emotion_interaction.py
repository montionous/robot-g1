"""情绪策略事件到语音互动：普通话、稳定/确认话术库和 G1 PCM。"""

from __future__ import annotations

import io
import json
import unittest
from subprocess import CompletedProcess
from unittest.mock import patch

from emotion_interaction import (
    INTERACTIONS,
    InteractionError,
    consume_events,
    consume_g1_pcm_bridge_events,
    consume_phrase_events,
    dispatch_event,
)


FORBIDDEN_POSSIBLE = ("挺开心", "有些难过", "有点火气")


def event(
    emotion: str,
    strategy_id: str,
    *,
    event_id: str = "event-1",
    inference_level: str = "possible",
) -> dict:
    return {
        "schema_version": "emotion_strategy_v1",
        "event_id": event_id,
        "emotion": emotion,
        "inference_level": inference_level,
        "strategy": {
            "strategy_id": strategy_id,
            "goal": "goal",
            "tone": "tone",
            "do": ["do"],
            "avoid": ["avoid"],
        },
    }


class FakeSpeechClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def speak(self, text: str, **kwargs) -> dict:
        self.calls.append((text, kwargs))
        return {
            "ok": True,
            "request_id": f"request-{len(self.calls)}",
            "audio_path": f"/tmp/request-{len(self.calls)}.wav",
            "played": kwargs["play_on_host"],
            "g1_played": False,
        }


class EmotionInteractionOptTest(unittest.TestCase):
    def test_three_emotions_use_distinct_voice_profiles(self) -> None:
        cases = (
            ("happy", "SHARE_POSITIVE", "happy", "cheerful", 1.05),
            ("sad", "EMPATHIZE_AND_INVITE", "comfort", "gentle", 0.82),
            ("angry", "DEESCALATE_AND_GIVE_SPACE", "normal", "calm", 0.70),
        )
        speeds = []
        for index, (emotion, strategy_id, style, voice_emotion, speed) in enumerate(cases):
            with self.subTest(emotion=emotion):
                client = FakeSpeechClient()
                receipt = dispatch_event(
                    event(emotion, strategy_id, event_id=f"event-{index}"),
                    client,
                    set(),
                    play_on_host=False,
                )
                _, options = client.calls[0]
                self.assertEqual(options["style"], style)
                self.assertEqual(options["emotion"], voice_emotion)
                self.assertEqual(options["speed"], speed)
                self.assertEqual(options["dialect"], "mandarin")
                self.assertEqual(receipt["status"], "delivered")
                speeds.append(options["speed"])
        self.assertEqual(len(set(speeds)), 3)
        self.assertLess(speeds[2], speeds[1])

    def test_angry_is_slower_quieter_and_lower_pitch_than_sad(self) -> None:
        sad_client = FakeSpeechClient()
        angry_client = FakeSpeechClient()
        dispatch_event(
            event("sad", "EMPATHIZE_AND_INVITE"), sad_client, set(), play_on_host=False
        )
        dispatch_event(
            event("angry", "DEESCALATE_AND_GIVE_SPACE"),
            angry_client,
            set(),
            play_on_host=False,
        )
        sad_options = sad_client.calls[0][1]
        angry_options = angry_client.calls[0][1]
        self.assertLess(angry_options["speed"], sad_options["speed"])
        self.assertEqual(angry_options["pitch"], 0.94)
        self.assertEqual(angry_options["volume"], 62)
        self.assertNotIn("pitch", sad_options)
        self.assertNotIn("volume", sad_options)

    def test_possible_phrases_do_not_assert_the_emotion(self) -> None:
        for strategy_id, interaction in INTERACTIONS.items():
            for phrase_id, text in interaction["phrases"]["possible"]:
                with self.subTest(phrase_id=phrase_id):
                    for forbidden in FORBIDDEN_POSSIBLE:
                        self.assertNotIn(forbidden, text)
                    self.assertTrue(phrase_id.endswith("possible") or "_possible_" in phrase_id)

    def test_stable_and_possible_banks_are_distinct(self) -> None:
        for strategy_id, interaction in INTERACTIONS.items():
            with self.subTest(strategy_id=strategy_id):
                stable_ids = {item[0] for item in interaction["phrases"]["stable_face"]}
                possible_ids = {item[0] for item in interaction["phrases"]["possible"]}
                stable_texts = {item[1] for item in interaction["phrases"]["stable_face"]}
                possible_texts = {item[1] for item in interaction["phrases"]["possible"]}
                self.assertEqual(len(stable_ids), 3)
                self.assertEqual(len(possible_ids), 3)
                self.assertFalse(stable_ids & possible_ids)
                self.assertFalse(stable_texts & possible_texts)

    @patch("emotion_interaction.random.choice")
    def test_dispatch_selects_the_inference_level_bank(self, choice) -> None:
        choice.side_effect = [
            ("companion_share_positive", "stable-text"),
            ("companion_share_positive_possible", "possible-text"),
        ]
        stable_client = FakeSpeechClient()
        possible_client = FakeSpeechClient()
        dispatch_event(
            event("happy", "SHARE_POSITIVE", inference_level="stable_face"),
            stable_client,
            set(),
            play_on_host=False,
        )
        dispatch_event(
            event("happy", "SHARE_POSITIVE", event_id="event-2", inference_level="possible"),
            possible_client,
            set(),
            play_on_host=False,
        )
        self.assertEqual(stable_client.calls[0][0], "stable-text")
        self.assertEqual(possible_client.calls[0][0], "possible-text")
        self.assertEqual(
            [item[0] for item in choice.call_args_list[0].args[0]],
            [
                "companion_share_positive",
                "companion_share_positive_2",
                "companion_share_positive_3",
            ],
        )
        self.assertEqual(
            [item[0] for item in choice.call_args_list[1].args[0]],
            [
                "companion_share_positive_possible",
                "companion_share_positive_possible_2",
                "companion_share_positive_possible_3",
            ],
        )

    @patch("emotion_interaction.random.choice")
    def test_action_face_uses_the_stable_face_phrase_bank(self, choice) -> None:
        choice.return_value = ("companion_share_positive", "stable-text")
        client = FakeSpeechClient()
        payload = event("happy", "SHARE_POSITIVE", inference_level="action_face")
        payload["behavior_cues"] = ["wave_open_palm"]

        dispatch_event(
            payload,
            client,
            set(),
            play_on_host=False,
        )

        self.assertEqual(client.calls[0][0], "stable-text")
        self.assertEqual(
            choice.call_args.args[0],
            INTERACTIONS["SHARE_POSITIVE"]["phrases"]["stable_face"],
        )

    def test_action_face_requires_happy_wave_or_clap(self) -> None:
        cases = (
            ("happy", "SHARE_POSITIVE", ["thumb_up"]),
            ("sad", "EMPATHIZE_AND_INVITE", ["wave_open_palm"]),
        )
        for emotion, strategy_id, behavior_cues in cases:
            with self.subTest(emotion=emotion, behavior_cues=behavior_cues):
                payload = event(emotion, strategy_id, inference_level="action_face")
                payload["behavior_cues"] = behavior_cues
                with self.assertRaisesRegex(InteractionError, "emotion_action_face_invalid"):
                    dispatch_event(payload, FakeSpeechClient(), set(), play_on_host=False)

    @patch("emotion_interaction.subprocess.run")
    @patch(
        "emotion_interaction.random.choice",
        return_value=("companion_share_positive_possible", "possible-text"),
    )
    def test_pcm_bridge_still_plays_teammate_wav(self, choice, run) -> None:
        run.return_value = CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps(
                {
                    "kind": "g1_companion_pcm_bridge",
                    "status": "completed",
                    "wav_path": "/tmp/request-1.wav",
                    "pcm_bytes": 32000,
                    "duration_milliseconds": 1000,
                }
            ),
            stderr="",
        )
        output = io.StringIO()
        summary = consume_g1_pcm_bridge_events(
            io.StringIO(json.dumps(event("happy", "SHARE_POSITIVE"))),
            FakeSpeechClient(),
            output,
            bridge_path="/tmp/pcm-bridge",
            dialect="mandarin",
        )
        self.assertEqual(
            run.call_args.args[0],
            ["/tmp/pcm-bridge", "--confirm-g1-companion-pcm", "/tmp/request-1.wav"],
        )
        self.assertGreater(run.call_args.kwargs["timeout"], 15.0)
        receipt = json.loads(output.getvalue())
        self.assertEqual(summary, {"received": 1, "completed": 1, "duplicates": 0})
        self.assertTrue(receipt["g1_played"])
        self.assertEqual(receipt["dialect"], "mandarin")
        self.assertEqual(receipt["inference_level"], "possible")
        self.assertEqual(choice.call_args.args[0][0][0], "companion_share_positive_possible")

    def test_consume_events_forwards_dialect(self) -> None:
        client = FakeSpeechClient()
        consume_events(
            io.StringIO(json.dumps(event("happy", "SHARE_POSITIVE"))),
            client,
            io.StringIO(),
            play_on_host=False,
            dialect="sichuan",
        )
        self.assertEqual(client.calls[0][1]["dialect"], "sichuan")

    @patch("emotion_interaction.subprocess.run")
    def test_pcm_duplicate_after_three_uniques_is_ignored(self, run) -> None:
        def completed_pcm(args, **kwargs):
            wav_path = args[2]
            return CompletedProcess(
                args=args,
                returncode=0,
                stdout=json.dumps(
                    {
                        "kind": "g1_companion_pcm_bridge",
                        "status": "completed",
                        "wav_path": wav_path,
                        "pcm_bytes": 32000,
                        "duration_milliseconds": 1000,
                    }
                ),
                stderr="",
            )

        run.side_effect = completed_pcm
        source = io.StringIO(
            "\n".join(
                (
                    json.dumps(event("happy", "SHARE_POSITIVE", event_id="a")),
                    json.dumps(event("sad", "EMPATHIZE_AND_INVITE", event_id="b")),
                    json.dumps(event("angry", "DEESCALATE_AND_GIVE_SPACE", event_id="c")),
                    json.dumps(event("happy", "SHARE_POSITIVE", event_id="a")),
                )
            )
        )
        summary = consume_g1_pcm_bridge_events(
            source,
            FakeSpeechClient(),
            io.StringIO(),
            bridge_path="/tmp/pcm-bridge",
            dialect="mandarin",
        )
        self.assertEqual(summary, {"received": 4, "completed": 3, "duplicates": 1})
        self.assertEqual(run.call_count, 3)

    def test_rejects_mismatched_strategy(self) -> None:
        with self.assertRaisesRegex(InteractionError, "strategy_emotion_mismatch"):
            dispatch_event(
                event("sad", "SHARE_POSITIVE"),
                FakeSpeechClient(),
                set(),
                play_on_host=False,
            )

    def test_rejects_invalid_behavior_cues(self) -> None:
        payload = event("happy", "SHARE_POSITIVE")
        payload["behavior_cues"] = ["wave_open_palm", 1]
        with self.assertRaisesRegex(InteractionError, "emotion_behavior_cues_invalid"):
            dispatch_event(payload, FakeSpeechClient(), set(), play_on_host=False)

    def test_duplicate_event_is_not_spoken_twice(self) -> None:
        client = FakeSpeechClient()
        seen: set[str] = set()
        payload = event("happy", "SHARE_POSITIVE")
        first = dispatch_event(payload, client, seen, play_on_host=True)
        duplicate = dispatch_event(payload, client, seen, play_on_host=True)
        self.assertEqual(first["status"], "delivered")
        self.assertEqual(duplicate["status"], "duplicate_ignored")
        self.assertEqual(len(client.calls), 1)

    def test_consumes_jsonl_and_ignores_known_emotion_summary(self) -> None:
        client = FakeSpeechClient()
        source = io.StringIO(
            "\n".join(
                (
                    json.dumps(event("happy", "SHARE_POSITIVE")),
                    json.dumps(event("happy", "SHARE_POSITIVE")),
                    json.dumps({"kind": "emotion_demo_summary", "strategy_events": 2}),
                )
            )
        )
        output = io.StringIO()
        summary = consume_events(source, client, output, play_on_host=False)
        receipts = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual([item["status"] for item in receipts], ["delivered", "duplicate_ignored"])
        self.assertEqual(summary, {"received": 2, "delivered": 1, "duplicates": 1})
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(client.calls[0][1]["dialect"], "mandarin")

    @patch("emotion_interaction.random.choice")
    def test_phrase_jsonl_uses_the_inference_level_bank(self, choice) -> None:
        choice.return_value = (
            "companion_share_positive_possible",
            "您这会儿看着兴致还行，要是我看走眼了您就说一声。",
        )
        output = io.StringIO()
        summary = consume_phrase_events(
            io.StringIO(json.dumps(event("happy", "SHARE_POSITIVE"))),
            output,
        )
        phrase = json.loads(output.getvalue())
        self.assertEqual(summary, {"received": 1, "emitted": 1, "duplicates": 0})
        self.assertEqual(
            set(phrase),
            {"schema_version", "event_id", "phrase_id"},
        )
        self.assertEqual(phrase["phrase_id"], "companion_share_positive_possible")
        self.assertEqual(
            [item[0] for item in choice.call_args.args[0]],
            [
                "companion_share_positive_possible",
                "companion_share_positive_possible_2",
                "companion_share_positive_possible_3",
            ],
        )


if __name__ == "__main__":
    unittest.main()

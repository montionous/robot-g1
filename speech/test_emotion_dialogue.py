"""情绪事件触发的有界自然对话：只用假语音和假 ElderChatClient 验证接线。"""

from __future__ import annotations

import io
import json
import os
from pathlib import Path
import queue
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import wave

import requests

from emotion_dialogue import (
    DEFAULT_ELDER_CHAT_URL,
    DEMO_SCENE_DIALOGUE,
    DEMO_SCENE_MOTION,
    DialogueMemory,
    DialogueError,
    _console_line,
    DIALOGUE_OPENING_FOLLOWS,
    _detection_opening,
    _spoken_opening,
    _is_motion_confirmation,
    _is_quiet_request,
    _require_elder_chat_health,
    _run_dialogue_pcm_bridge,
    _dialogue_pcm_timeout,
    consume_g1_dialogue_events,
    main,
    parse_arguments,
)
from scenarios.elder_companion.elder_chat_client import ElderChatClient


def _pcm(_bridge: str, _audio_path: str) -> dict:
    return {"pcm_bytes": 16000, "duration_milliseconds": 500}


def consume_events(
    source,
    client,
    output,
    *,
    demo_scene: str,
    audio_dir: Path | str,
    chat_client=None,
    play_audio=_pcm,
    console=None,
    enable_listen_invite: bool = False,
    visual_updates: queue.Queue | None = None,
):
    kwargs: dict = {
        "bridge_path": "/tmp/pcm-bridge",
        "audio_dir": Path(audio_dir),
        "chat_client": chat_client if chat_client is not None else FakeElderChat([]),
        "play_audio": play_audio,
        "console": io.StringIO() if console is None else console,
        "demo_scene": demo_scene,
    }
    if enable_listen_invite:
        kwargs["enable_listen_invite"] = True
    if visual_updates is not None:
        kwargs["visual_updates"] = visual_updates
    return consume_g1_dialogue_events(source, client, output, **kwargs)


def write_pcm_wav(path: Path, *, seconds: int) -> None:
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(b"\0\0" * 16000 * seconds)


def event(
    *,
    event_id: str = "event-1",
    emotion: str = "happy",
    behavior_cues: list[str] | None = None,
    inference_level: str = "stable_face",
) -> dict:
    strategies = {
        "happy": {
            "strategy_id": "SHARE_POSITIVE",
            "goal": "回应积极感受并邀请老人继续分享",
            "tone": "温暖、稍轻快但不夸张",
            "do": ["回应当前愉快感受"],
            "avoid": ["连续追问"],
        },
        "sad": {
            "strategy_id": "EMPATHIZE_AND_INVITE",
            "goal": "表达关心并询问老人是否愿意倾诉",
            "tone": "温和、缓慢、不施压",
            "do": ["先表达关心"],
            "avoid": ["强迫倾诉"],
        },
        "angry": {
            "strategy_id": "DEESCALATE_AND_GIVE_SPACE",
            "goal": "降低刺激并确认老人需要帮助还是安静空间",
            "tone": "低声、缓慢、克制",
            "do": ["减少动作并保持距离"],
            "avoid": ["争辩"],
        },
    }
    return {
        "schema_version": "emotion_strategy_v1",
        "event_id": event_id,
        "emotion": emotion,
        "inference_level": inference_level,
        "evidence_source": "face_and_behavior" if behavior_cues else "face",
        "match_score": 0.91,
        "stability_ratio": 0.8,
        "behavior_cues": [] if behavior_cues is None else behavior_cues,
        "strategy": strategies[emotion],
    }


class FakeSpeechClient:
    def __init__(self, transcripts: list[str]) -> None:
        self.transcripts = iter([*transcripts, "我想安静一会儿"])
        self.spoken: list[tuple[str, dict]] = []
        self.listened_paths: list[Path] = []
        self.listen_seconds: list[float] = []

    def speak(self, text: str, **options) -> dict:
        self.spoken.append((text, options))
        return {
            "ok": True,
            "audio_path": f"/tmp/reply-{len(self.spoken)}.wav",
        }

    def listen_g1(self, *, seconds: float, output_path: str, **options) -> dict:
        self.listen_seconds.append(seconds)
        path = Path(output_path)
        path.write_bytes(b"temporary microphone recording")
        self.listened_paths.append(path)
        return {
            "text": next(self.transcripts),
            "audio_path": str(path),
            "asr_ms": 12.0,
        }


class FakeElderChat:
    def __init__(
        self,
        replies: list[str] | list[dict],
        visual_transition_replies: list[str] | list[dict] | None = None,
    ) -> None:
        self.replies = iter(replies)
        self.calls: list[dict] = []
        self.visual_transition_replies = iter(visual_transition_replies or [])
        self.visual_transition_calls: list[dict] = []

    def chat(
        self,
        text: str,
        *,
        emotion=None,
        emotion_confidence=None,
        visual_context=None,
        mode_hint="auto",
    ) -> dict:
        self.calls.append(
            {
                "text": text,
                "emotion": emotion,
                "emotion_confidence": emotion_confidence,
                "visual_context": visual_context,
                "mode_hint": mode_hint,
            }
        )
        reply = next(self.replies)
        if isinstance(reply, dict):
            return dict(reply)
        return {"ok": True, "reply": reply, "should_end": False}

    def visual_transition(
        self,
        *,
        from_emotion: str,
        to_emotion: str,
        companion_action: str | None,
        visual_context: dict,
    ) -> dict:
        self.visual_transition_calls.append(
            {
                "from_emotion": from_emotion,
                "to_emotion": to_emotion,
                "companion_action": companion_action,
                "visual_context": visual_context,
            }
        )
        reply = next(self.visual_transition_replies)
        if isinstance(reply, dict):
            return dict(reply)
        return {"ok": True, "reply": reply, "should_end": False}


class OrderedSpeechClient(FakeSpeechClient):
    def __init__(self, transcripts: list[str], order: list[str]) -> None:
        super().__init__(transcripts)
        self._order = order

    def speak(self, text: str, **options) -> dict:
        if text != DEMO_SCENE_DIALOGUE:
            self._order.append("opening_speak")
        return super().speak(text, **options)

    def listen_g1(self, *, seconds: float, output_path: str, **options) -> dict:
        self._order.append("first_listen")
        return super().listen_g1(seconds=seconds, output_path=output_path)


class OrderedOutput(io.StringIO):
    def __init__(self, order: list[str]) -> None:
        super().__init__()
        self._order = order

    def write(self, value: str) -> int:
        if '"kind":"emotion_dialogue_custom_action_request"' in value:
            self._order.append("invite_request")
        return super().write(value)


class DetectionOpeningTest(unittest.TestCase):
    def test_listen_invite_follows_sad_opening_once_before_first_listen(self) -> None:
        order: list[str] = []
        client = OrderedSpeechClient(["我想说说心里话", "结束吧"], order)
        output = OrderedOutput(order)
        with tempfile.TemporaryDirectory() as temp_dir:
            consume_events(
                io.StringIO(json.dumps(event(emotion="sad"))),
                client,
                output,
                demo_scene="dialogue",
                audio_dir=Path(temp_dir),
                chat_client=FakeElderChat(["我在听。"]),
                enable_listen_invite=True,
            )

        records = [json.loads(line) for line in output.getvalue().splitlines()]
        requests = [
            row
            for row in records
            if row["kind"] == "emotion_dialogue_custom_action_request"
        ]
        self.assertEqual(
            client.spoken[1][0],
            "看到您好像心情有些低落。如果您愿意，可以和我说说发生了什么，我会认真听。",
        )
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0]["action_name"], "open_palm_invite")
        self.assertEqual(requests[0]["status"], "confirmed")
        self.assertEqual(requests[0]["sequence"], "with_detection_opening")
        self.assertFalse(requests[0]["physical_actions_emitted"])
        self.assertLess(order.index("invite_request"), order.index("opening_speak"))
        self.assertLess(order.index("invite_request"), order.index("first_listen"))

    def test_listen_invite_cover_face_uses_low_mood_posture_line(self) -> None:
        expected = {
            "possible": "看到您低着头捂着脸，好像心情有些低落。您愿意和我聊一聊吗？我可以陪着您。",
            "stable_face": "看到您好像心情有些低落，并且在捂脸。如果您愿意，可以跟我说说，我会认真听。",
        }
        for inference_level, spoken in expected.items():
            with self.subTest(inference_level=inference_level):
                client = FakeSpeechClient(["结束吧"])
                with tempfile.TemporaryDirectory() as temp_dir:
                    consume_events(
                        io.StringIO(
                            json.dumps(
                                event(
                                    emotion="sad",
                                    behavior_cues=["cover_face_head_down"],
                                    inference_level=inference_level,
                                )
                            )
                        ),
                        client,
                        io.StringIO(),
                        demo_scene="dialogue",
                        audio_dir=Path(temp_dir),
                        chat_client=FakeElderChat([]),
                        enable_listen_invite=True,
                    )
                self.assertEqual(client.spoken[1][0], spoken)

    def test_listen_invite_does_not_change_happy_or_angry(self) -> None:
        for emotion in ("happy", "angry"):
            with self.subTest(emotion=emotion), tempfile.TemporaryDirectory() as temp_dir:
                client = FakeSpeechClient(["结束吧"])
                output = io.StringIO()
                consume_events(
                    io.StringIO(json.dumps(event(emotion=emotion))),
                    client,
                    output,
                    demo_scene="dialogue",
                    audio_dir=Path(temp_dir),
                    chat_client=FakeElderChat([]),
                    enable_listen_invite=True,
                )
                records = [json.loads(line) for line in output.getvalue().splitlines()]
                self.assertFalse(
                    any(
                        row["kind"] == "emotion_dialogue_custom_action_request"
                        for row in records
                    )
                )
                self.assertNotIn("您愿意和我聊一聊吗？", [text for text, _ in client.spoken])

    def test_stable_happy_face_only(self) -> None:
        text = _detection_opening(event())
        self.assertEqual(text, "检测到您笑了，看起来非常开心")
        self.assertNotIn("可以吗", text)
        self.assertNotIn("貌似", text)

    def test_stable_happy_wave_mentions_smile_and_wave(self) -> None:
        text = _detection_opening(event(behavior_cues=["wave_open_palm"]))
        self.assertEqual(text, "检测到您笑了，并向我挥手")
        self.assertIn("笑了", text)
        self.assertIn("并向我挥手", text)
        self.assertNotIn("貌似", text)
        self.assertNotIn("可以吗", text)

    def test_action_trigger_happy_face_mentions_smile_without_face_stability(self) -> None:
        text = _spoken_opening(
            event(behavior_cues=["wave_open_palm"], inference_level="action_face"),
            {"motion_id": "reply_wave_once", "action_zh": "挥手", "action_id": 25},
        )

        self.assertEqual(text, "检测到您笑了，并向我挥手。我也想挥手回应，可以吗？")

    def test_possible_happy_wave_hedges_and_never_claims_a_smile(self) -> None:
        text = _detection_opening(
            event(behavior_cues=["wave_open_palm"], inference_level="possible")
        )
        self.assertEqual(text, "检测到您在挥手，貌似您很高兴")
        self.assertNotIn("检测到您笑了", text)
        self.assertNotIn("可以吗", text)

    def test_possible_angry_downward_fist_says_downward_strike_not_table(self) -> None:
        text = _detection_opening(
            event(
                emotion="angry",
                behavior_cues=["rapid_downward_fist_lower_frame"],
                inference_level="possible",
            )
        )
        self.assertEqual(text, "检测到您在向下捶，貌似您有些生气")
        self.assertIn("向下捶", text)
        self.assertIn("貌似您有些生气", text)
        self.assertNotIn("锤桌子", text)
        self.assertNotIn("检测到您笑了", text)

    def test_dialogue_happy_opening_adds_share_follow(self) -> None:
        text = _spoken_opening(event(), None)
        self.assertEqual(
            text,
            "检测到您笑了，看起来非常开心。有什么开心的事，也跟我分享一下吧。",
        )
        self.assertNotIn("可以吗", text)

    def test_dialogue_angry_face_adds_listen_follow(self) -> None:
        text = _spoken_opening(event(emotion="angry"), None)
        self.assertEqual(
            text,
            "检测到您好像有些生气。如果您愿意，可以跟我说说发生了什么，我在听。",
        )
        self.assertNotIn("可以吗", text)
        self.assertNotIn("您愿意和我聊一聊吗？", text)

    def test_dialogue_angry_downward_fist_adds_space_follow(self) -> None:
        text = _spoken_opening(
            event(
                emotion="angry",
                behavior_cues=["rapid_downward_fist_lower_frame"],
                inference_level="possible",
            ),
            None,
        )
        self.assertEqual(
            text,
            "检测到您在向下捶，貌似您有些生气。"
            f"{DIALOGUE_OPENING_FOLLOWS['angry']}",
        )
        self.assertNotIn("您愿意和我聊一聊吗？", text)
        self.assertNotIn("锤桌子", text)

    def test_motion_offer_skips_happy_share_follow(self) -> None:
        text = _spoken_opening(
            event(behavior_cues=["wave_open_palm"]),
            {"motion_id": "reply_wave_once", "action_zh": "挥手", "action_id": 25},
        )
        self.assertEqual(text, "检测到您笑了，并向我挥手。我也想挥手回应，可以吗？")
        self.assertNotIn(DIALOGUE_OPENING_FOLLOWS["happy"], text)

    def test_possible_sad_cover_face_hedges_sadness(self) -> None:
        text = _detection_opening(
            event(
                emotion="sad",
                behavior_cues=["cover_face_head_down"],
                inference_level="possible",
            )
        )
        self.assertEqual(text, "看到您低着头捂着脸，好像心情有些低落")
        self.assertNotIn("检测到您在捂脸", text)
        self.assertNotIn("貌似您有些难过", text)

    def test_stable_sad_cover_face_names_both_face_and_cover(self) -> None:
        text = _detection_opening(
            event(
                emotion="sad",
                behavior_cues=["cover_face_head_down"],
            )
        )
        self.assertEqual(text, "看到您好像心情有些低落，并且在捂脸")

    def test_sad_face_spoken_opening_uses_companionship_follow(self) -> None:
        text = _spoken_opening(event(emotion="sad"), None)
        self.assertEqual(
            text,
            "看到您好像心情有些低落。如果您愿意，可以和我说说发生了什么，我会认真听。",
        )
        self.assertNotIn("我在听。", text)

    def test_sad_cover_possible_spoken_opening_offers_to_stay(self) -> None:
        text = _spoken_opening(
            event(
                emotion="sad",
                behavior_cues=["cover_face_head_down"],
                inference_level="possible",
            ),
            None,
        )
        self.assertEqual(
            text,
            "看到您低着头捂着脸，好像心情有些低落。您愿意和我聊一聊吗？我可以陪着您。",
        )

    def test_sad_and_angry_follows_are_not_the_same(self) -> None:
        sad = _spoken_opening(event(emotion="sad"), None)
        angry = _spoken_opening(event(emotion="angry"), None)
        self.assertIn("我会认真听。", sad)
        self.assertIn("我在听。", angry)
        self.assertNotIn("也跟我分享一下吧。", sad)
        self.assertNotIn("也跟我分享一下吧。", angry)

    def test_sad_face_only_does_not_claim_covering_the_face(self) -> None:
        text = _detection_opening(event(emotion="sad"))
        self.assertEqual(text, "看到您好像心情有些低落")
        self.assertNotIn("捂着脸", text)

    def test_sad_without_posture_cues_does_not_claim_covering_the_face(self) -> None:
        for cues in ([], ["closed_fist"], ["wave_open_palm"]):
            with self.subTest(cues=cues):
                text = _detection_opening(
                    event(
                        emotion="sad",
                        behavior_cues=cues,
                        inference_level="possible",
                    )
                )
                self.assertEqual(text, "看到您好像心情有些低落")
                self.assertNotIn("捂着脸", text)
                self.assertNotIn("检测到您在捂脸", text)

    def test_sad_cover_face_wins_over_unrelated_opening_cues(self) -> None:
        text = _detection_opening(
            event(
                emotion="sad",
                behavior_cues=["wave_open_palm", "cover_face_head_down"],
                inference_level="possible",
            )
        )
        self.assertEqual(text, "看到您低着头捂着脸，好像心情有些低落")

    def test_sad_hand_near_eye_uses_the_same_low_mood_line(self) -> None:
        text = _detection_opening(
            event(
                emotion="sad",
                behavior_cues=["hand_near_eye_head_down"],
                inference_level="possible",
            )
        )
        self.assertEqual(text, "看到您低着头、手靠近眼睛，好像心情有些低落")

    def test_opening_never_returns_action_without_emotion(self) -> None:
        payloads = (
            event(behavior_cues=["wave_open_palm"]),
            event(behavior_cues=["wave_open_palm"], inference_level="possible"),
            event(
                emotion="angry",
                behavior_cues=["rapid_downward_fist_lower_frame"],
                inference_level="possible",
            ),
            event(
                emotion="sad",
                behavior_cues=["cover_face_head_down"],
                inference_level="possible",
            ),
            event(emotion="sad"),
            event(emotion="angry"),
        )
        emotion_marks = ("高兴", "开心", "笑了", "难过", "低落", "生气")
        for payload in payloads:
            with self.subTest(cues=payload["behavior_cues"], level=payload["inference_level"]):
                text = _detection_opening(payload)
                self.assertTrue(any(mark in text for mark in emotion_marks), text)
                self.assertFalse(
                    text.startswith("检测到您在")
                    and not any(mark in text for mark in emotion_marks)
                )
                self.assertNotIn("锤桌子", text)

    def test_known_cue_priority_prefers_clap_over_wave(self) -> None:
        text = _detection_opening(
            event(behavior_cues=["closed_fist", "wave_open_palm", "clap_two_hands"])
        )
        self.assertEqual(text, "检测到您笑了，并向我鼓掌")
        self.assertNotIn("挥手", text)
        self.assertNotIn("握拳", text)

    def test_possible_without_known_cue_still_hedges_emotion(self) -> None:
        text = _detection_opening(event(inference_level="possible"))
        self.assertEqual(text, "检测到一些动作线索，貌似您很高兴")
        self.assertNotIn("检测到您笑了", text)


class EmotionDialogueTest(unittest.TestCase):
    def test_reply_validation_text_stays_in_console_only(self) -> None:
        candidate = "候选回复包含老人未说的私密家庭安排。"
        repair = "第二份候选回复。"
        diagnostics = {
            "validation_ok": False,
            "validation_errors": ["UNREQUESTED_QUESTION"],
            "candidate_text": candidate,
            "repair_attempted": True,
            "repair_validation_errors": [],
            "repair_text": repair,
            "final_source": "repair",
        }
        chat = FakeElderChat([{"reply": "孩子回来，您挺高兴的。", "reply_validation": diagnostics}])
        output, console = io.StringIO(), io.StringIO()
        with tempfile.TemporaryDirectory() as directory:
            consume_events(io.StringIO(json.dumps(event()) + "\n"),
                           FakeSpeechClient(["孩子要回来。", "结束吧"]), output,
                           demo_scene="dialogue", audio_dir=directory, chat_client=chat, console=console)
        self.assertIn(candidate, console.getvalue())
        self.assertIn(repair, console.getvalue())
        self.assertNotIn(candidate, output.getvalue())
        self.assertNotIn(repair, output.getvalue())
        turns = [json.loads(line) for line in output.getvalue().splitlines()
                 if json.loads(line).get("kind") == "emotion_dialogue_turn"]
        self.assertEqual(turns[0]["reply_validation"]["validation_errors"], ["UNREQUESTED_QUESTION"])
        self.assertEqual(turns[0]["reply_validation"]["final_source"], "repair")

    def test_memory_ignores_happy_after_angry(self) -> None:
        memory = DialogueMemory(initial_emotion="angry")

        self.assertIsNone(memory.observe(event(event_id="event-happy", emotion="happy")))

    def test_memory_ignores_happy_after_sad_without_joke(self) -> None:
        memory = DialogueMemory(initial_emotion="sad")

        self.assertIsNone(memory.observe(event(event_id="event-happy", emotion="happy")))

    def test_memory_ignores_action_face_after_sad_joke(self) -> None:
        memory = DialogueMemory(initial_emotion="sad")
        memory.remember_completed_reply("请给我讲个笑话")

        self.assertIsNone(
            memory.observe(
                event(
                    event_id="event-action-face",
                    emotion="happy",
                    behavior_cues=["wave_open_palm"],
                    inference_level="action_face",
                )
            )
        )

    def test_angry_happy_visual_update_does_not_add_a_reply(self) -> None:
        client = FakeSpeechClient(["我有点烦"])
        chat = FakeElderChat(["我先安静陪着您。"], ["听到您笑了，我也很高兴。"])
        visual_updates: queue.Queue = queue.Queue()

        def play_audio(_bridge: str, _audio_path: str) -> dict:
            if client.spoken[-1][0] == "我先安静陪着您。":
                visual_updates.put(event(event_id="event-smile", emotion="happy"))
            return _pcm(_bridge, _audio_path)

        with tempfile.TemporaryDirectory() as temp_dir:
            output = io.StringIO()
            consume_events(
                io.StringIO(json.dumps(event(emotion="angry"))),
                client,
                output,
                demo_scene="dialogue",
                audio_dir=Path(temp_dir),
                chat_client=chat,
                visual_updates=visual_updates,
                play_audio=play_audio,
            )

        self.assertEqual(chat.visual_transition_calls, [])
        self.assertNotIn("emotion_dialogue_visual_transition", output.getvalue())

    def test_elder_chat_client_sends_a_structured_visual_transition(self) -> None:
        response = unittest.mock.Mock()
        response.json.return_value = {"ok": True, "session_id": "session-1", "reply": "好的"}
        with patch("scenarios.elder_companion.elder_chat_client.requests.post", return_value=response) as post:
            chat = ElderChatClient(base_url="http://elder.test")
            chat.session_id = "session-1"
            result = chat.visual_transition(
                from_emotion="angry",
                to_emotion="happy",
                companion_action=None,
                visual_context={"inference_level": "stable_face"},
            )

        self.assertEqual(result["reply"], "好的")
        self.assertEqual(
            post.call_args.kwargs["json"],
            {
                "elderly_id": 1,
                "session_id": "session-1",
                "from_emotion": "angry",
                "to_emotion": "happy",
                "companion_action": None,
                "visual_context": {"inference_level": "stable_face"},
            },
        )

    def test_sad_joke_then_happy_visual_transition_uses_same_llm_session_after_playback(self) -> None:
        client = FakeSpeechClient(["请给我讲个笑话"])
        chat = FakeElderChat(
            ["好呀，给您讲一个轻松的笑话。"],
            ["听到您笑了，我也很高兴。刚才的笑话能让您轻松一点就好。"],
        )
        visual_updates: queue.Queue = queue.Queue()

        def play_audio(_bridge: str, _audio_path: str) -> dict:
            if client.spoken[-1][0] == "好呀，给您讲一个轻松的笑话。":
                visual_updates.put(event(event_id="event-smile", emotion="happy"))
            return _pcm(_bridge, _audio_path)

        with tempfile.TemporaryDirectory() as temp_dir:
            output = io.StringIO()
            summary = consume_events(
                io.StringIO(json.dumps(event(emotion="sad"))),
                client,
                output,
                demo_scene="dialogue",
                audio_dir=Path(temp_dir),
                chat_client=chat,
                visual_updates=visual_updates,
                play_audio=play_audio,
            )

        records = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(summary, {"received": 1, "completed": 1, "duplicates": 0, "ignored": 0})
        self.assertEqual(len(chat.calls), 1)
        self.assertEqual(
            chat.visual_transition_calls,
            [
                {
                    "from_emotion": "sad",
                    "to_emotion": "happy",
                    "companion_action": "joke",
                    "visual_context": {
                        "inference_level": "stable_face",
                        "evidence_source": "face",
                        "behavior_cues": [],
                    },
                }
            ],
        )
        self.assertTrue(
            any("刚才的笑话能让您轻松一点就好。" in text for text, _ in client.spoken)
        )
        self.assertTrue(
            any(
                record["kind"] == "emotion_dialogue_visual_transition"
                and record["from_emotion"] == "sad"
                and record["to_emotion"] == "happy"
                and record["companion_action"] == "joke"
                and record["g1_played"] is True
                for record in records
            )
        )
        self.assertEqual(client.spoken[-1][0], "好的，很高兴和您聊这些开心的事。我们下次再聊。")
        self.assertEqual(client.spoken[-1][1]["style"], "happy")
        self.assertEqual(client.spoken[-1][1]["emotion"], "cheerful")
        self.assertNotEqual(client.spoken[-1][1]["style"], "comfort")

    def test_dialogue_pcm_timeout_covers_a_long_wav_and_rpc_margin(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            wav_path = Path(temp_dir) / "long.wav"
            write_pcm_wav(wav_path, seconds=21)
            bridge_response = {
                "kind": "g1_companion_pcm_bridge",
                "status": "completed",
                "wav_path": str(wav_path),
            }
            with patch("emotion_dialogue.subprocess.run") as run:
                run.return_value = subprocess.CompletedProcess(
                    ["pcm-bridge"], 0, stdout=json.dumps(bridge_response), stderr=""
                )
                self.assertEqual(
                    _run_dialogue_pcm_bridge("pcm-bridge", str(wav_path)),
                    bridge_response,
                )

        self.assertGreater(run.call_args.kwargs["timeout"], 21.0)

    def test_dialogue_pcm_timeout_uses_actual_size_for_streaming_wav_header(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            wav_path = Path(temp_dir) / "streaming.wav"
            write_pcm_wav(wav_path, seconds=2)
            data = bytearray(wav_path.read_bytes())
            struct.pack_into("<I", data, 4, 2147483583)
            struct.pack_into("<I", data, 40, 2147483547)
            wav_path.write_bytes(data)
            self.assertLess(_dialogue_pcm_timeout(str(wav_path)), 60)

    def test_event_runs_opening_and_three_turn_dialogue_without_retaining_mic_wav(self) -> None:
        client = FakeSpeechClient(["今天孩子来看我了", "我挺高兴的", "他陪我吃了顿饭"])
        chat = FakeElderChat(
            [
                "这真是件高兴事。您最想和我说哪一段？",
                "听您这么说，我也替您高兴。后来你们聊了些什么？",
                "能和家人这样相处，听着就很温暖。",
            ]
        )
        played: list[str] = []

        def play(bridge_path: str, audio_path: str) -> dict:
            self.assertEqual(bridge_path, "/tmp/pcm-bridge")
            played.append(audio_path)
            return {"pcm_bytes": 16000, "duration_milliseconds": 500}

        with tempfile.TemporaryDirectory() as temp_dir:
            output = io.StringIO()
            console = io.StringIO()
            summary = consume_events(
                io.StringIO(json.dumps(event())),
                client,
                output,
                demo_scene="dialogue",
                audio_dir=Path(temp_dir),
                chat_client=chat,
                play_audio=play,
                console=console,
            )

        self.assertEqual(summary, {"received": 1, "completed": 1, "duplicates": 0, "ignored": 0})
        self.assertEqual(len(client.spoken), 6)
        self.assertEqual(len(played), 6)
        self.assertEqual(client.spoken[0][0], "现在演示多轮对话场景")
        self.assertEqual(
            client.spoken[1][0],
            "检测到您笑了，看起来非常开心。有什么开心的事，也跟我分享一下吧。",
        )
        self.assertNotIn("现在演示动作交互场景", [text for text, _ in client.spoken])
        self.assertFalse(any("可以吗" in text for text, _ in client.spoken))
        self.assertEqual(len(chat.calls), 3)
        self.assertEqual(client.listen_seconds, [20.0, 20.0, 20.0, 20.0])
        self.assertEqual(
            [call["text"] for call in chat.calls],
            ["今天孩子来看我了", "我挺高兴的", "他陪我吃了顿饭"],
        )
        for call in chat.calls:
            self.assertEqual(call["emotion"], "happy")
            self.assertEqual(call["emotion_confidence"], 0.91)
            self.assertEqual(call["mode_hint"], "auto")
            self.assertEqual(call["visual_context"]["inference_level"], "stable_face")
            self.assertEqual(call["visual_context"]["evidence_source"], "face")
            self.assertEqual(call["visual_context"]["behavior_cues"], [])
            self.assertNotIn("engagement", call["visual_context"])
            self.assertNotIn("eye_contact", call["visual_context"])
        self.assertNotIn("现在演示多轮对话场景", [call["text"] for call in chat.calls])
        self.assertNotIn("检测到您笑了，看起来非常开心", [call["text"] for call in chat.calls])
        self.assertNotIn("round_no", chat.calls[0])
        self.assertNotIn("max_rounds", chat.calls[0])
        self.assertNotIn("policy_context", chat.calls[0])
        self.assertNotIn("history", chat.calls[0])
        self.assertTrue(all(not path.exists() for path in client.listened_paths))
        self.assertNotIn("今天孩子来看我了", output.getvalue())
        self.assertNotIn("emotion_dialogue_console", output.getvalue())
        self.assertNotIn("[现场]", output.getvalue())
        self.assertIn('"stage":"检测到情绪策略"', console.getvalue())
        self.assertIn('"evidence_source":"face"', console.getvalue())
        self.assertIn('"behavior_cues":[]', console.getvalue())
        self.assertIn("[现场] 情绪=高兴", console.getvalue())
        self.assertIn("依据=稳定面部表情", console.getvalue())
        self.assertIn("来源=面部表情", console.getvalue())
        self.assertIn("动作线索=无", console.getvalue())
        self.assertIn("[现场] 演示场景=多轮对话", console.getvalue())
        self.assertIn(f"[现场] G1说：{DEMO_SCENE_DIALOGUE}", console.getvalue())
        self.assertNotIn("[现场] 演示场景=动作交互", console.getvalue())
        self.assertIn("[现场] G1说：", console.getvalue())
        self.assertIn("[现场] 动作提议=无", console.getvalue())
        self.assertIn('"strategy_id":"SHARE_POSITIVE"', console.getvalue())
        self.assertIn('"style":"happy"', console.getvalue())
        self.assertIn('"emotion":"cheerful"', console.getvalue())
        self.assertIn('"dialect":"mandarin"', console.getvalue())
        self.assertIn('"speed":1.05', console.getvalue())
        self.assertIn('"pitch":1.02', console.getvalue())
        self.assertIn('"volume":78', console.getvalue())
        self.assertIn('"voice":"longanfengyue"', console.getvalue())
        self.assertIn('"model":"qwen-audio-3.0-tts-flash"', console.getvalue())
        self.assertIn('"stage":"检测到老人说的内容"', console.getvalue())
        self.assertIn("今天孩子来看我了", console.getvalue())
        self.assertIn("[现场] 老人说：今天孩子来看我了", console.getvalue())
        self.assertIn("[现场] 判定：继续陪聊", console.getvalue())
        self.assertIn('"stage":"模型输出"', console.getvalue())
        self.assertIn("这真是件高兴事", console.getvalue())
        self.assertIn("[现场] LLM说：这真是件高兴事", console.getvalue())

    def test_dialogue_continues_past_three_turns_until_the_elder_ends_it(self) -> None:
        client = FakeSpeechClient(
            ["第一件事", "第二件事", "第三件事", "第四件事", "你先退下吧"]
        )
        chat = FakeElderChat(["我在听。", "后来呢？", "我明白。", "您慢慢说。"])

        with tempfile.TemporaryDirectory() as temp_dir:
            output = io.StringIO()
            consume_events(
                io.StringIO(json.dumps(event())),
                client,
                output,
                demo_scene="dialogue",
                audio_dir=Path(temp_dir),
                chat_client=chat,
            )

        records = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(len(chat.calls), 4)
        self.assertEqual(client.listen_seconds, [20.0] * 5)
        self.assertTrue(
            any(
                record["kind"] == "emotion_dialogue_turn"
                and record["round_no"] == 5
                and record["status"] == "quiet_requested"
                for record in records
            )
        )

    def test_obvious_asr_fragment_is_not_sent_to_chat(self) -> None:
        client = FakeSpeechClient(["，老师。", "嗯，这回先到这儿吧。"])
        chat = FakeElderChat([])
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as temp_dir:
            consume_events(
                io.StringIO(json.dumps(event())), client, output,
                demo_scene="dialogue", audio_dir=Path(temp_dir), chat_client=chat,
            )
        turns = [json.loads(line) for line in output.getvalue().splitlines()
                 if '"kind":"emotion_dialogue_turn"' in line]
        self.assertEqual([turn["status"] for turn in turns], ["unclear_input", "quiet_requested"])
        self.assertEqual(chat.calls, [])
        self.assertEqual(len(client.spoken), 3)

    def test_light_question_decision_is_visible_in_console_and_turn_receipt(self) -> None:
        client = FakeSpeechClient(["周末见到她我很高兴。", "这回先到这儿吧。"])
        chat = FakeElderChat([{
            "reply": "周末准备一起吃点什么吗？", "mode": "caregiver",
            "question_opportunity": "good", "reply_action": "ASK_LIGHT",
            "reason": "当前话题已有一起吃饭的具体场景",
        }])
        output, console = io.StringIO(), io.StringIO()
        with tempfile.TemporaryDirectory() as temp_dir:
            consume_events(io.StringIO(json.dumps(event())), client, output,
                           demo_scene="dialogue", audio_dir=Path(temp_dir),
                           chat_client=chat, console=console)
        turn = next(json.loads(line) for line in output.getvalue().splitlines()
                    if '"status":"completed"' in line and '"kind":"emotion_dialogue_turn"' in line)
        self.assertEqual((turn["question_opportunity"], turn["reply_action"]), ("good", "ASK_LIGHT"))
        self.assertNotIn("reason", turn)
        self.assertIn('"reason":"当前话题已有一起吃饭的具体场景"', console.getvalue())
        self.assertIn("轻问机会=good 动作=ASK_LIGHT", console.getvalue())

    def test_api_should_end_speaks_reply_then_stops(self) -> None:
        client = FakeSpeechClient(["今天就这样吧", "这句不该再听"])
        chat = FakeElderChat(
            [
                {
                    "reply": "好的，那我先不打扰您了。",
                    "should_end": True,
                    "mode": "caregiver",
                    "transfer_to": "CONTACT_FAMILY",
                    "caregiver_strategy": ["gentle_close"],
                }
            ]
        )
        output = io.StringIO()
        console = io.StringIO()
        with tempfile.TemporaryDirectory() as temp_dir:
            consume_events(
                io.StringIO(json.dumps(event())),
                client,
                output,
                demo_scene="dialogue",
                audio_dir=Path(temp_dir),
                chat_client=chat,
                console=console,
            )

        records = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(len(chat.calls), 1)
        self.assertEqual(chat.calls[0]["text"], "今天就这样吧")
        self.assertEqual(chat.calls[0]["mode_hint"], "auto")
        self.assertEqual(len(client.listen_seconds), 1)
        self.assertEqual(client.spoken[-1][0], "好的，那我先不打扰您了。")
        self.assertNotIn("CONTACT_FAMILY", [text for text, _ in client.spoken])
        self.assertNotIn("caregiver", [text for text, _ in client.spoken])
        self.assertIn("[现场] LLM说：好的，那我先不打扰您了。", console.getvalue())
        self.assertIn("mode=caregiver", console.getvalue())
        self.assertTrue(
            any(
                record["kind"] == "emotion_dialogue_turn"
                and record["status"] == "session_ended"
                and record.get("mode") == "caregiver"
                and record.get("transfer_to") == "CONTACT_FAMILY"
                and "今天就这样吧" not in json.dumps(record, ensure_ascii=False)
                for record in records
            )
        )
        self.assertNotIn("今天就这样吧", output.getvalue())
        self.assertNotIn("这句不该再听", console.getvalue())

    def test_explicit_termination_phrases_are_quiet_requests(self) -> None:
        for phrase in (
            "我不想聊了",
            "结束吧",
            "就到这吧",
            "你先退下吧",
            "你先关闭吧",
            "我先不给你聊了",
            "我先不跟你聊了",
            "今天先聊到这里吧",
            "改天再聊吧",
            "我想一个人待一会儿",
            "嗯，这回先到这儿吧。",
            "本次先到这吧",
            "跟你聊了一会儿，我感觉心里好多了。谢谢你陪我说了这么久，本次就先到这吧。",
        ):
            with self.subTest(phrase=phrase):
                self.assertTrue(_is_quiet_request(phrase))

    def test_ordinary_chat_is_not_a_quiet_request(self) -> None:
        for phrase in (
            "我今天休息得很好", "比赛结束以后再出门", "我不想说天气",
            "这个故事结束了吗？", "先别结束", "故事还没结束吧", "先别结束聊天",
            "我还没说完呢", "这里很安静", "这首歌结束了",
            "他刚才说不聊了",
            "他刚才说，今天就先到这吧。",
            "他刚才说，他已经讲了很长时间，今天就先到这吧。",
            "她刚才说，大家都已经累了，今天就先到这吧。",
            "我朋友刚才说，今天就先到这吧。",
            "儿子说，今天先到这吧。",
            "孩子刚才说，本次就先到这吧。",
            "粉丝最先到这儿。",
            "还没到结束的时候",
        ):
            with self.subTest(phrase=phrase):
                self.assertFalse(_is_quiet_request(phrase))

    def test_scene_cue_selects_one_nonexecuting_motion_intent(self) -> None:
        for emotion, behavior_cues, motion_id, trigger in (
            ("happy", [], "no_motion", "emotion_strategy"),
            ("happy", ["wave_open_palm"], "reply_wave_once", "wave_open_palm"),
            ("happy", ["clap_two_hands"], "celebrate_once", "clap_two_hands"),
            ("sad", [], "listen_hold", "emotion_strategy"),
            ("angry", [], "return_to_neutral", "emotion_strategy"),
        ):
            with self.subTest(emotion=emotion, behavior_cues=behavior_cues), tempfile.TemporaryDirectory() as temp_dir:
                client = FakeSpeechClient(["不聊"])
                output = io.StringIO()
                consume_events(
                    io.StringIO(json.dumps(event(emotion=emotion, behavior_cues=behavior_cues))),
                    client,
                    output,
                    demo_scene="dialogue",
                    audio_dir=Path(temp_dir),
                    chat_client=FakeElderChat([]),
                    play_audio=lambda _bridge, _audio_path: {},
                )

                records = [json.loads(line) for line in output.getvalue().splitlines()]
                motions = [
                    record
                    for record in records
                    if record["kind"] == "emotion_dialogue_motion_intent"
                ]
                self.assertEqual(client.spoken[0][0], "现在演示多轮对话场景")
                self.assertNotIn("现在演示动作交互场景", [text for text, _ in client.spoken])
                self.assertTrue(
                    any(
                        record["kind"] == "emotion_dialogue_scene_announce"
                        and record.get("scene") == "dialogue"
                        and record.get("text") == "现在演示多轮对话场景"
                        for record in records
                    )
                )
                self.assertFalse(
                    any(record["kind"] == "emotion_dialogue_motion_request" for record in records)
                )
                self.assertEqual(len(motions), 1)
                self.assertEqual(motions[0]["motion_id"], motion_id)
                self.assertEqual(motions[0]["trigger"], trigger)
                self.assertEqual(motions[0]["execution"], "intent_only")
                self.assertFalse(motions[0]["physical_actions_emitted"])
                self.assertFalse(any("可以吗" in text for text, _ in client.spoken))

    def test_dialogue_happy_gesture_chats_without_motion_request(self) -> None:
        client = FakeSpeechClient(["好啊", "今天孩子来看我了", "我挺高兴的"])
        chat = FakeElderChat(["听您这么说真好。", "后来呢？", "能这样就很暖。"])
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as temp_dir:
            consume_events(
                io.StringIO(json.dumps(event(behavior_cues=["wave_open_palm"]))),
                client,
                output,
                demo_scene="dialogue",
                audio_dir=Path(temp_dir),
                chat_client=chat,
            )

        records = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(client.spoken[0][0], DEMO_SCENE_DIALOGUE)
        self.assertEqual(
            client.spoken[1][0],
            "检测到您笑了，并向我挥手。有什么开心的事，也跟我分享一下吧。",
        )
        self.assertNotIn(DEMO_SCENE_MOTION, [text for text, _ in client.spoken])
        self.assertFalse(any("可以吗" in text for text, _ in client.spoken))
        self.assertGreaterEqual(len(chat.calls), 1)
        self.assertFalse(
            any(record["kind"] == "emotion_dialogue_motion_request" for record in records)
        )
        self.assertTrue(
            any(
                record["kind"] == "emotion_dialogue_motion_intent"
                and record["motion_id"] == "reply_wave_once"
                for record in records
            )
        )

    def test_motion_happy_gesture_asks_then_emits_request_without_second_scene(self) -> None:
        cases = (
            (["wave_open_palm"], "reply_wave_once", 25, "挥手"),
            (["clap_two_hands"], "celebrate_once", 17, "鼓掌"),
        )
        for cues, motion_id, action_id, action_zh in cases:
            with self.subTest(cue=cues[0]), tempfile.TemporaryDirectory() as temp_dir:
                client = FakeSpeechClient(["好啊"])
                output = io.StringIO()
                console = io.StringIO()
                chat = FakeElderChat([])
                consume_events(
                    io.StringIO(json.dumps(event(behavior_cues=cues))),
                    client,
                    output,
                    demo_scene="motion",
                    audio_dir=Path(temp_dir),
                    chat_client=chat,
                    console=console,
                )

                records = [json.loads(line) for line in output.getvalue().splitlines()]
                self.assertEqual(client.spoken[0][0], DEMO_SCENE_MOTION)
                self.assertEqual(
                    client.spoken[1][0],
                    f"检测到您笑了，并向我{action_zh}。我也想{action_zh}回应，可以吗？",
                )
                self.assertIn("可以吗", client.spoken[1][0])
                self.assertNotIn("貌似", client.spoken[1][0])
                self.assertEqual(len(client.spoken), 2)
                self.assertEqual(
                    [text for text, _ in client.spoken].count(DEMO_SCENE_MOTION),
                    1,
                )
                self.assertEqual(chat.calls, [])
                self.assertNotIn("[现场] 演示场景=多轮对话", console.getvalue())
                self.assertIn("[现场] 演示场景=动作交互", console.getvalue())
                self.assertIn(f"[现场] G1说：{DEMO_SCENE_MOTION}", console.getvalue())
                self.assertIn(f"[现场] 动作提议={action_zh} 官方ID={action_id}", console.getvalue())
                self.assertIn("[现场] 老人说：好啊", console.getvalue())
                self.assertIn(f"判定：肯定，记录{action_zh}请求", console.getvalue())
                self.assertIn("停止听答", console.getvalue())
                self.assertNotIn("好啊", output.getvalue())
                announce_at = next(
                    index
                    for index, record in enumerate(records)
                    if record["kind"] == "emotion_dialogue_scene_announce"
                    and record.get("scene") == "motion"
                )
                opening_at = next(
                    index
                    for index, record in enumerate(records)
                    if record["kind"] == "emotion_dialogue_opening"
                )
                request_at = next(
                    index
                    for index, record in enumerate(records)
                    if record["kind"] == "emotion_dialogue_motion_request"
                )
                self.assertLess(announce_at, opening_at)
                self.assertLess(opening_at, request_at)
                self.assertEqual(records[announce_at]["event_id"], "session")
                self.assertEqual(records[announce_at]["text"], DEMO_SCENE_MOTION)
                self.assertTrue(records[announce_at]["g1_played"])
                self.assertFalse(
                    any(
                        record["kind"] == "emotion_dialogue_scene_announce"
                        and record.get("scene") == "dialogue"
                        for record in records
                    )
                )
                request = records[request_at]
                self.assertEqual(request["motion_id"], motion_id)
                self.assertEqual(request["action_id"], action_id)
                self.assertEqual(request["status"], "confirmed")
                self.assertEqual(request["execution"], "intent_only")
                self.assertFalse(request["physical_actions_emitted"])
                self.assertFalse(
                    any(record["kind"] == "emotion_dialogue_turn" for record in records)
                )

    def test_duration_cutoff_cannot_authorize_motion(self) -> None:
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "emotion_dialogue._listen_once", side_effect=[
                ("可以", 12.0, {"endpoint_reason": "max_duration"}),
                ("结束吧", 12.0, {"endpoint_reason": "silence"}),
            ],
        ):
            consume_events(
                io.StringIO(json.dumps(event(behavior_cues=["wave_open_palm"]))),
                FakeSpeechClient([]), output, demo_scene="motion", audio_dir=Path(temp_dir),
            )
        records = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertFalse(any(row["kind"] == "emotion_dialogue_motion_request" for row in records))
        self.assertTrue(any(row.get("status") == "incomplete_confirmation" for row in records))

    def test_duration_cutoff_decline_still_blocks_a_later_yes(self) -> None:
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "emotion_dialogue._listen_once", side_effect=[
                ("不要挥手", 12.0, {"endpoint_reason": "max_duration"}),
                ("好", 12.0, {"endpoint_reason": "silence"}),
            ],
        ):
            consume_events(
                io.StringIO(json.dumps(event(behavior_cues=["wave_open_palm"]))),
                FakeSpeechClient([]), output, demo_scene="motion", audio_dir=Path(temp_dir),
            )
        records = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertFalse(any(row["kind"] == "emotion_dialogue_motion_request" for row in records))
        self.assertTrue(any(row.get("status") == "declined" for row in records))

    def test_motion_offer_decline_never_emits_a_motion_request(self) -> None:
        client = FakeSpeechClient(["不用"])
        output = io.StringIO()
        chat = FakeElderChat(["好的，我陪着您。"])
        with tempfile.TemporaryDirectory() as temp_dir:
            consume_events(
                io.StringIO(json.dumps(event(behavior_cues=["clap_two_hands"]))),
                client,
                output,
                demo_scene="motion",
                audio_dir=Path(temp_dir),
                chat_client=chat,
            )

        records = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(client.spoken[0][0], DEMO_SCENE_MOTION)
        self.assertEqual(
            client.spoken[1][0],
            "检测到您笑了，并向我鼓掌。我也想鼓掌回应，可以吗？",
        )
        self.assertEqual([text for text, _ in client.spoken].count(DEMO_SCENE_MOTION), 1)
        self.assertEqual(chat.calls, [])
        self.assertFalse(
            any(record["kind"] == "emotion_dialogue_motion_request" for record in records)
        )

    def test_motion_offer_decline_then_yes_does_not_emit_a_motion_request(self) -> None:
        for decline in ("不用", "不行", "不好", "别"):
            with self.subTest(decline=decline), tempfile.TemporaryDirectory() as temp_dir:
                client = FakeSpeechClient([decline, "好啊"])
                output = io.StringIO()
                chat = FakeElderChat(["好的，我陪着您。", "那我们聊点别的。"])
                consume_events(
                    io.StringIO(json.dumps(event(behavior_cues=["wave_open_palm"]))),
                    client,
                    output,
                    demo_scene="motion",
                    audio_dir=Path(temp_dir),
                    chat_client=chat,
                )

                records = [json.loads(line) for line in output.getvalue().splitlines()]
                self.assertEqual(client.spoken[0][0], DEMO_SCENE_MOTION)
                self.assertEqual(len(client.listen_seconds), 1)
                self.assertEqual(chat.calls, [])
                self.assertIn(
                    {"kind": "emotion_dialogue_motion_offer", "status": "declined"},
                    [
                        {key: record[key] for key in ("kind", "status")}
                        for record in records
                        if record["kind"] == "emotion_dialogue_motion_offer"
                    ],
                )
                self.assertFalse(
                    any(record["kind"] == "emotion_dialogue_motion_request" for record in records)
                )

    def test_water_pending_yes_does_not_authorize_motion(self) -> None:
        client = FakeSpeechClient(["我有点口渴", "好啊"])
        output = io.StringIO()
        chat = FakeElderChat([])
        with tempfile.TemporaryDirectory() as temp_dir:
            consume_events(
                io.StringIO(json.dumps(event(behavior_cues=["wave_open_palm"]))),
                client,
                output,
                demo_scene="dialogue",
                audio_dir=Path(temp_dir),
                chat_client=chat,
            )

        records = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(client.spoken[0][0], DEMO_SCENE_DIALOGUE)
        self.assertNotIn(DEMO_SCENE_MOTION, [text for text, _ in client.spoken])
        self.assertFalse(
            any(record["kind"] == "emotion_dialogue_motion_request" for record in records)
        )
        self.assertTrue(
            any(
                record["kind"] == "emotion_dialogue_care_request" and record.get("need") == "water"
                for record in records
            )
        )
        self.assertEqual(chat.calls, [])

    def test_water_decline_continues_dialogue_without_motion_request(self) -> None:
        client = FakeSpeechClient(["我有点口渴", "不用", "好啊"])
        output = io.StringIO()
        chat = FakeElderChat(["那我们聊点别的。", "好呀，我来陪您。"])
        with tempfile.TemporaryDirectory() as temp_dir:
            consume_events(
                io.StringIO(json.dumps(event(behavior_cues=["wave_open_palm"]))),
                client,
                output,
                demo_scene="dialogue",
                audio_dir=Path(temp_dir),
                chat_client=chat,
            )

        records = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertTrue(
            any(
                record["kind"] == "emotion_dialogue_care_offer" and record.get("status") == "declined"
                for record in records
            )
        )
        self.assertFalse(
            any(record["kind"] == "emotion_dialogue_motion_request" for record in records)
        )
        self.assertEqual(len(chat.calls), 2)
        self.assertEqual([call["text"] for call in chat.calls], ["不用", "好啊"])
        self.assertNotIn("现在演示多轮对话场景", [call["text"] for call in chat.calls])
        self.assertNotIn("现在演示动作交互场景", [call["text"] for call in chat.calls])
        self.assertEqual(chat.calls[0]["mode_hint"], "auto")
        self.assertEqual(client.spoken[0][0], DEMO_SCENE_DIALOGUE)
        self.assertNotIn(DEMO_SCENE_MOTION, [text for text, _ in client.spoken])

    def test_ordinary_chat_does_not_clear_as_a_decline(self) -> None:
        self.assertFalse(_is_motion_confirmation("特别高兴"))
        client = FakeSpeechClient(["特别高兴", "好啊"])
        output = io.StringIO()
        chat = FakeElderChat(["听您这么说真好。", "那真好。"])
        with tempfile.TemporaryDirectory() as temp_dir:
            consume_events(
                io.StringIO(json.dumps(event(behavior_cues=["wave_open_palm"]))),
                client,
                output,
                demo_scene="dialogue",
                audio_dir=Path(temp_dir),
                chat_client=chat,
            )

        records = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertFalse(any(record.get("status") == "declined" for record in records))
        self.assertFalse(
            any(record["kind"] == "emotion_dialogue_motion_request" for record in records)
        )
        self.assertEqual(len(chat.calls), 2)
        self.assertEqual([call["text"] for call in chat.calls], ["特别高兴", "好啊"])
        self.assertNotIn("现在演示多轮对话场景", [call["text"] for call in chat.calls])
        self.assertNotIn("现在演示动作交互场景", [call["text"] for call in chat.calls])
        self.assertEqual(client.spoken[0][0], DEMO_SCENE_DIALOGUE)
        self.assertNotIn(DEMO_SCENE_MOTION, [text for text, _ in client.spoken])

    def test_leading_yes_with_asr_filler_confirms_motion(self) -> None:
        self.assertTrue(_is_motion_confirmation("可以。差不多。"))
        self.assertTrue(_is_motion_confirmation("嗯可以"))
        self.assertTrue(_is_motion_confirmation("可以啊"))
        self.assertTrue(_is_motion_confirmation("可以可以呀。"))
        self.assertTrue(_is_motion_confirmation("可以，我也想看你们分手。"))
        self.assertTrue(_is_motion_confirmation("可以，我们和别人一起挥手。"))
        self.assertTrue(_is_motion_confirmation("可以，看看别的。"))
        self.assertTrue(_is_motion_confirmation("可以，别人也想挥手。"))
        self.assertTrue(_is_motion_confirmation("可以，别的节目也可以。"))
        self.assertFalse(_is_motion_confirmation("不可以"))
        self.assertFalse(_is_motion_confirmation("可以，但是不行"))
        self.assertFalse(_is_motion_confirmation("可以，但是别挥手"))
        self.assertFalse(_is_motion_confirmation("可以，但是别这样"))
        self.assertFalse(_is_motion_confirmation("可以，但别太快"))
        self.assertFalse(_is_motion_confirmation("可以，别做了"))
        self.assertFalse(_is_motion_confirmation("可以，但别这样了"))
        self.assertFalse(_is_motion_confirmation("可以，但别做了吧"))
        self.assertFalse(_is_motion_confirmation("可以，但别太快了"))
        self.assertFalse(_is_motion_confirmation("可以，但别那么快"))
        self.assertFalse(_is_motion_confirmation("可以，但是别再挥手了"))
        self.assertFalse(_is_motion_confirmation("可以，不过别做这个"))
        self.assertFalse(_is_motion_confirmation("可以，请别这样做"))
        self.assertFalse(_is_motion_confirmation("可以，不过我希望你别挥太久"))
        self.assertFalse(_is_motion_confirmation("可以，但是请你别做太久"))
        self.assertFalse(_is_motion_confirmation("可以，我不愿意"))
        self.assertFalse(_is_motion_confirmation("嗯"))
        self.assertFalse(_is_motion_confirmation("特别高兴"))
        self.assertFalse(_is_motion_confirmation("好像不太合适"))
        self.assertFalse(_is_motion_confirmation("可以再考虑一下"))

        client = FakeSpeechClient(["可以。差不多。"])
        output = io.StringIO()
        chat = FakeElderChat([])
        with tempfile.TemporaryDirectory() as temp_dir:
            consume_events(
                io.StringIO(json.dumps(event(behavior_cues=["wave_open_palm"]))),
                client,
                output,
                demo_scene="motion",
                audio_dir=Path(temp_dir),
                chat_client=chat,
            )

        records = [json.loads(line) for line in output.getvalue().splitlines()]
        request = next(
            record
            for record in records
            if record["kind"] == "emotion_dialogue_motion_request"
        )
        self.assertEqual(request["action_id"], 25)
        self.assertEqual(request["status"], "confirmed")
        self.assertEqual(chat.calls, [])
        self.assertEqual(client.spoken[0][0], DEMO_SCENE_MOTION)
        self.assertEqual(
            client.spoken[1][0],
            "检测到您笑了，并向我挥手。我也想挥手回应，可以吗？",
        )
        self.assertEqual(len(client.spoken), 2)
        self.assertEqual([text for text, _ in client.spoken].count(DEMO_SCENE_MOTION), 1)
        announce_at = next(
            index
            for index, record in enumerate(records)
            if record["kind"] == "emotion_dialogue_scene_announce"
            and record.get("scene") == "motion"
        )
        request_at = next(
            index
            for index, record in enumerate(records)
            if record["kind"] == "emotion_dialogue_motion_request"
        )
        self.assertLess(announce_at, request_at)

    def test_empty_or_uncertain_reply_does_not_emit_a_motion_request(self) -> None:
        dialogue_cases = (
            ("", [], 1),
            ("嗯", ["我在听。"], 1),
            ("我想安静一会儿", [], 1),
        )
        for transcript, replies, _ in dialogue_cases:
            with self.subTest(scene="dialogue", transcript=transcript), tempfile.TemporaryDirectory() as temp_dir:
                client = FakeSpeechClient([transcript])
                output = io.StringIO()
                consume_events(
                    io.StringIO(json.dumps(event(behavior_cues=["clap_two_hands"]))),
                    client,
                    output,
                    demo_scene="dialogue",
                    audio_dir=Path(temp_dir),
                    chat_client=FakeElderChat(replies),
                )
                records = [json.loads(line) for line in output.getvalue().splitlines()]
                self.assertEqual(client.spoken[0][0], DEMO_SCENE_DIALOGUE)
                self.assertNotIn(DEMO_SCENE_MOTION, [text for text, _ in client.spoken])
                self.assertFalse(
                    any(record["kind"] == "emotion_dialogue_motion_request" for record in records)
                )

        motion_cases = (("", 1), ("嗯", 2), ("我想安静一会儿", 1))
        for transcript, _ in motion_cases:
            with self.subTest(scene="motion", transcript=transcript), tempfile.TemporaryDirectory() as temp_dir:
                client = FakeSpeechClient([transcript, "好啊"] if transcript == "嗯" else [transcript])
                output = io.StringIO()
                chat = FakeElderChat([])
                consume_events(
                    io.StringIO(json.dumps(event(behavior_cues=["clap_two_hands"]))),
                    client,
                    output,
                    demo_scene="motion",
                    audio_dir=Path(temp_dir),
                    chat_client=chat,
                )
                records = [json.loads(line) for line in output.getvalue().splitlines()]
                self.assertEqual(client.spoken[0][0], DEMO_SCENE_MOTION)
                self.assertEqual(chat.calls, [])
                if transcript == "嗯":
                    request = next(
                        record
                        for record in records
                        if record["kind"] == "emotion_dialogue_motion_request"
                    )
                    self.assertEqual(request["action_id"], 17)
                    self.assertEqual(len(client.listen_seconds), 2)
                else:
                    self.assertFalse(
                        any(record["kind"] == "emotion_dialogue_motion_request" for record in records)
                    )

    def test_water_confirmation_or_repeated_request_stays_nonexecuting(self) -> None:
        for response in ("好，谢谢", "可以，麻烦你了", "给我一杯水"):
            with self.subTest(response=response), tempfile.TemporaryDirectory() as temp_dir:
                client = FakeSpeechClient(["我有点口渴", response])
                chat = FakeElderChat([])
                played: list[str] = []
                output = io.StringIO()
                console = io.StringIO()
                summary = consume_events(
                    io.StringIO(json.dumps(event())),
                    client,
                    output,
                    demo_scene="dialogue",
                    audio_dir=Path(temp_dir),
                    chat_client=chat,
                    play_audio=lambda _bridge, audio_path: played.append(audio_path) or {},
                    console=console,
                )

                records = [json.loads(line) for line in output.getvalue().splitlines()]
                self.assertEqual(
                    summary, {"received": 1, "completed": 1, "duplicates": 0, "ignored": 0}
                )
                self.assertEqual(len(client.spoken), 5)
                self.assertEqual(len(played), 5)
                self.assertEqual(client.spoken[0][0], DEMO_SCENE_DIALOGUE)
                self.assertNotIn(DEMO_SCENE_MOTION, [text for text, _ in client.spoken])
                self.assertEqual(chat.calls, [])
                self.assertEqual(client.listen_seconds, [20.0, 20.0, 20.0])
                self.assertTrue(
                    any(
                        record["kind"] == "emotion_dialogue_turn"
                        and record.get("status") == "quiet_requested"
                        for record in records
                    )
                )
                self.assertNotIn("我有点口渴", output.getvalue())
                self.assertNotIn(response, output.getvalue())
                self.assertIn("[现场] G1说：您需要喝点水吗？", console.getvalue())
                self.assertIn("[现场] 判定：询问是否需要喝水，等待确认", console.getvalue())
                self.assertIn("[现场] 判定：确认饮水需求，只记录不递水", console.getvalue())
                self.assertIn("[现场] G1说：好的，我已经收到您的饮水需求。", console.getvalue())
                care_requests = [
                    record
                    for record in records
                    if record["kind"] == "emotion_dialogue_care_request"
                ]
                self.assertEqual(len(care_requests), 1)
                self.assertFalse(care_requests[0]["delivery_started"])
                self.assertIn(
                    {"kind": "emotion_dialogue_care_offer", "offer": "water", "status": "offered"},
                    [
                        {key: record[key] for key in ("kind", "offer", "status")}
                        for record in records
                        if record["kind"] == "emotion_dialogue_care_offer"
                    ],
                )
                self.assertIn(
                    {"kind": "emotion_dialogue_care_request", "need": "water", "status": "confirmed"},
                    [
                        {key: record[key] for key in ("kind", "need", "status")}
                        for record in records
                        if record["kind"] == "emotion_dialogue_care_request"
                    ],
                )

    def test_water_offer_declined_continues_the_dialogue(self) -> None:
        client = FakeSpeechClient(["我有点口渴", "不用了，我想聊聊"])
        chat = FakeElderChat(["当然，我陪您聊。您想从哪里说起？"])

        with tempfile.TemporaryDirectory() as temp_dir:
            output = io.StringIO()
            console = io.StringIO()
            consume_events(
                io.StringIO(json.dumps(event())),
                client,
                output,
                demo_scene="dialogue",
                audio_dir=Path(temp_dir),
                chat_client=chat,
                play_audio=lambda _bridge, _audio_path: {},
                console=console,
            )

        records = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(len(client.spoken), 5)
        self.assertEqual(client.spoken[0][0], DEMO_SCENE_DIALOGUE)
        self.assertNotIn(DEMO_SCENE_MOTION, [text for text, _ in client.spoken])
        self.assertEqual(len(chat.calls), 1)
        self.assertEqual(chat.calls[0]["text"], "不用了，我想聊聊")
        self.assertEqual(chat.calls[0]["mode_hint"], "auto")
        self.assertNotEqual(chat.calls[0]["text"], DEMO_SCENE_DIALOGUE)
        self.assertNotEqual(chat.calls[0]["text"], "检测到您笑了，看起来非常开心")
        self.assertIn("[现场] 判定：拒绝喝水，继续陪聊", console.getvalue())
        self.assertIn("[现场] 判定：继续陪聊", console.getvalue())
        self.assertFalse(
            any(record["kind"] == "emotion_dialogue_care_request" for record in records)
        )
        self.assertIn(
            {"kind": "emotion_dialogue_care_offer", "offer": "water", "status": "declined"},
            [
                {key: record[key] for key in ("kind", "offer", "status")}
                for record in records
                if record["kind"] == "emotion_dialogue_care_offer"
            ],
        )

    def test_sad_hydration_cue_offers_one_water_choice_after_the_opening(self) -> None:
        client = FakeSpeechClient(["我没怎么喝水，嘴有点干", "不用了，我想聊聊"])
        chat = FakeElderChat(["当然，我陪您聊。您想从哪里说起？"])

        with tempfile.TemporaryDirectory() as temp_dir:
            output = io.StringIO()
            consume_events(
                io.StringIO(json.dumps(event(emotion="sad"))),
                client,
                output,
                demo_scene="dialogue",
                audio_dir=Path(temp_dir),
                chat_client=chat,
                play_audio=lambda _bridge, _audio_path: {},
            )

        records = [json.loads(line) for line in output.getvalue().splitlines()]
        offers = [record for record in records if record["kind"] == "emotion_dialogue_care_offer"]
        self.assertEqual(len(client.spoken), 5)
        self.assertEqual(client.spoken[0][0], DEMO_SCENE_DIALOGUE)
        self.assertNotIn(DEMO_SCENE_MOTION, [text for text, _ in client.spoken])
        self.assertEqual(len(offers), 2)
        self.assertEqual(offers[0]["trigger"], "sad_hydration_cue")
        self.assertEqual(offers[1]["status"], "declined")
        self.assertFalse(any(record["kind"] == "emotion_dialogue_care_request" for record in records))

    def test_sad_hydration_cue_respects_a_same_turn_decline(self) -> None:
        client = FakeSpeechClient(["我没怎么喝水，不过不用麻烦"])
        chat = FakeElderChat(["好的，我就在这儿陪您。"])

        with tempfile.TemporaryDirectory() as temp_dir:
            output = io.StringIO()
            consume_events(
                io.StringIO(json.dumps(event(emotion="sad"))),
                client,
                output,
                demo_scene="dialogue",
                audio_dir=Path(temp_dir),
                chat_client=chat,
                play_audio=lambda _bridge, _audio_path: {},
            )

        records = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(len(client.spoken), 4)
        self.assertEqual(client.spoken[0][0], DEMO_SCENE_DIALOGUE)
        self.assertNotIn(DEMO_SCENE_MOTION, [text for text, _ in client.spoken])
        self.assertFalse(any(record["kind"] == "emotion_dialogue_care_offer" for record in records))

    def test_stop_and_water_rejection_do_not_create_follow_up_actions(self) -> None:
        for transcript in ("别问了", "别打扰我", "别给我水"):
            with self.subTest(transcript=transcript), tempfile.TemporaryDirectory() as temp_dir:
                client = FakeSpeechClient([transcript])
                chat = FakeElderChat(["这条回复不应播放"])
                output = io.StringIO()
                consume_events(
                    io.StringIO(json.dumps(event())),
                    client,
                    output,
                    demo_scene="dialogue",
                    audio_dir=Path(temp_dir),
                    chat_client=chat,
                    play_audio=lambda _bridge, _audio_path: {},
                )
                records = [json.loads(line) for line in output.getvalue().splitlines()]
                self.assertEqual(len(client.spoken), 3 if transcript != "别给我水" else 4)
                self.assertEqual(client.spoken[0][0], DEMO_SCENE_DIALOGUE)
                self.assertNotIn(DEMO_SCENE_MOTION, [text for text, _ in client.spoken])
                self.assertFalse(any(record["kind"] == "emotion_dialogue_care_request" for record in records))
                self.assertFalse(any(record["kind"] == "emotion_dialogue_care_offer" for record in records))
                if transcript != "别给我水":
                    self.assertEqual(chat.calls, [])

    def test_english_end_request_plays_a_closing_without_llm(self) -> None:
        client = FakeSpeechClient(["It's over."])
        chat = FakeElderChat([])
        played: list[str] = []

        with tempfile.TemporaryDirectory() as temp_dir:
            output = io.StringIO()
            summary = consume_events(
                io.StringIO(json.dumps(event())),
                client,
                output,
                demo_scene="dialogue",
                audio_dir=Path(temp_dir),
                chat_client=chat,
                play_audio=lambda _bridge, audio_path: played.append(audio_path) or {},
            )

        self.assertEqual(summary, {"received": 1, "completed": 1, "duplicates": 0, "ignored": 0})
        self.assertEqual(len(client.spoken), 3)
        self.assertEqual(client.spoken[-1][0], "好的，很高兴和您聊这些开心的事。我们下次再聊。")
        self.assertEqual(len(played), 3)
        self.assertEqual(client.spoken[0][0], DEMO_SCENE_DIALOGUE)
        self.assertNotIn(DEMO_SCENE_MOTION, [text for text, _ in client.spoken])
        self.assertEqual(chat.calls, [])
        self.assertIn('"status":"quiet_requested"', output.getvalue())

    def test_all_dialogue_termination_requests_play_an_emotion_appropriate_closing_without_llm(self) -> None:
        for emotion, transcript, closing in (
            ("happy", "本次结束吧", "好的，很高兴和您聊这些开心的事。我们下次再聊。"),
            ("sad", "等今天到这吧，先不聊了。", "好的，今天就聊到这里。您好好休息。"),
            ("angry", "你先退下吧", "好的，我先不打扰您了。等您想聊时再叫我。"),
            ("angry", "就到这吧", "好的，我先不打扰您了。等您想聊时再叫我。"),
            ("sad", "It's over.", "好的，今天就聊到这里。您好好休息。"),
        ):
            with self.subTest(emotion=emotion, transcript=transcript), tempfile.TemporaryDirectory() as temp_dir:
                client = FakeSpeechClient([transcript])
                chat = FakeElderChat([])
                played: list[str] = []
                output = io.StringIO()
                consume_events(
                    io.StringIO(json.dumps(event(emotion=emotion))),
                    client,
                    output,
                    demo_scene="dialogue",
                    audio_dir=Path(temp_dir),
                    chat_client=chat,
                    play_audio=lambda _bridge, audio_path: played.append(audio_path) or {},
                )

                self.assertEqual(len(client.spoken), 3)
                self.assertEqual(client.spoken[-1][0], closing)
                self.assertEqual(len(played), 3)
                self.assertEqual(chat.calls, [])
                self.assertIn('"status":"quiet_requested"', output.getvalue())
                self.assertIn('"g1_played":true', output.getvalue())

    def test_quiet_request_plays_a_closing_without_llm(self) -> None:
        client = FakeSpeechClient(["我想安静一会儿"])
        chat = FakeElderChat([])
        played: list[str] = []

        with tempfile.TemporaryDirectory() as temp_dir:
            output = io.StringIO()
            summary = consume_events(
                io.StringIO(json.dumps(event())),
                client,
                output,
                demo_scene="dialogue",
                audio_dir=Path(temp_dir),
                chat_client=chat,
                play_audio=lambda _bridge, audio_path: played.append(audio_path) or {},
            )

        self.assertEqual(summary, {"received": 1, "completed": 1, "duplicates": 0, "ignored": 0})
        self.assertEqual(len(client.spoken), 3)
        self.assertEqual(client.spoken[-1][0], "好的，很高兴和您聊这些开心的事。我们下次再聊。")
        self.assertEqual(len(played), 3)
        self.assertEqual(client.spoken[0][0], DEMO_SCENE_DIALOGUE)
        self.assertNotIn(DEMO_SCENE_MOTION, [text for text, _ in client.spoken])
        self.assertEqual(chat.calls, [])
        self.assertIn('"status":"quiet_requested"', output.getvalue())

    def test_only_first_unique_event_starts_a_dialogue(self) -> None:
        client = FakeSpeechClient(["我想安静"])
        played: list[str] = []
        source = "\n".join(
            (json.dumps(event()), json.dumps(event()), json.dumps(event(event_id="event-2")))
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            output = io.StringIO()
            console = io.StringIO()
            summary = consume_events(
                io.StringIO(source),
                client,
                output,
                demo_scene="dialogue",
                audio_dir=Path(temp_dir),
                chat_client=FakeElderChat([]),
                play_audio=lambda _bridge, audio_path: played.append(audio_path) or {},
                console=console,
            )

        self.assertEqual(summary, {"received": 3, "completed": 1, "duplicates": 1, "ignored": 1})
        self.assertEqual(len(client.spoken), 3)
        self.assertEqual(len(played), 3)
        self.assertEqual(client.spoken[0][0], DEMO_SCENE_DIALOGUE)
        self.assertNotIn(DEMO_SCENE_MOTION, [text for text, _ in client.spoken])
        self.assertIn("[现场] 判定：重复事件已忽略", console.getvalue())
        self.assertIn("[现场] 判定：已完成一条对话，后续事件忽略", console.getvalue())
        self.assertNotIn("emotion_dialogue_console", output.getvalue())

    def test_decline_and_quiet_never_play_the_motion_scene(self) -> None:
        dialogue_cases = (
            (["不用"], ["好的，我陪着您。"], 1),
            (["我想安静一会儿"], [], 1),
            ([""], [], 1),
        )
        for transcripts, replies, _ in dialogue_cases:
            with self.subTest(scene="dialogue", transcript=transcripts[0]), tempfile.TemporaryDirectory() as temp_dir:
                client = FakeSpeechClient(transcripts)
                consume_events(
                    io.StringIO(json.dumps(event(behavior_cues=["wave_open_palm"]))),
                    client,
                    io.StringIO(),
                    demo_scene="dialogue",
                    audio_dir=Path(temp_dir),
                    chat_client=FakeElderChat(replies),
                )
                spoken = [text for text, _ in client.spoken]
                self.assertEqual(spoken[0], DEMO_SCENE_DIALOGUE)
                self.assertNotIn(DEMO_SCENE_MOTION, spoken)

        motion_cases = (["不用"], ["我想安静一会儿"], [""])
        for transcripts in motion_cases:
            with self.subTest(scene="motion", transcript=transcripts[0]), tempfile.TemporaryDirectory() as temp_dir:
                client = FakeSpeechClient(transcripts)
                consume_events(
                    io.StringIO(json.dumps(event(behavior_cues=["wave_open_palm"]))),
                    client,
                    io.StringIO(),
                    demo_scene="motion",
                    audio_dir=Path(temp_dir),
                    chat_client=FakeElderChat([]),
                )
                spoken = [text for text, _ in client.spoken]
                self.assertEqual(spoken[0], DEMO_SCENE_MOTION)
                self.assertEqual(spoken.count(DEMO_SCENE_MOTION), 1)
                if transcripts == ["我想安静一会儿"]:
                    self.assertEqual(len(spoken), 2)

    def test_motion_ignores_non_gesture_event_then_asks(self) -> None:
        source = "\n".join(
            (
                json.dumps(event(event_id="sad-1", emotion="sad")),
                json.dumps(event(event_id="wave-1", behavior_cues=["wave_open_palm"])),
            )
        )
        client = FakeSpeechClient(["好啊"])
        output = io.StringIO()
        chat = FakeElderChat([])
        with tempfile.TemporaryDirectory() as temp_dir:
            summary = consume_events(
                io.StringIO(source),
                client,
                output,
                demo_scene="motion",
                audio_dir=Path(temp_dir),
                chat_client=chat,
            )

        records = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(summary, {"received": 2, "completed": 1, "duplicates": 0, "ignored": 1})
        self.assertEqual(client.spoken[0][0], DEMO_SCENE_MOTION)
        self.assertEqual(
            client.spoken[1][0],
            "检测到您笑了，并向我挥手。我也想挥手回应，可以吗？",
        )
        self.assertEqual(chat.calls, [])
        self.assertTrue(
            any(
                record["kind"] == "emotion_dialogue_receipt"
                and record.get("status") == "ignored_not_motion_cue"
                and record.get("event_id") == "sad-1"
                for record in records
            )
        )
        self.assertTrue(
            any(
                record["kind"] == "emotion_dialogue_motion_request"
                and record.get("action_id") == 25
                for record in records
            )
        )

    def test_motion_does_not_offer_water(self) -> None:
        client = FakeSpeechClient(["我有点口渴", "好啊"])
        output = io.StringIO()
        chat = FakeElderChat([])
        with tempfile.TemporaryDirectory() as temp_dir:
            consume_events(
                io.StringIO(json.dumps(event(behavior_cues=["wave_open_palm"]))),
                client,
                output,
                demo_scene="motion",
                audio_dir=Path(temp_dir),
                chat_client=chat,
            )

        records = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(chat.calls, [])
        self.assertFalse(any(record["kind"] == "emotion_dialogue_care_offer" for record in records))
        self.assertTrue(
            any(
                record["kind"] == "emotion_dialogue_motion_request" and record.get("action_id") == 25
                for record in records
            )
        )

    def test_startup_announce_pcm_failure_does_not_emit_a_motion_request(self) -> None:
        client = FakeSpeechClient(["好啊"])
        output = io.StringIO()

        def play(_bridge: str, _audio_path: str) -> dict | None:
            return None

        with tempfile.TemporaryDirectory() as temp_dir, self.assertRaises(DialogueError) as raised:
            consume_events(
                io.StringIO(json.dumps(event(behavior_cues=["wave_open_palm"]))),
                client,
                output,
                demo_scene="motion",
                audio_dir=Path(temp_dir),
                chat_client=FakeElderChat([]),
                play_audio=play,
            )

        self.assertEqual(str(raised.exception), "g1_pcm_bridge_response_invalid")
        records = [json.loads(line) for line in output.getvalue().splitlines() if line]
        self.assertFalse(
            any(record["kind"] == "emotion_dialogue_scene_announce" for record in records)
        )
        self.assertFalse(
            any(record["kind"] == "emotion_dialogue_motion_request" for record in records)
        )

    def test_console_line_marks_missing_asr_timing(self) -> None:
        line = _console_line(
            "检测到老人说的内容",
            {"text": "你好", "asr_ms": None, "round_no": 1},
        )
        self.assertIn("[现场] 老人说：你好", line)
        self.assertIn("ASR=未知", line)
        self.assertNotIn("Nonems", line)

    def test_console_line_marks_demo_scenes(self) -> None:
        self.assertEqual(DEMO_SCENE_DIALOGUE, "现在演示多轮对话场景")
        self.assertEqual(DEMO_SCENE_MOTION, "现在演示动作交互场景")
        self.assertNotIn("多伦", DEMO_SCENE_DIALOGUE)
        dialogue = _console_line(
            "演示场景",
            {"scene": "dialogue", "text": DEMO_SCENE_DIALOGUE},
        )
        motion = _console_line(
            "演示场景",
            {"scene": "motion", "text": DEMO_SCENE_MOTION},
        )
        self.assertIn("[现场] 演示场景=多轮对话", dialogue)
        self.assertIn("[现场] G1说：现在演示多轮对话场景", dialogue)
        self.assertIn("[现场] 演示场景=动作交互", motion)
        self.assertIn("[现场] G1说：现在演示动作交互场景", motion)

    def test_demo_scene_defaults_to_dialogue_without_motion_request(self) -> None:
        args = parse_arguments(
            [
                "--g1-pcm-bridge",
                "/tmp/pcm",
                "--confirm-g1-companion-pcm",
                "--audio-dir",
                "/tmp/mic",
            ]
        )
        self.assertEqual(args.demo_scene, "dialogue")
        self.assertEqual(args.elder_chat_url, DEFAULT_ELDER_CHAT_URL)
        self.assertEqual(args.timeout, 90.0)

        client = FakeSpeechClient(["好啊"])
        chat = FakeElderChat(["听您这么说真好。"])
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as temp_dir:
            consume_g1_dialogue_events(
                io.StringIO(json.dumps(event(behavior_cues=["wave_open_palm"]))),
                client,
                output,
                bridge_path="/tmp/pcm-bridge",
                audio_dir=Path(temp_dir),
                chat_client=chat,
                play_audio=_pcm,
                console=io.StringIO(),
            )

        records = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(client.spoken[0][0], DEMO_SCENE_DIALOGUE)
        self.assertEqual(
            client.spoken[1][0],
            "检测到您笑了，并向我挥手。有什么开心的事，也跟我分享一下吧。",
        )
        self.assertNotIn(DEMO_SCENE_MOTION, [text for text, _ in client.spoken])
        self.assertFalse(any("可以吗" in text for text, _ in client.spoken))
        self.assertGreaterEqual(len(chat.calls), 1)
        self.assertFalse(
            any(record["kind"] == "emotion_dialogue_motion_request" for record in records)
        )


class ElderUnifiedApiWiringTest(unittest.TestCase):
    def test_empty_asr_continues_without_unified_api_chat(self) -> None:
        client = FakeSpeechClient([""])
        chat = FakeElderChat(["这条回复不应播放"])
        with tempfile.TemporaryDirectory() as temp_dir:
            output = io.StringIO()
            consume_events(
                io.StringIO(json.dumps(event())),
                client,
                output,
                demo_scene="dialogue",
                audio_dir=Path(temp_dir),
                chat_client=chat,
            )

        self.assertEqual(chat.calls, [])
        self.assertIn('"status":"no_response"', output.getvalue())
        self.assertIn('"status":"quiet_requested"', output.getvalue())
        self.assertEqual(client.listen_seconds, [20.0, 20.0])

    def test_camera_pipe_eof_after_first_event_keeps_listening_until_elder_ends(self) -> None:
        client = FakeSpeechClient([""])
        chat = FakeElderChat(["这条回复不应播放"])
        read_fd, write_fd = os.pipe()
        with os.fdopen(write_fd, "w", encoding="utf-8") as writer:
            writer.write(json.dumps(event()) + "\n")
            writer.write(
                json.dumps({"kind": "emotion_demo_summary", "strategy_events": 1}) + "\n"
            )
        with os.fdopen(read_fd, "r", encoding="utf-8") as reader:
            with tempfile.TemporaryDirectory() as temp_dir:
                output = io.StringIO()
                console = io.StringIO()
                consume_events(
                    reader,
                    client,
                    output,
                    demo_scene="dialogue",
                    audio_dir=Path(temp_dir),
                    chat_client=chat,
                    console=console,
                )

        self.assertEqual(chat.calls, [])
        self.assertEqual(client.listen_seconds, [20.0, 20.0])
        self.assertIn('"status":"no_response"', output.getvalue())
        self.assertIn('"status":"quiet_requested"', output.getvalue())
        self.assertNotIn('"status":"preview_closed"', output.getvalue())

    def test_health_requires_ok_unified_service(self) -> None:
        with patch("emotion_dialogue.requests.get") as get:
            response = get.return_value
            response.raise_for_status.return_value = None
            response.json.return_value = {
                "ok": True,
                "service": "elder-companion-unified",
            }
            _require_elder_chat_health("http://127.0.0.1:8810", timeout=3.0)
            get.assert_called_once_with("http://127.0.0.1:8810/health", timeout=3.0)

    def test_health_rejects_wrong_service_and_unreachable(self) -> None:
        with patch("emotion_dialogue.requests.get") as get:
            response = get.return_value
            response.raise_for_status.return_value = None
            response.json.return_value = {"ok": True, "service": "other"}
            with self.assertRaises(DialogueError) as ctx:
                _require_elder_chat_health(DEFAULT_ELDER_CHAT_URL)
            self.assertEqual(str(ctx.exception), "elder_chat_service_unhealthy")
        with patch(
            "emotion_dialogue.requests.get",
            side_effect=requests.ConnectionError("down"),
        ):
            with self.assertRaises(DialogueError) as ctx:
                _require_elder_chat_health(DEFAULT_ELDER_CHAT_URL)
            self.assertEqual(str(ctx.exception), "elder_chat_service_unreachable")

    def test_dialogue_main_passes_timeout_to_elder_chat_client(self) -> None:
        with patch("emotion_dialogue.SpeechClient") as speech_cls, patch(
            "emotion_dialogue.ElderChatClient"
        ) as chat_cls, patch(
            "emotion_dialogue._require_elder_chat_health"
        ) as health, patch(
            "emotion_dialogue.consume_g1_dialogue_events"
        ) as consume:
            speech_cls.return_value.health.return_value = {"ok": True}
            consume.return_value = {
                "received": 0,
                "completed": 0,
                "duplicates": 0,
                "ignored": 0,
            }
            code = main(
                [
                    "--g1-pcm-bridge",
                    "/tmp/pcm",
                    "--confirm-g1-companion-pcm",
                    "--audio-dir",
                    "/tmp/mic",
                    "--timeout",
                    "42",
                    "--elder-chat-url",
                    "http://127.0.0.1:8810",
                    "--demo-scene",
                    "dialogue",
                ]
            )
        self.assertEqual(code, 0)
        health.assert_called_once_with("http://127.0.0.1:8810", timeout=10.0)
        chat_cls.assert_called_once_with(
            base_url="http://127.0.0.1:8810",
            timeout=42.0,
        )
        self.assertIs(
            consume.call_args.kwargs["chat_client"],
            chat_cls.return_value,
        )
        self.assertEqual(consume.call_args.kwargs["elder_chat_timeout"], 42.0)
        self.assertEqual(speech_cls.call_args.kwargs["timeout"], 42.0)

    def test_motion_main_does_not_touch_unified_api(self) -> None:
        with patch("emotion_dialogue.SpeechClient") as speech_cls, patch(
            "emotion_dialogue.ElderChatClient"
        ) as chat_cls, patch(
            "emotion_dialogue._require_elder_chat_health"
        ) as health, patch(
            "emotion_dialogue.consume_g1_dialogue_events"
        ) as consume:
            speech_cls.return_value.health.return_value = {"ok": True}
            consume.return_value = {
                "received": 0,
                "completed": 0,
                "duplicates": 0,
                "ignored": 0,
            }
            code = main(
                [
                    "--g1-pcm-bridge",
                    "/tmp/pcm",
                    "--confirm-g1-companion-pcm",
                    "--audio-dir",
                    "/tmp/mic",
                    "--demo-scene",
                    "motion",
                ]
            )
        self.assertEqual(code, 0)
        health.assert_not_called()
        chat_cls.assert_not_called()
        self.assertIsNone(consume.call_args.kwargs["chat_client"])

    def test_consume_creates_timed_client_after_health_when_missing(self) -> None:
        client = FakeSpeechClient(["结束吧"])
        with patch("emotion_dialogue._require_elder_chat_health") as health, patch(
            "emotion_dialogue.ElderChatClient"
        ) as chat_cls, tempfile.TemporaryDirectory() as temp_dir:
            chat_cls.return_value = FakeElderChat([])
            consume_g1_dialogue_events(
                io.StringIO(json.dumps(event())),
                client,
                io.StringIO(),
                bridge_path="/tmp/pcm-bridge",
                audio_dir=Path(temp_dir),
                play_audio=_pcm,
                console=io.StringIO(),
                demo_scene="dialogue",
                elder_chat_url="http://127.0.0.1:8810",
                elder_chat_timeout=42.0,
            )
        health.assert_called_once_with("http://127.0.0.1:8810", timeout=10.0)
        chat_cls.assert_called_once_with(
            base_url="http://127.0.0.1:8810",
            timeout=42.0,
        )


if __name__ == "__main__":
    unittest.main()

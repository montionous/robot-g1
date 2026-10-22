from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent

SCENE_DIR = (
    ROOT
    / "scenarios"
    / "companion_entertainment"
)

sys.path.insert(
    0,
    str(SCENE_DIR),
)


from demo_controller import (
    ShowcaseController,
)

from demo_intent import (
    classify_showcase_intent,
)

from demo_protocol import (
    DONE,
    END,
    NEXT_MUSIC,
    OTHER,
    PLAYING_MUSIC_FIRST,
    PLAYING_MUSIC_SECOND,
    PLAYING_NEWS,
    PLAYING_OPERA,
    PLAY_MUSIC,
    SWITCH_NEWS,
    SWITCH_OPERA,
    SPECIFIC_MEDIA_REQUEST,
    WAIT_MUSIC_REQUEST,
)


class FakeLLM:

    def __init__(
        self,
        intent,
        confidence=0.95,
    ):
        self.intent = intent
        self.confidence = (
            confidence
        )


    def classify(
        self,
        text,
        *,
        state,
        allowed_intents,
    ):
        return {
            "intent":
                self.intent,

            "confidence":
                self.confidence,

            "llm_ms":
                1.0,

            "model":
                "fake",
        }


class ShowcaseIntentTest(
    unittest.TestCase
):

    def test_music_request(self):
        result = (
            classify_showcase_intent(
                "机器人，给我放点音乐",
                state=
                    WAIT_MUSIC_REQUEST,
            )
        )

        self.assertEqual(
            result["intent"],
            PLAY_MUSIC,
        )


    def test_background_speech_ignored(self):
        result = (
            classify_showcase_intent(
                "这个音乐挺好听的",
                state=
                    PLAYING_MUSIC_FIRST,
            )
        )

        self.assertEqual(
            result["intent"],
            OTHER,
        )

        self.assertEqual(
            result["source"],
            "rule_only",
        )


    def test_next_music_allowed_once(self):
        result = (
            classify_showcase_intent(
                "机器人，换一首",
                state=
                    PLAYING_MUSIC_FIRST,
            )
        )

        self.assertEqual(
            result["intent"],
            NEXT_MUSIC,
        )


    def test_second_next_is_ignored(self):
        result = (
            classify_showcase_intent(
                "机器人，再换一首",
                state=
                    PLAYING_MUSIC_SECOND,
            )
        )

        self.assertEqual(
            result["intent"],
            OTHER,
        )


    def test_news_cannot_skip_next(self):
        result = (
            classify_showcase_intent(
                "机器人，换成新闻",
                state=
                    PLAYING_MUSIC_FIRST,
                llm=FakeLLM(
                    SWITCH_NEWS
                ),
            )
        )

        self.assertEqual(result["intent"], OTHER)
        controller = ShowcaseController()
        controller.state = PLAYING_MUSIC_FIRST
        self.assertEqual(controller.handle(result["intent"])["action"], "ignore")
        self.assertEqual(controller.handle(SWITCH_NEWS)["action"], "ignore")
        self.assertEqual(controller.state, PLAYING_MUSIC_FIRST)


    def test_news_after_next(self):
        result = (
            classify_showcase_intent(
                "机器人，换成新闻",
                state=
                    PLAYING_MUSIC_SECOND,
            )
        )

        self.assertEqual(
            result["intent"],
            SWITCH_NEWS,
        )


    def test_qinqiang_is_ignored(self):
        result = (
            classify_showcase_intent(
                "换成秦腔",
                state=
                    PLAYING_NEWS,
            )
        )

        self.assertEqual(result["intent"], OTHER)
        controller = ShowcaseController()
        controller.state = PLAYING_NEWS
        self.assertEqual(controller.handle(result["intent"])["action"], "ignore")
        self.assertEqual(controller.handle(SPECIFIC_MEDIA_REQUEST)["action"], "ignore")
        self.assertEqual(controller.state, PLAYING_NEWS)


    def test_generic_opera_is_allowed(self):
        result = (
            classify_showcase_intent(
                "换成戏曲",
                state=
                    PLAYING_NEWS,
            )
        )

        self.assertEqual(
            result["intent"],
            SWITCH_OPERA,
        )



    def test_opera_from_news(self):
        result = (
            classify_showcase_intent(
                "换成戏曲",
                state=
                    PLAYING_NEWS,
            )
        )

        self.assertEqual(
            result["intent"],
            SWITCH_OPERA,
        )


    def test_next_during_news_ignored(self):
        result = (
            classify_showcase_intent(
                "机器人，下一条",
                state=
                    PLAYING_NEWS,
                llm=FakeLLM(
                    NEXT_MUSIC
                ),
            )
        )

        self.assertEqual(result["intent"], OTHER)
        controller = ShowcaseController()
        controller.state = PLAYING_NEWS
        self.assertEqual(controller.handle(result["intent"])["action"], "ignore")
        self.assertEqual(controller.handle(NEXT_MUSIC)["action"], "ignore")
        self.assertEqual(controller.state, PLAYING_NEWS)


    def test_high_confidence_llm_fallback_is_accepted(self):
        result = (
            classify_showcase_intent(
                "机器人，我想听听"
                "今天都发生了什么",

                state=
                    PLAYING_MUSIC_SECOND,

                llm=FakeLLM(
                    SWITCH_NEWS,
                    confidence=0.95,
                ),
            )
        )

        self.assertEqual(
            result["intent"],
            SWITCH_NEWS,
        )

        self.assertEqual(
            result["source"],
            "llm",
        )



    def test_low_confidence_llm_ignored(self):
        result = (
            classify_showcase_intent(
                "机器人，我想听听"
                "今天都发生了什么",

                state=
                    PLAYING_MUSIC_SECOND,

                llm=FakeLLM(
                    SWITCH_NEWS,
                    confidence=0.60,
                ),
            )
        )

        self.assertEqual(
            result["intent"],
            OTHER,
        )


    def test_end(self):
        result = (
            classify_showcase_intent(
                "机器人，不听了",
                state=
                    PLAYING_OPERA,
            )
        )

        self.assertEqual(
            result["intent"],
            END,
        )


class ShowcaseControllerTest(
    unittest.TestCase
):

    def test_complete_fixed_flow(self):
        controller = (
            ShowcaseController()
        )

        self.assertEqual(
            controller.state,
            WAIT_MUSIC_REQUEST,
        )

        result = controller.handle(
            PLAY_MUSIC
        )

        self.assertEqual(
            result["action"],
            PLAY_MUSIC,
        )

        self.assertEqual(
            controller.state,
            PLAYING_MUSIC_FIRST,
        )

        result = controller.handle(
            NEXT_MUSIC
        )

        self.assertEqual(
            result["action"],
            NEXT_MUSIC,
        )

        self.assertEqual(
            controller.state,
            PLAYING_MUSIC_SECOND,
        )

        result = controller.handle(
            SWITCH_NEWS
        )

        self.assertEqual(
            result["action"],
            SWITCH_NEWS,
        )

        self.assertEqual(
            controller.state,
            PLAYING_NEWS,
        )

        result = controller.handle(
            SWITCH_OPERA
        )

        self.assertEqual(
            result["action"],
            SWITCH_OPERA,
        )

        self.assertEqual(
            controller.state,
            PLAYING_OPERA,
        )

        result = controller.handle(
            END
        )

        self.assertEqual(
            result["action"],
            END,
        )

        self.assertEqual(
            controller.state,
            DONE,
        )

        self.assertTrue(
            controller.done
        )


    def test_wrong_intent_never_moves_state(self):
        controller = (
            ShowcaseController()
        )

        controller.handle(
            PLAY_MUSIC
        )

        self.assertEqual(
            controller.state,
            PLAYING_MUSIC_FIRST,
        )

        result = controller.handle(
            SWITCH_NEWS
        )

        self.assertEqual(
            result["action"],
            "ignore",
        )

        self.assertEqual(
            controller.state,
            PLAYING_MUSIC_FIRST,
        )

        result = controller.handle(
            NEXT_MUSIC
        )

        self.assertEqual(
            result["action"],
            NEXT_MUSIC,
        )

        self.assertEqual(
            controller.state,
            PLAYING_MUSIC_SECOND,
        )


if __name__ == "__main__":
    unittest.main(
        verbosity=2
    )

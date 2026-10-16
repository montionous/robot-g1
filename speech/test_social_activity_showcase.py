#!/usr/bin/env python3

from __future__ import annotations

import sys
import unittest
from datetime import (
    date,
    timedelta,
)
from pathlib import Path


SCENE_DIR = (
    Path(__file__)
    .resolve()
    .parent
    / "scenarios"
    / "social_activity_support"
)

sys.path.insert(
    0,
    str(SCENE_DIR),
)


from showcase_controller import (
    ShowcaseController,
)

from showcase_intent import (
    classify_showcase_intent,
)

from showcase_protocol import (
    ASK_LOCATION,
    DONE,
    OTHER,
    QUERY,
    SELECTED_ACTIVITY,
    WAIT_CONFIRM,
    WAIT_END,
    WAIT_QUERY,
    WAIT_SELECT,
)


class FakeRepo:

    def __init__(self):
        tomorrow = (
            date.today()
            + timedelta(
                days=1
            )
        ).isoformat()

        self.items = [
            {
                "session_id":
                    101,

                "activity_date":
                    tomorrow,

                "start_time":
                    "15:30",

                "end_time":
                    "16:30",

                "capacity":
                    None,

                "registered_count":
                    15,

                "registration_deadline":
                    None,

                "status":
                    "open",

                "activity_id":
                    1,

                "name":
                    "集体唱歌",

                "category":
                    "music",

                "description":
                    "大家一起演唱经典歌曲和熟悉的老歌。",

                "tags":
                    "唱歌,合唱,音乐,老歌,社交",

                "organizer":
                    "赵老师",

                "location":
                    "三楼多功能厅",

                "requires_registration":
                    0,

                "notes":
                    "不需要专业唱歌基础。",

                "available_spots":
                    None,
            },

            {
                "session_id":
                    102,

                "activity_date":
                    tomorrow,

                "start_time":
                    "16:30",

                "end_time":
                    "17:30",

                "capacity":
                    20,

                "registered_count":
                    10,

                "registration_deadline":
                    None,

                "status":
                    "open",

                "activity_id":
                    2,

                "name":
                    "手工兴趣小组",

                "category":
                    "hobby",

                "description":
                    "进行简单手工制作和作品交流。",

                "tags":
                    "手工,兴趣,交流",

                "organizer":
                    "李老师",

                "location":
                    "二楼活动室",

                "requires_registration":
                    1,

                "notes":
                    "材料由活动室准备。",

                "available_spots":
                    10,
            },
        ]

        self.interests = {}
        self.notifications = []

    def query_sessions(
        self,
        **kwargs,
    ):
        return list(
            self.items
        )

    def get_interest(
        self,
        elder_id,
        session_id,
    ):
        return self.interests.get(
            (
                elder_id,
                session_id,
            )
        )

    def record_interest(
        self,
        *,
        elder_id,
        session_id,
        status,
    ):
        key = (
            elder_id,
            session_id,
        )

        if key in self.interests:
            return {
                "created":
                    False,

                "interest":
                    self.interests[
                        key
                    ],
            }

        value = {
            "elder_id":
                elder_id,

            "session_id":
                session_id,

            "status":
                status,
        }

        self.interests[
            key
        ] = value

        return {
            "created":
                True,

            "interest":
                value,
        }

    def create_notification(
        self,
        **kwargs,
    ):
        self.notifications.append(
            kwargs
        )

        return len(
            self.notifications
        )


class StubLLM:

    def __init__(
        self,
        *,
        intent,
        confidence,
    ):
        self.intent = intent
        self.confidence = confidence

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
        }


class ShowcaseTest(
    unittest.TestCase
):

    def make_controller(self):
        return (
            ShowcaseController(
                elder_id=1,
                elder_name="王大爷",
                repo=FakeRepo(),
            )
        )

    def classify(
        self,
        controller,
        text,
        llm=None,
    ):
        return (
            classify_showcase_intent(
                text,
                state=
                    controller.state,
                llm=llm,
            )
        )

    def test_initial_state(self):
        controller = (
            self.make_controller()
        )

        self.assertEqual(
            controller.state,
            WAIT_QUERY,
        )

    def test_query_is_brief(self):
        controller = (
            self.make_controller()
        )

        intent = self.classify(
            controller,
            "明天下午有什么活动？",
        )

        result = (
            controller.handle(
                intent["intent"],
                "明天下午有什么活动？",
            )
        )

        self.assertEqual(
            controller.state,
            WAIT_SELECT,
        )

        self.assertIn(
            "集体唱歌",
            result["reply"],
        )

        self.assertIn(
            "手工兴趣小组",
            result["reply"],
        )

        # 首次推荐不能把完整详情全部念出来
        self.assertNotIn(
            "三楼多功能厅",
            result["reply"],
        )

        self.assertNotIn(
            "不需要专业唱歌基础",
            result["reply"],
        )

    def test_wrong_detail_before_selection_ignored(self):
        controller = (
            self.make_controller()
        )

        controller.handle(
            "query",
            "明天下午有什么活动？",
        )

        intent = self.classify(
            controller,
            "几点开始？",
        )

        self.assertEqual(
            intent["intent"],
            OTHER,
        )

        self.assertEqual(
            intent["source"],
            "state_gate",
        )

        result = (
            controller.handle(
                intent["intent"],
                "几点开始？",
            )
        )

        self.assertEqual(
            result["action"],
            "ignore",
        )

        self.assertIsNone(
            result["reply"]
        )

        self.assertEqual(
            controller.state,
            WAIT_SELECT,
        )

    def test_select_song_activity(self):
        controller = (
            self.make_controller()
        )

        controller.handle(
            "query",
            "明天下午有什么活动？",
        )

        intent = self.classify(
            controller,
            "我想了解唱歌那个。",
        )

        result = (
            controller.handle(
                intent["intent"],
                "我想了解唱歌那个。",
            )
        )

        self.assertEqual(
            controller.state,
            SELECTED_ACTIVITY,
        )

        self.assertEqual(
            controller.selected[
                "name"
            ],
            "集体唱歌",
        )

        self.assertIn(
            "三楼多功能厅",
            result["reply"],
        )

        self.assertIn(
            "不限人数",
            result["reply"],
        )

        self.assertIn(
            "不需要提前报名",
            result["reply"],
        )

        self.assertIn(
            "不需要专业唱歌基础",
            result["reply"],
        )

    def test_can_ask_time_repeatedly(self):
        controller = (
            self.make_controller()
        )

        controller.handle(
            "query",
            "明天下午有什么活动？",
        )

        initial_intent = self.classify(
            controller,
            "这个活动听起来挺不错的。",
        )

        self.assertEqual(
            initial_intent["intent"],
            OTHER,
        )

        controller.handle(
            "select",
            "唱歌那个",
        )

        for text in [
            "几点开始？",
            "刚才几点来着？",
        ]:
            intent = self.classify(
                controller,
                text,
            )

            result = (
                controller.handle(
                    intent["intent"],
                    text,
                )
            )

            self.assertEqual(
                result["action"],
                "detail_time",
            )

            self.assertEqual(
                controller.state,
                SELECTED_ACTIVITY,
            )

    def test_location(self):
        controller = (
            self.make_controller()
        )

        controller.handle(
            "query",
            "明天下午有什么活动？",
        )

        controller.handle(
            "select",
            "唱歌那个",
        )

        intent = self.classify(
            controller,
            "在哪儿？",
        )

        self.assertEqual(
            intent["intent"],
            ASK_LOCATION,
        )

        result = (
            controller.handle(
                intent["intent"],
                "在哪儿？",
            )
        )

        self.assertIn(
            "三楼多功能厅",
            result["reply"],
        )

    def test_unlimited_availability(self):
        controller = (
            self.make_controller()
        )

        controller.handle(
            "query",
            "明天下午有什么活动？",
        )

        controller.handle(
            "select",
            "唱歌那个",
        )

        intent = self.classify(
            controller,
            "有人数限制吗？",
        )

        result = (
            controller.handle(
                intent["intent"],
                "有人数限制吗？",
            )
        )

        self.assertIn(
            "不限人数",
            result["reply"],
        )

    def test_no_registration_required(self):
        controller = (
            self.make_controller()
        )

        controller.handle(
            "query",
            "明天下午有什么活动？",
        )

        controller.handle(
            "select",
            "唱歌那个",
        )

        intent = self.classify(
            controller,
            "需要报名吗？",
        )

        result = (
            controller.handle(
                intent["intent"],
                "需要报名吗？",
            )
        )

        self.assertIn(
            "不需要提前报名",
            result["reply"],
        )

    def test_repeat_details(self):
        controller = (
            self.make_controller()
        )

        controller.handle(
            "query",
            "明天下午有什么活动？",
        )

        controller.handle(
            "select",
            "唱歌那个",
        )

        intent = self.classify(
            controller,
            "我没记住，再说一遍。",
        )

        result = (
            controller.handle(
                intent["intent"],
                "我没记住，再说一遍。",
            )
        )

        self.assertEqual(
            result["action"],
            "repeat_details",
        )

        self.assertIn(
            "集体唱歌",
            result["reply"],
        )

        self.assertIn(
            "三楼多功能厅",
            result["reply"],
        )

    def test_join_song_does_not_write_registration(self):
        controller = (
            self.make_controller()
        )

        repo = controller.repo

        controller.handle(
            "query",
            "明天下午有什么活动？",
        )

        controller.handle(
            "select",
            "唱歌那个",
        )

        intent = self.classify(
            controller,
            "那我去参加。",
        )

        result = (
            controller.handle(
                intent["intent"],
                "那我去参加。",
            )
        )

        self.assertEqual(
            result["action"],
            "participation_guidance",
        )

        self.assertIn(
            "不需要提前报名",
            result["reply"],
        )

        self.assertEqual(
            repo.interests,
            {},
        )

        self.assertEqual(
            repo.notifications,
            [],
        )

        self.assertEqual(
            controller.state,
            WAIT_END,
        )

    def test_after_join_details_are_ignored(self):
        controller = (
            self.make_controller()
        )

        controller.handle(
            "query",
            "明天下午有什么活动？",
        )

        controller.handle(
            "select",
            "唱歌那个",
        )

        controller.handle(
            "join",
            "那我去参加",
        )

        self.assertEqual(
            controller.state,
            WAIT_END,
        )

        intent = self.classify(
            controller,
            "几点开始？",
        )

        self.assertEqual(
            intent["intent"],
            OTHER,
        )

        self.assertEqual(
            intent["source"],
            "state_gate",
        )

        result = controller.handle(
            intent["intent"],
            "几点开始？",
        )

        self.assertEqual(
            result["action"],
            "ignore",
        )

        self.assertIsNone(
            result["reply"]
        )

        self.assertEqual(
            controller.state,
            WAIT_END,
        )

    def test_registration_activity_requires_confirmation(self):
        controller = (
            self.make_controller()
        )

        repo = controller.repo

        controller.handle(
            "query",
            "明天下午有什么活动？",
        )

        controller.handle(
            "select",
            "手工那个",
        )

        result = (
            controller.handle(
                "join",
                "我想参加",
            )
        )

        self.assertEqual(
            controller.state,
            WAIT_CONFIRM,
        )

        self.assertEqual(
            result["action"],
            "ask_join_confirmation",
        )

        confirm = self.classify(
            controller,
            "好的",
        )

        result = (
            controller.handle(
                confirm["intent"],
                "好的",
            )
        )

        self.assertEqual(
            result["action"],
            "interest_recorded",
        )

        self.assertEqual(
            len(
                repo.interests
            ),
            1,
        )

        self.assertEqual(
            len(
                repo.notifications
            ),
            1,
        )

        self.assertEqual(
            controller.state,
            WAIT_END,
        )

    def test_background_speech_is_ignored(self):
        controller = (
            self.make_controller()
        )

        controller.handle(
            "query",
            "明天下午有什么活动？",
        )

        controller.handle(
            "select",
            "唱歌那个",
        )

        intent = self.classify(
            controller,
            "这个活动听起来挺不错的。",
        )

        self.assertEqual(
            intent["intent"],
            OTHER,
        )

        result = (
            controller.handle(
                intent["intent"],
                "这个活动听起来挺不错的。",
            )
        )

        self.assertEqual(
            result["action"],
            "ignore",
        )

        self.assertIsNone(
            result["reply"]
        )

    def test_specific_activity_questions_remain_queries(self):
        controller = (
            self.make_controller()
        )

        for text in (
            "有没有唱歌活动？",
            "那唱歌呢？",
        ):
            with self.subTest(
                text=text,
            ):
                intent = self.classify(
                    controller,
                    text,
                )

                self.assertEqual(
                    intent["intent"],
                    QUERY,
                )

    def test_high_confidence_llm_fallback(self):
        controller = (
            self.make_controller()
        )

        controller.handle(
            "query",
            "明天下午有什么活动？",
        )

        controller.handle(
            "select",
            "唱歌那个",
        )

        llm = StubLLM(
            intent="ask_location",
            confidence=0.95,
        )

        intent = self.classify(
            controller,
            "我到时候得往哪边走来着",
            llm=llm,
        )

        self.assertEqual(
            intent["intent"],
            "ask_location",
        )

        self.assertEqual(
            intent["source"],
            "llm",
        )

    def test_low_confidence_llm_is_ignored(self):
        controller = (
            self.make_controller()
        )

        controller.handle(
            "query",
            "明天下午有什么活动？",
        )

        controller.handle(
            "select",
            "唱歌那个",
        )

        llm = StubLLM(
            intent="ask_location",
            confidence=0.60,
        )

        intent = self.classify(
            controller,
            "我到时候得往哪边走来着",
            llm=llm,
        )

        self.assertEqual(
            intent["intent"],
            OTHER,
        )

    def test_end(self):
        controller = (
            self.make_controller()
        )

        intent = self.classify(
            controller,
            "先这样吧。",
        )

        result = (
            controller.handle(
                intent["intent"],
                "先这样吧。",
            )
        )

        self.assertEqual(
            result["action"],
            "end",
        )

        self.assertEqual(
            controller.state,
            DONE,
        )


if __name__ == "__main__":
    unittest.main(
        verbosity=2
    )

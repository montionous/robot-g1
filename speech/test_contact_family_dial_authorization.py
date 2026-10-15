from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent

SCENE_DIR = (
    ROOT
    / "scenarios"
    / "contact_family"
)

sys.path.insert(
    0,
    str(SCENE_DIR),
)


from contact_family_logic import (
    ContactFamilySession,
    classify_dial_authorization,
    normalize_dial_authorization,
)


class DialAuthorizationClassifierTest(
    unittest.TestCase
):

    def test_exact_confirmation(self):
        self.assertIs(
            classify_dial_authorization(
                "确认拨号"
            ),
            True,
        )


    def test_spaces_and_punctuation_allowed(self):
        self.assertIs(
            classify_dial_authorization(
                " 确认 拨号。 "
            ),
            True,
        )


    def test_generic_yes_is_not_authorization(self):
        for text in (
            "好的",
            "好",
            "是的",
            "对",
            "可以",
            "确认",
            "嗯",
        ):
            with self.subTest(
                text=text
            ):
                self.assertIsNone(
                    classify_dial_authorization(
                        text
                    )
                )


    def test_longer_sentence_is_not_exact_authorization(self):
        for text in (
            "我确认拨号",
            "好的确认拨号",
            "确认拨号吧",
            "可以确认拨号",
        ):
            with self.subTest(
                text=text
            ):
                self.assertIsNone(
                    classify_dial_authorization(
                        text
                    )
                )


    def test_cancel(self):
        for text in (
            "取消",
            "取消拨号",
            "不拨打",
            "不打了",
            "算了",
            "不用了",
        ):
            with self.subTest(
                text=text
            ):
                self.assertIs(
                    classify_dial_authorization(
                        text
                    ),
                    False,
                )


    def test_normalization(self):
        self.assertEqual(
            normalize_dial_authorization(
                " 确认，拨号！ "
            ),
            "确认拨号",
        )


class DialAuthorizationStateTest(
    unittest.TestCase
):

    def make_confirmed_session(
        self,
    ):
        session = (
            ContactFamilySession(
                elderly_id=1
            )
        )

        # 本测试只测后半段状态机，
        # 不访问真实数据库。
        session.contact = {
            "id": 2,
            "name": "李先生",
            "relation": "儿子",
            "phone":
                "placeholder",
            "authorized": 1,
        }

        session.state = (
            "CONFIRMED"
        )

        return session


    def test_begin_authorization(self):
        session = (
            self.make_confirmed_session()
        )

        result = (
            session
            .begin_dial_authorization()
        )

        self.assertTrue(
            result["ok"]
        )

        self.assertEqual(
            session.state,
            "AWAITING_DIAL_AUTHORIZATION",
        )


    def test_exact_confirmation_authorizes(self):
        session = (
            self.make_confirmed_session()
        )

        session.begin_dial_authorization()

        result = (
            session
            .handle_dial_authorization(
                "确认拨号"
            )
        )

        self.assertTrue(
            result["authorized"]
        )

        self.assertEqual(
            session.state,
            "DIAL_AUTHORIZED",
        )


    def test_generic_yes_does_not_authorize(self):
        session = (
            self.make_confirmed_session()
        )

        session.begin_dial_authorization()

        result = (
            session
            .handle_dial_authorization(
                "好的"
            )
        )

        self.assertIsNone(
            result["authorized"]
        )

        self.assertEqual(
            session.state,
            "AWAITING_DIAL_AUTHORIZATION",
        )


    def test_cancel(self):
        session = (
            self.make_confirmed_session()
        )

        session.begin_dial_authorization()

        result = (
            session
            .handle_dial_authorization(
                "取消"
            )
        )

        self.assertFalse(
            result["authorized"]
        )

        self.assertEqual(
            session.state,
            "CANCELLED",
        )


    def test_cannot_authorize_before_first_confirmation(self):
        session = (
            ContactFamilySession(
                elderly_id=1
            )
        )

        result = (
            session
            .handle_dial_authorization(
                "确认拨号"
            )
        )

        self.assertFalse(
            result["authorized"]
        )

        self.assertNotEqual(
            session.state,
            "DIAL_AUTHORIZED",
        )


if __name__ == "__main__":
    unittest.main(
        verbosity=2
    )

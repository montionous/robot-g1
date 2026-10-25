"""Urgent care handoff: temporary real SQLite, no network/robot/production writes."""
from __future__ import annotations

import contextlib
import gc
import io
import json
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock, patch

import test_care_question_state as existing
import care_controller
import care_db
import elder_need_registry as registry
import init_elder_need_db
from care_need_bridge import CareNeedBridge
from care_urgent_assistance import submit_urgent_assistance, urgent_reply
import init_care_db
import init_care_memory


RED_FLAG = "我的头突然疼得特别厉害。"


class UrgentDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        temp = self.stack.enter_context(tempfile.TemporaryDirectory())
        # Existing registry/care helpers use connection context managers;
        # collect their closed-transaction handles before Windows temp cleanup.
        self.stack.callback(gc.collect)
        self.path = Path(temp) / "test.sqlite3"
        for module in (registry, care_db, init_elder_need_db, init_care_db, init_care_memory):
            self.stack.enter_context(patch.object(module, "DB_PATH", self.path))
        with contextlib.closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute("CREATE TABLE elderly_person (id INTEGER PRIMARY KEY, enabled INTEGER)")
            conn.execute("INSERT INTO elderly_person VALUES (1, 1), (2, 1)")
        with contextlib.redirect_stdout(io.StringIO()):
            init_elder_need_db.main()
            init_care_db.main()
            init_care_memory.main()
        self.session_id = care_db.create_session(1, 20)
        for target in ("requests.sessions.Session.request", "subprocess.Popen"):
            self.stack.enter_context(patch(target, side_effect=AssertionError("offline: " + target)))

    def submit(self, **overrides):
        args = dict(elderly_id=1, session_id=self.session_id, care_domain="general_care",
                    raw_text=RED_FLAG, matched_risk=["headache_sudden", "headache_severe"],
                    history=[{"role": "user", "content": "我有点头痛。"},
                             {"role": "assistant", "content": "有麻木吗？"}], round_no=2)
        args.update(overrides)
        return submit_urgent_assistance(**args)

    def rows(self, table):
        with contextlib.closing(registry.connect()) as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM " + table)]

    def test_atomic_records_contain_actual_user_evidence_and_platform_contract(self):
        result = self.submit()
        self.assertEqual(result["status"], "recorded")
        need = registry.get_need(result["need_id"])
        self.assertEqual((need["priority"], need["status"]), ("urgent", "detected"))
        self.assertEqual(need["need_category"], "care")
        self.assertEqual(need["need_code"], "care_urgent_assistance")
        self.assertEqual(need["raw_text"], RED_FLAG)
        self.assertEqual(need["details"]["notification_status"], "unconfirmed")
        self.assertEqual(need["details"]["reported_user_context"], ["我有点头痛。", RED_FLAG])
        task = self.rows("care_assistance_request")[0]
        self.assertEqual(task["id"], need["details"]["assistance_request_id"])
        self.assertEqual((task["risk_level"], task["status"]), ("external_route", "pending"))
        self.assertNotIn("已通知", urgent_reply(result))

    def test_retry_and_parallel_publish_create_one_pair(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            receipts = list(pool.map(lambda _: self.submit(), range(8)))
        self.assertTrue(all(row["status"] == "recorded" for row in receipts))
        self.assertEqual(len({row["need_id"] for row in receipts}), 1)
        self.assertEqual(len(self.rows("elder_need")), 1)
        self.assertEqual(len(self.rows("care_assistance_request")), 1)

    def test_escalation_reuses_pending_staff_item_and_shared_need(self):
        bridge = CareNeedBridge(elderly_id=1, session_id=self.session_id)
        task_id = care_db.create_assistance_request(
            session_id=self.session_id, elderly_id=1, care_domain="general_care",
            risk_level="needs_staff", user_description="头痛", summary="请关注")
        before = bridge.sync(care_domain="general_care", risk_level="needs_staff",
                             raw_text="头痛", round_no=1, staff_follow_up_created=True,
                             assistance_request_id=task_id)
        result = self.submit()
        after = registry.get_need(result["need_id"])
        self.assertEqual(result["need_id"], before["id"])
        self.assertEqual(result["assistance_request_id"], task_id)
        self.assertGreater(after["updated_at"], before["updated_at"])
        self.assertEqual(len(self.rows("care_assistance_request")), 1)
        for end_reason in ("external_abnormality_route", "manual_interrupt", "processing_error"):
            bridge.finalize(care_domain="general_care", risk_level="external_route",
                            end_reason=end_reason, staff_follow_up_created=True,
                            assistance_request_id=task_id)
            self.assertEqual(registry.get_need(before["id"]), after)

    def test_platform_state_survives_retry_and_finalization(self):
        result = self.submit()
        registry.update_need(result["need_id"], status="completed", handled_by="staff_platform")
        before = registry.get_need(result["need_id"])
        self.assertEqual(self.submit()["need_id"], result["need_id"])
        bridge = CareNeedBridge(elderly_id=1, session_id=self.session_id)
        bridge.need_id = result["need_id"]
        bridge.finalize(care_domain="general_care", risk_level="external_route",
                        end_reason="manual_interrupt")
        self.assertEqual(registry.get_need(result["need_id"]), before)

    def test_failure_of_shared_write_rolls_back_staff_item(self):
        with contextlib.closing(registry.connect()) as conn, conn:
            conn.execute("CREATE TRIGGER reject_need BEFORE INSERT ON elder_need "
                         "BEGIN SELECT RAISE(ABORT, 'test rejection'); END")
        result = self.submit()
        self.assertEqual(result["status"], "failed")
        self.assertEqual(self.rows("care_assistance_request"), [])
        self.assertEqual(self.rows("elder_need"), [])
        self.assertNotIn("已记录", urgent_reply(result))
        self.assertIn("未能提交", urgent_reply(result))

    def test_session_mismatch_does_not_record_for_wrong_elder(self):
        self.assertEqual(self.submit(elderly_id=2)["status"], "failed")
        self.assertFalse(self.rows("care_assistance_request"))

    def test_dry_run_never_opens_database(self):
        with patch.object(registry, "connect", side_effect=AssertionError("DB touched")):
            result = self.submit(dry_run=True)
        self.assertEqual(result["status"], "simulated")
        self.assertNotIn("已记录", urgent_reply(result))

    def test_controller_to_platform_tables_without_any_reply_or_judgment_llm(self):
        with patch.object(care_controller, "CareEndIntentLLM", side_effect=None) as end_class, \
             patch.object(care_controller, "build_personalized_risk_modifier",
                          side_effect=AssertionError("urgent profile lookup")):
            end_class.return_value.classify.side_effect = AssertionError("urgent end LLM")
            llm = Mock()
            llm.generate_reply.side_effect = AssertionError("urgent reply LLM")
            controller = care_controller.CareConsultation(
                elderly_id=1, session_id=self.session_id, llm=llm)
            # Both ordinary end/family phrases must yield to the actual red flag.
            result = controller.start(RED_FLAG + "帮我联系家人，不聊了。", preclassified=True)
        self.assertTrue(result["ok"])
        self.assertEqual(result["transfer_to"], "URGENT_ASSISTANCE")
        self.assertTrue(result["staff_follow_up_created"])
        self.assertEqual(registry.get_need(result["shared_need_id"])["priority"], "urgent")

    def test_showcase_explicit_urgent_write_does_not_enable_ordinary_bridge(self):
        with patch.object(care_controller, "CareEndIntentLLM"):
            controller = care_controller.CareConsultation(
                elderly_id=1, session_id=self.session_id, llm=Mock(),
                dry_run=True, record_urgent_needs=True)
            result = controller.start(RED_FLAG, preclassified=True)
        self.assertTrue(controller.care_need_bridge.dry_run)
        self.assertEqual(result["urgent_assistance"]["status"], "recorded")

    def test_urgent_cue_without_ordinary_care_keyword_can_enter_directly(self):
        with patch.object(care_controller, "CareEndIntentLLM") as end:
            controller = care_controller.CareConsultation(
                elderly_id=1, session_id=self.session_id, llm=Mock())
            result = controller.start("我喘不上气。")
        self.assertEqual(result["urgent_assistance"]["status"], "recorded")
        end.return_value.classify.assert_not_called()

    def test_complete_scene_commits_before_notice_and_exits_without_followup_or_gesture(self):
        import test_care_action_timing
        scene = test_care_action_timing.scene
        notices = []
        def speak(_speech, text, **kwargs):
            needs = self.rows("elder_need")
            self.assertEqual(len(needs), 1, "urgent record must exist before TTS")
            self.assertEqual(needs[0]["priority"], "urgent")
            notices.append(text)
        with contextlib.ExitStack() as stack:
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            stack.enter_context(patch.object(scene, "get_elderly", return_value={"name": "测试老人"}))
            for name in ("SpeechClient", "RobotLedClient", "RobotActionClient", "CareIntentLLM"):
                stack.enter_context(patch.object(scene, name))
            listen = stack.enter_context(patch.object(scene, "listen", return_value="我喘不上气。"))
            stack.enter_context(patch.object(scene, "speak", side_effect=speak))
            action = stack.enter_context(patch.object(scene, "trigger_robot_action"))
            llm = stack.enter_context(patch.object(care_controller, "CareLLM"))
            end = stack.enter_context(patch.object(care_controller, "CareEndIntentLLM"))
            memory = stack.enter_context(patch("care_session_finalize.persist_consultation_memory"))
            scene.run_scene(elderly_id=1, max_rounds=20, dialect="mandarin", listen_seconds=6,
                            announce_decisions=True, showcase=True, record_urgent_needs=True,
                            robot_actions="dry-run", robot_leds="dry-run")
            listen.assert_called_once()
            action.assert_not_called()
            llm.return_value.generate_reply.assert_not_called()
            end.return_value.classify.assert_not_called()
            scene.CareIntentLLM.assert_not_called()
            memory.assert_not_called()
        self.assertEqual(len(notices), 1)
        self.assertIn("已记录紧急求助", notices[0])
        self.assertEqual(self.rows("elder_need")[0]["status"], "detected")
        self.assertEqual(self.rows("care_assistance_request")[0]["status"], "pending")
        messages = self.rows("care_consultation_message")
        self.assertEqual([row["role"] for row in messages], ["user", "assistant"])
        session = self.rows("care_consultation_session")[-1]
        self.assertEqual(session["status"], "ended")
        self.assertEqual(session["end_reason"], "external_abnormality_route")


class UrgentSceneTests(unittest.TestCase):
    def test_notice_failure_cleanup_and_no_arm_or_mode_actions(self):
        import test_care_action_timing
        scene = test_care_action_timing.scene
        for status in ("recorded", "simulated", "failed"):
            with self.subTest(status=status), contextlib.ExitStack() as stack:
                for target in ("subprocess.Popen", "requests.sessions.Session.request", "sqlite3.connect"):
                    stack.enter_context(patch(target, side_effect=AssertionError(target)))
                mocks = {}
                for name in ("speak", "save_user_message", "save_assistant_message", "update_session_context",
                             "finalize_care_session", "record_receipt", "recording_mark_failed", "trigger_robot_action"):
                    mocks[name] = stack.enter_context(patch.object(scene, name))
                stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
                receipt = {"status": status}
                result = {"reply": urgent_reply(receipt), "urgent_assistance": receipt,
                          "transfer_to": "URGENT_ASSISTANCE"}
                leds = Mock()
                scene.finish_urgent_handoff(result=result, speech=Mock(), dialect="mandarin", leds=leds,
                                           session_id=1, consultation=Mock(), current_text=RED_FLAG)
                mocks["speak"].assert_called_once()
                mocks["trigger_robot_action"].assert_not_called()
                self.assertIsNone(scene.build_care_decision_message(result))
                self.assertEqual(mocks["recording_mark_failed"].call_count, int(status == "failed"))
                leds.show.assert_called_once_with("off", source="care_consultation_support:urgent_handoff_end")

    def test_tts_failure_still_finalizes_without_clearing_pending_task(self):
        import test_care_action_timing
        scene = test_care_action_timing.scene
        with patch.object(scene, "speak", side_effect=RuntimeError("tts failed")), \
             patch.object(scene, "finalize_care_session") as finish, \
             patch.object(scene, "record_receipt"), contextlib.redirect_stdout(io.StringIO()):
            leds = Mock()
            with self.assertRaises(RuntimeError):
                scene.finish_urgent_handoff(result={"reply": "notice", "urgent_assistance": {"status": "recorded"}},
                                           speech=Mock(), dialect="mandarin", leds=leds,
                                           session_id=1, consultation=Mock(), current_text=RED_FLAG)
            finish.assert_called_once()
            leds.show.assert_called_once()


if __name__ == "__main__":
    unittest.main()

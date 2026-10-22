from __future__ import annotations

import contextlib
import gc
import importlib.util
import io
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent
SOCIAL_DIR = ROOT / "scenarios" / "social_activity_support"
ENTERTAINMENT_DIR = ROOT / "scenarios" / "companion_entertainment"
CONTACT_DIR = ROOT / "scenarios" / "contact_family"
CARE_DIR = ROOT / "scenarios" / "care_consultation_support"

for path in (
    ROOT,
    SOCIAL_DIR,
    ENTERTAINMENT_DIR,
    CONTACT_DIR,
    CARE_DIR,
):
    sys.path.insert(0, str(path))


import elder_need_registry as registry
import init_elder_need_db
from activity_need_integration import ActivityNeedSession
from activity_controller import ActivityController
from care_need_bridge import CareNeedBridge
from contact_need_integration import ContactFamilyNeedSession
from entertainment_need_integration import EntertainmentNeedSession


class FakeMediaItem:
    def __init__(self, title):
        self.title = title


class FakeMediaLibrary:
    def __init__(self, items):
        self.items = list(items)

    def list_items(self, category):
        return list(self.items)


class FakeActivityRepo:
    def __init__(self, items):
        self.items = list(items)

    def query_sessions(self, **kwargs):
        return list(self.items)


class RegistrationFakeActivityRepo(FakeActivityRepo):
    def __init__(self, items):
        super().__init__(items)
        self.interests = {}
        self.notifications = []

    def get_interest(self, elder_id, session_id):
        return self.interests.get((elder_id, session_id))

    def record_interest(self, *, elder_id, session_id, status):
        key = (elder_id, session_id)
        if key in self.interests:
            return {
                "created": False,
                "interest": self.interests[key],
            }
        interest = {
            "elder_id": elder_id,
            "session_id": session_id,
            "status": status,
        }
        self.interests[key] = interest
        return {
            "created": True,
            "interest": interest,
        }

    def create_notification(self, **kwargs):
        self.notifications.append(dict(kwargs))
        return len(self.notifications)


class ElderNeedIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "elder_companion.db"
        self.old_registry_path = registry.DB_PATH
        self.old_init_path = init_elder_need_db.DB_PATH
        registry.DB_PATH = self.db_path
        init_elder_need_db.DB_PATH = self.db_path

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE elderly_person (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1
                )
                """
            )
            conn.execute(
                "INSERT INTO elderly_person(id,name,enabled) VALUES(1,'测试老人',1)"
            )

        with contextlib.redirect_stdout(io.StringIO()):
            init_elder_need_db.main()

    def tearDown(self):
        registry.DB_PATH = self.old_registry_path
        init_elder_need_db.DB_PATH = self.old_init_path
        # SQLite connection contexts commit/rollback but do not close; collect
        # their cycles before Windows removes the temporary database fixture.
        gc.collect()
        self.temp.cleanup()

    def create_completed_need(self, *, category, code, details):
        return registry.create_need(
            elderly_id=1,
            need_category=category,
            need_code=code,
            summary="测试共享需求",
            source_scene="TEST",
            status="completed",
            details=details,
        )

    def test_registry_updates_latest_text_round_and_status_filtered_history(self):
        row = registry.create_need(
            elderly_id=1,
            need_category="test",
            need_code="test_code",
            summary="第一轮",
            raw_text="第一句",
            source_scene="TEST",
            status="in_progress",
        )

        updated = registry.update_need(
            row["id"],
            raw_text="第二句",
            source_round_no=2,
            status="completed",
        )

        self.assertEqual(updated["raw_text"], "第二句")
        self.assertEqual(updated["source_round_no"], 2)
        history = registry.get_elder_need_history(
            1,
            need_category="test",
            status="completed",
        )
        self.assertEqual([item["id"] for item in history], [row["id"]])

    def test_entertainment_prefers_frequent_explicit_title_and_skips_bad_details(self):
        self.create_completed_need(
            category="entertainment",
            code="play_music",
            details={
                "request_mode": "explicit",
                "title": "常听歌曲",
            },
        )
        self.create_completed_need(
            category="entertainment",
            code="play_music",
            details={
                "request_mode": "explicit",
                "title": "另一首歌",
            },
        )
        self.create_completed_need(
            category="entertainment",
            code="play_music",
            details={
                "request_mode": "explicit",
                "title": "常听歌曲",
            },
        )

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO elder_need (
                    elderly_id,need_category,need_code,summary,priority,status,
                    source_scene,details_json,created_at,updated_at
                ) VALUES (1,'entertainment','play_music','坏数据','normal',
                    'completed','TEST','not-json','2026-01-01 00:00:00',
                    '2026-01-01 00:00:00')
                """
            )

        needs = EntertainmentNeedSession(
            elderly_id=1,
            library=FakeMediaLibrary(
                [
                    FakeMediaItem("常听歌曲"),
                    FakeMediaItem("另一首歌"),
                ]
            ),
            record=False,
        )

        self.assertEqual(needs.preferred_item("music").title, "常听歌曲")

    def test_activity_records_confirmed_interest_and_ranks_generic_results(self):
        item_a = {
            "activity_id": 10,
            "session_id": 101,
            "name": "集体唱歌",
            "category": "music",
            "activity_date": "2026-10-18",
            "start_time": "15:00",
            "status": "open",
        }
        item_b = {
            "activity_id": 20,
            "session_id": 202,
            "name": "手工兴趣小组",
            "category": "hobby",
            "activity_date": "2026-10-18",
            "start_time": "16:00",
            "status": "open",
        }

        controller = type(
            "Controller",
            (),
            {
                "last_filters": {},
                "selected": item_a,
            },
        )()
        needs = ActivityNeedSession(elderly_id=1, record=True)

        needs.record_result(
            raw_text="今天有什么活动",
            result={"action": "recommend", "recommended_count": 2},
            controller=controller,
        )
        needs.record_result(
            raw_text="我想参加唱歌",
            result={"action": "confirm_join", "selected": item_a},
            controller=controller,
        )
        needs.record_result(
            raw_text="对，帮我登记",
            result={"action": "interest_recorded", "selected": item_a},
            controller=controller,
        )

        interests = registry.get_elder_need_history(
            1,
            need_category="social_activity",
            need_code="activity_interest",
            status="completed",
        )
        self.assertEqual(len(interests), 1)
        self.assertEqual(interests[0]["details"]["activity_id"], 10)
        self.assertEqual(interests[0]["details"]["outcome"], "interest_recorded")

        self.create_completed_need(
            category="social_activity",
            code="activity_interest",
            details={
                "activity_id": 20,
                "activity_category": "hobby",
                "outcome": "interest_recorded",
            },
        )
        self.create_completed_need(
            category="social_activity",
            code="activity_interest",
            details={
                "activity_id": 20,
                "activity_category": "hobby",
                "outcome": "interest_recorded",
            },
        )

        ranked = needs.rank_recommendations([item_a, item_b], filters={})
        self.assertEqual(ranked[0]["activity_id"], 20)
        self.assertEqual(
            needs.rank_recommendations(
                [item_a, item_b],
                filters={"category": "music"},
            ),
            [item_a, item_b],
        )

    def test_activity_cancels_unanswered_registration_intent(self):
        item = {
            "activity_id": 10,
            "session_id": 101,
            "name": "集体唱歌",
            "category": "music",
            "activity_date": "2026-10-18",
            "start_time": "15:00",
            "status": "open",
        }
        controller = type("Controller", (), {"last_filters": {}, "selected": item})()
        needs = ActivityNeedSession(elderly_id=1, record=True)

        needs.record_result(
            raw_text="我要参加唱歌",
            result={"action": "confirm_join", "selected": item},
            controller=controller,
        )
        needs.close(outcome="scene_interrupted")

        row = registry.get_elder_need_history(
            1,
            need_category="social_activity",
            need_code="activity_interest",
        )[0]
        self.assertEqual(row["status"], "cancelled")
        self.assertEqual(row["details"]["outcome"], "scene_interrupted")

    def test_activity_records_recent_specific_query(self):
        item = {
            "activity_id": 10,
            "session_id": 101,
            "name": "集体唱歌",
            "category": "music",
        }
        controller = type(
            "Controller",
            (),
            {
                "last_filters": {"scope": "recent_specific"},
                "selected": item,
            },
        )()
        needs = ActivityNeedSession(elderly_id=1, record=True)

        needs.record_result(
            raw_text="最近有没有唱歌活动",
            result={"action": "selected_query", "selected": item},
            controller=controller,
        )

        row = registry.get_elder_need_history(
            1,
            need_category="social_activity",
            need_code="activity_query",
            status="completed",
        )[0]
        self.assertEqual(row["details"]["filters"], {"scope": "recent_specific"})
        self.assertEqual(row["details"]["result_action"], "selected_query")

    def test_activity_controller_uses_ranking_only_for_generic_query(self):
        items = [
            {
                "session_id": 101,
                "activity_id": 10,
                "name": "集体唱歌",
                "category": "music",
                "location": "三楼",
                "start_time": "15:00",
                "end_time": "16:00",
                "status": "open",
                "requires_registration": False,
                "registration_deadline": None,
                "available_spots": None,
            },
            {
                "session_id": 202,
                "activity_id": 20,
                "name": "手工兴趣小组",
                "category": "hobby",
                "location": "二楼",
                "start_time": "16:00",
                "end_time": "17:00",
                "status": "open",
                "requires_registration": False,
                "registration_deadline": None,
                "available_spots": None,
            },
        ]
        controller = ActivityController(repo=FakeActivityRepo(items))
        calls = []

        def ranker(results, *, filters):
            calls.append(dict(filters))
            return list(reversed(results))

        controller.preference_ranker = ranker
        generic = controller.query(
            "今天有什么活动",
            filters_override={
                "activity_date": "2099-01-01",
                "period": None,
                "category": None,
                "keyword": None,
            },
        )

        self.assertEqual(generic["action"], "recommend")
        self.assertEqual(controller.last_results[0]["activity_id"], 20)
        self.assertEqual(len(calls), 1)

        controller.query(
            "今天有没有唱歌活动",
            filters_override={
                "activity_date": "2099-01-01",
                "period": None,
                "category": "music",
                "keyword": None,
            },
        )
        self.assertEqual(len(calls), 1)
        self.assertEqual(controller.last_results[0]["activity_id"], 10)

    def test_activity_merges_existing_and_shared_interest_history(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript(
                """
                CREATE TABLE social_activity (
                    activity_id INTEGER PRIMARY KEY,
                    category TEXT NOT NULL
                );
                CREATE TABLE social_activity_session (
                    session_id INTEGER PRIMARY KEY,
                    activity_id INTEGER NOT NULL
                );
                CREATE TABLE social_activity_interest (
                    elder_id INTEGER NOT NULL,
                    session_id INTEGER NOT NULL,
                    status TEXT NOT NULL
                );
                INSERT INTO social_activity VALUES(20,'hobby');
                INSERT INTO social_activity_session VALUES(202,20);
                INSERT INTO social_activity_session VALUES(203,20);
                INSERT INTO social_activity_interest
                    VALUES(1,202,'pending');
                INSERT INTO social_activity_interest
                    VALUES(1,203,'confirmed');
                """
            )

        self.create_completed_need(
            category="social_activity",
            code="activity_interest",
            details={
                "activity_id": 10,
                "session_id": 101,
                "activity_category": "music",
            },
        )

        needs = ActivityNeedSession(elderly_id=1, record=False)
        items = [
            {"activity_id": 10, "session_id": 101, "category": "music"},
            {"activity_id": 20, "session_id": 202, "category": "hobby"},
        ]

        ranked = needs.rank_recommendations(items, filters={})
        self.assertEqual(ranked[0]["activity_id"], 20)

    def test_activity_deduplicates_shared_and_existing_session_history(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript(
                """
                CREATE TABLE social_activity (
                    activity_id INTEGER PRIMARY KEY,
                    category TEXT NOT NULL
                );
                CREATE TABLE social_activity_session (
                    session_id INTEGER PRIMARY KEY,
                    activity_id INTEGER NOT NULL
                );
                CREATE TABLE social_activity_interest (
                    elder_id INTEGER NOT NULL,
                    session_id INTEGER NOT NULL,
                    status TEXT NOT NULL
                );
                INSERT INTO social_activity VALUES(20,'hobby');
                INSERT INTO social_activity_session VALUES(202,20);
                INSERT INTO social_activity_interest
                    VALUES(1,202,'confirmed');
                """
            )

        for session_id in (101, 102):
            self.create_completed_need(
                category="social_activity",
                code="activity_interest",
                details={
                    "activity_id": 10,
                    "session_id": session_id,
                    "activity_category": "music",
                },
            )

        self.create_completed_need(
            category="social_activity",
            code="activity_interest",
            details={
                "activity_id": 20,
                "session_id": 202,
                "activity_category": "hobby",
            },
        )

        needs = ActivityNeedSession(elderly_id=1, record=False)
        items = [
            {"activity_id": 20, "session_id": 202, "category": "hobby"},
            {"activity_id": 10, "session_id": 101, "category": "music"},
        ]

        ranked = needs.rank_recommendations(items, filters={})
        self.assertEqual(ranked[0]["activity_id"], 10)

    def test_activity_confirmation_cannot_switch_pending_target(self):
        item_a = {
            "activity_id": 10,
            "session_id": 101,
            "name": "集体唱歌",
            "category": "music",
            "activity_date": "2026-10-18",
            "start_time": "15:00",
            "end_time": "16:00",
            "location": "三楼",
            "description": "唱歌活动",
            "tags": "唱歌",
            "status": "open",
            "requires_registration": False,
            "registration_deadline": None,
            "available_spots": None,
        }
        item_b = {
            **item_a,
            "activity_id": 20,
            "session_id": 202,
            "name": "手工兴趣小组",
            "category": "hobby",
        }
        repo = RegistrationFakeActivityRepo([item_a, item_b])
        controller = ActivityController(repo=repo)
        controller.selected = item_a
        controller.last_results = [item_a, item_b]
        needs = ActivityNeedSession(elderly_id=1, record=True)

        pending = controller.handle_action("join", "我要参加唱歌")
        self.assertEqual(pending["action"], "confirm_join")
        needs.record_result(
            raw_text="我要参加唱歌",
            result=pending,
            controller=controller,
        )

        blocked = controller.handle_action("query", "今天还有什么活动")
        self.assertEqual(blocked["action"], "awaiting_join_confirmation")
        self.assertEqual(controller.selected["session_id"], 101)

        completed = controller.handle_action("confirm_yes", "对")
        self.assertEqual(completed["action"], "interest_recorded")
        needs.record_result(
            raw_text="对",
            result=completed,
            controller=controller,
        )

        self.assertEqual(list(repo.interests), [(1, 101)])
        row = registry.get_elder_need_history(
            1,
            need_category="social_activity",
            need_code="activity_interest",
            status="completed",
        )[0]
        self.assertEqual(row["details"]["session_id"], 101)

    def test_activity_voice_scene_cancels_pending_need_when_tts_fails(self):
        module_name = "social_activity_voice_cleanup_test"
        spec = importlib.util.spec_from_file_location(
            module_name,
            SOCIAL_DIR / "g1_voice_demo.py",
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)

        item = {
            "activity_id": 10,
            "session_id": 101,
            "name": "集体唱歌",
            "category": "music",
            "activity_date": "2026-10-18",
            "start_time": "15:00",
            "status": "open",
        }

        class FakeSpeech:
            pass

        class FakeController:
            def __init__(self, **kwargs):
                self.active = True
                self.selected = None
                self.awaiting_join_confirmation = False
                self.pending_join_mode = None
                self.preference_ranker = None

            def handle_text(self, text):
                self.selected = item
                return {
                    "action": "confirm_join",
                    "selected": item,
                    "active": True,
                    "reply": "请确认是否登记。",
                }

        with patch.object(module, "SpeechClient", FakeSpeech), patch.object(
            module,
            "ActivityController",
            FakeController,
        ), patch.object(
            module,
            "ActivityIntentLLM",
            side_effect=RuntimeError("offline"),
        ), patch.object(
            module,
            "listen",
            return_value="我要参加唱歌",
        ), patch.object(
            module,
            "build_decision_message",
            return_value=None,
        ), patch.object(
            module,
            "speak",
            side_effect=RuntimeError("tts unavailable"),
        ):
            with self.assertRaisesRegex(RuntimeError, "tts unavailable"):
                module.run_scene(
                    elder_id=1,
                    elder_name="测试老人",
                    dialect="mandarin",
                    listen_seconds=1,
                    announce_decisions=False,
                    record_elder_needs=True,
                )

        row = registry.get_elder_need_history(
            1,
            need_category="social_activity",
            need_code="activity_interest",
        )[0]
        self.assertEqual(row["status"], "cancelled")
        self.assertEqual(row["details"]["outcome"], "scene_interrupted")

    def test_contact_need_excludes_phone_and_authorization_text(self):
        needs = ContactFamilyNeedSession(elderly_id=1, record=True)
        needs.begin(
            raw_text="请拨打女儿张女士的号码13800138000",
            contact={
                "name": "张女士",
                "relation": "女儿",
                "phone": "13800138000",
            },
        )
        needs.finish(
            status="in_progress",
            outcome="dial_authorized_safe_stub",
            contact={
                "name": "张女士",
                "relation": "女儿",
                "phone": "13800138000",
            },
        )
        # 已受理的联系请求应保留 in_progress，不被场景统一收尾覆盖。
        needs.close(outcome="scene_interrupted")

        row = registry.get_elder_need_history(
            1,
            need_category="contact_family",
            need_code="contact_family_call",
        )[0]
        self.assertEqual(row["status"], "in_progress")
        self.assertIsNone(row["raw_text"])
        self.assertEqual(row["details"]["contact_relation"], "女儿")
        self.assertNotIn("phone", row["details"])
        self.assertNotIn("name", row["details"])
        self.assertNotIn("contact_id", row["details"])
        self.assertEqual(row["details"]["outcome"], "dial_authorized_safe_stub")
        self.assertNotIn("13800138000", repr(row))
        self.assertNotIn("张女士", repr(row))

    def test_contact_need_keeps_handle_after_transient_update_failure(self):
        needs = ContactFamilyNeedSession(elderly_id=1, record=True)
        need_id = needs.begin(
            raw_text="我想联系女儿",
            contact={"relation": "女儿"},
        )

        with patch(
            "contact_need_integration.update_need",
            side_effect=sqlite3.OperationalError("database is locked"),
        ):
            self.assertIsNone(
                needs.finish(
                    status="failed",
                    outcome="拨号失败 13800138000",
                )
            )

        self.assertEqual(needs.need_id, need_id)
        self.assertEqual(registry.get_need(need_id)["status"], "in_progress")

        finished = needs.finish(
            status="failed",
            outcome="拨号失败 13800138000",
        )
        self.assertEqual(finished["details"]["outcome"], "dial_failed")
        self.assertIsNone(needs.need_id)

    def test_contact_need_close_cancels_unfinished_request(self):
        needs = ContactFamilyNeedSession(elderly_id=1, record=True)
        needs.begin(
            raw_text="我想联系女儿",
            contact={"relation": "女儿"},
        )
        needs.close(outcome="scene_interrupted")

        row = registry.get_elder_need_history(
            1,
            need_category="contact_family",
            need_code="contact_family_call",
        )[0]
        self.assertEqual(row["status"], "cancelled")
        self.assertEqual(row["details"]["outcome"], "scene_interrupted")

    def test_contact_voice_scene_marks_pending_need_failed_on_tts_error(self):
        module_name = "contact_family_voice_cleanup_test"
        spec = importlib.util.spec_from_file_location(
            module_name,
            CONTACT_DIR / "g1_voice_demo.py",
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)

        class FakeSpeech:
            g1_pcm_bridge = False

            @staticmethod
            def health():
                return {"service": "offline-test"}

        class FakeSession:
            def __init__(self, elderly_id):
                self.contact = {
                    "id": 7,
                    "name": "张女士",
                    "relation": "女儿",
                    "phone": "13800138000",
                }

            def handle_request(self, text):
                return {
                    "state": "AWAITING_CONFIRMATION",
                    "relation": "女儿",
                    "contact_name": "张女士",
                    "phone_masked": "138****8000",
                    "reply": "您想联系女儿，对吗？",
                }

        with patch.object(module, "SpeechClient", FakeSpeech), patch.object(
            module,
            "get_elderly",
            return_value={"name": "测试老人"},
        ), patch.object(
            module,
            "ContactFamilySession",
            FakeSession,
        ), patch.object(
            module,
            "listen",
            return_value="请联系女儿13800138000",
        ), patch.object(
            module,
            "announce_decision",
            return_value=None,
        ), patch.object(
            module,
            "say",
            side_effect=RuntimeError("tts unavailable"),
        ):
            with self.assertRaisesRegex(RuntimeError, "tts unavailable"):
                module.run_scene(
                    elderly_id=1,
                    dialect="mandarin",
                    announce_decisions=False,
                    call_backend="safe_stub",
                    request_seconds=1,
                    target_seconds=1,
                    confirm_seconds=1,
                    followup_seconds=1,
                    call_timeout=1,
                    call_rounds=1,
                    elder_turn_seconds=1,
                    family_turn_timeout=1,
                    record_elder_needs=True,
                )

        row = registry.get_elder_need_history(
            1,
            need_category="contact_family",
            need_code="contact_family_call",
        )[0]
        self.assertEqual(row["status"], "failed")
        self.assertEqual(row["details"]["outcome"], "scene_failed")
        self.assertIsNone(row["raw_text"])
        self.assertNotIn("13800138000", repr(row))

    def test_contact_text_demo_imports_from_its_own_directory(self):
        result = subprocess.run(
            [sys.executable, "text_demo.py", "--help"],
            cwd=CONTACT_DIR,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--no-need-write", result.stdout)

    def test_care_bridge_refreshes_shared_need_with_latest_round(self):
        bridge = CareNeedBridge(
            elderly_id=1,
            session_id="care-test",
            dry_run=False,
        )

        first = bridge.sync(
            care_domain="mobility",
            risk_level="low",
            raw_text="膝盖有点酸",
            round_no=1,
        )
        second = bridge.sync(
            care_domain="mobility",
            risk_level="needs_staff",
            raw_text="已经疼了好几天",
            round_no=2,
            staff_follow_up_created=True,
            assistance_request_id=7,
        )

        self.assertEqual(first["id"], second["id"])
        current = registry.get_need(first["id"])
        self.assertEqual(current["raw_text"], "已经疼了好几天")
        self.assertEqual(current["source_round_no"], 2)
        self.assertEqual(current["details"]["latest_raw_text"], "已经疼了好几天")
        self.assertEqual(current["details"]["initial_risk_level"], "low")

        final = bridge.finalize(
            care_domain="mobility",
            risk_level="needs_staff",
            end_reason="completed",
            staff_follow_up_created=True,
            assistance_request_id=7,
        )
        self.assertEqual(final["status"], "in_progress")


if __name__ == "__main__":
    unittest.main()

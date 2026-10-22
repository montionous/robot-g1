from __future__ import annotations

import sqlite3
import sys
import tempfile

from contextlib import closing
from importlib.util import (
    module_from_spec,
    spec_from_file_location,
)
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote


SCENE_DIR = Path(__file__).resolve().parent
ROOT = SCENE_DIR.parents[1]

DATA_DIR = ROOT / "data"

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SCENE_DIR))

REAL_DB = (
    ROOT / "data" / "elder_companion.db"
).resolve()

RAW_CONNECT = sqlite3.connect

CHECK_TABLES = [
    "care_consultation_session",
    "care_consultation_message",
    "care_assistance_request",
    "elder_need",
    "elder_care_memory",
    "elder_care_memory_occurrence",
    "care_memory_ingestion",
]


def _load_initializer(
    name: str,
    path: Path,
):
    """Load a database initializer without importing project runtime state."""
    spec = spec_from_file_location(name, path)

    if spec is None or spec.loader is None:
        raise RuntimeError(
            f"无法加载测试数据库初始化脚本: {path}"
        )

    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _create_seed_database(
    database_path: Path,
) -> None:
    """Create the minimum isolated CARE showcase database for this test."""
    initializers = [
        (
            "care_showcase_base_db",
            DATA_DIR / "init_db.py",
        ),
        (
            "care_showcase_care_db",
            SCENE_DIR / "init_care_db.py",
        ),
        (
            "care_showcase_profile_schema",
            SCENE_DIR / "init_personal_care_profile.py",
        ),
        (
            "care_showcase_profile_seed",
            SCENE_DIR / "seed_personal_care_profile.py",
        ),
        (
            "care_showcase_memory_schema",
            SCENE_DIR / "init_care_memory.py",
        ),
        (
            "care_showcase_memory_occurrence_schema",
            SCENE_DIR / "init_care_memory_occurrence.py",
        ),
    ]

    for name, path in initializers:
        module = _load_initializer(name, path)

        with patch.object(module, "DB_PATH", database_path):
            module.main()


def _copy_database(
    source_path: Path,
    destination_path: Path,
) -> None:
    """Use SQLite's backup API so the source database stays read-only."""
    source_uri = (
        "file:"
        + quote(str(source_path), safe="/")
        + "?mode=ro"
    )

    with closing(
        RAW_CONNECT(source_uri, uri=True)
    ) as source, closing(
        RAW_CONNECT(str(destination_path))
    ) as target:
        source.backup(target)


def counts(path):
    result = {}

    with closing(RAW_CONNECT(str(path))) as conn:
        for table in CHECK_TABLES:
            exists = conn.execute(
                """
                SELECT 1 FROM sqlite_master
                WHERE type = 'table' AND name = ?
                """,
                (table,),
            ).fetchone()

            result[table] = (
                conn.execute(
                    f'SELECT COUNT(*) FROM "{table}"'
                ).fetchone()[0]
                if exists
                else 0
            )

    return result


class OfflineCareLLM:
    def generate_reply(
        self,
        *,
        history,
        round_no,
        max_rounds,
        policy_context,
    ):
        return {
            "text": (
                "结合您平时的膝部状态，"
                "我想再了解一下，"
                "这次不适是否影响了行走？"
            ),
            "llm_ms": 1,
            "model": "offline-care-stub",
        }


class OfflineEndIntentLLM:
    def classify(self, text, *, history):
        return {
            "should_end": "先这样吧" in text,
            "confidence": 1.0,
            "reason": "offline_test",
        }


class OfflineMemoryLLM:
    def summarize(
        self,
        *,
        care_domain,
        history,
        final_risk,
    ):
        return {
            "should_store": True,
            "summary": (
                "老人本次反映膝部不适较平时明显，"
                "且已经持续数日，"
                "需工作人员进一步关注。"
            ),
            "llm_ms": 1,
            "model": "offline-memory-stub",
        }


def main():
    with tempfile.TemporaryDirectory(
        prefix="care_showcase_test_"
    ) as temp_dir:

        TEST_DB = (
            Path(temp_dir) / "elder_companion_test.db"
        ).resolve()

        if REAL_DB.is_file():
            _copy_database(REAL_DB, TEST_DB)
            print("数据库隔离: 已创建原始数据库的 SQLite 副本")
        else:
            _create_seed_database(TEST_DB)
            print(
                "数据库隔离: 原始数据库不存在，"
                "已创建临时演示数据库"
            )

        before = counts(TEST_DB)

        print("测试数据库:", TEST_DB)

        # 拦截整个测试进程内的 sqlite3.connect。
        # 即使代码仍使用原始 DB_PATH，也重定向到副本。
        # 其他未知磁盘数据库一律拒绝连接。
        def guarded_connect(database, *args, **kwargs):
            if str(database) == ":memory:":
                return RAW_CONNECT(
                    database, *args, **kwargs
                )

            if kwargs.get("uri"):
                raise RuntimeError(
                    f"测试期间禁止额外 URI 数据库连接: {database}"
                )

            target_path = (
                Path(database).expanduser().resolve()
            )

            if target_path not in {REAL_DB, TEST_DB}:
                raise RuntimeError(
                    f"拒绝访问未知数据库: {target_path}"
                )

            return RAW_CONNECT(
                str(TEST_DB), *args, **kwargs
            )

        with patch.object(
            sqlite3, "connect", guarded_connect
        ):
            import care_db
            import care_controller
            import care_memory_persistence

            from care_session_finalize import (
                finalize_care_session,
            )
            from care_profile_announcement import (
                build_showcase_profile_announcement,
            )
            from care_memory_announcement import (
                build_memory_announcement,
            )
            from g1_voice_demo import (
                build_care_decision_message,
            )

            elderly = care_db.get_elderly(1)
            assert elderly is not None, (
                "测试副本中未找到 elderly_id=1"
            )

            print("测试老人:", elderly["name"])

            with (
                patch.object(
                    care_controller,
                    "CareEndIntentLLM",
                    OfflineEndIntentLLM,
                ),
                patch.object(
                    care_memory_persistence,
                    "CareMemoryLLM",
                    OfflineMemoryLLM,
                ),
            ):
                session_id = care_db.create_session(
                    1,
                    20,
                    session_source="showcase",
                    persist_memory=False,
                )

                consultation = (
                    care_controller.CareConsultation(
                        elderly_id=1,
                        session_id=session_id,
                        max_rounds=20,
                        llm=OfflineCareLLM(),
                        dry_run=True,
                    )
                )

                # 模拟 g1_voice_demo 中的会话记录。
                def save_turn(user_text, result):
                    round_no = max(
                        1, consultation.round_no
                    )

                    care_db.add_message(
                        session_id=session_id,
                        round_no=round_no,
                        role="user",
                        content=user_text,
                    )

                    if result.get("reply"):
                        care_db.add_message(
                            session_id=session_id,
                            round_no=round_no,
                            role="assistant",
                            content=result["reply"],
                        )

                    care_db.update_session_context(
                        session_id=session_id,
                        care_domain=result.get(
                            "care_domain"
                        ),
                        risk_level=result.get(
                            "risk_level"
                        ),
                    )

                print("\n=== 1. 首轮个体化护理 ===")

                text1 = "我今天膝盖又有点酸。"

                r1 = consultation.start(
                    text1,
                    preclassified=True,
                )

                save_turn(text1, r1)

                plan = (
                    r1.get("personalization_plan") or {}
                )

                profile_announcement = (
                    build_showcase_profile_announcement(
                        plan,
                        announced_reasons=set(),
                        max_items=3,
                    )
                )

                print(
                    "护理领域:",
                    r1.get("care_domain"),
                )
                print(
                    "首轮风险:",
                    r1.get("risk_level"),
                )
                print(
                    "个体化播报:",
                    profile_announcement["text"],
                )

                assert r1.get("care_domain") == "mobility"
                assert plan.get("personalized") is True
                assert profile_announcement["text"]
                assert "膝骨关节炎" in (
                    profile_announcement["text"]
                )
                assert not r1.get("transfer_to")

                print("PASS: 个体化档案调用")

                print("\n=== 2. 风险升级 ===")

                text2 = (
                    "今天膝盖比平时明显加重，"
                    "而且已经持续好几天了。"
                )

                r2 = consultation.handle_user_text(
                    text2
                )

                save_turn(text2, r2)

                risk_announcement = (
                    build_care_decision_message(
                        r2,
                        showcase=True,
                    )
                )

                print(
                    "当前风险:",
                    r2.get("risk_level"),
                )
                print(
                    "个体化风险:",
                    r2.get("personalized_risk"),
                )
                print(
                    "匹配规则:",
                    r2.get("matched_risk"),
                )
                print(
                    "工作人员关注事项模拟:",
                    r2.get(
                        "staff_follow_up_simulated"
                    ),
                )
                print(
                    "判断播报:",
                    risk_announcement,
                )

                assert r2.get("risk_level") == "needs_staff", (
                    "本轮没有升级为 needs_staff，"
                    "请检查上面打印的风险规则匹配结果"
                )
                assert r2.get(
                    "new_staff_follow_up"
                ) is True
                assert r2.get(
                    "staff_follow_up_simulated"
                ) is True
                assert r2.get(
                    "assistance_request_id"
                ) is None
                assert risk_announcement
                assert "工作人员" in risk_announcement

                print("PASS: 风险升级和模拟关注事项")

                print("\n=== 3. 老人主动结束 ===")

                text3 = "好的，那先这样吧。"

                r3 = consultation.handle_user_text(
                    text3
                )

                save_turn(text3, r3)

                print("会话状态:", r3.get("state"))
                print("结束原因:", r3.get("end_reason"))

                assert r3.get("state") == "ENDED"

                end_reason = (
                    r3.get("end_reason")
                    or "user_requested"
                )

                assert end_reason == "user_requested"

                print("PASS: 老人主动结束")

                print("\n=== 4. 长期护理记忆预览 ===")

                finalized = finalize_care_session(
                    session_id=session_id,
                    consultation=consultation,
                    end_reason=end_reason,
                )

                memory = (
                    finalized.get("memory") or {}
                )

                announcement = (
                    build_memory_announcement(
                        finalized,
                        showcase=True,
                    )
                )

                print("记忆结果:", memory)
                print(
                    "记忆预览播报:",
                    announcement.get("text"),
                )

                assert finalized.get(
                    "session_finished"
                ) is True
                assert finalized.get(
                    "memory_error"
                ) is None
                assert memory.get("preview") is True
                assert memory.get("stored") is False
                assert announcement["kind"] == "preview"
                assert "不会写入正式护理档案" in announcement["console_text"]
                assert "演示模式" not in announcement["text"]
                assert "不会写入" not in announcement["text"]

                print("PASS: 长期护理记忆预览")

        # 所有 SQLite 测试连接都已经离开拦截区。
        after = counts(TEST_DB)

        print("\n=== 5. 数据库写入边界 ===")

        for table in CHECK_TABLES:
            delta = after[table] - before[table]

            print(f"{table}: 变化 {delta:+d}")

            if table == "care_consultation_session":
                assert delta == 1
            elif table == "care_consultation_message":
                assert delta >= 3
            else:
                assert delta == 0, (
                    f"演示不应该新增 {table} 记录"
                )

        print("PASS: 咨询记录只写入临时副本")
        print("PASS: 工作人员事项未真实创建")
        print("PASS: 跨场景需求未新增")
        print("PASS: 长期护理记忆未新增")

    print("\n" + "=" * 55)
    print("PASS: CARE 离线完整场景验收")
    print("临时测试数据库已自动清理")
    print("原始数据库未作为测试写入目标")
    print("=" * 55)


if __name__ == "__main__":
    main()

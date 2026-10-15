from __future__ import annotations

import json
import sqlite3
from pathlib import Path


DB_PATH = Path(__file__).resolve().parent / "elder_companion.db"


def main():
    conn = sqlite3.connect(DB_PATH)

    conn.execute("PRAGMA foreign_keys = ON")

    # =====================================================
    # 老人信息
    # =====================================================

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS elderly_person (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            name TEXT NOT NULL,
            gender TEXT,
            age INTEGER,
            room TEXT,

            enabled INTEGER NOT NULL DEFAULT 1,

            created_at TEXT NOT NULL
                DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    # =====================================================
    # 家属联系人
    # =====================================================

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS family_contact (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            elderly_id INTEGER NOT NULL,

            name TEXT NOT NULL,
            relation TEXT NOT NULL,

            phone TEXT NOT NULL,

            aliases TEXT,

            authorized INTEGER NOT NULL DEFAULT 1,
            is_primary INTEGER NOT NULL DEFAULT 0,
            enabled INTEGER NOT NULL DEFAULT 1,

            created_at TEXT NOT NULL
                DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (elderly_id)
                REFERENCES elderly_person(id)
        )
        """
    )

    # =====================================================
    # 联系家属日志
    # =====================================================

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS contact_call_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            elderly_id INTEGER NOT NULL,
            contact_id INTEGER,

            recognized_text TEXT,
            requested_relation TEXT,

            confirmed INTEGER NOT NULL DEFAULT 0,

            call_status TEXT,

            created_at TEXT NOT NULL
                DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (elderly_id)
                REFERENCES elderly_person(id),

            FOREIGN KEY (contact_id)
                REFERENCES family_contact(id)
        )
        """
    )

    # =====================================================
    # 初赛测试老人
    # =====================================================

    row = conn.execute(
        """
        SELECT id
        FROM elderly_person
        WHERE name = ?
        LIMIT 1
        """,
        ("王大爷",),
    ).fetchone()

    if row is None:

        cursor = conn.execute(
            """
            INSERT INTO elderly_person (
                name,
                gender,
                age,
                room
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                "王大爷",
                "男",
                76,
                "101",
            ),
        )

        elderly_id = cursor.lastrowid

        # 女儿
        conn.execute(
            """
            INSERT INTO family_contact (
                elderly_id,
                name,
                relation,
                phone,
                aliases,
                authorized,
                is_primary
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                elderly_id,
                "张女士",
                "女儿",

                # 后面改成真实演示号码
                "REPLACE_WITH_DAUGHTER_PHONE",

                json.dumps(
                    [
                        "女儿",
                        "闺女",
                        "姑娘",
                    ],
                    ensure_ascii=False,
                ),

                1,
                1,
            ),
        )

        # 儿子
        conn.execute(
            """
            INSERT INTO family_contact (
                elderly_id,
                name,
                relation,
                phone,
                aliases,
                authorized,
                is_primary
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                elderly_id,
                "李先生",
                "儿子",

                # 后面改成真实演示号码
                "REPLACE_WITH_SON_PHONE",

                json.dumps(
                    [
                        "儿子",
                        "小李",
                    ],
                    ensure_ascii=False,
                ),

                1,
                0,
            ),
        )

        print("已创建测试老人和家属")

    else:
        print(
            "测试老人已经存在，"
            "不会重复插入"
        )

    conn.commit()
    conn.close()

    print()
    print("数据库位置：")
    print(DB_PATH)


if __name__ == "__main__":
    main()

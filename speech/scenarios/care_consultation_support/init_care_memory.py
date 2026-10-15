#!/usr/bin/env python3

from __future__ import annotations

import sqlite3
from pathlib import Path


ROOT = (
    Path(__file__).resolve()
    .parents[2]
)

DB_PATH = (
    ROOT
    / "data"
    / "elder_companion.db"
)


def has_column(
    conn,
    table,
    column,
):

    rows = conn.execute(
        f"PRAGMA table_info({table})"
    ).fetchall()

    return any(
        row[1] == column
        for row in rows
    )


def main():

    conn = sqlite3.connect(
        DB_PATH
    )

    conn.execute(
        "PRAGMA foreign_keys = ON"
    )


    # =====================================================
    # 标记当前护理会话属于什么来源
    # =====================================================

    if not has_column(
        conn,
        "care_consultation_session",
        "session_source",
    ):

        conn.execute(
            """
            ALTER TABLE care_consultation_session
            ADD COLUMN session_source TEXT
            NOT NULL DEFAULT 'runtime'
            """
        )


    if not has_column(
        conn,
        "care_consultation_session",
        "persist_memory",
    ):

        conn.execute(
            """
            ALTER TABLE care_consultation_session
            ADD COLUMN persist_memory INTEGER
            NOT NULL DEFAULT 1
            """
        )


    # =====================================================
    # 长期护理咨询记忆
    #
    # memory_key 是结构化主题键，
    # 不直接使用自然语言 summary 做唯一键。
    # 所以模型措辞不同也不会产生重复记录。
    # =====================================================

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS elder_care_memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            elderly_id INTEGER NOT NULL,

            care_domain TEXT NOT NULL,

            memory_key TEXT NOT NULL,

            summary TEXT NOT NULL,

            occurrence_count INTEGER
                NOT NULL DEFAULT 1,

            first_observed_at TEXT,

            last_observed_at TEXT,

            source_type TEXT NOT NULL
                DEFAULT 'consultation',

            source_session_id INTEGER,

            verified INTEGER NOT NULL
                DEFAULT 1,

            created_at TEXT NOT NULL
                DEFAULT CURRENT_TIMESTAMP,

            updated_at TEXT NOT NULL
                DEFAULT CURRENT_TIMESTAMP,

            UNIQUE (
                elderly_id,
                care_domain,
                memory_key
            ),

            FOREIGN KEY (elderly_id)
                REFERENCES elderly_person(id),

            FOREIGN KEY (source_session_id)
                REFERENCES care_consultation_session(id)
        )
        """
    )


    conn.commit()
    conn.close()

    print(
        "长期护理记忆结构初始化完成"
    )


if __name__ == "__main__":
    main()

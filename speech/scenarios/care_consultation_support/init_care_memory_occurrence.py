#!/usr/bin/env python3

from __future__ import annotations

import sqlite3
from pathlib import Path


PROJECT_ROOT = (
    Path(__file__).resolve()
    .parents[2]
)

DB_PATH = (
    PROJECT_ROOT
    / "data"
    / "elder_companion.db"
)


def main():

    conn = sqlite3.connect(
        DB_PATH
    )

    conn.execute(
        "PRAGMA foreign_keys = ON"
    )


    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS
        elder_care_memory_occurrence (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            memory_id INTEGER NOT NULL,

            elderly_id INTEGER NOT NULL,

            care_domain TEXT NOT NULL,

            memory_key TEXT NOT NULL,

            summary TEXT NOT NULL,

            final_risk TEXT,

            observed_at TEXT NOT NULL,

            source_type TEXT NOT NULL
                DEFAULT 'consultation',

            source_session_id INTEGER,

            -- 每一次历史事实都有稳定来源键。
            --
            -- 正式护理：
            -- session:123
            --
            -- 人工审核演示历史：
            -- seed:mobility:knee_discomfort:2026-08-18
            source_ref TEXT NOT NULL UNIQUE,

            created_at TEXT NOT NULL
                DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (memory_id)
                REFERENCES elder_care_memory(id),

            FOREIGN KEY (elderly_id)
                REFERENCES elderly_person(id),

            FOREIGN KEY (source_session_id)
                REFERENCES care_consultation_session(id)
        )
        """
    )


    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS
        idx_care_memory_occurrence_lookup

        ON elder_care_memory_occurrence (
            elderly_id,
            care_domain,
            memory_key,
            observed_at
        )
        """
    )


    conn.commit()
    conn.close()

    print(
        "护理历史明细表初始化完成"
    )


if __name__ == "__main__":
    main()

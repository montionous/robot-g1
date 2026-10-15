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

    conn = sqlite3.connect(DB_PATH)

    conn.execute(
        "PRAGMA foreign_keys = ON"
    )

    # =====================================================
    # 1. 已确认的既往健康状况 / 病史
    # =====================================================

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS elder_health_condition (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            elderly_id INTEGER NOT NULL,

            condition_name TEXT NOT NULL,
            condition_category TEXT NOT NULL,
            body_area TEXT,

            status TEXT NOT NULL
                DEFAULT 'active',

            diagnosed INTEGER NOT NULL
                DEFAULT 1,

            diagnosed_at TEXT,

            notes TEXT,

            source TEXT NOT NULL
                DEFAULT 'demo_verified_record',

            verified INTEGER NOT NULL
                DEFAULT 1,

            created_at TEXT NOT NULL
                DEFAULT CURRENT_TIMESTAMP,

            UNIQUE (
                elderly_id,
                condition_name
            ),

            FOREIGN KEY (elderly_id)
                REFERENCES elderly_person(id)
        )
        """
    )

    # =====================================================
    # 2. 老人的个人护理基线
    # =====================================================

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS elder_care_baseline (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            elderly_id INTEGER NOT NULL,

            care_domain TEXT NOT NULL,
            baseline_key TEXT NOT NULL,
            baseline_value TEXT NOT NULL,

            source TEXT NOT NULL
                DEFAULT 'demo_verified_record',

            verified INTEGER NOT NULL
                DEFAULT 1,

            updated_at TEXT NOT NULL
                DEFAULT CURRENT_TIMESTAMP,

            UNIQUE (
                elderly_id,
                care_domain,
                baseline_key
            ),

            FOREIGN KEY (elderly_id)
                REFERENCES elderly_person(id)
        )
        """
    )

    # =====================================================
    # 3. 既往护理 / 健康事件
    # =====================================================

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS elder_care_event (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            elderly_id INTEGER NOT NULL,

            event_type TEXT NOT NULL,
            event_date TEXT,

            care_domain TEXT NOT NULL,

            summary TEXT NOT NULL,
            outcome TEXT,

            source TEXT NOT NULL
                DEFAULT 'demo_verified_record',

            verified INTEGER NOT NULL
                DEFAULT 1,

            created_at TEXT NOT NULL
                DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (elderly_id)
                REFERENCES elderly_person(id)
        )
        """
    )

    conn.commit()
    conn.close()

    print(
        "个体护理档案表初始化完成"
    )
    print(
        "数据库:",
        DB_PATH,
    )


if __name__ == "__main__":
    main()

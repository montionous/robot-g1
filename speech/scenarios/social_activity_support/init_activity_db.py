#!/usr/bin/env python3

from __future__ import annotations

import sqlite3
from pathlib import Path


SCENE_DIR = Path(__file__).resolve().parent
SPEECH_ROOT = SCENE_DIR.parents[1]

DB_PATH = (
    SPEECH_ROOT
    / "data"
    / "elder_companion.db"
)


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS social_activity (
    activity_id INTEGER PRIMARY KEY AUTOINCREMENT,

    name TEXT NOT NULL,
    category TEXT NOT NULL,

    description TEXT NOT NULL DEFAULT '',
    tags TEXT NOT NULL DEFAULT '',

    organizer TEXT NOT NULL DEFAULT '',
    location TEXT NOT NULL DEFAULT '',

    requires_registration INTEGER NOT NULL DEFAULT 1,

    notes TEXT NOT NULL DEFAULT '',
    enabled INTEGER NOT NULL DEFAULT 1,

    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);


CREATE TABLE IF NOT EXISTS social_activity_session (
    session_id INTEGER PRIMARY KEY AUTOINCREMENT,

    activity_id INTEGER NOT NULL,

    activity_date TEXT NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,

    capacity INTEGER,
    registered_count INTEGER NOT NULL DEFAULT 0,

    registration_deadline TEXT,

    status TEXT NOT NULL DEFAULT 'open',

    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (
        activity_id
    )
    REFERENCES social_activity (
        activity_id
    )
);


CREATE TABLE IF NOT EXISTS social_activity_interest (
    interest_id INTEGER PRIMARY KEY AUTOINCREMENT,

    elder_id INTEGER NOT NULL,
    session_id INTEGER NOT NULL,

    status TEXT NOT NULL DEFAULT 'pending',

    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    UNIQUE (
        elder_id,
        session_id
    ),

    FOREIGN KEY (
        session_id
    )
    REFERENCES social_activity_session (
        session_id
    )
);


CREATE TABLE IF NOT EXISTS staff_notification (
    notification_id INTEGER PRIMARY KEY AUTOINCREMENT,

    elder_id INTEGER NOT NULL,
    session_id INTEGER,

    notification_type TEXT NOT NULL,
    message TEXT NOT NULL,

    status TEXT NOT NULL DEFAULT 'pending',

    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (
        session_id
    )
    REFERENCES social_activity_session (
        session_id
    )
);


CREATE INDEX IF NOT EXISTS
idx_social_session_date
ON social_activity_session (
    activity_date,
    start_time
);


CREATE INDEX IF NOT EXISTS
idx_social_interest_elder
ON social_activity_interest (
    elder_id
);


CREATE INDEX IF NOT EXISTS
idx_staff_notification_status
ON staff_notification (
    status
);
"""


def init_db():

    DB_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with sqlite3.connect(
        DB_PATH
    ) as conn:

        conn.executescript(
            SCHEMA
        )

        conn.commit()

    print(
        "数据库初始化完成:"
    )

    print(
        DB_PATH
    )


if __name__ == "__main__":
    init_db()

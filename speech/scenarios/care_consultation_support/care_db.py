from __future__ import annotations

import json
import sqlite3

from datetime import datetime
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


def connect():

    conn = sqlite3.connect(DB_PATH)

    conn.row_factory = sqlite3.Row

    conn.execute(
        "PRAGMA foreign_keys = ON"
    )

    return conn


def get_elderly(
    elderly_id: int,
):

    with connect() as conn:

        row = conn.execute(
            """
            SELECT *
            FROM elderly_person
            WHERE id = ?
              AND enabled = 1
            LIMIT 1
            """,
            (elderly_id,),
        ).fetchone()

    if row is None:
        return None

    return dict(row)


def create_session(
    elderly_id: int,
    max_rounds: int,
    *,
    session_source: str = "runtime",
    persist_memory: bool = True,
):

    with connect() as conn:

        cursor = conn.execute(
            """
            INSERT INTO care_consultation_session (
                elderly_id,
                max_rounds,
                status,
                session_source,
                persist_memory
            )
            VALUES (?, ?, 'consulting', ?, ?)
            """,
            (
                elderly_id,
                max_rounds,
                session_source,
                1
                if persist_memory
                else 0,
            ),
        )

        conn.commit()

        return cursor.lastrowid


def update_session_context(
    *,
    session_id: int,
    care_domain: str | None,
    risk_level: str | None,
):

    with connect() as conn:

        conn.execute(
            """
            UPDATE care_consultation_session
            SET
                care_domain = ?,
                risk_level = ?
            WHERE id = ?
            """,
            (
                care_domain,
                risk_level,
                session_id,
            ),
        )

        conn.commit()


def add_message(
    *,
    session_id: int,
    round_no: int,
    role: str,
    content: str,
    tags=None,
):

    tags_json = None

    if tags is not None:

        tags_json = json.dumps(
            tags,
            ensure_ascii=False,
        )

    with connect() as conn:

        conn.execute(
            """
            INSERT INTO care_consultation_message (
                session_id,
                round_no,
                role,
                content,
                tags_json
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                session_id,
                round_no,
                role,
                content,
                tags_json,
            ),
        )

        conn.commit()


def create_assistance_request(
    *,
    session_id: int,
    elderly_id: int,
    care_domain: str,
    risk_level: str,
    user_description: str,
    summary: str,
):

    with connect() as conn:

        cursor = conn.execute(
            """
            INSERT INTO care_assistance_request (
                session_id,
                elderly_id,
                care_domain,
                risk_level,
                user_description,
                summary,
                status
            )
            VALUES (?, ?, ?, ?, ?, ?, 'pending')
            """,
            (
                session_id,
                elderly_id,
                care_domain,
                risk_level,
                user_description,
                summary,
            ),
        )

        conn.commit()

        return cursor.lastrowid


def finish_session(
    *,
    session_id: int,
    completed_rounds: int,
    end_reason: str,
):

    with connect() as conn:

        conn.execute(
            """
            UPDATE care_consultation_session

            SET
                completed_rounds = ?,
                status = 'ended',
                end_reason = ?,
                ended_at = ?

            WHERE id = ?
            """,
            (
                completed_rounds,
                end_reason,
                datetime.now().isoformat(
                    timespec="seconds"
                ),
                session_id,
            ),
        )

        conn.commit()

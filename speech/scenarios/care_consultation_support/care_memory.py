from __future__ import annotations

import sqlite3
from datetime import datetime
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


def connect():

    conn = sqlite3.connect(
        DB_PATH
    )

    conn.row_factory = (
        sqlite3.Row
    )

    conn.execute(
        "PRAGMA foreign_keys = ON"
    )

    return conn


def upsert_care_memory(
    *,
    elderly_id,
    care_domain,
    memory_key,
    summary,
    observed_at=None,
    source_type="consultation",
    source_session_id=None,
    increment=True,
):

    observed_at = (
        observed_at
        or datetime.now().isoformat(
            timespec="seconds"
        )
    )


    with connect() as conn:

        old = conn.execute(
            """
            SELECT *
            FROM elder_care_memory
            WHERE elderly_id = ?
              AND care_domain = ?
              AND memory_key = ?
            LIMIT 1
            """,
            (
                elderly_id,
                care_domain,
                memory_key,
            ),
        ).fetchone()


        if old is None:

            cursor = conn.execute(
                """
                INSERT INTO elder_care_memory (
                    elderly_id,
                    care_domain,
                    memory_key,
                    summary,
                    occurrence_count,
                    first_observed_at,
                    last_observed_at,
                    source_type,
                    source_session_id,
                    verified
                )
                VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?, 1)
                """,
                (
                    elderly_id,
                    care_domain,
                    memory_key,
                    summary,
                    observed_at,
                    observed_at,
                    source_type,
                    source_session_id,
                ),
            )

            conn.commit()

            return {
                "action":
                    "inserted",

                "id":
                    cursor.lastrowid,

                "occurrence_count":
                    1,
            }


        count = int(
            old[
                "occurrence_count"
            ]
            or 1
        )

        if increment:
            count += 1


        conn.execute(
            """
            UPDATE elder_care_memory

            SET
                summary = ?,
                occurrence_count = ?,
                last_observed_at = ?,
                source_type = ?,
                source_session_id = ?,
                updated_at = CURRENT_TIMESTAMP

            WHERE id = ?
            """,
            (
                summary,
                count,
                observed_at,
                source_type,
                source_session_id,
                old["id"],
            ),
        )

        conn.commit()

        return {
            "action":
                (
                    "updated_count"
                    if increment
                    else "updated"
                ),

            "id":
                old["id"],

            "occurrence_count":
                count,
        }


def get_care_memories(
    elderly_id,
    care_domain,
    *,
    limit=5,
):

    with connect() as conn:

        rows = conn.execute(
            """
            SELECT
                memory_key,
                summary,
                occurrence_count,
                first_observed_at,
                last_observed_at,
                source_type,
                verified

            FROM elder_care_memory

            WHERE elderly_id = ?
              AND care_domain = ?
              AND verified = 1

            ORDER BY
                last_observed_at DESC,
                id DESC

            LIMIT ?
            """,
            (
                elderly_id,
                care_domain,
                limit,
            ),
        ).fetchall()


    return [
        dict(row)
        for row in rows
    ]


def session_can_persist_memory(
    session_id,
):

    with connect() as conn:

        row = conn.execute(
            """
            SELECT
                session_source,
                persist_memory

            FROM care_consultation_session

            WHERE id = ?

            LIMIT 1
            """,
            (session_id,),
        ).fetchone()


    if row is None:
        return False


    return bool(
        row["persist_memory"]
    )


def get_recent_care_occurrences(
    elderly_id,
    care_domain,
    *,
    memory_key=None,
    limit=3,
):

    with connect() as conn:

        if memory_key:

            rows = conn.execute(
                """
                SELECT
                    memory_key,
                    summary,
                    final_risk,
                    observed_at,
                    source_type

                FROM elder_care_memory_occurrence

                WHERE elderly_id = ?
                  AND care_domain = ?
                  AND memory_key = ?

                ORDER BY
                    observed_at DESC,
                    id DESC

                LIMIT ?
                """,
                (
                    elderly_id,
                    care_domain,
                    memory_key,
                    limit,
                ),
            ).fetchall()

        else:

            rows = conn.execute(
                """
                SELECT
                    memory_key,
                    summary,
                    final_risk,
                    observed_at,
                    source_type

                FROM elder_care_memory_occurrence

                WHERE elderly_id = ?
                  AND care_domain = ?

                ORDER BY
                    observed_at DESC,
                    id DESC

                LIMIT ?
                """,
                (
                    elderly_id,
                    care_domain,
                    limit,
                ),
            ).fetchall()


    return [
        dict(row)
        for row in rows
    ]

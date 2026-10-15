from __future__ import annotations

import json
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


def connect():
    conn = sqlite3.connect(DB_PATH)

    conn.row_factory = sqlite3.Row

    conn.execute(
        "PRAGMA foreign_keys = ON"
    )

    return conn


# =========================================================
# 老人
# =========================================================

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


# =========================================================
# 家属联系人
# =========================================================

def list_family_contacts(
    elderly_id: int,
):

    with connect() as conn:

        rows = conn.execute(
            """
            SELECT *
            FROM family_contact
            WHERE elderly_id = ?
              AND authorized = 1
              AND enabled = 1
            ORDER BY
                is_primary DESC,
                id ASC
            """,
            (elderly_id,),
        ).fetchall()

    contacts = []

    for row in rows:

        item = dict(row)

        raw_aliases = item.get(
            "aliases"
        )

        if raw_aliases:

            try:
                item["aliases"] = (
                    json.loads(
                        raw_aliases
                    )
                )

            except Exception:
                item["aliases"] = []

        else:
            item["aliases"] = []

        contacts.append(
            item
        )

    return contacts


def find_family_contact(
    elderly_id: int,
    text: str,
):

    normalized = (
        str(text)
        .strip()
        .replace(" ", "")
    )

    contacts = list_family_contacts(
        elderly_id
    )

    for contact in contacts:

        candidates = [
            contact["relation"],
            contact["name"],
            *contact["aliases"],
        ]

        for candidate in candidates:

            if (
                candidate
                and candidate in normalized
            ):
                return contact

    return None


# =========================================================
# 通话记录
# =========================================================

def create_call_log(
    *,
    elderly_id: int,
    contact_id: int | None,
    recognized_text: str,
    requested_relation: str | None,
    confirmed: bool,
    call_status: str,
):

    with connect() as conn:

        cursor = conn.execute(
            """
            INSERT INTO contact_call_log (
                elderly_id,
                contact_id,
                recognized_text,
                requested_relation,
                confirmed,
                call_status
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                elderly_id,
                contact_id,
                recognized_text,
                requested_relation,
                1 if confirmed else 0,
                call_status,
            ),
        )

        conn.commit()

        return cursor.lastrowid


def list_recent_call_logs(
    limit: int = 10,
):

    with connect() as conn:

        rows = conn.execute(
            """
            SELECT
                log.id,

                elderly.name
                    AS elderly_name,

                contact.name
                    AS contact_name,

                contact.relation,

                log.recognized_text,

                log.confirmed,

                log.call_status,

                log.created_at

            FROM contact_call_log AS log

            LEFT JOIN elderly_person AS elderly
                ON elderly.id = log.elderly_id

            LEFT JOIN family_contact AS contact
                ON contact.id = log.contact_id

            ORDER BY log.id DESC

            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    return [
        dict(row)
        for row in rows
    ]

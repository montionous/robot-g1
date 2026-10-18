from __future__ import annotations

import json
import sqlite3

from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path


PROJECT_ROOT = (
    Path(__file__).resolve()
    .parent
)

DB_PATH = (
    PROJECT_ROOT
    / "data"
    / "elder_companion.db"
)


VALID_PRIORITIES = {
    "normal",
    "high",
    "urgent",
}

VALID_STATUSES = {
    "detected",
    "in_progress",
    "completed",
    "cancelled",
    "failed",
}


CHINA_TZ = ZoneInfo(
    "Asia/Shanghai"
)


def _now_text():

    return (
        datetime.now(
            CHINA_TZ
        )
        .strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    )


def connect():

    conn = sqlite3.connect(
        DB_PATH,
        timeout=5.0,
    )

    conn.row_factory = (
        sqlite3.Row
    )

    conn.execute(
        "PRAGMA foreign_keys = ON"
    )

    conn.execute(
        "PRAGMA busy_timeout = 5000"
    )

    return conn


def elderly_is_enabled(
    elderly_id,
):
    """Return whether an enabled elder exists in the shared database."""

    try:
        value = int(
            elderly_id
        )

    except (
        TypeError,
        ValueError,
    ):
        return False


    with connect() as conn:

        row = conn.execute(
            """
            SELECT 1

            FROM elderly_person

            WHERE id = ?
              AND enabled = 1

            LIMIT 1
            """,
            (
                value,
            ),
        ).fetchone()

    return row is not None


def _json_dump(
    value,
):

    if value is None:
        return None

    return json.dumps(
        value,
        ensure_ascii=False,
    )


def _row_to_dict(
    row,
):

    if row is None:
        return None

    result = dict(row)

    raw = result.get(
        "details_json"
    )

    if raw:

        try:
            details = json.loads(
                raw
            )

            # details_json 是给跨场景模块读取的键值对象。
            # 历史脏数据不能让推荐或护理同步在 .get / ** 展开时崩溃。
            result[
                "details"
            ] = (
                details
                if isinstance(
                    details,
                    dict,
                )
                else None
            )

        except Exception:

            result[
                "details"
            ] = None

    else:

        result[
            "details"
        ] = None

    return result


def create_need(
    *,
    elderly_id: int,
    need_category: str,
    need_code: str,
    summary: str,
    source_scene: str,
    raw_text: str | None = None,
    priority: str = "normal",
    status: str = "detected",
    source_session_id=None,
    source_round_no: int | None = None,
    confidence: float | None = None,
    details=None,
    dedupe_key: str | None = None,
    handled_by: str | None = None,
):

    if priority not in VALID_PRIORITIES:

        raise ValueError(
            f"非法 priority: {priority}"
        )

    if status not in VALID_STATUSES:

        raise ValueError(
            f"非法 status: {status}"
        )


    with connect() as conn:

        # -------------------------------------------------
        # 如果同一个需求因为重试再次提交，
        # dedupe_key 用于防止重复产生记录。
        # -------------------------------------------------

        if dedupe_key:

            existing = (
                conn.execute(
                    """
                    SELECT *

                    FROM elder_need

                    WHERE dedupe_key = ?

                    LIMIT 1
                    """,
                    (
                        dedupe_key,
                    ),
                )
                .fetchone()
            )

            if existing is not None:

                return _row_to_dict(
                    existing
                )


        cursor = conn.execute(
            """
            INSERT INTO elder_need (
                elderly_id,
                need_category,
                need_code,
                summary,
                raw_text,
                priority,
                status,
                source_scene,
                source_session_id,
                source_round_no,
                confidence,
                details_json,
                dedupe_key,
                handled_by,
                created_at,
                updated_at
            )
            VALUES (
                ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?,
                ?
            )
            """,
            (
                elderly_id,
                need_category,
                need_code,
                summary,
                raw_text,
                priority,
                status,
                source_scene,
                (
                    str(
                        source_session_id
                    )
                    if source_session_id
                    is not None
                    else None
                ),
                source_round_no,
                confidence,
                _json_dump(
                    details
                ),
                dedupe_key,
                handled_by,
                _now_text(),
                _now_text(),
            ),
        )

        need_id = (
            cursor.lastrowid
        )

        conn.commit()


        row = (
            conn.execute(
                """
                SELECT *

                FROM elder_need

                WHERE id = ?
                """,
                (
                    need_id,
                ),
            )
            .fetchone()
        )


    return _row_to_dict(
        row
    )


def get_need(
    need_id: int,
):

    with connect() as conn:

        row = (
            conn.execute(
                """
                SELECT *

                FROM elder_need

                WHERE id = ?

                LIMIT 1
                """,
                (
                    need_id,
                ),
            )
            .fetchone()
        )

    return _row_to_dict(
        row
    )


def update_need(
    need_id: int,
    *,
    summary=None,
    raw_text=None,
    priority=None,
    status=None,
    details=None,
    handled_by=None,
    source_round_no=None,
):

    if (
        priority is not None
        and priority
        not in VALID_PRIORITIES
    ):

        raise ValueError(
            f"非法 priority: {priority}"
        )


    if (
        status is not None
        and status
        not in VALID_STATUSES
    ):

        raise ValueError(
            f"非法 status: {status}"
        )


    fields = []
    values = []


    if summary is not None:

        fields.append(
            "summary = ?"
        )

        values.append(
            summary
        )


    if raw_text is not None:

        fields.append(
            "raw_text = ?"
        )

        values.append(
            raw_text
        )


    if priority is not None:

        fields.append(
            "priority = ?"
        )

        values.append(
            priority
        )


    if status is not None:

        fields.append(
            "status = ?"
        )

        values.append(
            status
        )


        if status in {
            "completed",
            "cancelled",
            "failed",
        }:

            fields.append(
                "completed_at = ?"
            )

            values.append(
                _now_text()
            )

        else:

            # 非终态需求不应保留旧的完成时间。
            fields.append(
                "completed_at = NULL"
            )


    if details is not None:

        fields.append(
            "details_json = ?"
        )

        values.append(
            _json_dump(
                details
            )
        )


    if handled_by is not None:

        fields.append(
            "handled_by = ?"
        )

        values.append(
            handled_by
        )


    if source_round_no is not None:

        fields.append(
            "source_round_no = ?"
        )

        values.append(
            int(
                source_round_no
            )
        )


    if not fields:

        return get_need(
            need_id
        )


    fields.append(
        "updated_at = ?"
    )

    values.append(
        _now_text()
    )

    values.append(
        need_id
    )


    with connect() as conn:

        conn.execute(
            f"""
            UPDATE elder_need

            SET
                {", ".join(fields)}

            WHERE id = ?
            """,
            values,
        )

        conn.commit()


    return get_need(
        need_id
    )


def list_needs(
    *,
    elderly_id=None,
    status=None,
    need_category=None,
    source_scene=None,
    limit=100,
):

    where = []
    values = []


    if elderly_id is not None:

        where.append(
            "elderly_id = ?"
        )

        values.append(
            elderly_id
        )


    if status is not None:

        where.append(
            "status = ?"
        )

        values.append(
            status
        )


    if need_category is not None:

        where.append(
            "need_category = ?"
        )

        values.append(
            need_category
        )


    if source_scene is not None:

        where.append(
            "source_scene = ?"
        )

        values.append(
            source_scene
        )


    sql = """
        SELECT *

        FROM elder_need
    """


    if where:

        sql += (
            "\nWHERE "
            + " AND ".join(
                where
            )
        )


    sql += """
        ORDER BY
            id DESC

        LIMIT ?
    """

    values.append(
        max(
            1,
            int(limit),
        )
    )


    with connect() as conn:

        rows = (
            conn.execute(
                sql,
                values,
            )
            .fetchall()
        )


    return [
        _row_to_dict(
            row
        )
        for row in rows
    ]


def get_elder_need_history(
    elderly_id: int,
    *,
    need_category=None,
    need_code=None,
    source_scene=None,
    status=None,
    limit=20,
):

    where = [
        "elderly_id = ?"
    ]

    values = [
        elderly_id
    ]


    if need_category is not None:

        where.append(
            "need_category = ?"
        )

        values.append(
            need_category
        )


    if need_code is not None:

        where.append(
            "need_code = ?"
        )

        values.append(
            need_code
        )


    if source_scene is not None:

        where.append(
            "source_scene = ?"
        )

        values.append(
            source_scene
        )


    if status is not None:

        where.append(
            "status = ?"
        )

        values.append(
            status
        )


    values.append(
        max(
            1,
            int(limit),
        )
    )


    with connect() as conn:

        rows = conn.execute(
            f"""
            SELECT *

            FROM elder_need

            WHERE {
                " AND ".join(
                    where
                )
            }

            ORDER BY
                id DESC

            LIMIT ?
            """,
            values,
        ).fetchall()


    return [
        _row_to_dict(
            row
        )
        for row in rows
    ]


def get_need_frequency(
    elderly_id: int,
    *,
    need_category=None,
    status=None,
    limit=20,
):

    where = [
        "elderly_id = ?"
    ]

    values = [
        elderly_id
    ]


    if need_category is not None:

        where.append(
            "need_category = ?"
        )

        values.append(
            need_category
        )


    if status is not None:

        where.append(
            "status = ?"
        )

        values.append(
            status
        )


    values.append(
        max(
            1,
            int(limit),
        )
    )


    with connect() as conn:

        rows = conn.execute(
            f"""
            SELECT
                need_code,
                COUNT(*) AS occurrence_count,
                MAX(created_at)
                    AS last_requested_at

            FROM elder_need

            WHERE {
                " AND ".join(
                    where
                )
            }

            GROUP BY
                need_code

            ORDER BY
                occurrence_count DESC,
                last_requested_at DESC

            LIMIT ?
            """,
            values,
        ).fetchall()


    return [
        dict(row)
        for row in rows
    ]

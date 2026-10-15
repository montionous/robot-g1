#!/usr/bin/env python3

from __future__ import annotations

import sqlite3

from datetime import date, timedelta

from init_activity_db import DB_PATH


# ---------------------------------------------------------
# 后续演示用场次
#
# 目的：
# 让“本场满员 / 报名截止 / 已取消”
# 后可以真实查询下一场，而不是由大模型编造。
# ---------------------------------------------------------

FUTURE_SESSIONS = [
    {
        "day_offset": 1,
        "name": "棋牌交流",
        "start": "14:00",
        "end": "15:00",
        "capacity": 8,
        "registered": 3,
        "deadline": "13:30",
        "status": "open",
    },
    {
        "day_offset": 1,
        "name": "手工兴趣小组",
        "start": "16:30",
        "end": "17:30",
        "capacity": 10,
        "registered": 4,
        "deadline": "13:00",
        "status": "open",
    },
    {
        "day_offset": 1,
        "name": "戏曲欣赏",
        "start": "19:30",
        "end": "20:30",
        "capacity": None,
        "registered": 6,
        "deadline": None,
        "status": "open",
    },

    {
        "day_offset": 2,
        "name": "书法交流",
        "start": "10:30",
        "end": "11:30",
        "capacity": 12,
        "registered": 5,
        "deadline": "10:00",
        "status": "open",
    },
    {
        "day_offset": 2,
        "name": "下午茶话会",
        "start": "15:00",
        "end": "16:00",
        "capacity": 12,
        "registered": 5,
        "deadline": "14:30",
        "status": "open",
    },
    {
        "day_offset": 2,
        "name": "集体唱歌",
        "start": "15:30",
        "end": "16:30",
        "capacity": None,
        "registered": 8,
        "deadline": None,
        "status": "open",
    },

    {
        "day_offset": 3,
        "name": "健康知识讲座",
        "start": "09:30",
        "end": "10:30",
        "capacity": None,
        "registered": 12,
        "deadline": None,
        "status": "open",
    },
    {
        "day_offset": 3,
        "name": "棋牌交流",
        "start": "14:00",
        "end": "15:00",
        "capacity": 8,
        "registered": 2,
        "deadline": "13:30",
        "status": "open",
    },
]


def get_activity_id(
    conn,
    name,
):

    row = conn.execute(
        """
        SELECT activity_id
        FROM social_activity
        WHERE
            name = ?
            AND enabled = 1
        ORDER BY activity_id
        LIMIT 1
        """,
        (name,),
    ).fetchone()

    if row is None:
        raise RuntimeError(
            f"找不到活动: {name}"
        )

    return int(
        row["activity_id"]
    )


def upsert_session(
    conn,
    *,
    activity_id,
    activity_date,
    start_time,
    end_time,
    capacity,
    registered_count,
    registration_deadline,
    status,
):

    rows = conn.execute(
        """
        SELECT session_id
        FROM social_activity_session
        WHERE
            activity_id = ?
            AND activity_date = ?
            AND start_time = ?
        ORDER BY session_id
        """,
        (
            activity_id,
            activity_date,
            start_time,
        ),
    ).fetchall()

    if len(rows) > 1:
        raise RuntimeError(
            "发现重复活动场次: "
            f"activity_id={activity_id}, "
            f"date={activity_date}, "
            f"start={start_time}"
        )

    if rows:

        session_id = int(
            rows[0]["session_id"]
        )

        conn.execute(
            """
            UPDATE social_activity_session
            SET
                end_time = ?,
                capacity = ?,
                registered_count = ?,
                registration_deadline = ?,
                status = ?
            WHERE session_id = ?
            """,
            (
                end_time,
                capacity,
                registered_count,
                registration_deadline,
                status,
                session_id,
            ),
        )

        return (
            "updated",
            session_id,
        )

    cursor = conn.execute(
        """
        INSERT INTO social_activity_session (
            activity_id,
            activity_date,
            start_time,
            end_time,
            capacity,
            registered_count,
            registration_deadline,
            status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            activity_id,
            activity_date,
            start_time,
            end_time,
            capacity,
            registered_count,
            registration_deadline,
            status,
        ),
    )

    return (
        "inserted",
        int(cursor.lastrowid),
    )


def main():

    today = date.today()

    conn = sqlite3.connect(
        DB_PATH
    )

    conn.row_factory = sqlite3.Row

    conn.execute(
        "PRAGMA foreign_keys = ON"
    )

    inserted = 0
    updated = 0

    try:

        conn.execute(
            "BEGIN"
        )

        for item in FUTURE_SESSIONS:

            day = (
                today
                + timedelta(
                    days=item[
                        "day_offset"
                    ]
                )
            )

            activity_id = (
                get_activity_id(
                    conn,
                    item["name"],
                )
            )

            deadline = None

            if item["deadline"]:

                deadline = (
                    day.isoformat()
                    + "T"
                    + item["deadline"]
                    + ":00"
                )

            action, session_id = (
                upsert_session(
                    conn,
                    activity_id=
                        activity_id,
                    activity_date=
                        day.isoformat(),
                    start_time=
                        item["start"],
                    end_time=
                        item["end"],
                    capacity=
                        item["capacity"],
                    registered_count=
                        item["registered"],
                    registration_deadline=
                        deadline,
                    status=
                        item["status"],
                )
            )

            if action == "inserted":
                inserted += 1
            else:
                updated += 1

            print(
                f"{action:8s}",
                f"session_id={session_id}",
                day.isoformat(),
                item["start"],
                item["name"],
                item["status"],
            )

        conn.commit()

    except Exception:

        conn.rollback()
        raise

    finally:

        conn.close()

    print()
    print("未来演示场次准备完成")
    print("新增:", inserted)
    print("更新:", updated)
    print(
        "未删除任何历史数据"
    )


if __name__ == "__main__":
    main()

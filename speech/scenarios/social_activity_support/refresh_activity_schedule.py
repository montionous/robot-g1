#!/usr/bin/env python3

from __future__ import annotations

import sqlite3
import sys
from datetime import (
    date,
    datetime,
    timedelta,
)
from pathlib import Path


SCENE_DIR = (
    Path(__file__)
    .resolve()
    .parent
)

sys.path.insert(
    0,
    str(SCENE_DIR),
)

from init_activity_db import (
    DB_PATH,
)


def deadline(
    day,
    time_text,
):
    if time_text is None:
        return None

    return (
        f"{day.isoformat()}"
        f"T{time_text}:00"
    )


def get_activity_id(
    conn,
    name,
):
    row = conn.execute(
        """
        SELECT activity_id
        FROM social_activity
        WHERE name = ?
          AND enabled = 1
        ORDER BY activity_id
        LIMIT 1
        """,
        (name,),
    ).fetchone()

    if row is None:
        raise RuntimeError(
            f"数据库中没有活动定义: {name}"
        )

    return int(
        row["activity_id"]
    )


def ensure_activity_definitions(
    conn,
):
    """
    只修正确认过的业务属性。
    不删除活动定义，不重建 ID。
    """

    conn.execute(
        """
        UPDATE social_activity

        SET
            category = 'music',
            description = ?,
            tags = ?,
            organizer = ?,
            location = ?,
            requires_registration = 0,
            notes = ?,
            enabled = 1

        WHERE name = '集体唱歌'
        """,
        (
            "大家一起演唱经典歌曲和熟悉的老歌。",
            "唱歌,合唱,音乐,老歌,社交",
            "赵老师",
            "三楼多功能厅",
            "不需要专业唱歌基础。",
        ),
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
    """
    SQLite 当前没有
    (activity_id, activity_date, start_time)
    唯一约束。

    因此手工 SELECT -> UPDATE / INSERT，
    保证脚本可重复运行且不重复造场次。
    """

    rows = conn.execute(
        """
        SELECT session_id
        FROM social_activity_session

        WHERE activity_id = ?
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
        ids = [
            row["session_id"]
            for row in rows
        ]

        raise RuntimeError(
            "发现重复活动场次，停止刷新："
            f"activity_id={activity_id}, "
            f"date={activity_date}, "
            f"start={start_time}, "
            f"session_ids={ids}"
        )

    if rows:
        session_id = int(
            rows[0][
                "session_id"
            ]
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
        int(
            cursor.lastrowid
        ),
    )


def build_schedule():
    today = date.today()

    tomorrow = (
        today
        + timedelta(
            days=1
        )
    )

    return [
        # =================================================
        # 今天
        # =================================================

        {
            "name":
                "健康知识讲座",

            "date":
                today,

            "start":
                "09:30",

            "end":
                "10:30",

            "capacity":
                None,

            "registered":
                18,

            "deadline":
                None,

            "status":
                "open",
        },

        {
            "name":
                "书法交流",

            "date":
                today,

            "start":
                "10:30",

            "end":
                "11:30",

            "capacity":
                12,

            "registered":
                7,

            "deadline":
                deadline(
                    today,
                    "10:00",
                ),

            "status":
                "open",
        },

        {
            "name":
                "棋牌交流",

            "date":
                today,

            "start":
                "14:00",

            "end":
                "15:00",

            "capacity":
                8,

            "registered":
                8,

            "deadline":
                deadline(
                    today,
                    "13:30",
                ),

            "status":
                "full",
        },

        {
            "name":
                "下午茶话会",

            "date":
                today,

            "start":
                "15:00",

            "end":
                "16:00",

            "capacity":
                12,

            "registered":
                9,

            "deadline":
                deadline(
                    today,
                    "14:30",
                ),

            "status":
                "open",
        },

        {
            "name":
                "集体唱歌",

            "date":
                today,

            "start":
                "15:30",

            "end":
                "16:30",

            "capacity":
                None,

            "registered":
                15,

            "deadline":
                None,

            "status":
                "open",
        },

        {
            "name":
                "手工兴趣小组",

            "date":
                today,

            "start":
                "16:30",

            "end":
                "17:30",

            "capacity":
                10,

            "registered":
                6,

            "deadline":
                deadline(
                    today,
                    "13:00",
                ),

            "status":
                "closed",
        },

        {
            "name":
                "集体观影",

            "date":
                today,

            "start":
                "19:00",

            "end":
                "21:00",

            "capacity":
                None,

            "registered":
                20,

            "deadline":
                None,

            "status":
                "open",
        },

        {
            "name":
                "戏曲欣赏",

            "date":
                today,

            "start":
                "19:30",

            "end":
                "20:30",

            "capacity":
                None,

            "registered":
                10,

            "deadline":
                None,

            "status":
                "cancelled",
        },

        # =================================================
        # 明天
        # =================================================

        {
            "name":
                "下午茶话会",

            "date":
                tomorrow,

            "start":
                "15:00",

            "end":
                "16:00",

            "capacity":
                12,

            "registered":
                4,

            "deadline":
                deadline(
                    tomorrow,
                    "14:30",
                ),

            "status":
                "open",
        },

        {
            "name":
                "集体唱歌",

            "date":
                tomorrow,

            "start":
                "15:30",

            "end":
                "16:30",

            "capacity":
                None,

            "registered":
                8,

            "deadline":
                None,

            "status":
                "open",
        },
    ]


def main():
    print(
        "数据库:",
        DB_PATH,
    )

    print(
        "刷新时间:",
        datetime.now().isoformat(
            timespec="seconds"
        ),
    )

    conn = sqlite3.connect(
        DB_PATH
    )

    conn.row_factory = (
        sqlite3.Row
    )

    conn.execute(
        "PRAGMA foreign_keys = ON"
    )

    try:
        conn.execute(
            "BEGIN"
        )

        ensure_activity_definitions(
            conn
        )

        schedule = (
            build_schedule()
        )

        inserted = 0
        updated = 0

        for item in schedule:
            activity_id = (
                get_activity_id(
                    conn,
                    item[
                        "name"
                    ],
                )
            )

            action, session_id = (
                upsert_session(
                    conn,

                    activity_id=
                        activity_id,

                    activity_date=
                        item[
                            "date"
                        ].isoformat(),

                    start_time=
                        item[
                            "start"
                        ],

                    end_time=
                        item[
                            "end"
                        ],

                    capacity=
                        item[
                            "capacity"
                        ],

                    registered_count=
                        item[
                            "registered"
                        ],

                    registration_deadline=
                        item[
                            "deadline"
                        ],

                    status=
                        item[
                            "status"
                        ],
                )
            )

            if action == "inserted":
                inserted += 1

            else:
                updated += 1

            print(
                f"{action:8s}",
                f"session_id={session_id}",
                item["date"],
                item["start"],
                item["name"],
            )

        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()

    print()
    print(
        "刷新完成"
    )

    print(
        "新增:",
        inserted,
    )

    print(
        "更新:",
        updated,
    )

    print(
        "未删除任何历史场次、"
        "参加意愿或工作人员通知"
    )


if __name__ == "__main__":
    main()

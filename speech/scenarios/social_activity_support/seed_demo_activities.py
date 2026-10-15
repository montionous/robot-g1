#!/usr/bin/env python3

from __future__ import annotations

import sqlite3
from datetime import date, timedelta

from init_activity_db import (
    DB_PATH,
    init_db,
)


def deadline(
    day,
    clock,
):
    return (
        f"{day.isoformat()}"
        f"T{clock}:00"
    )


def main():

    init_db()

    today = date.today()

    tomorrow = (
        today
        + timedelta(days=1)
    )

    activities = [
        {
            "name":
                "健康知识讲座",

            "category":
                "health",

            "description":
                "介绍日常健康管理和生活保健知识。",

            "tags":
                "健康,讲座,保健",

            "organizer":
                "李医生",

            "location":
                "一楼健康教室",

            "requires_registration":
                0,

            "notes":
                "活动过程中可以现场提问。",
        },

        {
            "name":
                "书法交流",

            "category":
                "culture",

            "description":
                "一起练习书法并交流作品。",

            "tags":
                "书法,文化,交流",

            "organizer":
                "陈老师",

            "location":
                "二楼书画室",

            "requires_registration":
                1,

            "notes":
                "活动室提供基础书写用品。",
        },

        {
            "name":
                "棋牌交流",

            "category":
                "social",

            "description":
                "老人一起进行象棋、扑克等轻松交流活动。",

            "tags":
                "棋牌,象棋,聊天,社交,交流",

            "organizer":
                "周老师",

            "location":
                "二楼棋牌室",

            "requires_registration":
                1,

            "notes":
                "目前人数较多。",
        },

        {
            "name":
                "下午茶话会",

            "category":
                "social",

            "description":
                "大家一起喝茶、聊天，认识其他老人。",

            "tags":
                "聊天,交友,社交,茶话会,交流",

            "organizer":
                "王老师",

            "location":
                "二楼活动室",

            "requires_registration":
                1,

            "notes":
                "建议提前十分钟到场。",
        },

        {
            "name":
                "集体唱歌",

            "category":
                "music",

            "description":
                "大家一起演唱经典歌曲和熟悉的老歌。",

            "tags":
                "唱歌,合唱,音乐,老歌,社交",

            "organizer":
                "赵老师",

            "location":
                "三楼多功能厅",

            "requires_registration":
                0,

            "notes":
                "不需要专业唱歌基础。",
        },

        {
            "name":
                "手工兴趣小组",

            "category":
                "hobby",

            "description":
                "进行简单手工制作和作品交流。",

            "tags":
                "手工,兴趣,交流",

            "organizer":
                "孙老师",

            "location":
                "二楼手工室",

            "requires_registration":
                1,

            "notes":
                "材料由活动室统一准备。",
        },

        {
            "name":
                "集体观影",

            "category":
                "movie",

            "description":
                "大家一起观看经典影片。",

            "tags":
                "电影,观影,娱乐,集体",

            "organizer":
                "刘老师",

            "location":
                "一楼放映室",

            "requires_registration":
                0,

            "notes":
                "无需提前报名。",
        },

        {
            "name":
                "戏曲欣赏",

            "category":
                "opera",

            "description":
                "一起欣赏经典戏曲选段。",

            "tags":
                "戏曲,京剧,黄梅戏,娱乐",

            "organizer":
                "钱老师",

            "location":
                "三楼多功能厅",

            "requires_registration":
                0,

            "notes":
                "本场活动临时取消。",
        },
    ]


    with sqlite3.connect(
        DB_PATH
    ) as conn:

        conn.execute(
            "PRAGMA foreign_keys = ON"
        )

        # 只清理本场景自己的 Demo 数据
        conn.execute(
            "DELETE FROM staff_notification"
        )

        conn.execute(
            "DELETE FROM social_activity_interest"
        )

        conn.execute(
            "DELETE FROM social_activity_session"
        )

        conn.execute(
            "DELETE FROM social_activity"
        )

        activity_ids = {}

        for item in activities:

            cursor = conn.execute(
                """
                INSERT INTO social_activity (
                    name,
                    category,
                    description,
                    tags,
                    organizer,
                    location,
                    requires_registration,
                    notes,
                    enabled
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
                """,
                (
                    item[
                        "name"
                    ],

                    item[
                        "category"
                    ],

                    item[
                        "description"
                    ],

                    item[
                        "tags"
                    ],

                    item[
                        "organizer"
                    ],

                    item[
                        "location"
                    ],

                    item[
                        "requires_registration"
                    ],

                    item[
                        "notes"
                    ],
                ),
            )

            activity_ids[
                item["name"]
            ] = cursor.lastrowid


        sessions = [
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

            # 明天再准备两场，
            # 用于测试“明天有什么活动”
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


        for item in sessions:

            conn.execute(
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
                    activity_ids[
                        item["name"]
                    ],

                    item[
                        "date"
                    ].isoformat(),

                    item[
                        "start"
                    ],

                    item[
                        "end"
                    ],

                    item[
                        "capacity"
                    ],

                    item[
                        "registered"
                    ],

                    item[
                        "deadline"
                    ],

                    item[
                        "status"
                    ],
                ),
            )

        conn.commit()


    print(
        "Demo 活动初始化完成"
    )

    print(
        "今天:",
        today.isoformat(),
    )

    print(
        "明天:",
        tomorrow.isoformat(),
    )

    print(
        "活动:",
        len(activities),
    )

    print(
        "场次:",
        len(sessions),
    )


if __name__ == "__main__":
    main()

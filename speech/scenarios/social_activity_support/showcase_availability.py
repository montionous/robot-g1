#!/usr/bin/env python3

from __future__ import annotations

from datetime import date, datetime


def date_label(
    date_text,
):
    day = date.fromisoformat(
        str(date_text)
    )

    delta = (
        day
        - date.today()
    ).days

    if delta == 0:
        return "今天"

    if delta == 1:
        return "明天"

    if delta == 2:
        return "后天"

    return (
        f"{day.month}月"
        f"{day.day}日"
    )


def time_label(
    time_text,
):
    hour_text, minute_text = (
        str(time_text)[:5]
        .split(":")
    )

    hour = int(hour_text)
    minute = int(minute_text)

    if hour < 12:
        period = "上午"

    elif hour < 18:
        period = "下午"

    else:
        period = "晚上"

    display_hour = hour % 12

    if display_hour == 0:
        display_hour = 12

    if minute == 0:
        minute_part = ""

    elif minute == 30:
        minute_part = "半"

    else:
        minute_part = (
            f"{minute}分"
        )

    return (
        f"{period}"
        f"{display_hour}点"
        f"{minute_part}"
    )


def registration_deadline_passed(
    item,
):
    if not item.get(
        "requires_registration"
    ):
        return False

    deadline = item.get(
        "registration_deadline"
    )

    if not deadline:
        return False

    try:
        deadline_dt = (
            datetime.fromisoformat(
                str(deadline)
            )
        )

    except ValueError:
        return False

    return (
        datetime.now()
        >= deadline_dt
    )


def unavailable_reason(
    item,
):
    """
    返回不能参加的明确原因。

    None 表示从活动状态上看可以参加。
    """

    status = str(
        item.get(
            "status",
            "",
        )
    )

    if status == "cancelled":
        return "已经取消了"

    if status == "full":
        return "已经满员了"

    if status == "closed":
        return "报名已经截止了"

    capacity = item.get(
        "capacity"
    )

    registered = (
        item.get(
            "registered_count",
            0,
        )
        or 0
    )

    if (
        capacity is not None
        and registered
        >= capacity
    ):
        return "已经满员了"

    if registration_deadline_passed(
        item
    ):
        return "已经超过报名时间了"

    return None


def next_available_session(
    repo,
    item,
):
    """
    查询同一活动之后第一场真正可参加的场次。
    """

    after_date = item[
        "activity_date"
    ]

    after_time = item[
        "start_time"
    ]

    # 正常演示数据不会很多。
    # 循环是为了防止后面出现
    # status=open 但实际报名已截止的场次。
    for _ in range(20):

        candidate = (
            repo.get_next_session(
                activity_id=
                    item[
                        "activity_id"
                    ],
                after_date=
                    after_date,
                after_time=
                    after_time,
                only_available=True,
            )
        )

        if candidate is None:
            return None

        if (
            unavailable_reason(
                candidate
            )
            is None
        ):
            return candidate

        after_date = candidate[
            "activity_date"
        ]

        after_time = candidate[
            "start_time"
        ]

    return None


def build_unavailable_reply(
    repo,
    item,
):
    """
    当前场次不可参加时生成确定性回复。

    时间、地点、状态全部来自数据库，
    不让大模型自行生成。
    """

    reason = unavailable_reason(
        item
    )

    if reason is None:
        return None

    current_when = (
        date_label(
            item[
                "activity_date"
            ]
        )
        + time_label(
            item[
                "start_time"
            ]
        )
    )

    reply = (
        f"{current_when}的"
        f"{item['name']}"
        f"{reason}，"
        "所以这场暂时不能参加。"
    )

    next_item = (
        next_available_session(
            repo,
            item,
        )
    )

    if next_item is None:

        return (
            reply
            + "目前还没有查到"
            + f"{item['name']}"
            + "的下一场安排。"
        )

    next_when = (
        date_label(
            next_item[
                "activity_date"
            ]
        )
        + time_label(
            next_item[
                "start_time"
            ]
        )
    )

    return (
        reply
        + f"下一场是{next_when}，"
        + f"地点在"
        + f"{next_item['location']}。"
    )

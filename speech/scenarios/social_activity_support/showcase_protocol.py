#!/usr/bin/env python3

from __future__ import annotations


# =========================================================
# 状态
# =========================================================

WAIT_QUERY = "wait_query"
WAIT_SELECT = "wait_select"
SELECTED_ACTIVITY = "selected_activity"
WAIT_CONFIRM = "wait_confirm"
WAIT_END = "wait_end"
DONE = "done"


# =========================================================
# 意图
# =========================================================

QUERY = "query"
SELECT = "select"

ASK_TIME = "ask_time"
ASK_LOCATION = "ask_location"
ASK_AVAILABILITY = "ask_availability"
ASK_REGISTRATION = "ask_registration"

REPEAT_DETAILS = "repeat_details"
JOIN = "join"

CONFIRM_YES = "confirm_yes"
CONFIRM_NO = "confirm_no"

END = "end"
OTHER = "other"


ALL_INTENTS = {
    QUERY,
    SELECT,
    ASK_TIME,
    ASK_LOCATION,
    ASK_AVAILABILITY,
    ASK_REGISTRATION,
    REPEAT_DETAILS,
    JOIN,
    CONFIRM_YES,
    CONFIRM_NO,
    END,
    OTHER,
}


# =========================================================
# 每个状态只允许这些意图
# =========================================================

ALLOWED_BY_STATE = {
    WAIT_QUERY: {
        QUERY,
        END,
    },

    WAIT_SELECT: {
        QUERY,
        SELECT,
        END,
    },

    SELECTED_ACTIVITY: {
        QUERY,
        ASK_TIME,
        ASK_LOCATION,
        ASK_AVAILABILITY,
        ASK_REGISTRATION,
        REPEAT_DETAILS,
        JOIN,
        END,
    },

    WAIT_CONFIRM: {
        CONFIRM_YES,
        CONFIRM_NO,
        END,
    },

    WAIT_END: {
        END,
    },

    DONE: set(),
}


# =========================================================
# 固定播报
# =========================================================

OPENING = (
    "您好，我可以帮您看看今天或明天"
    "有什么社区集体活动。"
)

END_REPLY = (
    "好的，那这次活动咨询就先到这里。"
    "需要的时候您再叫我。"
)


DECISION_MESSAGES = {
    QUERY:
        "您正在查询社区集体活动。",

    SELECT:
        "您对其中一个活动感兴趣。",

    ASK_TIME:
        "您正在询问活动时间。",

    ASK_LOCATION:
        "您正在询问活动地点。",

    ASK_AVAILABILITY:
        "您正在询问活动参加人数情况。",

    ASK_REGISTRATION:
        "您正在询问活动报名要求。",

    REPEAT_DETAILS:
        "您希望再次了解当前活动的信息。",

    JOIN:
        "您表示希望参加当前活动。",

    CONFIRM_YES:
        "您确认登记参加当前活动。",

    CONFIRM_NO:
        "您暂时不登记当前活动。",

    END:
        "您希望结束这次活动咨询。",
}

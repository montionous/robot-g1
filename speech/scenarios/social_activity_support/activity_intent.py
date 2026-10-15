#!/usr/bin/env python3

from __future__ import annotations

import re
from datetime import date, timedelta


def compact(text):

    return re.sub(
        r"[\s，,。！？!?、：:]",
        "",
        str(text or ""),
    )


def classify_action(
    text,
):

    value = compact(
        text
    )


    if any(
        word in value
        for word in [
            "不想参加",
            "不参加了",
            "不去了",
            "算了",
            "不用了",
            "不感兴趣",
            "先这样",
        ]
    ):
        return "decline"


    if any(
        word in value
        for word in [
            "我要参加",
            "我想参加",
            "帮我报名",
            "我要报名",
            "参加这个",
            "我就去这个",
            "我想去",
        ]
    ):
        return "join"


    if any(
        word in value
        for word in [
            "还有位置吗",
            "还有名额吗",
            "有位置吗",
            "有名额吗",
            "满了吗",
            "还有几个位置",
            "还剩几个名额",
        ]
    ):
        return "ask_availability"


    if any(
        word in value
        for word in [
            "几点",
            "什么时候",
            "什么时间",
            "几点开始",
        ]
    ):
        return "ask_time"


    if any(
        word in value
        for word in [
            "在哪里",
            "在哪儿",
            "在哪",
            "什么地方",
            "地点",
        ]
    ):
        return "ask_location"


    if any(
        word in value
        for word in [
            "要报名吗",
            "需要报名吗",
            "要不要报名",
            "怎么报名",
        ]
    ):
        return "ask_registration"


    if any(
        word in value
        for word in [
            "还有别的吗",
            "还有其他的吗",
            "还有吗",
            "再推荐几个",
            "换几个",
            "别的活动",
        ]
    ):
        return "more"


    if any(
        word in value
        for word in [
            "第一个",
            "第1个",
            "第一个活动",
            "第二个",
            "第2个",
            "第三个",
            "第3个",
            "唱歌那个",
            "茶话会那个",
            "聊天那个",
            "讲座那个",
            "电影那个",
            "观影那个",
            "书法那个",
            "棋牌那个",
            "手工那个",
            "戏曲那个",
            "下午那个",
            "上午那个",
            "晚上那个",
        ]
    ):
        return "select"


    if value in [
        "对",
        "是",
        "是的",
        "没错",
        "确定",
        "好的",
        "好",
        "可以",
        "行",
    ]:
        return "confirm_yes"


    if value in [
        "不",
        "不是",
        "不要",
        "不对",
        "不了",
    ]:
        return "confirm_no"


    activity_words = [
        "活动",
        "社区",
        "唱歌",
        "合唱",
        "聊天",
        "聊聊天",
        "讲座",
        "健康",
        "电影",
        "观影",
        "戏曲",
        "京剧",
        "黄梅戏",
        "书法",
        "棋牌",
        "象棋",
        "手工",
        "茶话会",
        "出去",
    ]


    if any(
        word in value
        for word in activity_words
    ):
        return "query"


    return "unknown"


def parse_query_filters(
    text,
):

    value = compact(
        text
    )

    today = date.today()

    target_date = today

    if "明天" in value:

        target_date = (
            today
            + timedelta(days=1)
        )


    period = None

    if any(
        word in value
        for word in [
            "上午",
            "早上",
            "早晨",
        ]
    ):
        period = "morning"

    elif any(
        word in value
        for word in [
            "下午",
            "午后",
        ]
    ):
        period = "afternoon"

    elif any(
        word in value
        for word in [
            "晚上",
            "今晚",
            "夜里",
        ]
    ):
        period = "evening"


    category = None
    keyword = None


    if any(
        word in value
        for word in [
            "唱歌",
            "合唱",
            "音乐",
        ]
    ):
        category = "music"


    elif any(
        word in value
        for word in [
            "聊天",
            "聊聊天",
            "交朋友",
            "交友",
            "和大家",
        ]
    ):
        category = "social"


    elif any(
        word in value
        for word in [
            "健康",
            "讲座",
            "保健",
        ]
    ):
        category = "health"


    elif any(
        word in value
        for word in [
            "电影",
            "观影",
        ]
    ):
        category = "movie"


    elif any(
        word in value
        for word in [
            "戏曲",
            "京剧",
            "黄梅戏",
        ]
    ):
        category = "opera"


    elif "书法" in value:

        keyword = "书法"


    elif any(
        word in value
        for word in [
            "棋牌",
            "象棋",
        ]
    ):
        keyword = "棋牌"


    elif "手工" in value:

        keyword = "手工"


    elif "茶话会" in value:

        keyword = "茶话会"


    return {
        "activity_date":
            target_date.isoformat(),

        "period":
            period,

        "category":
            category,

        "keyword":
            keyword,
    }


def ordinal_index(
    text,
):

    value = compact(
        text
    )

    if any(
        x in value
        for x in [
            "第一个",
            "第1个",
        ]
    ):
        return 0

    if any(
        x in value
        for x in [
            "第二个",
            "第2个",
        ]
    ):
        return 1

    if any(
        x in value
        for x in [
            "第三个",
            "第3个",
        ]
    ):
        return 2

    return None


if __name__ == "__main__":

    tests = [
        "今天有什么活动吗",
        "社区有没有活动",
        "我想出去和大家聊聊天",
        "今天有没有唱歌活动",
        "下午有什么活动",
        "明天有什么活动",
        "第一个",
        "唱歌那个",
        "几点开始",
        "在哪里",
        "还有位置吗",
        "我要参加",
        "不想参加了",
    ]

    for text in tests:

        print(
            text,
            "->",
            classify_action(text),
            parse_query_filters(text),
        )

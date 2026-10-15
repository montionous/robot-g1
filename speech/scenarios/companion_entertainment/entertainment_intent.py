#!/usr/bin/env python3

from __future__ import annotations

import re


STOP_WORDS = [
    "不听了",
    "不听啦",
    "不用了",
    "别放了",
    "关闭音乐",
    "关闭播放",
    "停止播放",
    "停一下",
    "停止",
    "停了吧",
    "关掉",
    "结束",
]


NEXT_WORDS = [
    "换一个",
    "换一首",
    "换首",
    "下一首",
    "下一个",
    "再换一个",
    "再换一首",
    "换一段",
]


CONTINUE_WORDS = [
    "继续",
    "继续听",
    "还想听",
    "再听一个",
]


MUSIC_WORDS = [
    "音乐",
    "歌曲",
    "听歌",
    "放歌",
]


NEWS_WORDS = [
    "新闻",
    "体育新闻",
    "新闻简讯",
    "资讯",
]


OPERA_WORDS = [
    "戏曲",
    "京剧",
    "黄梅戏",
    "越剧",
    "豫剧",
    "评剧",
    "秦腔",
    "唱戏",
]


GENERIC_ENTERTAINMENT_WORDS = [
    "有点无聊",
    "好无聊",
    "无聊",
    "放点东西",
    "听点东西",
    "有什么节目",
    "有没有节目",
    "放个节目",
]


# 按长度从长到短处理，避免“我想听”抢先匹配
REQUEST_PREFIXES = [
    "机器人给我播放一下",
    "机器人给我放一下",
    "机器人我想听一下",

    "我想要听一下",
    "我想听一下",
    "给我播放一下",
    "给我放一下",

    "我想要听",
    "我想听",
    "给我播放",
    "给我放点",
    "给我放",

    "播放一下",
    "放一下",
    "听一下",

    "给我换成",
    "给我换个",
    "给我换一个",

    "切换到",
    "切换成",
    "换成",
    "换到",

    "放点",
    "听点",
    "来点",

    "放一首",
    "听一首",
    "来一首",

    "放首",
    "听首",

    "来一段",
    "来一个",
    "来个",

    "播放",
    "放",
    "听",
]


REQUEST_SUFFIXES = [
    "可以吗",
    "好不好",
    "好吗",
    "行吗",
    "吧",
    "一下",
]


def compact(text):
    return re.sub(
        r"[\s，,。！？!?、：:]",
        "",
        str(text or ""),
    )


def detect_category(text):
    value = compact(text)

    if any(
        word in value
        for word in OPERA_WORDS
    ):
        return "opera"

    if any(
        word in value
        for word in NEWS_WORDS
    ):
        return "news"

    if any(
        word in value
        for word in MUSIC_WORDS
    ):
        return "music"

    return None


def remove_prefix(text):
    value = text

    changed = True

    while changed:
        changed = False

        for prefix in sorted(
            REQUEST_PREFIXES,
            key=len,
            reverse=True,
        ):
            if value.startswith(prefix):
                value = value[len(prefix):]
                changed = True
                break

    return value


def remove_suffix(text):
    value = text

    changed = True

    while changed:
        changed = False

        for suffix in sorted(
            REQUEST_SUFFIXES,
            key=len,
            reverse=True,
        ):
            if value.endswith(suffix):
                value = value[:-len(suffix)]
                changed = True
                break

    return value


def extract_target(text):
    value = compact(text)

    # 去掉开头的“机器人”
    if value.startswith("机器人"):
        value = value[len("机器人"):]

    value = remove_prefix(value)

    # 去掉类别词，但保留真正曲名
    category_words = sorted(
        set(
            MUSIC_WORDS
            + NEWS_WORDS
            + OPERA_WORDS
        ),
        key=len,
        reverse=True,
    )

    for word in category_words:
        value = value.replace(
            word,
            "",
        )

    value = remove_prefix(value)
    value = remove_suffix(value)

    return value.strip()


def looks_like_request(text):
    value = compact(text)

    if value.startswith("机器人"):
        value = value[len("机器人"):]

    return any(
        value.startswith(prefix)
        for prefix in REQUEST_PREFIXES
    )


def classify_command(
    text,
    *,
    current_category=None,
):
    value = compact(text)

    if not value:
        return {
            "action": "unknown",
            "category": None,
            "query": None,
        }

    # 1. 停止
    if any(
        word in value
        for word in STOP_WORDS
    ):
        return {
            "action": "stop",
            "category": current_category,
            "query": None,
        }

    # 2. 下一首
    if any(
        word in value
        for word in NEXT_WORDS
    ):
        return {
            "action": "next",
            "category": current_category,
            "query": None,
        }

    # 3. 继续
    if any(
        word in value
        for word in CONTINUE_WORDS
    ):
        return {
            "action": "continue",
            "category": current_category,
            "query": None,
        }

    # 4. 无聊 / 节目请求
    if any(
        word in value
        for word in GENERIC_ENTERTAINMENT_WORDS
    ):
        return {
            "action": "ask_category",
            "category": None,
            "query": None,
        }

    # 5. 判断音乐 / 新闻 / 戏曲
    category = detect_category(value)

    target = extract_target(value)

    # 有明确类别，但没有具体曲名
    #
    # 放点音乐
    # 听新闻
    # 换成戏曲
    # 来个京剧
    if (
        category is not None
        and not target
    ):
        return {
            "action": "play_category",
            "category": category,
            "query": None,
        }

    # 有类别，也有具体内容
    #
    # 我想听京剧贵妃醉酒
    # 放黄梅戏女驸马
    if (
        category is not None
        and target
    ):
        return {
            "action": "play_query",
            "category": category,
            "query": target,
        }

    # 没说类别，但明显是点播请求
    #
    # 我想听甜蜜蜜
    # 播放小城故事
    # 我想听贵妃醉酒
    if looks_like_request(value):

        target = extract_target(value)

        if target:
            return {
                "action": "play_query",
                "category": current_category,
                "query": target,
            }

    # 已经在某个类别中，可以直接说名字
    #
    # 当前 music:
    #   “甜蜜蜜”
    #
    # 当前 opera:
    #   “贵妃醉酒”
    if (
        current_category is not None
        and len(value) >= 2
    ):
        return {
            "action": "play_query",
            "category": current_category,
            "query": value,
        }

    return {
        "action": "unknown",
        "category": None,
        "query": None,
    }


if __name__ == "__main__":

    tests = [
        (
            "有点无聊",
            None,
        ),
        (
            "放点音乐",
            None,
        ),
        (
            "给我放点音乐",
            None,
        ),
        (
            "听新闻",
            None,
        ),
        (
            "我想听新闻",
            None,
        ),
        (
            "换成戏曲",
            "music",
        ),
        (
            "来个京剧",
            "music",
        ),
        (
            "我想听甜蜜蜜",
            None,
        ),
        (
            "播放小城故事",
            None,
        ),
        (
            "我想听贵妃醉酒",
            "opera",
        ),
        (
            "我想听京剧贵妃醉酒",
            "music",
        ),
        (
            "换一个",
            "music",
        ),
        (
            "下一首",
            "opera",
        ),
        (
            "不听了",
            "music",
        ),
    ]

    for text, category in tests:

        result = classify_command(
            text,
            current_category=category,
        )

        print(
            f"{text:<18}",
            "->",
            result,
        )

from __future__ import annotations

import json
from pathlib import Path


SCENE_DIR = Path(__file__).resolve().parent

CATALOG_PATH = (
    SCENE_DIR
    / "content_catalog.json"
)


CATEGORY_LABELS = {
    "music": "音乐",
    "news": "新闻",
    "opera": "戏曲",
}


CATEGORY_KEYWORDS = {
    "music": [
        "音乐",
        "听歌",
        "歌曲",
        "歌",
        "轻音乐",
        "放首歌",
        "放点歌",
    ],

    "news": [
        "新闻",
        "资讯",
        "体育新闻",
        "体育资讯",
        "简讯",
    ],

    "opera": [
        "戏曲",
        "京剧",
        "秦腔",
        "豫剧",
        "越剧",
        "黄梅戏",
        "唱戏",
    ],
}


ENTERTAINMENT_WORDS = [
    "无聊",
    "娱乐",
    "节目",
    "放点什么",
    "听点什么",
    "陪我听",
    "有东西听吗",
]


STOP_WORDS = [
    "不听了",
    "不用了",
    "算了",
    "停一下",
    "停",
    "停止",
    "关掉",
    "结束",
]


NEXT_WORDS = [
    "换一个",
    "下一个",
    "换一首",
    "换首",
    "换一个节目",
    "换一段",
]


CONTINUE_WORDS = [
    "继续",
    "还想听",
    "再听一个",
    "再来一个",
    "再放一个",
    "接着听",
]


def normalize_text(text):
    return (
        str(text or "")
        .replace(" ", "")
        .replace("，", "")
        .replace(",", "")
        .replace("。", "")
        .replace("？", "")
        .replace("?", "")
        .strip()
    )


def detect_category(text):
    text = normalize_text(text)

    for category, words in (
        CATEGORY_KEYWORDS.items()
    ):
        if any(
            word in text
            for word in words
        ):
            return category

    return None


def is_entertainment_request(text):
    text = normalize_text(text)

    if detect_category(text):
        return True

    return any(
        word in text
        for word in ENTERTAINMENT_WORDS
    )


def classify_followup(
    text,
    *,
    current_category=None,
):
    text = normalize_text(text)

    if not text:
        return {
            "action": "unknown",
            "category": None,
        }

    if any(
        word in text
        for word in STOP_WORDS
    ):
        return {
            "action": "stop",
            "category": None,
        }

    category = detect_category(text)

    if (
        category is not None
        and category != current_category
    ):
        return {
            "action": "switch",
            "category": category,
        }

    if any(
        word in text
        for word in NEXT_WORDS
    ):
        return {
            "action": "next",
            "category":
                current_category,
        }

    if any(
        word in text
        for word in CONTINUE_WORDS
    ):
        return {
            "action": "continue",
            "category":
                current_category,
        }

    if category == current_category:
        return {
            "action": "continue",
            "category":
                current_category,
        }

    return {
        "action": "unknown",
        "category": None,
    }


def load_catalog():
    with CATALOG_PATH.open(
        "r",
        encoding="utf-8",
    ) as f:
        return json.load(f)


class EntertainmentSession:

    def __init__(self):
        self.catalog = load_catalog()

        self.indices = {
            "music": 0,
            "news": 0,
            "opera": 0,
        }


    def get_items(
        self,
        category,
        *,
        existing_only=True,
    ):
        raw_items = (
            self.catalog
            .get(
                category,
                []
            )
        )

        items = []

        for raw in raw_items:
            if not raw.get(
                "enabled",
                True,
            ):
                continue

            item = dict(raw)

            path = (
                SCENE_DIR
                / item["path"]
            )

            item[
                "full_path"
            ] = str(
                path.resolve()
            )

            item[
                "exists"
            ] = path.exists()

            if (
                existing_only
                and not path.exists()
            ):
                continue

            items.append(
                item
            )

        return items


    def next_item(
        self,
        category,
    ):
        items = self.get_items(
            category,
            existing_only=True,
        )

        if not items:
            return None

        index = (
            self.indices
            .get(
                category,
                0,
            )
        )

        item = items[
            index
            % len(items)
        ]

        self.indices[
            category
        ] = (
            index + 1
        )

        return item

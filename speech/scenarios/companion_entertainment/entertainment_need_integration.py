#!/usr/bin/env python3
from __future__ import annotations

import re
import sqlite3
from uuid import uuid4

from elder_need_registry import (
    create_need,
    elderly_is_enabled,
    get_elder_need_history,
    update_need,
)
from local_media_library import clean_search_query, normalize


SCENE = "COMPANION_ENTERTAINMENT"

LABELS = {
    "music": "音乐",
    "opera": "戏曲",
    "news": "新闻",
}


def is_explicit_title_request(query, title, category):
    """
    保守判断老人是否明确提到了作品名称。

    例如：
      甜蜜蜜 -> 邓丽君-甜蜜蜜：明确点歌
      邓丽君 -> 邓丽君-甜蜜蜜：仅歌手请求
      贵妃醉酒 -> 京剧-贵妃醉酒-海岛冰轮初转腾：明确点戏

    不能确定时按普通关键词请求保存，
    避免把自动选中的作品记为主动偏好。
    """
    if category not in ("music", "opera"):
        return False

    cleaned = clean_search_query(query)
    title = str(title or "").strip()

    if not cleaned or not title:
        return False

    segments = [
        normalize(part)
        for part in re.split(r"[-—–_]+", title)
        if normalize(part)
    ]

    if not segments:
        return False

    if len(segments) == 1:
        candidates = segments
    elif category == "music":
        # 通常是“歌手-歌曲”格式。
        candidates = segments[-1:]
    else:
        # 通常是“剧种-剧目-唱段”格式。
        candidates = segments[1:]

    return any(
        part == cleaned
        or (
            len(part) >= 3
            and part in cleaned
        )
        for part in candidates
    )


class EntertainmentNeedSession:

    def __init__(self, *, elderly_id=None, library, record=False):
        self.library = library
        self.session_id = uuid4().hex
        self.round_no = 0
        self.elderly_id = None
        self.record = False

        if elderly_id is None:
            print("共享需求：未指定老人ID，暂不关联老人", flush=True)
            return

        try:
            if not elderly_is_enabled(
                elderly_id
            ):
                print(f"共享需求：老人ID {elderly_id} 不存在或未启用", flush=True)
                return

        except (ValueError, sqlite3.Error) as exc:
            print(f"共享需求：身份校验失败 {exc!r}", flush=True)
            return

        self.elderly_id = int(elderly_id)
        self.record = bool(record)

        print(
            f"共享需求：elderly_id={self.elderly_id} "
            f"写入={'开启' if self.record else '关闭（只读）'}",
            flush=True,
        )

    def preferred_item(self, category):
        """按主动点播次数和最近一次成功播放选择本地可用内容。"""

        if self.elderly_id is None or category not in {"music", "opera"}:
            return None

        try:
            available = {
                normalize(item.title): item
                for item in self.library.list_items(category)
            }

            scores = {}

            for position, row in enumerate(
                get_elder_need_history(
                    self.elderly_id,
                    need_category="entertainment",
                    need_code=f"play_{category}",
                    status="completed",
                    limit=100,
                )
            ):
                details = row.get("details") or {}

                if details.get("request_mode") != "explicit":
                    continue

                title = details.get("title")

                if not isinstance(title, str) or not title.strip():
                    continue

                item_key = normalize(title)

                if item_key not in available:
                    continue

                score = scores.setdefault(
                    item_key,
                    {
                        "count": 0,
                        "last_position": position,
                    },
                )
                score["count"] += 1
                score["last_position"] = min(
                    score["last_position"],
                    position,
                )

            if scores:
                preferred_key = min(
                    scores,
                    key=lambda key: (
                        -scores[key]["count"],
                        scores[key]["last_position"],
                        key,
                    ),
                )
                item = available[preferred_key]
                print(
                    "历史点播优先："
                    f"{category} / {item.title} "
                    f"(成功点播 {scores[preferred_key]['count']} 次)",
                    flush=True,
                )
                return item

        except (sqlite3.Error, ValueError, TypeError) as exc:
            print(
                f"历史点播读取失败，回退默认顺序：{exc!r}",
                flush=True,
            )

        return None

    def begin(self, *, raw_text, command, result):
        """有效需求确认之后、判断播报之前创建记录。"""

        if not self.record or not command or not raw_text:
            return None

        action = command.get("action")
        result_action = result.get("action") if result else None

        if action not in {
            "play_query",
            "play_category",
            "next",
            "stop",
        }:
            return None

        if result_action in {"unknown", "ignore"}:
            return None

        category = (
            command.get("category")
            or (result or {}).get("category")
        )

        if action == "stop":
            need_code = "stop_entertainment"
            mode = "stop"
            summary = "老人要求结束娱乐播放"

        else:
            if category not in LABELS:
                return None

            need_code = f"play_{category}"

            mode = {
                "play_query": "query",
                "play_category": "category",
                "next": "next",
            }[action]

            summary = f"老人要求播放{LABELS[category]}"

        play_item = (result or {}).get("play_item")

        # 只有明确点到作品名称才记录为 explicit。
        # 歌手、泛类别等关键词不升级为作品偏好。
        if mode == "query" and isinstance(play_item, dict):
            if is_explicit_title_request(
                query=command.get("query"),
                title=play_item.get("title"),
                category=category,
            ):
                mode = "explicit"

        details = {
            "request_mode": mode,
        }

        if category in LABELS:
            details["media_type"] = category

        if command.get("query"):
            details["requested_query"] = str(command["query"])

        if isinstance(play_item, dict) and play_item.get("title"):
            if mode == "explicit":
                details["title"] = play_item["title"]
                summary = (
                    f"老人主动点播{LABELS[category]}"
                    f"《{play_item['title']}》"
                )
            else:
                details["selected_title"] = play_item["title"]

        self.round_no += 1

        try:
            need = create_need(
                elderly_id=self.elderly_id,
                need_category="entertainment",
                need_code=need_code,
                summary=summary,
                raw_text=str(raw_text).strip(),
                priority="normal",
                status="in_progress",
                source_scene=SCENE,
                source_session_id=self.session_id,
                source_round_no=self.round_no,
                details=details,
                dedupe_key=(
                    f"entertainment:{self.session_id}:"
                    f"{self.round_no}:{need_code}"
                ),
                handled_by=SCENE,
            )

            print(
                f"共享需求创建：id={need['id']} {need_code}",
                flush=True,
            )
            return need["id"]

        except Exception as exc:
            print(
                f"共享需求写入异常（不影响娱乐）：{exc!r}",
                flush=True,
            )
            return None

    def finish(self, need_id, *, succeeded=True):
        if need_id is None:
            return

        try:
            update_need(
                need_id,
                status="completed" if succeeded else "failed",
                handled_by=SCENE,
            )

        except Exception as exc:
            print(
                f"共享需求状态更新异常：{exc!r}",
                flush=True,
            )

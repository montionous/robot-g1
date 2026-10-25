#!/usr/bin/env python3

from __future__ import annotations

import re
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path


SCENE_DIR = Path(__file__).resolve().parent

CONTENT_DIR = (
    SCENE_DIR
    / "content"
)


CATEGORY_DIRS = {
    "music":
        CONTENT_DIR / "music",

    "news":
        CONTENT_DIR / "news",

    "opera":
        CONTENT_DIR / "opera",
}


CATEGORY_LABELS = {
    "music": "音乐",
    "news": "新闻",
    "opera": "戏曲",
}


SUPPORTED_EXTENSIONS = {
    ".mp3",
    ".m4a",
    ".flac",
    ".mp4",
    ".wav",
    ".aac",
    ".ogg",
    ".opus",
}


@dataclass
class MediaItem:
    category: str
    path: Path
    title: str

    def as_dict(self):
        return {
            "category": self.category,
            "path": str(self.path),
            "title": self.title,
        }


def remove_order_prefix(text):
    return re.sub(
        r"^\s*\d+\s*[_\-.、 ]*\s*",
        "",
        str(text),
    )


def display_title(path: Path):
    return remove_order_prefix(
        path.stem
    )


def normalize(text):
    text = str(
        text or ""
    ).lower()

    text = remove_order_prefix(
        text
    )

    text = re.sub(
        r"[\s_\-.—·（）()"
        r"《》【】\[\]"
        r"，,。！？!?：:、]",
        "",
        text,
    )

    return text


def clean_search_query(text):
    text = str(
        text or ""
    ).strip()

    phrases = [
        "机器人",
        "我想听一下",
        "我想听",
        "我想要听",
        "给我播放一下",
        "给我播放",
        "给我放一下",
        "给我放",
        "播放一下",
        "播放",
        "放一下",
        "放一首",
        "放首",
        "听一下",
        "听一首",
        "听首",
        "来一首",
        "来一个",
        "来一段",
        "一首",
        "一段",
        "可以吗",
        "好吗",
        "吧",
    ]

    for phrase in phrases:
        text = text.replace(
            phrase,
            "",
        )

    category_words = [
        "音乐",
        "歌曲",
        "戏曲",
        "京剧",
        "黄梅戏",
        "越剧",
        "豫剧",
        "评剧",
        "秦腔",
        "新闻",
    ]

    for word in category_words:
        text = text.replace(
            word,
            "",
        )

    return normalize(
        text
    )


class LocalMediaLibrary:

    def __init__(self):
        self._audio_probe_cache = {}

        for directory in (
            CATEGORY_DIRS.values()
        ):
            directory.mkdir(
                parents=True,
                exist_ok=True,
            )


    def _has_audio(self, path):
        """Probe each file version once; extensions alone do not prove audio."""
        try:
            stat = path.stat()
            version = (stat.st_size, stat.st_mtime_ns)
            cached = self._audio_probe_cache.get(path)
            if cached is not None and cached[0] == version:
                return cached[1]
            result = subprocess.run(
                ["ffprobe", "-v", "error", "-select_streams", "a:0",
                 "-show_entries", "stream=sample_rate,channels", "-of", "json", str(path)],
                check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, timeout=3.0,
            )
            streams = json.loads(result.stdout).get("streams", [])
            playable = bool(streams and int(streams[0].get("sample_rate", 0)) > 0
                            and int(streams[0].get("channels", 0)) > 0)
            reason = "没有有效音频流" if not playable else ""
        except (OSError, subprocess.SubprocessError, ValueError, TypeError, AttributeError, IndexError) as exc:
            playable = False
            reason = type(exc).__name__
            # A disappearing file is excluded without caching a stale version.
            if "version" not in locals():
                return False
        self._audio_probe_cache[path] = (version, playable)
        if not playable:
            print(f"媒体不可用，跳过：{path.name}（{reason}）", flush=True)
        return playable


    def list_items(
        self,
        category,
    ):
        if category not in CATEGORY_DIRS:
            return []

        directory = (
            CATEGORY_DIRS[
                category
            ]
        )

        paths = [
            path
            for path
            in directory.iterdir()
            if (
                path.is_file()
                and path.suffix.lower()
                in SUPPORTED_EXTENSIONS
            )
        ]

        paths.sort(
            key=lambda p:
                p.name.lower()
        )

        paths = [path for path in paths if self._has_audio(path)]

        return [
            MediaItem(
                category=category,
                path=path.resolve(),
                title=display_title(
                    path
                ),
            )
            for path in paths
        ]


    def first(
        self,
        category,
    ):
        items = self.list_items(
            category
        )

        return (
            items[0]
            if items
            else None
        )


    def next_item(
        self,
        category,
        current_path=None,
    ):
        items = self.list_items(
            category
        )

        if not items:
            return None

        if current_path is None:
            return items[0]

        current_path = Path(
            current_path
        ).resolve()

        for index, item in enumerate(
            items
        ):
            if (
                item.path.resolve()
                == current_path
            ):
                return items[
                    (index + 1)
                    % len(items)
                ]

        return items[0]


    def search(
        self,
        query,
        *,
        category=None,
    ):
        cleaned = clean_search_query(
            query
        )

        if not cleaned:
            return []

        categories = (
            [category]
            if category
            else [
                "music",
                "opera",
                "news",
            ]
        )

        results = []

        for current_category in categories:

            for item in self.list_items(
                current_category
            ):

                candidate = normalize(
                    item.title
                )

                if (
                    cleaned
                    in candidate
                ):
                    score = 100.0

                elif (
                    candidate
                    in cleaned
                ):
                    score = 90.0

                else:
                    query_chars = set(
                        cleaned
                    )

                    if not query_chars:
                        continue

                    hits = sum(
                        1
                        for char
                        in query_chars
                        if char
                        in candidate
                    )

                    score = (
                        hits
                        / len(
                            query_chars
                        )
                    )

                    if score < 0.60:
                        continue

                results.append(
                    (
                        score,
                        item,
                    )
                )

        results.sort(
            key=lambda pair:
                pair[0],
            reverse=True,
        )

        return [
            item
            for _score, item
            in results
        ]


if __name__ == "__main__":

    library = LocalMediaLibrary()

    for category in (
        "music",
        "news",
        "opera",
    ):

        print()
        print(
            CATEGORY_LABELS[
                category
            ]
        )
        print("-" * 60)

        items = library.list_items(
            category
        )

        if not items:
            print("(空)")
            continue

        for index, item in enumerate(
            items,
            start=1,
        ):
            print(
                f"{index:02d}. "
                f"{item.title}"
            )
            print(
                f"    {item.path.name}"
            )

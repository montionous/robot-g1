#!/usr/bin/env python3

from __future__ import annotations

from local_media_library import (
    CATEGORY_LABELS,
    LocalMediaLibrary,
)

from entertainment_intent import (
    classify_command,
)


class EntertainmentController:

    def __init__(self):

        self.library = (
            LocalMediaLibrary()
        )

        self.current_category = None
        self.current_item = None
        self.active = True


    def _result(
        self,
        *,
        action,
        reply,
        play_item=None,
        stop_playback=False,
    ):

        return {
            "action":
                action,

            "reply":
                reply,

            "category":
                self.current_category,

            "current_item":
                (
                    self.current_item
                    .as_dict()
                    if self.current_item
                    else None
                ),

            "play_item":
                (
                    play_item
                    .as_dict()
                    if play_item
                    else None
                ),

            "stop_playback":
                stop_playback,

            "active":
                self.active,
        }


    def _play_item(
        self,
        item,
        *,
        prefix=None,
    ):

        self.current_category = (
            item.category
        )

        self.current_item = item

        label = CATEGORY_LABELS[
            item.category
        ]

        # 新闻标题可能来自内部文件名，
        # 不直接播报给老人。
        if item.category == "news":

            if prefix is None:
                reply = (
                    "好的，为您播放一则新闻。"
                )

            else:
                reply = (
                    "好的，为您换一则新闻。"
                )

        else:

            if prefix is None:
                prefix = (
                    f"好的，为您播放"
                    f"{label}，"
                )

            reply = (
                f"{prefix}"
                f"{item.title}。"
            )

        return self._result(
            action="play",
            reply=reply,
            play_item=item,
            stop_playback=True,
        )


    def play_category(
        self,
        category,
    ):

        item = self.library.first(
            category
        )
        selection_reason = "default"

        # 历史主动点播优先；无历史或不可用时保持原顺序。
        if category in ("music", "opera"):
            lookup = getattr(self, "preferred_item_lookup", None)

            if callable(lookup):
                try:
                    preferred = lookup(category)

                    if preferred is not None:
                        item = preferred
                        selection_reason = "history"

                except Exception as exc:
                    print(
                        f"历史点播偏好不可用: {exc!r}",
                        flush=True,
                    )

        if item is None:

            self.current_category = (
                category
            )

            return self._result(
                action="empty",
                reply=(
                    f"现在还没有准备好"
                    f"{CATEGORY_LABELS[category]}"
                    "内容。"
                ),
                stop_playback=True,
            )

        result = self._play_item(item)
        # Keep the reason tied to this selection; narration must not query a
        # second, potentially changed history snapshot after choosing a file.
        result["selection_reason"] = selection_reason
        return result


    def next_item(self):

        if self.current_category is None:

            return self._result(
                action="ask_category",
                reply=(
                    "您想听音乐、"
                    "新闻还是戏曲？"
                ),
            )

        item = (
            self.library
            .next_item(
                self.current_category,
                (
                    self.current_item.path
                    if self.current_item
                    else None
                ),
            )
        )

        if item is None:

            return self._result(
                action="empty",
                reply=(
                    "这个类别暂时"
                    "没有更多内容。"
                ),
            )

        return self._play_item(
            item,
            prefix="好的，给您换成",
        )


    def play_query(
        self,
        query,
        category=None,
    ):

        results = self.library.search(
            query,
            category=category,
        )

        if not results:

            return self._result(
                action="not_found",
                reply=(
                    f"我这里暂时没有找到"
                    f"“{query}”。"
                    "您可以换一个。"
                ),
            )

        item = results[0]

        return self._play_item(
            item,
            prefix="找到了，为您播放",
        )


    def stop(self):

        self.active = False

        return self._result(
            action="stop",
            reply=(
                "好的，那我们先不听了。"
                "需要的时候再告诉我。"
            ),
            stop_playback=True,
        )


    def handle_command(
        self,
        command,
    ):

        action = command[
            "action"
        ]

        if action == "stop":
            return self.stop()

        if action == "ask_category":

            return self._result(
                action="ask_category",
                reply=(
                    "您想听音乐、"
                    "新闻还是戏曲？"
                ),
            )

        if action == "play_category":

            category = command.get(
                "category"
            )

            if category not in (
                "music",
                "news",
                "opera",
            ):

                return self._result(
                    action="unknown",
                    reply=(
                        "我还不确定您想听"
                        "音乐、新闻还是戏曲。"
                    ),
                )

            return self.play_category(
                category
            )

        if action == "next":

            return self.next_item()

        if action == "continue":

            # “继续”表示保持当前内容继续播放，
            # 不能解释成“下一首”。
            #
            # 真正的暂停/恢复能力会由播放器层负责。
            if self.current_item is None:
                return self._result(
                    action="ask_category",
                    reply=(
                        "您想听音乐、"
                        "新闻还是戏曲？"
                    ),
                )

            return self._result(
                action="continue",
                reply=None,
                stop_playback=False,
            )

        if action == "play_query":

            query = command.get(
                "query"
            )

            if not query:

                return self._result(
                    action="unknown",
                    reply=(
                        "我还不确定您具体想听什么。"
                    ),
                )

            return self.play_query(
                query,
                category=command.get(
                    "category"
                ),
            )

        return self._result(
            action="unknown",
            reply=None,
        )


    def handle_text(
        self,
        text,
    ):

        command = classify_command(
            text,
            current_category=
                self.current_category,
        )

        return self.handle_command(
            command
        )

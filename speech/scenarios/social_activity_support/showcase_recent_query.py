#!/usr/bin/env python3

from __future__ import annotations

from showcase_availability import (
    build_unavailable_reply,
    date_label,
    time_label,
    unavailable_reason,
)


class RecentActivityQueryResolver:

    def __init__(
        self,
        repo,
        matcher,
    ):

        self.repo = repo
        self.matcher = matcher


    @staticmethod
    def _available_text(
        item,
    ):

        return (
            f"{date_label(item['activity_date'])}"
            f"{time_label(item['start_time'])}"
            f"有{item['name']}，"
            f"地点在{item['location']}。"
        )


    @staticmethod
    def _short_status(
        item,
    ):

        reason = (
            unavailable_reason(
                item
            )
        )

        if reason is None:
            return ""

        if "满员" in reason:
            return "，目前已经满员"

        if "报名" in reason:
            return "，目前报名已经截止"

        if "取消" in reason:
            return "，这场已经取消"

        return (
            "，目前暂时不能参加"
        )


    def resolve(
        self,
        text,
        *,
        days=7,
        list_limit=3,
    ):

        catalog = (
            self.repo
            .list_activities()
        )

        match = (
            self.matcher.match(
                text,
                catalog,
            )
        )

        # ---------------------------------------------
        # 1. 已经锁定数据库中的具体活动
        # ---------------------------------------------

        if match.get(
            "matched"
        ):

            activity = match[
                "activity"
            ]

            sessions = (
                self.repo
                .query_upcoming_sessions(
                    activity_id=
                        activity[
                            "activity_id"
                        ],
                    days=days,
                    include_cancelled=True,
                    limit=20,
                )
            )

            if not sessions:

                return {
                    "mode":
                        "specific_no_session",

                    "activity":
                        activity,

                    "session":
                        None,

                    "match":
                        match,

                    "reply":
                        (
                            "最近没有查到"
                            f"{activity['name']}"
                            "的场次安排。"
                        ),
                }

            session = sessions[0]

            reason = (
                unavailable_reason(
                    session
                )
            )

            if reason is not None:

                reply = (
                    build_unavailable_reply(
                        self.repo,
                        session,
                    )
                )

            else:

                reply = (
                    self._available_text(
                        session
                    )
                )

            return {
                "mode":
                    "specific",

                "activity":
                    activity,

                "session":
                    session,

                "match":
                    match,

                "reply":
                    reply,
            }


        # ---------------------------------------------
        # 2. 指定了某种活动，但数据库不存在
        # ---------------------------------------------

        if match.get(
            "specific_request"
        ):

            requested = (
                match.get(
                    "requested_activity"
                )
                or "这类"
            )

            return {
                "mode":
                    "specific_not_found",

                "activity":
                    None,

                "session":
                    None,

                "match":
                    match,

                "reply":
                    (
                        "最近没有查到"
                        f"{requested}"
                        "相关的社区活动。"
                    ),
            }


        # ---------------------------------------------
        # 3. 泛查询：最近有什么活动
        # ---------------------------------------------

        sessions = (
            self.repo
            .query_upcoming_sessions(
                days=days,
                include_cancelled=False,
                limit=50,
            )
        )

        if not sessions:

            return {
                "mode":
                    "generic_empty",

                "activity":
                    None,

                "session":
                    None,

                "match":
                    match,

                "reply":
                    (
                        "最近暂时没有查到"
                        "社区集体活动安排。"
                    ),
            }


        # 泛查询只推荐当前真正可以参加的活动。
        #
        # 满员、报名截止、取消等场次，
        # 不主动放进推荐列表。
        # 只有老人专门询问该活动时，
        # 才说明不能参加的原因和下一场时间。
        available_sessions = [
            item
            for item in sessions
            if unavailable_reason(
                item
            ) is None
        ]

        if not available_sessions:

            return {
                "mode":
                    "generic_empty",

                "activity":
                    None,

                "session":
                    None,

                "match":
                    match,

                "reply":
                    (
                        "最近暂时没有查到"
                        "可以参加的社区集体活动。"
                    ),
            }


        # 相同活动未来可能重复举行。
        # 泛查询时每种活动只推荐最近的一场。
        selected = []
        seen_activity_ids = set()

        for item in available_sessions:

            activity_id = item[
                "activity_id"
            ]

            if (
                activity_id
                in seen_activity_ids
            ):
                continue

            seen_activity_ids.add(
                activity_id
            )

            selected.append(
                item
            )

            if (
                len(selected)
                >= list_limit
            ):
                break


        # 按日期组织播报。
        #
        # 例如：
        # 今天下午3点有下午茶话会、
        # 下午3点半有集体唱歌、
        # 晚上7点有集体观影。
        #
        # 同一天只说一次“今天”。
        grouped = []

        for item in selected:

            current_date = item[
                "activity_date"
            ]

            if (
                not grouped
                or grouped[-1][0]
                != current_date
            ):
                grouped.append(
                    (
                        current_date,
                        [],
                    )
                )

            grouped[-1][1].append(
                item
            )


        date_parts = []

        for activity_date, items in grouped:

            item_parts = []

            for item in items:

                item_parts.append(
                    (
                        f"{time_label(item['start_time'])}"
                        f"有{item['name']}"
                    )
                )

            date_parts.append(
                (
                    f"{date_label(activity_date)}"
                    + "、".join(
                        item_parts
                    )
                )
            )


        reply = (
            "最近的活动有："
            + "；".join(
                date_parts
            )
            + "。您对哪个比较感兴趣？"
        )

        return {
            "mode":
                "generic_list",

            "activity":
                None,

            "session":
                None,

            "sessions":
                selected,

            "match":
                match,

            "reply":
                reply,
        }

#!/usr/bin/env python3

from __future__ import annotations

from datetime import date, datetime

from activity_intent import (
    classify_action,
    compact,
    ordinal_index,
    parse_query_filters,
)

from activity_repository import (
    ActivityRepository,
)


STATUS_LABELS = {
    "open":
        "可以参加",

    "full":
        "目前已满",

    "closed":
        "报名已经截止",

    "cancelled":
        "活动已经取消",
}


class ActivityController:

    def __init__(
        self,
        *,
        elder_id=1,
        elder_name="王大爷",
        repo=None,
    ):

        self.repo = (
            repo
            if repo is not None
            else ActivityRepository()
        )

        self.elder_id = elder_id
        self.elder_name = elder_name

        self.active = True

        self.last_results = []
        self.last_filters = None
        self.page_index = 0

        self.selected = None

        self.awaiting_join_confirmation = False
        self.pending_join_mode = None

        # 由 activity_need_integration 注入。控制器本身不依赖
        # 跨场景数据库，读取失败时仍按原有日程顺序推荐。
        self.preference_ranker = None


    def _result(
        self,
        action,
        reply,
    ):

        return {
            "action":
                action,

            "reply":
                reply,

            "active":
                self.active,

            "selected":
                self.selected,

            "recommended_count":
                len(
                    self.last_results
                ),
        }


    @staticmethod
    def _date_label(
        date_text,
    ):

        today = (
            date.today()
            .isoformat()
        )

        if date_text == today:
            return "今天"

        return "明天"


    @staticmethod
    def _registration_deadline_passed(
        item,
    ):

        deadline = item.get(
            "registration_deadline"
        )

        if not deadline:
            return False

        try:
            deadline_time = (
                datetime.fromisoformat(
                    deadline
                )
            )

        except ValueError:
            return False

        return (
            datetime.now()
            >= deadline_time
        )


    @staticmethod
    def _is_recommendable(
        item,
    ):
        """
        判断一个活动当前是否适合主动推荐给老人。

        泛查询只推荐现在仍可正常参加的活动。

        老人明确查询某个活动时，
        即使已满、截止或取消，
        仍可返回该活动并说明具体状态。
        """

        # 只有 open 状态适合主动推荐
        if item.get(
            "status"
        ) != "open":
            return False

        # 需要报名，并且报名已经截止
        if (
            item.get(
                "requires_registration"
            )
            and ActivityController
            ._registration_deadline_passed(
                item
            )
        ):
            return False

        # 有人数限制且没有剩余名额
        spots = item.get(
            "available_spots"
        )

        if (
            spots is not None
            and spots <= 0
        ):
            return False

        return True


    @staticmethod
    def _status_text(
        item,
    ):

        status = item[
            "status"
        ]

        if status == "open":

            if (
                item[
                    "requires_registration"
                ]
                and ActivityController
                ._registration_deadline_passed(
                    item
                )
            ):
                return "报名已经截止"

            spots = item[
                "available_spots"
            ]

            if spots is None:
                return "不限人数，可以参加"

            return (
                f"还有{spots}个名额"
            )

        return STATUS_LABELS.get(
            status,
            status,
        )


    def _show_page(self):

        page_size = 3

        start = (
            self.page_index
            * page_size
        )

        end = (
            start
            + page_size
        )

        page = self.last_results[
            start:end
        ]

        if not page:

            return self._result(
                "no_more",
                "暂时没有更多合适的活动了。",
            )


        ordinal_names = [
            "第一",
            "第二",
            "第三",
        ]

        parts = []

        for index, item in enumerate(
            page
        ):

            parts.append(
                (
                    f"{ordinal_names[index]}，"
                    f"{item['start_time']}的"
                    f"{item['name']}，"
                    f"地点在{item['location']}，"
                    f"{self._status_text(item)}"
                )
            )


        reply = (
            "我查到这些活动。"
            + "；".join(parts)
            + "。您可以说第一个、"
              "唱歌那个，也可以问几点、"
              "在哪里或者还有没有名额。"
        )

        return self._result(
            "recommend",
            reply,
        )


    def _rank_generic_recommendations(
        self,
        results,
        filters,
    ):
        """Use an optional preference callback without changing query safety."""

        ranker = self.preference_ranker

        if not callable(ranker):
            return results

        if filters.get("category") or filters.get("keyword"):
            return results

        try:
            ranked = list(
                ranker(
                    results,
                    filters=filters,
                )
            )

            original_ids = [
                item.get("session_id")
                for item in results
            ]
            ranked_ids = [
                item.get("session_id")
                for item in ranked
            ]

            if (
                len(ranked) == len(results)
                and sorted(ranked_ids) == sorted(original_ids)
            ):
                return ranked

            print("历史活动偏好返回异常，保留原推荐顺序", flush=True)

        except Exception as exc:
            print(
                f"历史活动偏好不可用，保留原推荐顺序：{exc!r}",
                flush=True,
            )

        return results


    def query(
        self,
        text,
        *,
        filters_override=None,
    ):

        if filters_override is not None:

            filters = {
                "activity_date":
                    filters_override.get(
                        "activity_date"
                    ),

                "period":
                    filters_override.get(
                        "period"
                    ),

                "category":
                    filters_override.get(
                        "category"
                    ),

                "keyword":
                    filters_override.get(
                        "keyword"
                    ),
            }

        else:

            filters = (
                parse_query_filters(
                    text
                )
            )

        include_cancelled = (
            filters["category"]
            is not None

            or filters["keyword"]
            is not None
        )


        results = (
            self.repo
            .query_sessions(
                **filters,
                include_cancelled=
                    include_cancelled,
            )
        )


        # -------------------------------------------------
        # 泛推荐：
        # “今天有什么活动”
        # “下午有什么活动”
        #
        # 只展示当前真正可以参加的活动。
        #
        # 明确查询：
        # “今天有没有手工活动”
        # “有没有棋牌交流”
        #
        # 保留已满 / 截止 / 取消结果，
        # 让机器人向老人说明实际状态。
        # -------------------------------------------------

        explicit_activity_query = (
            filters["category"]
            is not None
            or filters["keyword"]
            is not None
        )

        if not explicit_activity_query:

            results = [
                item
                for item in results
                if self._is_recommendable(
                    item
                )
            ]

            results = self._rank_generic_recommendations(
                results,
                filters,
            )


        self.last_filters = (
            filters
        )

        self.last_results = (
            results
        )

        self.page_index = 0
        self.selected = None


        if not results:

            return self._result(
                "not_found",
                "我没有查到符合条件的活动。",
            )


        # 只有一个结果时直接详细介绍
        if len(results) == 1:

            self.selected = (
                results[0]
            )

            return self._result(
                "single_result",
                self._describe(
                    self.selected
                ),
            )


        return self._show_page()


    def _describe(
        self,
        item,
    ):

        date_label = (
            self._date_label(
                item[
                    "activity_date"
                ]
            )
        )

        registration = (
            "需要提前登记"
            if item[
                "requires_registration"
            ]
            else "不需要提前登记"
        )

        return (
            f"{date_label}"
            f"{item['start_time']}到"
            f"{item['end_time']}，"
            f"{item['name']}在"
            f"{item['location']}举行。"
            f"{item['description']}"
            f"目前{self._status_text(item)}，"
            f"{registration}。"
        )


    def select(
        self,
        text,
    ):

        if not self.last_results:

            return self._result(
                "need_query",
                "您还没有选择活动，可以先问我今天有什么活动。",
            )


        page_size = 3

        start = (
            self.page_index
            * page_size
        )

        page = self.last_results[
            start:
            start + page_size
        ]


        index = ordinal_index(
            text
        )

        if (
            index is not None
            and index < len(page)
        ):

            self.selected = (
                page[index]
            )

            return self._result(
                "selected",
                self._describe(
                    self.selected
                ),
            )


        value = compact(
            text
        )


        keywords = [
            "唱歌",
            "茶话会",
            "聊天",
            "讲座",
            "健康",
            "电影",
            "观影",
            "书法",
            "棋牌",
            "手工",
            "戏曲",
        ]


        for keyword in keywords:

            if keyword not in value:
                continue

            for item in page:

                haystack = (
                    item["name"]
                    + item["tags"]
                    + item["description"]
                )

                if keyword in haystack:

                    self.selected = (
                        item
                    )

                    return self._result(
                        "selected",
                        self._describe(
                            item
                        ),
                    )


        # 上午 / 下午 / 晚上那个
        if "上午" in value:

            candidates = [
                x
                for x in page
                if x[
                    "start_time"
                ] < "12:00"
            ]

        elif "下午" in value:

            candidates = [
                x
                for x in page
                if (
                    "12:00"
                    <= x[
                        "start_time"
                    ]
                    < "18:00"
                )
            ]

        elif "晚上" in value:

            candidates = [
                x
                for x in page
                if x[
                    "start_time"
                ] >= "18:00"
            ]

        else:

            candidates = []


        if len(candidates) == 1:

            self.selected = (
                candidates[0]
            )

            return self._result(
                "selected",
                self._describe(
                    self.selected
                ),
            )


        return self._result(
            "select_failed",
            "我还不确定您指的是哪个活动，可以说第一个、第二个，或者直接说活动名称。",
        )


    def more(self):

        if not self.last_results:

            return self._result(
                "need_query",
                "您可以先问我今天有什么活动。",
            )

        self.page_index += 1

        result = self._show_page()

        if result[
            "action"
        ] == "no_more":

            self.page_index = max(
                0,
                self.page_index - 1,
            )

        return result


    def ask_time(self):

        if not self.selected:

            return self._result(
                "need_select",
                "您想问哪个活动？",
            )

        item = self.selected

        return self._result(
            "detail_time",
            (
                f"{item['name']}"
                f"{item['activity_date']} "
                f"{item['start_time']}开始，"
                f"{item['end_time']}结束。"
            ),
        )


    def ask_location(self):

        if not self.selected:

            return self._result(
                "need_select",
                "您想问哪个活动？",
            )

        return self._result(
            "detail_location",
            (
                f"{self.selected['name']}"
                f"在{self.selected['location']}举行。"
            ),
        )


    def ask_availability(self):

        if not self.selected:

            return self._result(
                "need_select",
                "您想问哪个活动？",
            )

        return self._result(
            "detail_availability",
            (
                f"{self.selected['name']}"
                f"{self._status_text(self.selected)}。"
            ),
        )


    def ask_registration(self):

        if not self.selected:

            return self._result(
                "need_select",
                "您想问哪个活动？",
            )

        if self.selected[
            "requires_registration"
        ]:

            reply = (
                f"{self.selected['name']}"
                "需要提前登记。"
            )

        else:

            reply = (
                f"{self.selected['name']}"
                "不需要提前登记。"
            )

        return self._result(
            "detail_registration",
            reply,
        )


    def join(self):

        if not self.selected:

            if len(
                self.last_results
            ) == 1:

                self.selected = (
                    self.last_results[0]
                )

            else:

                return self._result(
                    "need_select",
                    "您想参加哪个活动？",
                )


        item = self.selected

        existing = (
            self.repo
            .get_interest(
                self.elder_id,
                item[
                    "session_id"
                ],
            )
        )


        if existing:

            return self._result(
                "already_recorded",
                (
                    f"您之前已经登记过"
                    f"{item['name']}，"
                    f"当前记录状态是"
                    f"{existing['status']}。"
                ),
            )


        if item[
            "status"
        ] == "cancelled":

            return self._result(
                "cancelled",
                (
                    f"{item['name']}"
                    "已经取消，"
                    "暂时不能登记参加。"
                ),
            )


        if item[
            "status"
        ] == "full":

            self.awaiting_join_confirmation = (
                True
            )

            self.pending_join_mode = (
                "waitlist"
            )

            return self._result(
                "confirm_waitlist",
                (
                    f"{item['name']}目前已经满员。"
                    "我可以帮您记录候补意愿，"
                    "如果有位置再由工作人员确认。"
                    "需要我记录吗？"
                ),
            )


        if (
            item[
                "status"
            ] == "closed"
            or (
                item[
                    "requires_registration"
                ]
                and self
                ._registration_deadline_passed(
                    item
                )
            )
        ):

            self.awaiting_join_confirmation = (
                True
            )

            self.pending_join_mode = (
                "late_inquiry"
            )

            return self._result(
                "confirm_late_inquiry",
                (
                    f"{item['name']}已经超过报名时间。"
                    "如果您仍然想参加，"
                    "我可以帮您联系工作人员询问。"
                    "需要我联系吗？"
                ),
            )


        self.awaiting_join_confirmation = (
            True
        )

        self.pending_join_mode = (
            "normal"
        )

        return self._result(
            "confirm_join",
            (
                f"您是想参加"
                f"{item['activity_date']} "
                f"{item['start_time']}的"
                f"{item['name']}，对吗？"
            ),
        )


    def confirm_yes(self):

        if not (
            self.awaiting_join_confirmation
            and self.selected
        ):

            return self._result(
                "unexpected_confirm",
                "您可以先选择一个想参加的活动。",
            )


        item = self.selected
        mode = self.pending_join_mode


        if mode == "waitlist":

            interest_status = (
                "waitlist"
            )

            notification_type = (
                "activity_waitlist"
            )

            reply = (
                "好的，我已经帮您记录候补意愿，"
                "并生成了工作人员通知。"
            )


        elif mode == "late_inquiry":

            interest_status = (
                "pending"
            )

            notification_type = (
                "late_registration_inquiry"
            )

            reply = (
                "好的，我已经记录您的意愿，"
                "并请工作人员确认是否还能参加。"
            )


        else:

            interest_status = (
                "pending"
            )

            notification_type = (
                "activity_interest"
            )

            reply = (
                "好的，我已经帮您记录参加意愿，"
                "并生成工作人员通知，"
                "等待工作人员确认。"
            )


        result = (
            self.repo
            .record_interest(
                elder_id=
                    self.elder_id,

                session_id=
                    item[
                        "session_id"
                    ],

                status=
                    interest_status,
            )
        )


        if not result[
            "created"
        ]:

            self.awaiting_join_confirmation = (
                False
            )

            self.pending_join_mode = None

            return self._result(
                "already_recorded",
                "这个活动之前已经登记过了。",
            )


        message = (
            f"{self.elder_name}希望参加"
            f"{item['activity_date']} "
            f"{item['start_time']}的"
            f"{item['name']}。"
        )


        if mode == "waitlist":

            message += (
                "当前活动已满，"
                "请工作人员处理候补。"
            )

        elif mode == "late_inquiry":

            message += (
                "当前报名已截止，"
                "请工作人员确认是否可以参加。"
            )


        notification_id = (
            self.repo
            .create_notification(
                elder_id=
                    self.elder_id,

                session_id=
                    item[
                        "session_id"
                    ],

                notification_type=
                    notification_type,

                message=
                    message,
            )
        )


        self.awaiting_join_confirmation = (
            False
        )

        self.pending_join_mode = None


        return self._result(
            "interest_recorded",
            reply,
        )


    def confirm_no(self):

        self.awaiting_join_confirmation = (
            False
        )

        self.pending_join_mode = None

        return self._result(
            "join_cancelled",
            "好的，这次不登记。",
        )


    def decline(self):

        self.active = False

        return self._result(
            "end",
            (
                "好的，这次先不参加，"
                "我就不继续推荐了。"
            ),
        )


    def handle_action(
        self,
        action,
        text,
        *,
        filters_override=None,
    ):

        # 正在等待参加确认时，
        # 优先处理“对 / 不”
        if self.awaiting_join_confirmation:

            if action == "confirm_yes":
                return self.confirm_yes()

            if action in [
                "confirm_no",
                "decline",
            ]:
                return self.confirm_no()

            # 还在确认上一项活动时，不能让新的查询或选择替换
            # self.selected。否则“对”会登记新活动，而共享需求仍指向
            # 旧活动，造成跨场景记录和业务登记不一致。
            return self._result(
                "awaiting_join_confirmation",
                "请先回答是否登记当前活动；如果不想登记，可以说算了。",
            )


        if action == "query":

            return self.query(
                text,
                filters_override=
                    filters_override,
            )


        if action == "select":
            return self.select(
                text
            )


        if action == "more":
            return self.more()


        if action == "ask_time":
            return self.ask_time()


        if action == "ask_location":
            return self.ask_location()


        if action == "ask_availability":
            return self.ask_availability()


        if action == "ask_registration":
            return self.ask_registration()


        if action == "join":

            # 支持一句话同时包含：
            # “选择活动 + 参加意愿”
            #
            # 例如：
            # 帮我报名第一个
            # 我要参加第二个
            # 我想参加唱歌那个
            # 茶话会那个我想去
            #
            # 如果当前还没有 selected，
            # 先尝试从老人本轮原话中选择活动。
            if not self.selected:

                select_result = (
                    self.select(
                        text
                    )
                )

                if select_result.get(
                    "action"
                ) == "selected":

                    # select() 已经设置 self.selected，
                    # 直接进入正常参加确认流程，
                    # 不额外播报一次“已选择”。
                    return self.join()

                # 这句话里没有明确指出哪个活动
                return self._result(
                    "need_select",
                    "您想参加哪个活动？",
                )

            return self.join()


        if action == "confirm_yes":
            return self.confirm_yes()


        if action == "confirm_no":
            return self.confirm_no()


        if action == "decline":
            return self.decline()


        return self._result(
            "unknown",
            (
                "我没有听清。"
                "您可以问今天有什么活动、"
                "下午有什么活动，"
                "或者有没有唱歌、聊天、"
                "讲座和观影活动。"
            ),
        )


    def handle_text(
        self,
        text,
    ):

        action = classify_action(
            text
        )

        return self.handle_action(
            action,
            text,
        )

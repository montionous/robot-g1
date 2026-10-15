#!/usr/bin/env python3

from __future__ import annotations

import re
from datetime import (
    date,
    datetime,
)

from activity_intent import (
    ordinal_index,
    parse_query_filters,
)

from activity_repository import (
    ActivityRepository,
)

from showcase_availability import (
    next_available_session,
    unavailable_reason,
)

from showcase_protocol import (
    ALLOWED_BY_STATE,
    ASK_AVAILABILITY,
    ASK_LOCATION,
    ASK_REGISTRATION,
    ASK_TIME,
    CONFIRM_NO,
    CONFIRM_YES,
    DONE,
    END,
    END_REPLY,
    JOIN,
    OTHER,
    QUERY,
    REPEAT_DETAILS,
    SELECT,
    SELECTED_ACTIVITY,
    WAIT_CONFIRM,
    WAIT_END,
    WAIT_QUERY,
    WAIT_SELECT,
)


STATUS_LABELS = {
    "open":
        "可以参加",

    "full":
        "目前已经满员",

    "closed":
        "报名已经截止",

    "cancelled":
        "活动已经取消",
}


def compact(text):
    value = str(
        text or ""
    ).strip()

    return re.sub(
        r"[\s，。！？,.!?、；;：:]+",
        "",
        value,
    )


class ShowcaseController:

    def __init__(
        self,
        *,
        elder_id=1,
        elder_name="王大爷",
        repo=None,
        recent_resolver=None,
    ):
        self.repo = (
            repo
            if repo is not None
            else ActivityRepository()
        )

        self.recent_resolver = (
            recent_resolver
        )

        self.elder_id = (
            elder_id
        )

        self.elder_name = (
            elder_name
        )

        self.state = (
            WAIT_QUERY
        )

        self.last_results = []
        self.last_filters = None
        self.selected = None

    @property
    def done(self):
        return (
            self.state
            == DONE
        )

    @property
    def allowed_intents(self):
        return (
            ALLOWED_BY_STATE.get(
                self.state,
                set(),
            )
        )

    def _result(
        self,
        action,
        reply=None,
        *,
        changed=False,
    ):
        return {
            "action":
                action,

            "reply":
                reply,

            "state":
                self.state,

            "changed":
                changed,

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

        tomorrow = (
            date.fromordinal(
                date.today()
                .toordinal()
                + 1
            )
            .isoformat()
        )

        if date_text == today:
            return "今天"

        if date_text == tomorrow:
            return "明天"

        return str(
            date_text
        )

    @staticmethod
    def _time_label(
        time_text,
    ):
        value = str(
            time_text or ""
        ).strip()

        try:
            hour_text, minute_text = (
                value.split(
                    ":",
                    1,
                )
            )

            hour = int(
                hour_text
            )

            minute = int(
                minute_text
            )

        except Exception:
            return value

        if hour < 6:
            prefix = "凌晨"

        elif hour < 12:
            prefix = "上午"

        elif hour == 12:
            prefix = "中午"

        elif hour < 18:
            prefix = "下午"

        else:
            prefix = "晚上"

        spoken_hour = (
            hour
            if hour <= 12
            else hour - 12
        )

        if minute == 0:
            suffix = (
                f"{spoken_hour}点"
            )

        elif minute == 30:
            suffix = (
                f"{spoken_hour}点半"
            )

        else:
            suffix = (
                f"{spoken_hour}点"
                f"{minute}分"
            )

        return (
            prefix
            + suffix
        )

    @staticmethod
    def _deadline_passed(
        item,
    ):
        deadline = item.get(
            "registration_deadline"
        )

        if not deadline:
            return False

        try:
            value = (
                datetime.fromisoformat(
                    deadline
                )
            )
        except ValueError:
            return False

        return (
            datetime.now()
            >= value
        )

    @classmethod
    def _status_text(
        cls,
        item,
    ):
        status = item.get(
            "status"
        )

        if status == "open":

            if (
                item.get(
                    "requires_registration"
                )
                and cls._deadline_passed(
                    item
                )
            ):
                return (
                    "报名已经截止"
                )

            spots = item.get(
                "available_spots"
            )

            if spots is None:
                return (
                    "不限人数，可以参加"
                )

            return (
                f"还有{spots}个名额"
            )

        return (
            STATUS_LABELS.get(
                status,
                str(status),
            )
        )

    @classmethod
    def _registration_text(
        cls,
        item,
    ):
        if not item.get(
            "requires_registration"
        ):
            return (
                "不需要提前报名"
            )

        if cls._deadline_passed(
            item
        ):
            return (
                "需要提前登记，"
                "但当前报名已经截止"
            )

        return (
            "需要提前登记"
        )

    @classmethod
    def _describe(
        cls,
        item,
    ):
        date_label = (
            cls._date_label(
                item[
                    "activity_date"
                ]
            )
        )

        start_text = (
            cls._time_label(
                item[
                    "start_time"
                ]
            )
        )

        end_text = (
            cls._time_label(
                item[
                    "end_time"
                ]
            )
        )

        parts = [
            (
                f"{item['name']}"
                f"{date_label}"
                f"{start_text}开始，"
                f"{end_text}结束，"
                f"在{item['location']}举行。"
            ),

            str(
                item.get(
                    "description",
                    "",
                )
            ).strip(),

            (
                f"这个活动"
                f"{cls._status_text(item)}，"
                f"{cls._registration_text(item)}。"
            ),
        ]

        notes = str(
            item.get(
                "notes",
                "",
            )
            or ""
        ).strip()

        if notes:
            parts.append(
                notes
            )

        return "".join(
            part
            for part in parts
            if part
        )

    def _query_label(
        self,
        filters,
        results,
    ):
        if results:
            date_label = (
                self._date_label(
                    results[0][
                        "activity_date"
                    ]
                )
            )
        else:
            date_label = ""

        period = (
            filters.get(
                "period"
            )
            if filters
            else None
        )

        period_label = {
            "morning":
                "上午",

            "afternoon":
                "下午",

            "evening":
                "晚上",
        }.get(
            period,
            "",
        )

        return (
            date_label
            + period_label
        )

    @staticmethod
    def _should_use_recent_query(
        text,
    ):
        """
        明确指定今天、明天、某个时段的查询，
        继续走原来的精确查询逻辑。

        “最近 / 这两天 / 有没有某类活动 /
        那唱歌呢”走增强语义查询。
        """

        value = compact(
            text
        )

        if any(
            word in value
            for word in (
                "最近",
                "这两天",
                "这几天",
                "近几天",
            )
        ):
            return True

        if any(
            word in value
            for word in (
                "今天",
                "明天",
                "上午",
                "下午",
                "晚上",
                "早上",
                "中午",
            )
        ):
            return False

        return True


    def _query_recent(
        self,
        text,
    ):
        previous_state = (
            self.state
        )

        result = (
            self.recent_resolver
            .resolve(
                text,
                days=7,
                list_limit=3,
            )
        )

        mode = result.get(
            "mode"
        )

        reply = result.get(
            "reply"
        )

        # ---------------------------------------------
        # 泛查询：
        # “最近有什么活动”
        # ---------------------------------------------

        if mode == "generic_list":

            sessions = list(
                result.get(
                    "sessions"
                )
                or []
            )

            self.last_filters = {
                "scope":
                    "recent",
            }

            self.last_results = (
                sessions
            )

            self.selected = None

            if sessions:
                self.state = (
                    WAIT_SELECT
                )

                return self._result(
                    "recommend",
                    reply,
                    changed=True,
                )

            return self._result(
                "not_found",
                reply,
            )


        # ---------------------------------------------
        # 明确询问某一种活动：
        # “最近有没有唱歌的”
        # ---------------------------------------------

        if mode == "specific":

            session = result.get(
                "session"
            )

            if session is None:
                return self._result(
                    "not_found",
                    reply,
                )

            target = session

            # 当前场次不能参加时，
            # 回复会说明原因和下一场。
            #
            # 后续“几点”“在哪里”“我要参加”
            # 应自然指向下一场可参加场次。
            if (
                unavailable_reason(
                    session
                )
                is not None
            ):
                target = (
                    next_available_session(
                        self.repo,
                        session,
                    )
                )

            if target is not None:

                self.last_filters = {
                    "scope":
                        "recent_specific",
                }

                self.last_results = [
                    target
                ]

                self.selected = (
                    target
                )

                self.state = (
                    SELECTED_ACTIVITY
                )

                return self._result(
                    "selected_query",
                    reply,
                    changed=True,
                )

            # 当前不可参加且没有下一场：
            # 只回答事实，不破坏之前的会话上下文。
            self.state = (
                previous_state
            )

            return self._result(
                "not_found",
                reply,
            )


        # ---------------------------------------------
        # 指定了数据库不存在的活动，
        # 或最近没有对应场次。
        #
        # 不破坏老人之前已经选中的活动，
        # 也不清空之前推荐列表。
        # ---------------------------------------------

        self.state = (
            previous_state
        )

        return self._result(
            "not_found",
            reply,
        )


    def _query(
        self,
        text,
    ):
        if (
            self.recent_resolver
            is not None
            and self._should_use_recent_query(
                text
            )
        ):
            try:
                return (
                    self._query_recent(
                        text
                    )
                )

            except Exception:
                # 云端语义匹配临时不可用时，
                # 保留原有数据库查询能力。
                pass

        filters = (
            parse_query_filters(
                text
            )
        )

        results = (
            self.repo
            .query_sessions(
                **filters,
                include_cancelled=False,
                limit=30,
            )
        )

        self.last_filters = (
            filters
        )

        self.last_results = [
            item
            for item in results
            if unavailable_reason(
                item
            ) is None
        ][:3]

        self.selected = None

        if not self.last_results:
            return self._result(
                "not_found",
                (
                    "我暂时没有查到"
                    "符合条件的活动。"
                ),
            )

        names = []

        for item in (
            self.last_results
        ):
            name = str(
                item.get(
                    "name",
                    "",
                )
            ).strip()

            if (
                name
                and name not in names
            ):
                names.append(
                    name
                )

        label = (
            self._query_label(
                filters,
                self.last_results,
            )
        )

        self.state = (
            WAIT_SELECT
        )

        return self._result(
            "recommend",
            (
                f"{label}有"
                f"{'、'.join(names)}。"
                "您对哪个比较感兴趣？"
            ),
            changed=True,
        )

    @staticmethod
    def _selection_tokens(
        item,
    ):
        tokens = []

        name = str(
            item.get(
                "name",
                "",
            )
        ).strip()

        if name:
            tokens.append(
                name
            )

        tags = str(
            item.get(
                "tags",
                "",
            )
            or ""
        )

        for token in re.split(
            r"[,，、\s]+",
            tags,
        ):
            token = (
                token.strip()
            )

            if len(token) >= 2:
                tokens.append(
                    token
                )

        return tokens

    def _match_selection(
        self,
        text,
    ):
        if not self.last_results:
            return None

        index = (
            ordinal_index(
                text
            )
        )

        if (
            index is not None
            and 0 <= index
            < len(
                self.last_results
            )
        ):
            return (
                self.last_results[
                    index
                ]
            )

        value = (
            compact(
                text
            )
        )

        scored = []

        for item in (
            self.last_results
        ):
            score = 0

            for token in (
                self._selection_tokens(
                    item
                )
            ):
                current = (
                    compact(
                        token
                    )
                )

                if (
                    len(current) >= 2
                    and current in value
                ):
                    score = max(
                        score,
                        len(current),
                    )

            if score > 0:
                scored.append(
                    (
                        score,
                        item,
                    )
                )

        if not scored:
            return None

        scored.sort(
            key=lambda value:
                value[0],
            reverse=True,
        )

        return (
            scored[0][1]
        )

    def _select(
        self,
        text,
    ):
        item = (
            self._match_selection(
                text
            )
        )

        if item is None:
            return self._result(
                "ignore",
                None,
            )

        self.selected = item

        self.state = (
            SELECTED_ACTIVITY
        )

        return self._result(
            "selected",
            self._describe(
                item
            ),
            changed=True,
        )

    def _need_selected(
        self,
    ):
        return (
            self.selected
            is not None
        )

    def _ask_time(
        self,
    ):
        item = (
            self.selected
        )

        return self._result(
            "detail_time",
            (
                f"{item['name']}"
                f"{self._date_label(item['activity_date'])}"
                f"{self._time_label(item['start_time'])}开始，"
                f"{self._time_label(item['end_time'])}结束。"
            ),
        )

    def _ask_location(
        self,
    ):
        item = (
            self.selected
        )

        return self._result(
            "detail_location",
            (
                f"{item['name']}"
                f"在{item['location']}举行。"
            ),
        )

    def _ask_availability(
        self,
    ):
        item = (
            self.selected
        )

        return self._result(
            "detail_availability",
            (
                f"{item['name']}"
                f"{self._status_text(item)}。"
            ),
        )

    def _ask_registration(
        self,
    ):
        item = (
            self.selected
        )

        return self._result(
            "detail_registration",
            (
                f"{item['name']}"
                f"{self._registration_text(item)}。"
            ),
        )

    def _repeat_details(
        self,
    ):
        return self._result(
            "repeat_details",
            self._describe(
                self.selected
            ),
        )

    def _join(
        self,
    ):
        item = (
            self.selected
        )

        status = item.get(
            "status"
        )

        if status == "cancelled":
            return self._result(
                "cannot_join",
                (
                    f"{item['name']}"
                    "已经取消，"
                    "现在不能参加。"
                ),
            )

        if status == "full":
            return self._result(
                "cannot_join",
                (
                    f"{item['name']}"
                    "目前已经满员。"
                ),
            )

        if status == "closed":
            return self._result(
                "cannot_join",
                (
                    f"{item['name']}"
                    "报名已经截止。"
                ),
            )

        # -------------------------------------------------
        # 不需要报名的活动：
        # 直接给参加指引，不写数据库。
        # 集体唱歌走这里。
        # -------------------------------------------------

        if not item.get(
            "requires_registration"
        ):
            self.state = (
                WAIT_END
            )

            return self._result(
                "participation_guidance",
                (
                    f"好的，{item['name']}"
                    "不需要提前报名。"
                    f"{self._date_label(item['activity_date'])}"
                    f"{self._time_label(item['start_time'])}"
                    f"到{item['location']}参加就可以。"
                ),
                changed=True,
            )

        # -------------------------------------------------
        # 需要报名的其他活动：
        # 仍保留二次确认能力。
        # -------------------------------------------------

        self.state = (
            WAIT_CONFIRM
        )

        return self._result(
            "ask_join_confirmation",
            (
                f"{item['name']}"
                "需要提前登记。"
                "您确认要登记参加吗？"
            ),
            changed=True,
        )

    def _confirm_yes(
        self,
    ):
        item = (
            self.selected
        )

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
            self.state = (
                WAIT_END
            )

            return self._result(
                "already_recorded",
                (
                    f"您之前已经登记过"
                    f"{item['name']}。"
                ),
                changed=True,
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
                    "pending",
            )
        )

        if not result.get(
            "created"
        ):
            self.state = (
                SELECTED_ACTIVITY
            )

            return self._result(
                "already_recorded",
                (
                    f"您之前已经登记过"
                    f"{item['name']}。"
                ),
                changed=True,
            )

        message = (
            f"{self.elder_name}希望参加"
            f"{item['activity_date']} "
            f"{item['start_time']}的"
            f"{item['name']}。"
        )

        self.repo.create_notification(
            elder_id=
                self.elder_id,

            session_id=
                item[
                    "session_id"
                ],

            notification_type=
                "activity_interest",

            message=
                message,
        )

        self.state = (
            WAIT_END
        )

        return self._result(
            "interest_recorded",
            (
                "好的，我已经帮您记录参加意愿，"
                "并生成工作人员通知，"
                "等待工作人员确认。"
            ),
            changed=True,
        )

    def _confirm_no(
        self,
    ):
        self.state = (
            SELECTED_ACTIVITY
        )

        return self._result(
            "join_cancelled",
            "好的，这次先不登记。",
            changed=True,
        )

    def handle(
        self,
        intent,
        text="",
    ):
        if self.done:
            return self._result(
                "done",
                None,
            )

        allowed = (
            self.allowed_intents
        )

        if (
            intent == OTHER
            or intent
            not in allowed
        ):
            return self._result(
                "ignore",
                None,
            )

        if intent == END:
            self.state = DONE

            return self._result(
                "end",
                END_REPLY,
                changed=True,
            )

        if (
            self.state
            in {
                WAIT_QUERY,
                WAIT_SELECT,
                SELECTED_ACTIVITY,
            }
            and intent == QUERY
        ):
            return self._query(
                text
            )

        if (
            self.state
            == WAIT_SELECT
            and intent == SELECT
        ):
            return self._select(
                text
            )

        if (
            self.state
            == SELECTED_ACTIVITY
        ):
            if not (
                self._need_selected()
            ):
                return self._result(
                    "ignore",
                    None,
                )

            if intent == ASK_TIME:
                return self._ask_time()

            if intent == ASK_LOCATION:
                return self._ask_location()

            if intent == ASK_AVAILABILITY:
                return self._ask_availability()

            if intent == ASK_REGISTRATION:
                return self._ask_registration()

            if intent == REPEAT_DETAILS:
                return self._repeat_details()

            if intent == JOIN:
                return self._join()

        if (
            self.state
            == WAIT_CONFIRM
        ):
            if intent == CONFIRM_YES:
                return self._confirm_yes()

            if intent == CONFIRM_NO:
                return self._confirm_no()

        return self._result(
            "ignore",
            None,
        )

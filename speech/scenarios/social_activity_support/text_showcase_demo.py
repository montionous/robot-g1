#!/usr/bin/env python3

from __future__ import annotations

import argparse
from datetime import date, timedelta

from activity_repository import ActivityRepository
from showcase_activity_matcher import ActivitySemanticMatcher
from showcase_controller import ShowcaseController
from showcase_recent_query import RecentActivityQueryResolver
from showcase_intent import (
    SocialActivityIntentLLM,
    classify_showcase_intent,
)
from showcase_protocol import (
    ASK_AVAILABILITY,
    ASK_LOCATION,
    ASK_REGISTRATION,
    ASK_TIME,
    CONFIRM_NO,
    CONFIRM_YES,
    END,
    JOIN,
    OPENING,
    OTHER,
    QUERY,
    REPEAT_DETAILS,
    SELECT,
)


class DemoRepo:
    """
    仅用于文字版 showcase。

    不读写 SQLite。
    日期始终跟随当前日期，
    避免演示数据过期。
    """

    def __init__(self):
        today = date.today()
        tomorrow = today + timedelta(days=1)

        self.items = (
            self._build_day(
                today.isoformat(),
            )
            + self._build_day(
                tomorrow.isoformat(),
            )
        )

        self.interests = {}
        self.notifications = []

    @staticmethod
    def _build_day(
        activity_date,
    ):
        return [
            {
                "session_id":
                    int(
                        activity_date
                        .replace("-", "")
                    )
                    * 10
                    + 1,

                "activity_date":
                    activity_date,

                "start_time":
                    "15:30",

                "end_time":
                    "16:30",

                "capacity":
                    None,

                "registered_count":
                    15,

                "registration_deadline":
                    None,

                "status":
                    "open",

                "activity_id":
                    1,

                "name":
                    "集体唱歌",

                "category":
                    "music",

                "description":
                    "大家一起演唱经典歌曲和熟悉的老歌。",

                "tags":
                    "唱歌,合唱,音乐,老歌,社交",

                "organizer":
                    "赵老师",

                "location":
                    "三楼多功能厅",

                "requires_registration":
                    0,

                "notes":
                    "不需要专业唱歌基础。",

                "available_spots":
                    None,
            },

            {
                "session_id":
                    int(
                        activity_date
                        .replace("-", "")
                    )
                    * 10
                    + 2,

                "activity_date":
                    activity_date,

                "start_time":
                    "14:30",

                "end_time":
                    "15:30",

                "capacity":
                    20,

                "registered_count":
                    12,

                "registration_deadline":
                    None,

                "status":
                    "open",

                "activity_id":
                    2,

                "name":
                    "手工兴趣小组",

                "category":
                    "hobby",

                "description":
                    "大家一起做简单手工作品并交流。",

                "tags":
                    "手工,兴趣,交流",

                "organizer":
                    "李老师",

                "location":
                    "二楼活动室",

                "requires_registration":
                    1,

                "notes":
                    "材料由活动室统一准备。",

                "available_spots":
                    8,
            },

            {
                "session_id":
                    int(
                        activity_date
                        .replace("-", "")
                    )
                    * 10
                    + 3,

                "activity_date":
                    activity_date,

                "start_time":
                    "16:40",

                "end_time":
                    "17:20",

                "capacity":
                    40,

                "registered_count":
                    18,

                "registration_deadline":
                    None,

                "status":
                    "open",

                "activity_id":
                    3,

                "name":
                    "健康知识讲座",

                "category":
                    "lecture",

                "description":
                    "工作人员介绍日常健康生活知识。",

                "tags":
                    "健康,讲座,知识",

                "organizer":
                    "社区服务中心",

                "location":
                    "一楼会议室",

                "requires_registration":
                    0,

                "notes":
                    "",

                "available_spots":
                    22,
            },
        ]

    def query_sessions(
        self,
        *,
        activity_date=None,
        period=None,
        category=None,
        keyword=None,
        include_cancelled=False,
        limit=30,
    ):
        if activity_date is None:
            activity_date = (
                date.today()
                .isoformat()
            )

        results = []

        for item in self.items:
            if (
                item["activity_date"]
                != activity_date
            ):
                continue

            if (
                not include_cancelled
                and item["status"]
                == "cancelled"
            ):
                continue

            hour = int(
                item["start_time"]
                .split(":")[0]
            )

            if (
                period == "morning"
                and not (
                    6 <= hour < 12
                )
            ):
                continue

            if (
                period == "afternoon"
                and not (
                    12 <= hour < 18
                )
            ):
                continue

            if (
                period == "evening"
                and hour < 18
            ):
                continue

            if (
                category
                and item["category"]
                != category
            ):
                continue

            if keyword:
                haystack = (
                    item["name"]
                    + item["description"]
                    + item["tags"]
                )

                if (
                    str(keyword)
                    not in haystack
                ):
                    continue

            results.append(
                dict(item)
            )

        results.sort(
            key=lambda item:
                item["start_time"]
        )

        return (
            results[:limit]
        )

    def get_interest(
        self,
        elder_id,
        session_id,
    ):
        return self.interests.get(
            (
                elder_id,
                session_id,
            )
        )

    def record_interest(
        self,
        *,
        elder_id,
        session_id,
        status,
    ):
        key = (
            elder_id,
            session_id,
        )

        if key in self.interests:
            return {
                "created":
                    False,
            }

        self.interests[key] = {
            "elder_id":
                elder_id,

            "session_id":
                session_id,

            "status":
                status,
        }

        return {
            "created":
                True,
        }

    def create_notification(
        self,
        **kwargs,
    ):
        self.notifications.append(
            dict(kwargs)
        )

        return len(
            self.notifications
        )


def build_decision_message(
    intent,
    result,
):
    selected = (
        result.get(
            "selected"
        )
    )

    name = (
        selected.get(
            "name"
        )
        if selected
        else None
    )

    if intent == QUERY:
        return (
            "检测到您希望查询社区集体活动。"
        )

    if intent == SELECT:
        if name:
            return (
                f"检测到您对{name}感兴趣。"
            )

        return (
            "检测到您对刚才介绍的活动感兴趣。"
        )

    if intent == ASK_TIME:
        return (
            "检测到您正在询问活动时间。"
        )

    if intent == ASK_LOCATION:
        return (
            "检测到您正在询问活动地点。"
        )

    if intent == ASK_AVAILABILITY:
        return (
            "检测到您正在询问活动人数情况。"
        )

    if intent == ASK_REGISTRATION:
        return (
            "检测到您正在询问活动报名要求。"
        )

    if intent == REPEAT_DETAILS:
        return (
            "检测到您希望重新了解活动信息。"
        )

    if intent == JOIN:
        if name:
            return (
                f"检测到您希望参加{name}。"
            )

        return (
            "检测到您希望参加当前活动。"
        )

    if intent == CONFIRM_YES:
        return (
            "检测到您确认登记参加活动。"
        )

    if intent == CONFIRM_NO:
        return (
            "检测到您暂时不登记活动。"
        )

    if intent == END:
        return (
            "检测到您希望结束活动咨询。"
        )

    return None


def handle_one(
    controller,
    text,
    *,
    llm,
):
    print()
    print(
        f"老人: {text}"
    )

    intent_result = (
        classify_showcase_intent(
            text,
            state=
                controller.state,
            llm=llm,
        )
    )

    intent = (
        intent_result[
            "intent"
        ]
    )

    print(
        "意图:",
        intent,
        "source="
        + str(
            intent_result.get(
                "source"
            )
        ),
        "confidence="
        + f"{float(intent_result.get('confidence', 0)):.2f}",
    )

    if intent == OTHER:
        print(
            "流程动作: ignore"
        )

        print(
            "机器人: [静默]"
        )

        print(
            "当前状态:",
            controller.state,
        )

        return

    result = (
        controller.handle(
            intent,
            text,
        )
    )

    print(
        "流程动作:",
        result[
            "action"
        ],
    )

    decision = (
        build_decision_message(
            intent,
            result,
        )
    )

    if decision:
        print(
            "判断播报:",
            decision,
        )

    selected = (
        result.get(
            "selected"
        )
    )

    if selected:
        print(
            "当前活动:",
            selected["name"],
        )

    reply = (
        result.get(
            "reply"
        )
    )

    if reply:
        print(
            "机器人:",
            reply,
        )
    else:
        print(
            "机器人: [静默]"
        )

    print(
        "下一状态:",
        controller.state,
    )


def run_scripted(
    controller,
    *,
    llm,
):
    texts = [
        # 错序输入：必须静默
        "几点开始？",

        "明天下午有什么活动？",

        # 查询后尚未选择：
        # 详情问题必须静默
        "需要报名吗？",

        "我想了解一下集体唱歌。",

        "刚才几点开始来着？",

        "在哪儿？",

        "有人数限制吗？",

        "需要报名吗？",

        # 环境描述：必须静默
        "这个活动听起来挺不错的。",

        "我没记住，你再完整说一遍。",

        "那我去参加。",

        "好的，先这样吧。",
    ]

    for text in texts:
        if controller.done:
            break

        handle_one(
            controller,
            text,
            llm=llm,
        )


def main():
    parser = (
        argparse.ArgumentParser()
    )

    parser.add_argument(
        "--no-llm",
        action="store_true",
    )

    parser.add_argument(
        "--scripted",
        action="store_true",
    )

    parser.add_argument(
        "--demo-data",
        action="store_true",
        help=(
            "使用内存演示数据；"
            "默认使用真实 SQLite"
        ),
    )

    args = (
        parser.parse_args()
    )

    if args.demo_data:
        repo = (
            DemoRepo()
        )

        data_source = (
            "内存演示数据，不写 SQLite"
        )

    else:
        repo = (
            ActivityRepository()
        )

        data_source = (
            "真实 SQLite"
        )

    controller = (
        ShowcaseController(
            elder_id=1,
            elder_name="王大爷",
            repo=repo,
        )
    )

    llm = None

    if not args.no_llm:
        try:
            llm = (
                SocialActivityIntentLLM()
            )

            print(
                "意图识别: 规则 + Qwen fallback"
            )

        except Exception as exc:
            print(
                "Qwen不可用:",
                repr(exc),
            )

            print(
                "意图识别: 仅规则"
            )

    else:
        print(
            "意图识别: 仅规则"
        )

    if (
        llm is not None
        and not args.demo_data
    ):
        try:
            controller.recent_resolver = (
                RecentActivityQueryResolver(
                    repo,
                    ActivitySemanticMatcher(),
                )
            )

            print(
                "活动语义匹配: "
                "Qwen + SQLite候选约束"
            )

        except Exception as exc:
            print(
                "活动语义匹配不可用:",
                repr(exc),
            )


    print(
        "数据源:",
        data_source,
    )

    print(
        "初始状态:",
        controller.state,
    )

    print()
    print(
        "机器人:",
        OPENING,
    )

    if args.scripted:
        run_scripted(
            controller,
            llm=llm,
        )

        return

    while not controller.done:
        print()

        try:
            text = input(
                "老人> "
            ).strip()

        except (
            EOFError,
            KeyboardInterrupt,
        ):
            print()
            break

        if not text:
            continue

        handle_one(
            controller,
            text,
            llm=llm,
        )


if __name__ == "__main__":
    main()

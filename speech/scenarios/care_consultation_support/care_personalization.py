from __future__ import annotations

import sqlite3
from pathlib import Path

from care_memory import (
    get_care_memories,
)


PROJECT_ROOT = (
    Path(__file__).resolve()
    .parents[2]
)

DB_PATH = (
    PROJECT_ROOT
    / "data"
    / "elder_companion.db"
)


DOMAIN_CONDITION_CATEGORIES = {
    "mobility": {
        "musculoskeletal",
    },

    # 高血压等信息可以作为已确认健康背景读取，
    # 但绝不能据此推断“头晕就是高血压导致的”。
    "dizziness": {
        "cardiovascular",
    },
}


def connect():

    conn = sqlite3.connect(
        DB_PATH
    )

    conn.row_factory = (
        sqlite3.Row
    )

    return conn


def get_personal_care_profile(
    elderly_id,
    care_domain,
):

    categories = (
        DOMAIN_CONDITION_CATEGORIES
        .get(
            care_domain,
            set(),
        )
    )

    with connect() as conn:

        baselines = (
            conn.execute(
                """
                SELECT
                    baseline_key,
                    baseline_value,
                    source,
                    verified

                FROM elder_care_baseline

                WHERE elderly_id = ?
                  AND care_domain = ?
                  AND verified = 1

                ORDER BY id
                """,
                (
                    elderly_id,
                    care_domain,
                ),
            )
            .fetchall()
        )


        events = (
            conn.execute(
                """
                SELECT
                    event_type,
                    event_date,
                    summary,
                    outcome,
                    source,
                    verified

                FROM elder_care_event

                WHERE elderly_id = ?
                  AND care_domain = ?
                  AND verified = 1

                ORDER BY
                    event_date DESC,
                    id DESC
                """,
                (
                    elderly_id,
                    care_domain,
                ),
            )
            .fetchall()
        )


        conditions = []

        if categories:

            placeholders = ",".join(
                "?"
                for _ in categories
            )

            query = f"""
                SELECT
                    condition_name,
                    condition_category,
                    body_area,
                    status,
                    diagnosed,
                    diagnosed_at,
                    notes,
                    source,
                    verified

                FROM elder_health_condition

                WHERE elderly_id = ?
                  AND verified = 1
                  AND condition_category
                      IN ({placeholders})

                ORDER BY id
            """

            conditions = (
                conn.execute(
                    query,
                    (
                        elderly_id,
                        *sorted(
                            categories
                        ),
                    ),
                )
                .fetchall()
            )


    memories = (
        get_care_memories(
            elderly_id,
            care_domain,
        )
    )


    return {
        "memories":
            memories,

        "conditions": [
            dict(row)
            for row in conditions
        ],

        "baselines": [
            dict(row)
            for row in baselines
        ],

        "events": [
            dict(row)
            for row in events
        ],
    }


def _baseline_map(
    profile,
):

    return {
        item["baseline_key"]:
            item["baseline_value"]

        for item
        in profile["baselines"]
    }


def _history_text(
    history,
    *,
    role=None,
):

    parts = []

    for item in history or []:

        if (
            role is not None
            and item.get("role")
            != role
        ):
            continue

        value = str(
            item.get(
                "content",
                "",
            )
        ).strip()

        if value:
            parts.append(
                value
            )

    return "\n".join(
        parts
    )


def _contains_any(
    text,
    words,
):

    text = str(
        text or ""
    )

    return any(
        word in text
        for word in words
    )


def build_personalization_plan(
    *,
    elderly_id,
    care_domain,
    user_text,
    round_no,
    history=None,
    risk_level=None,
):

    profile = (
        get_personal_care_profile(
            elderly_id,
            care_domain,
        )
    )

    baseline = (
        _baseline_map(
            profile
        )
    )

    user_text = str(
        user_text or ""
    ).strip()

    user_history = (
        _history_text(
            history,
            role="user",
        )
    )

    conversation_text = (
        user_history
        + "\n"
        + user_text
    )


    plan = {
        "personalized":
            False,

        "strategy":
            None,

        "profile":
            profile,

        "must_use":
            [],

        # 可以帮助模型理解老人过去发生过什么，
        # 但不要求每一条都向老人朗读。
        "context_facts":
            [],

        "preferred_question":
            None,

        "fallback_reply":
            None,

        "required_groups":
            [],

        "display_reasons":
            [],

        "risk_level":
            risk_level,
    }


    # =====================================================
    # mobility / 膝部
    # =====================================================

    if (
        care_domain == "mobility"
        and "膝" in conversation_text
    ):

        knee_condition = next(
            (
                item
                for item
                in profile[
                    "conditions"
                ]
                if (
                    item.get(
                        "body_area"
                    )
                    == "knee"
                )
            ),
            None,
        )

        memories = (
            profile.get(
                "memories",
                [],
            )
        )

        for memory in memories[:3]:

            plan[
                "context_facts"
            ].append(
                (
                    "老人既往护理咨询："
                    f"{memory['summary']}"
                    "；累计记录"
                    f"{memory['occurrence_count']}次。"
                )
            )

            plan[
                "display_reasons"
            ].append(
                (
                    "既往护理咨询: "
                    f"{memory['summary']}"
                    "（"
                    f"{memory['occurrence_count']}次"
                    "）"
                )
            )


        usual_knee = (
            baseline.get(
                "usual_knee_state"
            )
        )

        walking = (
            baseline.get(
                "walking_independence"
            )
        )

        device = (
            baseline.get(
                "assistive_device"
            )
        )

        fall = next(
            (
                item
                for item
                in profile[
                    "events"
                ]
                if (
                    item.get(
                        "event_type"
                    )
                    == "fall"
                )
            ),
            None,
        )


        if knee_condition:

            plan[
                "personalized"
            ] = True

            plan[
                "display_reasons"
            ].append(
                (
                    "既往病史: "
                    f"{knee_condition['condition_name']}"
                )
            )


        if usual_knee:

            plan[
                "personalized"
            ] = True

            plan[
                "display_reasons"
            ].append(
                (
                    "个人基线: "
                    f"{usual_knee}"
                )
            )


        if walking:

            plan[
                "display_reasons"
            ].append(
                (
                    "活动基线: "
                    f"{walking}"
                )
            )


        if device:

            plan[
                "display_reasons"
            ].append(
                (
                    "辅助器具: "
                    f"{device}"
                )
            )


        if fall:

            plan[
                "display_reasons"
            ].append(
                (
                    "既往护理事件: "
                    f"{fall['summary']}"
                )
            )


        # -------------------------------------------------
        # 这里必须看整个老人对话历史，
        # 不能只看当前一句。
        #
        # 例如：
        # 第2轮：“今天比平时明显一点”
        # 第3轮：“走路还稳，我想出去走一会儿”
        #
        # 第3轮仍然应该记住第2轮已经完成了
        # “与本人平时基线比较”。
        # -------------------------------------------------

        comparison_done = (
            _contains_any(
                conversation_text,
                [
                    "比平时",
                    "和平时",
                    "和平常",
                    "比平常",
                    "明显一点",
                    "明显一些",
                    "更酸",
                    "更疼",
                    "更难受",
                    "差不多",
                    "严重一点",
                    "厉害一点",
                ],
            )
        )

        walking_known = (
            _contains_any(
                conversation_text,
                [
                    "走路还稳",
                    "走路挺稳",
                    "走路稳定",
                    "走路还算稳",
                    "还算稳",
                    "站得稳",
                    "站立还稳",
                    "走路不稳",
                    "站不稳",
                ],
            )
        )

        asking_activity = (
            _contains_any(
                user_text,
                [
                    "出去",
                    "走走",
                    "散步",
                    "活动",
                    "下楼",
                    "能走",
                    "可以走",
                ],
            )
        )


        # -------------------------------------------------
        # 第一阶段：
        # 既往病史 + 本人基线比较
        # -------------------------------------------------

        if (
            round_no <= 1
            or not comparison_done
        ):

            plan[
                "strategy"
            ] = (
                "baseline_comparison"
            )

            if knee_condition:

                plan[
                    "must_use"
                ].append(
                    (
                        "数据库中有已确认的既往病史："
                        f"{knee_condition['condition_name']}。"
                        "必须明确这是既往记录，"
                        "不能把本次症状重新诊断为该疾病。"
                    )
                )

            if usual_knee:

                plan[
                    "must_use"
                ].append(
                    (
                        "老人自己的护理基线："
                        f"{usual_knee}。"
                    )
                )

            plan[
                "preferred_question"
            ] = (
                "今天这种膝部不适和您平时相比，"
                "是差不多还是明显一些？"
            )

            plan[
                "required_groups"
            ] = [
                {
                    "name":
                        "既往膝部健康记录",

                    "any":
                        [
                            "关节炎",
                            "膝关节",
                            "既往",
                            "记录",
                            "档案",
                            "之前",
                        ],
                },
                {
                    "name":
                        "个人基线比较",

                    "any":
                        [
                            "平时",
                            "平常",
                            "以前",
                            "以往",
                            "相比",
                        ],
                },
            ]

            plan[
                "fallback_reply"
            ] = (
                "您的档案里记录过既往膝骨关节炎，"
                "平时膝部偶尔也会有些酸胀。"
                "今天这种不舒服和平时相比，"
                "是差不多还是明显一些？"
            )


        # -------------------------------------------------
        # 老人正在询问能否活动：
        # 必须用到其平时的辅助器具
        # -------------------------------------------------

        elif (
            asking_activity
            and device
        ):

            plan[
                "strategy"
            ] = (
                "activity_guidance_with_device"
            )

            plan[
                "must_use"
            ].append(
                (
                    "老人平时的辅助器具："
                    f"{device}。"
                    "回答活动问题时必须体现这条个体信息。"
                )
            )

            plan[
                "required_groups"
            ] = [
                {
                    "name":
                        "个人辅助器具",

                    "any":
                        [
                            "手杖",
                            "拐杖",
                        ],
                },
            ]

            plan[
                "fallback_reply"
            ] = (
                "您平时外出会使用手杖，"
                "今天如果要出去活动也请继续使用。"
                "先少量活动，不要勉强，"
                "膝盖明显不舒服就停下来休息。"
            )


        # -------------------------------------------------
        # 已比较出与平时不同后：
        # 与本人平时活动功能继续比较
        # -------------------------------------------------

        elif not walking_known:

            plan[
                "strategy"
            ] = (
                "functional_baseline_comparison"
            )

            if walking:

                plan[
                    "must_use"
                ].append(
                    (
                        "老人平时活动能力："
                        f"{walking}。"
                    )
                )

            if fall:

                plan[
                    "must_use"
                ].append(
                    (
                        "老人既往存在跌倒记录，"
                        "因此本轮要关注行走安全，"
                        "但不要夸大风险。"
                    )
                )

            plan[
                "preferred_question"
            ] = (
                "您现在站起来和走路，"
                "还和平时一样稳吗？"
            )

            plan[
                "required_groups"
            ] = [
                {
                    "name":
                        "个人功能基线",

                    "any":
                        [
                            "平时",
                            "平常",
                            "以前",
                            "以往",
                        ],
                },
                {
                    "name":
                        "站立或行走功能",

                    "any":
                        [
                            "走路",
                            "行走",
                            "站起来",
                            "站立",
                        ],
                },
            ]

            plan[
                "fallback_reply"
            ] = (
                "既然今天比平时明显一些，"
                "我再和您平时的活动状态比较一下。"
                "您现在站起来和走路，"
                "还和平时一样稳吗？"
            )


        else:

            plan[
                "strategy"
            ] = (
                "profile_aware_follow_up"
            )


    # =====================================================
    # sleep：睡眠个体化护理
    # =====================================================

    elif care_domain == "sleep":

        usual_sleep = (
            baseline.get(
                "usual_sleep"
            )
        )

        if usual_sleep:

            plan[
                "personalized"
            ] = True

            plan[
                "display_reasons"
            ].append(
                (
                    "个人睡眠基线: "
                    f"{usual_sleep}"
                )
            )


            # 最近一次同领域历史咨询仅作为背景，
            # 不要求每轮向老人复述。
            memories = (
                profile.get(
                    "memories",
                    [],
                )
            )

            if (
                memories
                and round_no <= 1
            ):

                latest_memory = (
                    memories[0]
                )

                plan.setdefault(
                    "context_facts",
                    [],
                ).append(
                    (
                        "老人既往睡眠护理咨询："
                        f"{latest_memory['summary']}"
                    )
                )

                plan[
                    "display_reasons"
                ].append(
                    (
                        "既往护理咨询: "
                        f"{latest_memory['summary']}"
                    )
                )


            user_history_text = "\n".join(
                str(
                    item.get(
                        "content",
                        "",
                    )
                )
                for item in (
                    history or []
                )
                if item.get(
                    "role"
                )
                == "user"
            )

            sleep_text = (
                user_history_text
                + "\n"
                + user_text
            )


            comparison_done = any(
                marker in sleep_text
                for marker in [
                    "比平时",
                    "和平时比",
                    "比平常",
                    "和平常比",
                    "比以前",
                    "比之前",
                    "醒得更多",
                    "醒的更多",
                    "更难入睡",
                    "更难睡着",
                    "更难再睡",
                    "睡得更差",
                    "睡的更差",
                ]
            )


            duration_known = any(
                marker in sleep_text
                for marker in [
                    "昨晚",
                    "昨天晚上",
                    "前天",
                    "一晚上",
                    "一夜",
                    "这两天",
                    "两天",
                    "两三天",
                    "三天",
                    "几天",
                    "这几天",
                    "连续",
                    "一周",
                    "好几晚",
                    "几晚",
                ]
            )


            # “白天有点犯困”“白天还是挺精神”等
            # 中间经常会插入口语程度词，
            # 因此不能只依赖完整固定短语。
            daytime_known = (
                "白天" in sleep_text
                and any(
                    marker in sleep_text
                    for marker in [
                        "困",
                        "犯困",
                        "没精神",
                        "精神",
                        "疲倦",
                        "很累",
                        "还好",
                        "正常",
                        "影响",
                    ]
                )
            )


            # -------------------------------------------------
            # 第一步：和本人平时睡眠比较
            # -------------------------------------------------

            if (
                round_no <= 1
                or not comparison_done
            ):

                plan[
                    "strategy"
                ] = (
                    "sleep_baseline_comparison"
                )

                plan[
                    "must_use"
                ].append(
                    (
                        "老人自己的睡眠基线："
                        f"{usual_sleep}。"
                    )
                )


                if any(
                    word in user_text
                    for word in [
                        "睡不着",
                        "入睡",
                        "很久才睡",
                    ]
                ):

                    question = (
                        "这次入睡和平时相比，"
                        "是不是更困难？"
                    )

                    fallback = (
                        "您的护理档案显示，"
                        "平时睡眠总体有自己的规律。"
                        "这次入睡和平时相比，"
                        "是不是更困难？"
                    )

                elif "醒" in user_text:

                    question = (
                        "这次夜里醒的情况和平时相比，"
                        "是不是更明显？"
                    )

                    fallback = (
                        "您平时偶尔夜里会醒一次，"
                        "多数还能再次入睡。"
                        "这次夜里醒的情况和平时相比，"
                        "是不是更明显？"
                    )

                else:

                    question = (
                        "这次睡眠和平时相比，"
                        "是不是明显差一些？"
                    )

                    fallback = (
                        "您的护理档案里记录，"
                        "平时偶尔夜里会醒，"
                        "多数还能再次入睡。"
                        "这次睡眠和平时相比，"
                        "是不是明显差一些？"
                    )


                plan[
                    "preferred_question"
                ] = question

                plan[
                    "required_groups"
                ] = [
                    {
                        "name":
                            "睡眠个人基线比较",

                        "any": [
                            "平时",
                            "平常",
                            "以前",
                            "相比",
                        ],
                    },
                ]

                plan[
                    "fallback_reply"
                ] = fallback


            # -------------------------------------------------
            # 第二步：持续时间
            # -------------------------------------------------

            elif not duration_known:

                plan[
                    "strategy"
                ] = (
                    "sleep_duration_assessment"
                )

                plan[
                    "preferred_question"
                ] = (
                    "这种比平时更明显的睡不好，"
                    "大概持续多久了？"
                )

                plan[
                    "required_groups"
                ] = [
                    {
                        "name":
                            "睡眠持续时间评估",

                        "any": [
                            "多久",
                            "几天",
                            "持续",
                            "昨晚",
                        ],
                    },
                ]

                plan[
                    "fallback_reply"
                ] = (
                    "这次睡眠比您平时更受影响。"
                    "这种情况大概持续多久了？"
                )


            # -------------------------------------------------
            # 第三步：白天影响
            # -------------------------------------------------

            elif not daytime_known:

                plan[
                    "strategy"
                ] = (
                    "sleep_daytime_impact"
                )

                plan[
                    "preferred_question"
                ] = (
                    "今天白天有没有因为睡不好，"
                    "明显犯困或者没精神？"
                )

                plan[
                    "required_groups"
                ] = [
                    {
                        "name":
                            "睡眠白天影响",

                        "any": [
                            "白天",
                            "犯困",
                            "没精神",
                            "精神",
                        ],
                    },
                ]

                plan[
                    "fallback_reply"
                ] = (
                    "我再了解一下睡眠对您白天状态的影响。"
                    "今天白天有没有明显犯困或者没精神？"
                )


            else:

                plan[
                    "strategy"
                ] = (
                    "sleep_profile_aware_follow_up"
                )


    # =====================================================
    # appetite：食欲个体化护理
    # =====================================================

    elif care_domain == "appetite":

        usual_appetite = (
            baseline.get(
                "usual_appetite"
            )
        )

        if usual_appetite:

            plan[
                "personalized"
            ] = True

            plan[
                "display_reasons"
            ].append(
                (
                    "个人食欲基线: "
                    f"{usual_appetite}"
                )
            )


            memories = (
                profile.get(
                    "memories",
                    [],
                )
            )

            if (
                memories
                and round_no <= 1
            ):

                latest_memory = (
                    memories[0]
                )

                plan.setdefault(
                    "context_facts",
                    [],
                ).append(
                    (
                        "老人既往饮食护理咨询："
                        f"{latest_memory['summary']}"
                    )
                )

                plan[
                    "display_reasons"
                ].append(
                    (
                        "既往护理咨询: "
                        f"{latest_memory['summary']}"
                    )
                )


            user_history_text = "\n".join(
                str(
                    item.get(
                        "content",
                        "",
                    )
                )
                for item in (
                    history or []
                )
                if item.get(
                    "role"
                )
                == "user"
            )

            appetite_text = (
                user_history_text
                + "\n"
                + user_text
            )


            comparison_done = any(
                marker in appetite_text
                for marker in [
                    "比平时",
                    "和平时比",
                    "比平常",
                    "比以前",
                    "比之前",
                    "少一半",
                    "只吃一半",
                    "不到一半",
                    "明显少",
                    "少很多",
                    "吃得更少",
                    "吃的更少",
                    "没怎么吃",
                    "几乎没吃",
                ]
            )


            duration_known = any(
                marker in appetite_text
                for marker in [
                    "今天",
                    "昨天",
                    "这两天",
                    "两天",
                    "两三天",
                    "三天",
                    "几天",
                    "这几天",
                    "连续",
                    "一周",
                    "一直",
                ]
            )


            # 兼容：
            # “水还喝得下”
            # “喝水和平时差不多”
            # “水喝得比较少”等自然说法。
            water_context = any(
                marker in appetite_text
                for marker in [
                    "喝水",
                    "饮水",
                    "水还",
                    "水也",
                    "水喝",
                    "喝得下水",
                    "喝不下水",
                ]
            )

            hydration_known = (
                water_context
                and any(
                    marker in appetite_text
                    for marker in [
                        "喝得下",
                        "喝不下",
                        "差不多",
                        "正常",
                        "少",
                        "多",
                    ]
                )
            )


            # -------------------------------------------------
            # 第一步：和个人食欲基线比较
            # -------------------------------------------------

            if (
                round_no <= 1
                or not comparison_done
            ):

                plan[
                    "strategy"
                ] = (
                    "appetite_baseline_comparison"
                )

                plan[
                    "must_use"
                ].append(
                    (
                        "老人自己的食欲基线："
                        f"{usual_appetite}。"
                    )
                )

                plan[
                    "preferred_question"
                ] = (
                    "这次的食量和您平时相比，"
                    "大概少了多少？"
                )

                plan[
                    "required_groups"
                ] = [
                    {
                        "name":
                            "食欲个人基线比较",

                        "any": [
                            "平时",
                            "平常",
                            "以前",
                            "相比",
                        ],
                    },
                ]

                plan[
                    "fallback_reply"
                ] = (
                    "您的护理档案显示，"
                    "平时大部分正餐都能正常进食。"
                    "这次的食量和平时相比，"
                    "大概少了多少？"
                )


            # -------------------------------------------------
            # 第二步：持续时间
            # -------------------------------------------------

            elif not duration_known:

                plan[
                    "strategy"
                ] = (
                    "appetite_duration_assessment"
                )

                plan[
                    "preferred_question"
                ] = (
                    "这种胃口变差大概持续多久了？"
                )

                plan[
                    "required_groups"
                ] = [
                    {
                        "name":
                            "食欲持续时间评估",

                        "any": [
                            "多久",
                            "几天",
                            "持续",
                        ],
                    },
                ]

                plan[
                    "fallback_reply"
                ] = (
                    "您的食量已经比平时少一些。"
                    "这种胃口变差大概持续多久了？"
                )


            # -------------------------------------------------
            # 第三步：饮水情况
            #
            # 已经知道食量下降后，只再问一个信息点：
            # 是否还能正常饮水。
            # -------------------------------------------------

            elif not hydration_known:

                plan[
                    "strategy"
                ] = (
                    "appetite_hydration_assessment"
                )

                plan[
                    "preferred_question"
                ] = (
                    "今天喝水还和平时差不多吗？"
                )

                plan[
                    "required_groups"
                ] = [
                    {
                        "name":
                            "饮水情况评估",

                        "any": [
                            "喝水",
                            "饮水",
                            "水",
                        ],
                    },
                ]

                plan[
                    "fallback_reply"
                ] = (
                    "我再了解一下您现在的饮水情况。"
                    "今天喝水还和平时差不多吗？"
                )


            else:

                plan[
                    "strategy"
                ] = (
                    "appetite_profile_aware_follow_up"
                )


    # =====================================================
    # dizziness：头晕个体化护理
    # =====================================================

    elif care_domain == "dizziness":

        usual_dizziness = (
            baseline.get(
                "usual_dizziness_state"
            )
        )

        if usual_dizziness:

            plan[
                "personalized"
            ] = True

            plan[
                "display_reasons"
            ].append(
                (
                    "个人一般状态基线: "
                    f"{usual_dizziness}"
                )
            )

            plan[
                "must_use"
            ].append(
                (
                    "老人平时的一般状态基线："
                    f"{usual_dizziness}。"
                )
            )


            # 高血压等既往心血管记录只能作为背景，
            # 绝不能据此推断头晕病因。
            cardiovascular = next(
                (
                    item
                    for item
                    in profile.get(
                        "conditions",
                        [],
                    )
                    if item.get(
                        "condition_category"
                    )
                    == "cardiovascular"
                ),
                None,
            )

            if cardiovascular:

                plan.setdefault(
                    "context_facts",
                    [],
                ).append(
                    (
                        "既往健康背景："
                        f"{cardiovascular['condition_name']}。"
                        "只能作为工作人员后续了解时的背景，"
                        "不得说它导致了本次头晕。"
                    )
                )

                plan[
                    "display_reasons"
                ].append(
                    (
                        "既往健康背景: "
                        f"{cardiovascular['condition_name']}"
                        "（不作为头晕病因判断）"
                    )
                )


            conversation_text = (
                _history_text(
                    history,
                    role="user",
                )
                + "\n"
                + user_text
            )


            function_known = (
                _contains_any(
                    conversation_text,
                    [
                        "走路还稳",
                        "走路正常",
                        "站得稳",
                        "站着还稳",
                        "站起来还行",
                        "走路不稳",
                        "站不稳",
                        "走路发飘",
                        "站起来晃",
                        "影响走路",
                    ],
                )
                or (
                    _contains_any(
                        conversation_text,
                        [
                            "站",
                            "走路",
                            "行走",
                        ],
                    )
                    and _contains_any(
                        conversation_text,
                        [
                            "稳",
                            "不稳",
                            "发飘",
                            "摇晃",
                            "晃",
                        ],
                    )
                )
            )


            timing_known = _contains_any(
                conversation_text,
                [
                    "刚刚",
                    "刚才",
                    "今天",
                    "早上",
                    "上午",
                    "下午",
                    "晚上",
                    "昨天",
                    "这两天",
                    "几天",
                    "一会儿",
                    "半小时",
                    "一个小时",
                ],
            )


            repeated_known = _contains_any(
                conversation_text,
                [
                    "第一次",
                    "偶尔",
                    "反复",
                    "经常",
                    "总是",
                    "以前也有",
                    "之前也有",
                ],
            )


            if not function_known:

                plan[
                    "strategy"
                ] = (
                    "dizziness_function_assessment"
                )

                plan[
                    "preferred_question"
                ] = (
                    "您现在站起来或者走路时，"
                    "会不会比平时更不稳？"
                )

                plan[
                    "required_groups"
                ] = [
                    {
                        "name":
                            "头晕安全提醒",

                        "any": [
                            "坐稳",
                            "坐下",
                            "不要突然起身",
                            "不要急着起身",
                            "避免突然起身",
                        ],
                    },
                    {
                        "name":
                            "头晕功能影响评估",

                        "any": [
                            "站",
                            "走路",
                            "行走",
                            "稳",
                        ],
                    },
                ]

                plan[
                    "fallback_reply"
                ] = (
                    "您平时站立和行走通常比较稳定，"
                    "现在有头晕时先坐稳，不要急着起身。"
                    "您现在站起来或者走路时，"
                    "会不会比平时更不稳？"
                )


            elif not timing_known:

                plan[
                    "strategy"
                ] = (
                    "dizziness_timing_assessment"
                )

                plan[
                    "preferred_question"
                ] = (
                    "这次头晕大概从什么时候开始的？"
                )

                plan[
                    "required_groups"
                ] = [
                    {
                        "name":
                            "头晕出现时间",

                        "any": [
                            "什么时候",
                            "多久",
                            "开始",
                        ],
                    },
                ]

                plan[
                    "fallback_reply"
                ] = (
                    "先继续坐稳休息，不要突然起身。"
                    "这次头晕大概从什么时候开始的？"
                )


            elif not repeated_known:

                plan[
                    "strategy"
                ] = (
                    "dizziness_recurrence_assessment"
                )

                plan[
                    "preferred_question"
                ] = (
                    "最近这种头晕是第一次出现，"
                    "还是已经反复出现过？"
                )

                plan[
                    "required_groups"
                ] = [
                    {
                        "name":
                            "头晕是否反复",

                        "any": [
                            "第一次",
                            "反复",
                            "以前",
                            "之前",
                            "经常",
                        ],
                    },
                ]

                plan[
                    "fallback_reply"
                ] = (
                    "我再了解一下这种头晕是不是反复出现。"
                    "最近这是第一次，还是以前也出现过？"
                )


            else:

                plan[
                    "strategy"
                ] = (
                    "dizziness_profile_aware_follow_up"
                )


    # =====================================================
    # bowel：排便护理
    # =====================================================

    elif care_domain == "bowel":

        usual_bowel = (
            baseline.get(
                "usual_bowel_pattern"
            )
        )

        if usual_bowel:

            plan[
                "personalized"
            ] = True

            plan[
                "display_reasons"
            ].append(
                (
                    "个人排便基线: "
                    f"{usual_bowel}"
                )
            )


            conversation_text = (
                _history_text(
                    history,
                    role="user",
                )
                + "\n"
                + user_text
            )


            interval_known = _contains_any(
                conversation_text,
                [
                    "一天",
                    "两天",
                    "三天",
                    "四天",
                    "五天",
                    "几天",
                    "好几天",
                    "昨天",
                    "前天",
                    "每天",
                    "隔天",
                ],
            )


            difficulty_known = _contains_any(
                conversation_text,
                [
                    "费力",
                    "费劲",
                    "困难",
                    "排不出来",
                    "解不出来",
                    "很难排",
                    "不费力",
                    "还算顺畅",
                    "比较顺畅",
                ],
            )


            activity_change_known = (
                _contains_any(
                    conversation_text,
                    [
                        "活动少",
                        "活动量少",
                        "没怎么活动",
                        "没怎么动",
                        "和平时一样活动",
                        "活动正常",
                        "走动少",
                    ],
                )
                or (
                    "活动" in conversation_text
                    and _contains_any(
                        conversation_text,
                        [
                            "少",
                            "减少",
                            "没怎么",
                            "正常",
                            "一样",
                            "差不多",
                        ],
                    )
                )
                or (
                    "走动" in conversation_text
                    and _contains_any(
                        conversation_text,
                        [
                            "少",
                            "减少",
                            "正常",
                            "一样",
                        ],
                    )
                )
            )


            if round_no <= 1:

                plan[
                    "must_use"
                ].append(
                    (
                        "老人自己的排便基线："
                        f"{usual_bowel}。"
                    )
                )


                if interval_known:

                    plan[
                        "strategy"
                    ] = (
                        "bowel_difficulty_assessment"
                    )

                    plan[
                        "preferred_question"
                    ] = (
                        "这次排便时会不会比平时明显更费力？"
                    )

                else:

                    plan[
                        "strategy"
                    ] = (
                        "bowel_interval_assessment"
                    )

                    plan[
                        "preferred_question"
                    ] = (
                        "您平时通常每天或隔天排便，"
                        "这次大概多久没有排便了？"
                    )


            elif not interval_known:

                plan[
                    "strategy"
                ] = (
                    "bowel_interval_assessment"
                )

                plan[
                    "preferred_question"
                ] = (
                    "这次大概多久没有排便了？"
                )


            elif not difficulty_known:

                plan[
                    "strategy"
                ] = (
                    "bowel_difficulty_assessment"
                )

                plan[
                    "preferred_question"
                ] = (
                    "这次排便时会不会比平时明显更费力？"
                )


            elif not activity_change_known:

                plan[
                    "strategy"
                ] = (
                    "bowel_activity_change_assessment"
                )

                plan[
                    "preferred_question"
                ] = (
                    "最近活动量和平时相比，"
                    "有没有明显减少？"
                )


            else:

                plan[
                    "strategy"
                ] = (
                    "bowel_profile_aware_follow_up"
                )

                plan[
                    "must_use"
                ].append(
                    (
                        "本轮只能依据审核护理知识给出一般建议："
                        "可以提醒适量饮水、保持日常活动、"
                        "保持规律排便习惯。"
                        "不要解释便秘的生理机制，"
                        "不要说活动减少导致或影响肠道蠕动，"
                        "不要推荐任何药物。"
                    )
                )

                plan[
                    "required_groups"
                ] = [
                    {
                        "name":
                            "审核范围内的排便护理建议",

                        "any": [
                            "饮水",
                            "日常活动",
                            "规律排便",
                            "排便习惯",
                        ],
                    },
                ]

                plan[
                    "fallback_reply"
                ] = (
                    "这两天您的活动量比平时少一些。"
                    "可以注意适量饮水，"
                    "尽量保持平时的日常活动和规律排便习惯。"
                )


            if plan.get(
                "preferred_question"
            ):

                plan[
                    "required_groups"
                ] = [
                    {
                        "name":
                            "排便护理评估",

                        "any": [
                            "排便",
                            "费力",
                            "多久",
                            "活动",
                            "平时",
                        ],
                    },
                ]

                plan[
                    "fallback_reply"
                ] = (
                    plan[
                        "preferred_question"
                    ]
                )


    # =====================================================
    # fatigue：疲劳与一般状态
    # =====================================================

    elif care_domain == "fatigue":

        usual_energy = (
            baseline.get(
                "usual_energy_level"
            )
        )

        if usual_energy:

            plan[
                "personalized"
            ] = True

            plan[
                "display_reasons"
            ].append(
                (
                    "个人精神活动基线: "
                    f"{usual_energy}"
                )
            )


            conversation_text = (
                _history_text(
                    history,
                    role="user",
                )
                + "\n"
                + user_text
            )


            comparison_done = _contains_any(
                conversation_text,
                [
                    "比平时累",
                    "比平常累",
                    "比以前累",
                    "更累",
                    "比平时乏力",
                    "比平时没精神",
                    "精神比平时差",
                    "和平时差不多",
                ],
            )


            duration_known = _contains_any(
                conversation_text,
                [
                    "今天",
                    "昨天",
                    "这两天",
                    "两三天",
                    "三天",
                    "几天",
                    "这几天",
                    "一周",
                    "一直",
                    "最近",
                ],
            )


            function_known = _contains_any(
                conversation_text,
                [
                    "影响活动",
                    "日常活动",
                    "起床",
                    "洗漱",
                    "做饭",
                    "走几步",
                    "走路就累",
                    "活动正常",
                    "还能活动",
                    "不影响活动",
                ],
            )


            if (
                round_no <= 1
                or not comparison_done
            ):

                plan[
                    "strategy"
                ] = (
                    "fatigue_baseline_comparison"
                )

                plan[
                    "must_use"
                ].append(
                    (
                        "老人自己的精神和活动基线："
                        f"{usual_energy}。"
                    )
                )

                plan[
                    "preferred_question"
                ] = (
                    "这次觉得累和您平时相比，"
                    "是不是明显一些？"
                )

                plan[
                    "required_groups"
                ] = [
                    {
                        "name":
                            "疲劳个人基线比较",

                        "any": [
                            "平时",
                            "平常",
                            "以前",
                            "相比",
                        ],
                    },
                ]

                plan[
                    "fallback_reply"
                ] = (
                    "您平时白天精神还可以，"
                    "能够完成日常室内活动。"
                    "这次觉得累和平时相比，"
                    "是不是明显一些？"
                )


            elif not duration_known:

                plan[
                    "strategy"
                ] = (
                    "fatigue_duration_assessment"
                )

                plan[
                    "preferred_question"
                ] = (
                    "这种比平时更累的情况，"
                    "大概持续多久了？"
                )


            elif not function_known:

                plan[
                    "strategy"
                ] = (
                    "fatigue_function_assessment"
                )

                plan[
                    "preferred_question"
                ] = (
                    "现在这种疲劳有没有影响"
                    "您平时的日常活动？"
                )


            else:

                plan[
                    "strategy"
                ] = (
                    "fatigue_profile_aware_follow_up"
                )


            if (
                plan.get(
                    "preferred_question"
                )
                and not plan.get(
                    "required_groups"
                )
            ):

                plan[
                    "required_groups"
                ] = [
                    {
                        "name":
                            "疲劳护理评估",

                        "any": [
                            "多久",
                            "持续",
                            "活动",
                            "平时",
                        ],
                    },
                ]

                plan[
                    "fallback_reply"
                ] = (
                    plan[
                        "preferred_question"
                    ]
                )


    # =====================================================
    # 本轮档案选择
    #
    # all_profile_reasons：
    #     后台完整相关档案。
    #
    # display_reasons：
    #     本轮真正参与当前护理决策的档案。
    #
    # 避免比赛终端每一轮机械打印所有病史。
    # =====================================================

    plan[
        "all_profile_reasons"
    ] = list(
        plan.get(
            "display_reasons",
            [],
        )
    )


    if care_domain == "mobility":

        strategy = plan.get(
            "strategy"
        )

        if (
            strategy
            == "baseline_comparison"
        ):

            prefixes = (
                "既往护理咨询:",
                "既往病史:",
                "个人基线:",
            )

        elif (
            strategy
            == "functional_baseline_comparison"
        ):

            prefixes = (
                "个人基线:",
                "活动基线:",
                "既往护理事件:",
            )

            # 这一阶段不再需要把既往咨询摘要
            # 每轮重复送给大模型。
            plan[
                "context_facts"
            ] = []

        elif (
            strategy
            == "activity_guidance_with_device"
        ):

            prefixes = (
                "个人基线:",
                "活动基线:",
                "辅助器具:",
            )

            plan[
                "context_facts"
            ] = []

        else:

            prefixes = None


        if prefixes:

            plan[
                "display_reasons"
            ] = [
                item
                for item
                in plan[
                    "all_profile_reasons"
                ]
                if item.startswith(
                    prefixes
                )
            ]


    return plan


def build_personalization_prompt(
    plan,
):

    if not plan.get(
        "personalized"
    ):

        return ""


    lines = [
        "[PERSONALIZED_CARE_PROFILE]",
        (
            "下面的信息来自数据库中已确认的老人个人健康档案和护理基线。"
        ),
        (
            "只能把既往疾病作为已确认的历史背景，"
            "不能据此诊断本次症状的病因。"
        ),
        (
            "本轮必须体现与该老人本人有关的信息，"
            "不能退化成任何老人都适用的通用回答。"
        ),
        "",
    ]


    context_facts = (
        plan.get(
            "context_facts",
            [],
        )
    )

    if context_facts:

        lines.extend([
            "",
            "[RELEVANT_CARE_HISTORY]",
            (
                "以下是相关的既往护理咨询摘要。"
            ),
            (
                "可以用于理解变化趋势，"
                "但不要机械逐条向老人朗读。"
            ),
        ])

        for item in context_facts:

            lines.append(
                f"- {item}"
            )


    for item in plan.get(
        "must_use",
        [],
    ):

        lines.append(
            f"- {item}"
        )


    strategy = plan.get(
        "strategy"
    )

    if strategy:

        lines.extend([
            "",
            "[PERSONALIZATION_STRATEGY]",
            strategy,
        ])


    question = plan.get(
        "preferred_question"
    )

    strategy = plan.get(
        "strategy"
    )


    if question:

        lines.extend([
            "",
            "[CURRENT_PERSONALIZATION_GOAL]",
            question,
        ])


    # -----------------------------------------------------
    # 首轮个体化：
    # 强制压缩成两句话，避免模型生成三句后
    # 被 clean_reply 截断，导致个体化检查失败。
    # -----------------------------------------------------

    if (
        strategy
        == "baseline_comparison"
    ):

        lines.extend([
            "",
            "[OUTPUT_STRUCTURE]",
            (
                "本轮尽量严格使用两句话。"
            ),
            (
                "第一句话：自然结合既往健康记录"
                "和老人自己的平时护理基线。"
            ),
            (
                "第二句话：只询问当前情况"
                "和本人平时相比是否有明显变化。"
            ),
            (
                "不要分别用三句话介绍病史、"
                "介绍基线、再提问。"
            ),
        ])


    # -----------------------------------------------------
    # 功能基线比较：
    # 如果老人当前没有提出新的明确问题，
    # 必须完成这一个功能追问。
    # -----------------------------------------------------

    elif (
        strategy
        == "functional_baseline_comparison"
        and question
    ):

        lines.extend([
            "",
            "[OUTPUT_STRUCTURE]",
            (
                "如果老人本轮没有提出需要直接回答的"
                "具体问题，本轮必须完成下面这个"
                "唯一护理追问："
            ),
            question,
            (
                "可以先有一句简短安全提醒，"
                "但最多只能再提出这一个问题。"
            ),
        ])


    # -----------------------------------------------------
    # 当前已经需要工作人员关注时的活动建议
    # -----------------------------------------------------

    elif (
        strategy
        == "activity_guidance_with_device"
    ):

        lines.extend([
            "",
            "[ACTIVITY_GUIDANCE]",
            (
                "必须结合老人平时使用的辅助器具。"
            ),
            (
                "如果当前风险已经是 needs_staff，"
                "不要主动鼓励老人外出或说"
                "“可以放心出去走走”。"
            ),
            (
                "应表达为：如果确实需要活动，"
                "减少活动量、继续使用平时的辅助器具、"
                "不要勉强，明显不适时停止并休息。"
            ),
            (
                "不要给出精确分钟数、距离、步数"
                "或运动强度。"
            ),
        ])


    lines.extend([
        "",
        (
            "不要机械朗读数据库字段，"
            "要把个体信息自然地融入护理对话。"
        ),
    ])


    return "\n".join(
        lines
    )


def check_personalized_reply(
    reply,
    plan,
):

    reply = str(
        reply or ""
    )

    groups = (
        plan.get(
            "required_groups",
            [],
        )
    )

    missing = []

    for group in groups:

        words = (
            group.get(
                "any",
                [],
            )
        )

        if not any(
            word in reply
            for word in words
        ):

            missing.append(
                group.get(
                    "name",
                    "unknown",
                )
            )


    return {
        "passed":
            not missing,

        "missing":
            missing,

        "strategy":
            plan.get(
                "strategy"
            ),

        "personalized":
            bool(
                plan.get(
                    "personalized"
                )
            ),
    }


# =========================================================
# 个体化风险修正
#
# 注意：
# - 既往疾病本身不能直接把风险升级。
# - 既往跌倒本身也不能直接把当前咨询升级。
# - 只有当前状态相对该老人自己的已确认基线发生
#   明确变化时，才作为额外护理关注依据。
# =========================================================


def build_personalized_risk_modifier(
    *,
    elderly_id,
    care_domain,
    user_text,
    history=None,
):

    profile = (
        get_personal_care_profile(
            elderly_id,
            care_domain,
        )
    )

    baseline = (
        _baseline_map(
            profile
        )
    )

    user_text = str(
        user_text or ""
    ).strip()

    user_history = (
        _history_text(
            history,
            role="user",
        )
    )

    conversation_text = (
        user_history
        + "\n"
        + user_text
    )


    def has_any(
        value,
        words,
    ):

        return any(
            word in value
            for word in words
        )


    empty_result = {
        "applied":
            False,

        "risk_level":
            None,

        "modifier":
            None,

        "matched":
            [],

        "reason":
            None,

        "baseline_used":
            None,
    }


    # =====================================================
    # mobility / 膝部
    # =====================================================

    if (
        care_domain == "mobility"
        and "膝" in conversation_text
    ):

        usual_knee = (
            baseline.get(
                "usual_knee_state"
            )
        )

        if not usual_knee:
            return empty_result


        baseline_worsened = has_any(
            user_text,
            [
                "比平时明显",
                "比平常明显",
                "比以前明显",
                "比平时严重",
                "比平常严重",
                "比以前严重",
                "比平时更疼",
                "比平时更酸",
                "比平时更不舒服",
                "明显一点",
                "明显一些",
                "更明显",
                "严重一点",
                "严重一些",
                "厉害一点",
                "厉害一些",
            ],
        )


        if baseline_worsened:

            return {
                "applied":
                    True,

                "risk_level":
                    "needs_staff",

                "modifier":
                    "personal_baseline_worsened",

                "matched": [
                    "personal_baseline_worsened",
                ],

                "reason":
                    (
                        "当前膝部不适较老人本人"
                        "平时护理基线更加明显"
                    ),

                "baseline_used":
                    usual_knee,
            }


        return empty_result


    # =====================================================
    # sleep
    #
    # 单独一个晚上睡得差：
    #   只标记“偏离本人基线”，继续评估。
    #
    # 基线明显变化 + 持续多日 / 白天明显受影响：
    #   needs_staff
    # =====================================================

    if care_domain == "sleep":

        usual_sleep = (
            baseline.get(
                "usual_sleep"
            )
        )

        if not usual_sleep:
            return empty_result


        current_change = has_any(
            user_text,
            [
                "比平时睡得差",
                "比平时睡的差",
                "比平常差",
                "比以前差",
                "比平时醒得多",
                "比平时醒的多",
                "醒得更多",
                "醒的更多",
                "更难入睡",
                "更难睡着",
                "更难再睡",
                "明显睡不好",
                "明显差一些",
                "明显差很多",
                "三四次",
                "好几次",
                "反复醒",
            ],
        )


        previous_change = has_any(
            conversation_text,
            [
                "比平时睡得差",
                "比平时睡的差",
                "比平常差",
                "比以前差",
                "比平时醒得多",
                "比平时醒的多",
                "醒得更多",
                "醒的更多",
                "更难入睡",
                "更难睡着",
                "更难再睡",
                "三四次",
                "好几次",
                "反复醒",
            ],
        )


        persistent = has_any(
            conversation_text,
            [
                "这两天",
                "两三天",
                "三天",
                "几天",
                "这几天",
                "连续",
                "好几晚",
                "一周",
                "一直",
            ],
        )


        daytime_impact_current = (
            "白天" in user_text
            and has_any(
                user_text,
                [
                    "困",
                    "犯困",
                    "没精神",
                    "精神不好",
                    "精神差",
                    "疲倦",
                    "很累",
                    "影响",
                ],
            )
        )


        # 睡眠升级为 needs_staff 采用较严格标准：
        #
        # 1. 已明确比本人平时睡眠基线更差；
        # 2. 问题不是仅偶发一晚，而是持续存在；
        # 3. 白天状态已经明显受到影响。
        #
        # 单独一晚睡差 + 第二天轻微犯困，
        # 仍属于继续护理观察范围。
        if (
            previous_change
            and persistent
            and daytime_impact_current
        ):

            return {
                "applied":
                    True,

                "risk_level":
                    "needs_staff",

                "modifier":
                    "personal_sleep_baseline_worsened",

                "matched": [
                    "personal_sleep_baseline_worsened",
                ],

                "reason":
                    (
                        "睡眠情况较老人本人平时基线明显变化，"
                        "且问题持续并已经影响白天状态"
                    ),

                "baseline_used":
                    usual_sleep,
            }


        if current_change:

            return {
                "applied":
                    True,

                "risk_level":
                    None,

                "modifier":
                    "personal_sleep_baseline_changed",

                "matched": [
                    "personal_sleep_baseline_changed",
                ],

                "reason":
                    (
                        "本次睡眠较老人本人平时基线有所变化，"
                        "需要继续了解持续时间和白天影响"
                    ),

                "baseline_used":
                    usual_sleep,
            }


        return empty_result


    # =====================================================
    # appetite
    #
    # 轻度、短时食欲下降：
    #   继续评估。
    #
    # 明显进食减少并持续，
    # 或已经影响饮水 / 基本进食：
    #   needs_staff
    # =====================================================

    if care_domain == "appetite":

        usual_appetite = (
            baseline.get(
                "usual_appetite"
            )
        )

        if not usual_appetite:
            return empty_result


        baseline_changed_current = has_any(
            user_text,
            [
                "没什么胃口",
                "胃口不好",
                "胃口不太好",
                "食欲不好",
                "食欲下降",
                "吃得少",
                "吃的少",
                "饭量少",
                "食量少",
                "比平时少",
            ],
        )


        marked_reduction_current = has_any(
            user_text,
            [
                "少一半",
                "少了一半",
                "只吃一半",
                "不到一半",
                "少很多",
                "明显少",
                "几乎没吃",
                "没怎么吃",
                "吃不下",
            ],
        )


        marked_reduction_history = has_any(
            conversation_text,
            [
                "少一半",
                "少了一半",
                "只吃一半",
                "不到一半",
                "少很多",
                "明显少",
                "几乎没吃",
                "没怎么吃",
                "吃不下",
            ],
        )


        persistent = has_any(
            conversation_text,
            [
                "这两天",
                "两三天",
                "三天",
                "几天",
                "这几天",
                "连续",
                "一周",
                "一直",
            ],
        )


        hydration_problem_current = has_any(
            user_text,
            [
                "水也喝不下",
                "喝不下水",
                "不怎么喝水",
                "喝水也少",
                "水喝得少",
                "饮水也少",
            ],
        )


        if (
            hydration_problem_current
            or (
                marked_reduction_history
                and persistent
                and marked_reduction_current
            )
        ):

            return {
                "applied":
                    True,

                "risk_level":
                    "needs_staff",

                "modifier":
                    "personal_appetite_baseline_worsened",

                "matched": [
                    "personal_appetite_baseline_worsened",
                ],

                "reason":
                    (
                        (
                            "当前饮水情况也受到影响，"
                            "建议工作人员进一步关注"
                            if hydration_problem_current
                            else
                            "当前进食情况较老人本人平时食欲基线"
                            "明显下降，且已经持续存在"
                        )
                    ),

                "baseline_used":
                    usual_appetite,
            }


        if (
            baseline_changed_current
            or marked_reduction_current
        ):

            return {
                "applied":
                    True,

                "risk_level":
                    None,

                "modifier":
                    "personal_appetite_baseline_changed",

                "matched": [
                    "personal_appetite_baseline_changed",
                ],

                "reason":
                    (
                        "当前食欲较老人本人平时基线有所下降，"
                        "需要继续了解进食量、持续时间和饮水情况"
                    ),

                "baseline_used":
                    usual_appetite,
            }


        return empty_result


    # =====================================================
    # dizziness
    #
    # 通用风险层已经固定 needs_staff；
    # 此处只增加“为什么这个老人值得关注”的个体化依据。
    # =====================================================

    if care_domain == "dizziness":

        usual_dizziness = (
            baseline.get(
                "usual_dizziness_state"
            )
        )

        if (
            usual_dizziness
            and has_any(
                user_text,
                [
                    "头晕",
                    "眩晕",
                    "晕",
                    "眼前发黑",
                ],
            )
        ):

            return {
                "applied":
                    True,

                "risk_level":
                    "needs_staff",

                "modifier":
                    "personal_dizziness_baseline_changed",

                "matched": [
                    "personal_dizziness_baseline_changed",
                ],

                "reason":
                    (
                        "当前出现头晕，与老人本人平时"
                        "一般状态基线存在变化；"
                        "头晕场景采用保守护理策略"
                    ),

                "baseline_used":
                    usual_dizziness,
            }


        return empty_result


    # =====================================================
    # bowel
    #
    # 排便模式发生变化本身先继续护理评估。
    # 是否需要工作人员关注继续交给通用风险规则。
    # =====================================================

    if care_domain == "bowel":

        usual_bowel = (
            baseline.get(
                "usual_bowel_pattern"
            )
        )

        if (
            usual_bowel
            and has_any(
                user_text,
                [
                    "便秘",
                    "没排便",
                    "没大便",
                    "排不出来",
                    "解不出来",
                    "排便困难",
                    "排便费力",
                ],
            )
        ):

            return {
                "applied":
                    True,

                "risk_level":
                    None,

                "modifier":
                    "personal_bowel_baseline_changed",

                "matched": [
                    "personal_bowel_baseline_changed",
                ],

                "reason":
                    (
                        "当前排便情况较老人本人"
                        "平时排便基线发生变化，"
                        "需要继续了解排便间隔和困难程度"
                    ),

                "baseline_used":
                    usual_bowel,
            }


        return empty_result


    # =====================================================
    # fatigue
    #
    # 较个人基线更疲劳：
    #   先继续评估。
    #
    # 如果这种变化持续存在或已经影响日常活动：
    #   needs_staff。
    # =====================================================

    if care_domain == "fatigue":

        usual_energy = (
            baseline.get(
                "usual_energy_level"
            )
        )

        if not usual_energy:
            return empty_result


        baseline_change = has_any(
            conversation_text,
            [
                "比平时累",
                "比平常累",
                "比以前累",
                "比平时更累",
                "更累",
                "比平时乏力",
                "比平时没精神",
                "精神比平时差",
            ],
        )


        persistent = has_any(
            conversation_text,
            [
                "这两天",
                "两三天",
                "三天",
                "几天",
                "这几天",
                "好几天",
                "一周",
                "一直",
            ],
        )


        function_impact = has_any(
            conversation_text,
            [
                "影响活动",
                "影响日常",
                "起床都累",
                "起床费劲",
                "洗漱都累",
                "做饭都累",
                "走几步就累",
                "走路就累",
                "活动不了",
            ],
        )


        if (
            baseline_change
            and (
                persistent
                or function_impact
            )
        ):

            return {
                "applied":
                    True,

                "risk_level":
                    "needs_staff",

                "modifier":
                    "personal_fatigue_baseline_worsened",

                "matched": [
                    "personal_fatigue_baseline_worsened",
                ],

                "reason":
                    (
                        "疲劳程度较老人本人平时状态明显增加，"
                        "并存在持续或影响日常活动的表现"
                    ),

                "baseline_used":
                    usual_energy,
            }


        if baseline_change:

            return {
                "applied":
                    True,

                "risk_level":
                    None,

                "modifier":
                    "personal_fatigue_baseline_changed",

                "matched": [
                    "personal_fatigue_baseline_changed",
                ],

                "reason":
                    (
                        "当前疲劳较老人本人平时"
                        "精神活动基线有所增加，"
                        "需要继续了解持续时间和日常影响"
                    ),

                "baseline_used":
                    usual_energy,
            }


        return empty_result


    return empty_result

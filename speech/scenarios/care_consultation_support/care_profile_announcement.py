from __future__ import annotations

import re


def _split_reason(
    reason,
):

    text = str(
        reason or ""
    ).strip()

    if not text:
        return "", ""


    for separator in (
        ":",
        "：",
    ):

        if separator in text:

            label, value = (
                text.split(
                    separator,
                    1,
                )
            )

            return (
                label.strip(),
                value.strip(
                    " 。；;,"
                ),
            )


    return (
        "",
        text.strip(
            " 。；;,"
        ),
    )


def _render_reason(
    reason,
):

    label, value = (
        _split_reason(
            reason
        )
    )

    if not value:
        return None


    if label == "既往护理咨询":

        # 个体化模块可能把历史次数附在：
        # “……。（1次）”
        #
        # 演示播报改成自然口语，
        # 避免直接朗读括号。
        count_match = re.search(
            r"（(\d+)次）$",
            value,
        )

        count = None

        if count_match:

            count = (
                count_match.group(1)
            )

            value = (
                value[
                    :count_match.start()
                ]
                .rstrip(
                    "。；; "
                )
            )


        # 典型历史摘要：
        # 曾就膝部酸胀进行过护理咨询，
        # 当时行走稳定，休息后不适有所缓解。
        summary_match = re.match(
            r"^曾就(.+?)进行过护理咨询[，,](.+)$",
            value,
        )

        if (
            count
            and summary_match
        ):

            topic = (
                summary_match
                .group(1)
                .strip()
            )

            remainder = (
                summary_match
                .group(2)
                .strip()
            )

            return (
                f"此前有过{count}次"
                f"{topic}相关的护理咨询，"
                f"{remainder}"
            )


        if count:

            return (
                f"此前记录过{count}次相关护理咨询，"
                + value
            )


        return (
            "此前的护理咨询记录显示，"
            + value
        )


    if label == "既往病史":

        return (
            "既往健康记录中有"
            + value
        )


    if label in {
        "个人基线",
        "个人睡眠基线",
        "个人食欲基线",
        "个人排便基线",
        "个人精神活动基线",
        "活动基线",
    }:

        return (
            "您的个人护理基线记录显示，"
            + value
        )


    if label == "辅助器具":

        return (
            "平时辅助器具记录显示，"
            + value
        )


    if label == "既往护理事件":

        return (
            "既往护理记录显示，"
            + value
        )


    return (
        "护理档案中记录，"
        + value
    )


def build_showcase_profile_announcement(
    personalization_plan,
    *,
    announced_reasons=None,
    max_items=3,
):

    plan = (
        personalization_plan
        if isinstance(
            personalization_plan,
            dict,
        )
        else {}
    )

    if not plan.get(
        "personalized",
        False,
    ):

        return {
            "text": None,
            "items": [],
            "reason_keys": [],
        }


    reasons = (
        plan.get(
            "display_reasons"
        )
        or []
    )


    already = set(
        announced_reasons
        or ()
    )


    items = []
    reason_keys = []


    for reason in reasons:

        key = str(
            reason or ""
        ).strip()

        if (
            not key
            or key in already
        ):
            continue


        rendered = (
            _render_reason(
                key
            )
        )

        if not rendered:
            continue


        items.append(
            rendered
        )

        reason_keys.append(
            key
        )


        if len(items) >= max(
            1,
            int(max_items),
        ):
            break


    if not items:

        return {
            "text": None,
            "items": [],
            "reason_keys": [],
        }


    text = (
        "我查到与这次情况相关的个人护理档案："
        + "；".join(
            items
        )
        + "。"
        + "我会结合这些记录继续了解。"
    )


    return {
        "text":
            text,

        "items":
            items,

        "reason_keys":
            reason_keys,
    }

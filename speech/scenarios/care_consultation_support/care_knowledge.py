from __future__ import annotations

import json
from pathlib import Path


KNOWLEDGE_PATH = (
    Path(__file__).resolve().parent
    / "care_knowledge.json"
)


def _normalize(
    text,
):

    return (
        str(text or "")
        .lower()
        .replace(" ", "")
    )


def load_care_knowledge():

    with KNOWLEDGE_PATH.open(
        "r",
        encoding="utf-8",
    ) as f:

        return json.load(f)


CARDS = load_care_knowledge()


def retrieve_care_knowledge(
    *,
    text,
    care_domain,
    risk_level,
    top_k=3,
):

    # 紧急情况优先执行本地安全流程，
    # 不继续依靠普通护理知识生成建议。
    if risk_level == "urgent":
        return []

    query = _normalize(
        text
    )

    candidates = []

    for card in CARDS:

        domain = card.get(
            "domain"
        )

        # 优先当前护理领域；
        # general_care 可以作为通用补充。
        if domain not in {
            care_domain,
            "general_care",
        }:
            continue

        score = 0

        if domain == care_domain:
            score += 10

        for keyword in card.get(
            "keywords",
            [],
        ):

            if _normalize(
                keyword
            ) in query:

                score += 4

        # needs_staff 时，
        # 优先包含升级条件的知识卡。
        if (
            risk_level
            == "needs_staff"
            and card.get(
                "escalate_if"
            )
        ):
            score += 1

        candidates.append(
            (
                score,
                card["id"],
                card,
            )
        )

    candidates.sort(
        key=lambda x: (
            -x[0],
            x[1],
        )
    )

    return [
        item[2]
        for item in candidates[
            :max(
                1,
                int(top_k),
            )
        ]
    ]


def knowledge_refs(
    cards,
):

    return [
        {
            "id":
                card.get(
                    "id"
                ),

            "title":
                card.get(
                    "title"
                ),

            "source":
                card.get(
                    "source"
                ),
        }
        for card in (
            cards or []
        )
    ]


def format_knowledge_for_prompt(
    cards,
):

    if not cards:

        return ""

    parts = [
        """
[CURATED_CARE_KNOWLEDGE]
以下内容来自经过筛选的养老护理知识卡。
只能在与老人当前情况相符时使用。
知识卡不能替代风险判断，也不能作为疾病诊断依据。
"""
    ]

    for index, card in enumerate(
        cards,
        start=1,
    ):

        parts.append(
            (
                f"\n知识卡{index}："
                f"{card['title']}\n"
                f"安全护理要点："
                f"{card['guidance']}\n"
                f"可选追问："
                f"{card['followup']}\n"
                f"升级条件："
                f"{card['escalate_if']}\n"
                f"禁止事项："
                f"{card['avoid']}\n"
            )
        )

    parts.append(
        """
[KNOWLEDGE_USAGE_RULES]
- 不需要逐条复述知识卡。
- 只选当前最相关的1个护理要点回答。
- 不向老人朗读知识来源名称。
- 如果知识卡与本地风险等级冲突，以本地风险等级为准。
- 不因为知识卡存在就降低风险等级。

- 当本轮提供了护理知识卡时，
  具体护理建议必须能够直接追溯到这些知识卡。
- 不得自行增加知识卡中没有出现的饮食、
  饮水、运动、睡眠或药物建议。
- 追问也应优先来自知识卡中的“可选追问”。
- 如果知识卡不足以支持一个具体建议，
  可以进行一般性的情况了解，
  但不要自行补充新的护理措施。
- 任何情况下都不能通过常识自由发挥
  来替代本地护理知识库。
"""
    )

    return "".join(
        parts
    )

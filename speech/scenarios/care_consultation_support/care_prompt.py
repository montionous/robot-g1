from __future__ import annotations


DOMAIN_LABELS = {
    "mobility":
        "肢体活动与肌肉关节不适",

    "dizziness":
        "头晕与一般状态",

    "sleep":
        "睡眠护理",

    "appetite":
        "饮食与食欲",

    "bowel":
        "排便与生活护理",

    "fatigue":
        "疲劳与一般状态",

    "general_care":
        "一般日常护理",
}


# =========================================================
# 本地审核护理知识卡
#
# 这些内容不是诊断结论，
# 用于限制大模型只能在低风险护理范围内回答。
# =========================================================

DOMAIN_KNOWLEDGE = {

    "mobility": [
        (
            "了解不适部位、持续时间、"
            "是否与活动相关，以及休息后是否缓解。"
        ),
        (
            "关注近期是否跌倒、扭伤或碰撞，"
            "并了解站立、行走和平衡是否受到影响。"
        ),
        (
            "低风险情况下强调活动与休息交替，"
            "避免勉强进行明显诱发不适的活动，"
            "同时注意行走安全和防跌倒。"
        ),
        (
            "如果不适持续、反复、逐渐明显"
            "或已经影响日常活动，"
            "应由工作人员进一步了解。"
        ),
    ],

    "dizziness": [
        (
            "先让老人保持安全姿势，"
            "避免头晕时突然起身或独自行走。"
        ),
        (
            "了解头晕出现时间、是否反复，"
            "以及是否已经影响站立或行走。"
        ),
        (
            "老年人出现新的或反复头晕时，"
            "应由工作人员进一步了解。"
        ),
    ],

    "sleep": [
        (
            "了解入睡困难、夜间易醒或早醒等表现，"
            "以及持续时间和白天影响。"
        ),
        (
            "可提供规律作息、睡前减少刺激、"
            "保持舒适睡眠环境等一般护理建议。"
        ),
        (
            "如果睡眠问题持续并明显影响白天状态，"
            "建议工作人员进一步了解。"
        ),
    ],

    "appetite": [
        (
            "了解食欲下降持续多久，"
            "是否仍能正常进食和饮水。"
        ),
        (
            "低风险情况下可建议少量多次、"
            "选择老人容易接受的食物，"
            "并注意补充水分。"
        ),
        (
            "如果持续吃不下或明显影响日常状态，"
            "建议工作人员进一步了解。"
        ),
    ],

    "bowel": [
        (
            "了解排便间隔、排便困难情况"
            "以及近期生活习惯是否变化。"
        ),
        (
            "低风险情况下可提醒适量饮水、"
            "保持日常活动和规律排便习惯。"
        ),
        (
            "近期活动量变化只能作为护理背景记录，"
            "不要直接断言活动减少导致便秘，"
            "也不要自行解释肠道蠕动等生理机制。"
        ),
        (
            "不要自行建议老人使用处方药"
            "或随意增加药物。"
        ),
    ],

    "fatigue": [
        (
            "了解疲劳持续时间、活动后变化"
            "以及是否影响日常生活。"
        ),
        (
            "低风险情况下可建议适当休息、"
            "活动与休息交替并保证基本饮食饮水。"
        ),
        (
            "持续或逐渐加重的疲劳"
            "应由工作人员进一步了解。"
        ),
    ],

    "general_care": [
        (
            "先了解不适出现时间、变化趋势"
            "以及是否影响日常活动。"
        ),
        (
            "只提供低风险、非诊断性的"
            "一般护理信息。"
        ),
    ],
}


def response_mode_for_risk(
    risk_level,
):

    if risk_level == "needs_staff":
        return "staff_follow_up"

    return "basic_care"


def assessment_stage(
    *,
    round_no,
    risk_level,
):

    if risk_level == "needs_staff":
        return "staff_follow_up"

    if round_no <= 1:
        return "initial_assessment"

    return "follow_up"


def build_policy_context(
    *,
    care_domain,
    risk_level,
    round_no,
    max_rounds,
):

    response_mode = (
        response_mode_for_risk(
            risk_level
        )
    )

    care_stage = (
        assessment_stage(
            round_no=round_no,
            risk_level=risk_level,
        )
    )

    domain_label = (
        DOMAIN_LABELS.get(
            care_domain,
            "一般日常护理",
        )
    )

    knowledge_used = (
        DOMAIN_KNOWLEDGE.get(
            care_domain,
            DOMAIN_KNOWLEDGE[
                "general_care"
            ],
        )
    )

    tags = {
        "SCENARIO":
            "care_consultation_support",

        "CARE_DOMAIN":
            care_domain,

        "RISK_LEVEL":
            risk_level,

        "RESPONSE_MODE":
            response_mode,

        "CARE_STAGE":
            care_stage,

        "ROUND":
            str(round_no),
    }

    knowledge_text = "\n".join(
        f"- {item}"
        for item in knowledge_used
    )

    context = f"""
[TAGS]
SCENARIO=care_consultation_support
CARE_DOMAIN={care_domain}
RISK_LEVEL={risk_level}
RESPONSE_MODE={response_mode}
CARE_STAGE={care_stage}

[CARE_CONTEXT]
当前护理领域：{domain_label}

[CARE_KNOWLEDGE]
{knowledge_text}

[PROFESSIONAL_CARE_METHOD]
- 先理解老人当前最主要的不适。
- 护理评估优先关注：持续时间、变化趋势、诱发因素、缓解因素、近期外伤，以及对站立、行走、睡眠、饮食等日常功能的影响。
- 信息不足时，只追问一个当前最有价值的问题。
- 不要为了凑轮次而重复提问。
- 已经获得的信息不要重复询问。
- 给建议时，要说明老人现在可以做什么，而不是只说空泛的“注意休息”。

[SAFETY_RULES]
- 不进行疾病诊断，不说“您得了某某病”。
- 不猜测具体疾病原因。
- 不保证症状一定没有危险。
- 不推荐处方药。
- 不调整老人当前药物和剂量。
- 不让老人自行停药、加药或换药。
- 不提供侵入性操作。
- 不要求老人自行进行有跌倒风险的测试。
- 只提供低风险、一般性的基础护理信息。
- 回复必须适合通过机器人语音播报。
- 不使用Markdown、列表、标题。
"""

    if risk_level == "low":

        context += """
[RESPONSE_REQUIREMENT]
- 回复1到2句话。
- 优先体现护理评估逻辑。
- 可以给出一项简单、明确、低风险的护理建议。
- 如果需要追问，本轮只能获取一个新的护理信息点。
- 一个回复里绝不能同时询问“持续多久”和“有没有摔倒”等两个问题。
- 不要把两个问题用“以及”“另外”“还有”“或者”等词合并。
- 如果老人已经主动提供了某项信息，就不要再询问该信息。
- 对肢体活动不适，按照当前缺失信息逐步评估，不要一次问完。

[MOBILITY_ASSESSMENT_ORDER]
对于肢体活动或关节不适，优先顺序如下：
1. 如果持续时间未知，优先只询问持续多久。
2. 如果持续时间已经明确但近期外伤情况未知，再询问是否有摔倒、扭伤或碰撞。
3. 如果前两项已明确，再了解站立或走路是否稳定、是否受到影响。
4. 每一轮最多前进一步，不能跨两步同时提问。
"""

    elif risk_level == "needs_staff":

        context += """
[RESPONSE_REQUIREMENT]
- 回复1到2句话。
- 必须优先直接回答老人当前这一轮提出的问题。
- 已经确认过的信息不要再次追问，包括近期是否摔倒、是否扭伤、走路是否稳定等。
- 如果老人询问“还能不能走”“还能不能活动”这类日常活动问题，应给出保守、可执行的低风险建议，例如缩短活动时间、避免勉强、出现明显不适就停下来休息。
- 不要给出精确运动时长、步数或强度处方。
- 可以给一项当前安全、低风险的护理提醒，但该提醒必须直接来自本轮 CARE_KNOWLEDGE，不得增加知识卡之外的新护理措施。
- 如果 CARE_KNOWLEDGE 中没有必要的新建议，可以不额外给建议。
- 必须保持老人原话的含义，例如“食量少一半”只能表述为“食量比平时少了一半”，不要改成“胃口减半”。
- 明确说明因为情况持续、反复、加重或影响功能，建议工作人员进一步关注。
- 不询问“要不要记录”。
- 不询问“要不要联系工作人员”。
- 系统会自动完成护理记录和工作人员关注事项。
- 不要在你的回复中说“我会通知工作人员”“我会联系工作人员”或“我已经记录”，这些由程序统一追加。
- 你只需要说明为什么建议进一步关注，并给出当前安全、低风险的护理提醒。
- 不声称工作人员已经完成检查。
"""

    return {
        "tags":
            tags,

        "policy_context":
            context,

        "knowledge_used":
            knowledge_used,

        "care_stage":
            care_stage,
    }

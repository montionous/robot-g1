from __future__ import annotations

from care_headache_risk import classify_headache_risk


# =========================================================
# 不属于“日常护理咨询”的明显异常表现
#
# 这些不是 CARE_CONSULTATION_SUPPORT 的最高风险档。
# 检出后直接交给团队的异常处理场景。
# =========================================================

EXTERNAL_ABNORMALITY_PHRASES = [
    "胸口剧烈疼",
    "胸口很痛",
    "胸痛",
    "喘不上气",
    "呼吸困难",
    "不能呼吸",
    "意识不清",
    "叫不醒",
    "突然说不清话",
    "说话不清楚",
    "一边手脚没力",
    "一侧手脚没力",
    "一侧身体没力",
    "突然站不起来",
    "大量出血",
    "血止不住",
    "摔倒后站不起来",
    "跌倒后站不起来",
]


# =========================================================
# 日常护理范围内，
# 但建议工作人员进一步关注
# =========================================================

NEEDS_STAFF_PHRASES = [
    "好几天",
    "几天了",
    "一直",
    "反复",
    "越来越疼",
    "越来越痛",
    "越来越严重",
    "越来越不舒服",
    "比昨天明显",
    "比之前明显",
    "影响走路",
    "走路困难",
    "不能正常走路",
    "疼得睡不着",
    "一直吃不下",
    "连续吃不下",
    "一直没胃口",
]


def classify_risk(
    text,
    *,
    care_domain=None,
    history=None,
):

    value = (
        str(text or "")
        .replace(" ", "")
    )

    abnormal_hits = [
        phrase
        for phrase in EXTERNAL_ABNORMALITY_PHRASES
        if phrase in value
    ]

    if abnormal_hits:

        return {
            "risk_level":
                "external_route",

            "matched":
                abnormal_hits,

            "route_to":
                "URGENT_ASSISTANCE",
        }


    headache_risk = classify_headache_risk(text, history=history)
    if headache_risk is not None:
        return headache_risk

    staff_hits = [
        phrase
        for phrase in NEEDS_STAFF_PHRASES
        if phrase in value
    ]

    if staff_hits:

        return {
            "risk_level":
                "needs_staff",

            "matched":
                staff_hits,

            "route_to":
                None,
        }


    # 头晕在老年护理场景里采用更保守策略。
    if care_domain == "dizziness":

        return {
            "risk_level":
                "needs_staff",

            "matched":
                ["dizziness"],

            "route_to":
                None,
        }


    return {
        "risk_level":
            "low",

        "matched":
            [],

        "route_to":
            None,
    }

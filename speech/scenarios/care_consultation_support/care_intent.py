from __future__ import annotations

import re

CARE_TRIGGER_WORDS = [
    "不舒服",
    "难受",
    "疼",
    "痛",
    "酸",
    "酸痛",
    "头晕",
    "晕",
    "没精神",
    "乏力",
    "累",
    "睡不好",
    "睡得不太好",
    "昨晚没睡好",
    "晚上没睡好",
    "夜里醒",
    "醒了好几次",
    "醒了三四次",
    "睡得不好",
    "睡的不太好",
    "睡眠不好",
    "夜里总醒",
    "半夜醒",
    "睡不着",
    "失眠",
    "没胃口",
    "胃口不好",
    "胃口不太好",
    "食欲不好",
    "食欲下降",
    "食量少",
    "饭量少",
    "吃得少",
    "吃的少",
    "不想吃",
    "吃不下",
    "便秘",
    "没有排便",
    "没有大便",
    "走路不舒服",
    "没排便",
    "没大便",
    "排不出来",
    "解不出来",
    "排便困难",
    "排便费力",
    "容易累",
    "特别累",
    "精神差",
    "怎么办",
]


END_WORDS = [
    "不用了",
    "先这样吧",
    "先这样了",
    "那先这样",
    "那就这样",
    "就这样吧",
    "就这样了",
    "今天先这样",
    "今天就这样",
    "今天就到这",
    "今天先到这",
    "就到这吧",
    "先不问了",
    "不问了",
    "我想休息了",
    "我要休息了",
    "我先休息会儿",
    "我先休息一会儿",
    "改天再问",
    "改天再说",
]


FAMILY_WORDS = [
    "女儿",
    "儿子",
    "老伴",
    "家人",
    "孙子",
    "孙女",
]


STAFF_YES_WORDS = [
    "好",
    "好的",
    "可以",
    "行",
    "麻烦你",
    "帮我联系",
    "帮我记录",
    "联系工作人员",
]


STAFF_NO_WORDS = [
    "不用",
    "不用了",
    "先不用",
    "不要",
    "算了",
]


def normalize(
    text,
):

    return (
        str(text or "")
        .strip()
        .replace(" ", "")
    )


def is_care_trigger(
    text,
):

    value = normalize(text)

    return any(
        word in value
        for word in CARE_TRIGGER_WORDS
    )


def wants_to_end(
    text,
):

    value = normalize(
        text
    )

    # 去掉 ASR 常见句末标点和语气字符。
    value = (
        value
        .rstrip(
            "。！？!?，,"
        )
    )

    # “那就这样的”是口语/ASR常见形式，
    # 统一成“那就这样”。
    if value.endswith(
        "这样的"
    ):
        value = (
            value[:-1]
        )

    # 明确的短结束表达。
    if value in END_WORDS:
        return True

    # 较长句子的自然结束表达，
    # 只允许出现在句尾。
    return any(
        value.endswith(
            word
        )
        for word in END_WORDS
    )


def wants_contact_family(
    text,
):

    value = normalize(text)

    # ponytail: explicit request grammar; narrative ambiguity stays with the caller.
    clauses = re.split(r"[，,。！？!?；;]", value)
    request = clauses[0]
    cancel_action = r"联系|拨号|打(?:个)?电话|通话" if re.search(r"打(?:个)?电话|通话", request) else "联系"
    if any(re.fullmatch(
        rf"(?:先)?(?:算了(?:不用(?:了)?)?|不用(?:了)?|不需要(?:了)?|取消|(?:不用|不要|别)(?:再)?(?:{cancel_action})(?:了)?)(?:吧)?",
        clause,
    ) for clause in clauses[1:]):
        return False
    family = r"(?:我的?)?(?:" + "|".join(FAMILY_WORDS) + r")"
    return bool(re.fullmatch(
        r"(?:请(?:你|您)?|麻烦(?:你|您)?|(?:你|您)(?:能不能|能|可以|可不可以))?"
        r"(?:我(?:想|要)(?:让(?:你|您))?)?(?:帮我|替我)?"
        rf"(?:联系(?:一下|下)?{family}|给{family}(?:打(?:个)?电话|通话))"
        r"(?:好吗|可以吗|行吗|吧|吗)?",
        request,
    ))


def confirms_staff_contact(
    text,
):

    value = normalize(text)

    return any(
        word == value
        or word in value
        for word in STAFF_YES_WORDS
    )


def declines_staff_contact(
    text,
):

    value = normalize(text)

    return any(
        word == value
        or word in value
        for word in STAFF_NO_WORDS
    )


def detect_care_domain(
    text,
):

    value = normalize(text)

    if any(
        word in value
        for word in [
            "腿",
            "膝",
            "腰",
            "肩",
            "胳膊",
            "手臂",
            "脚",
            "走路",
            "站",
        ]
    ):
        return "mobility"

    if any(
        word in value
        for word in [
            "头晕",
            "眩晕",
            "眼前发黑",
            "晕",
        ]
    ):
        return "dizziness"

    if any(
        word in value
        for word in [
            "睡不好",
            "睡不着",
            "失眠",
            "夜里醒",
            "睡眠",
            "睡眠不好",
            "总醒",
            "醒了好几次",
            "入睡困难",
            "早醒",
            "睡不好",
            "睡得不太好",
            "昨晚没睡好",
            "晚上没睡好",
            "醒得多",
            "醒的多",
            "醒了三四次",
            "睡得不好",
            "睡的不太好",
            "夜醒",
            "半夜醒",
            "夜里醒",
        ]
    ):
        return "sleep"

    if any(
        word in value
        for word in [
            "没胃口",
            "不想吃",
            "吃不下",
            "食欲",
            "胃口",
            "吃饭",
            "进食",
            "食量",
            "饭量",
            "吃得少",
            "吃的少",
        ]
    ):
        return "appetite"

    if any(
        word in value
        for word in [
            "便秘",
            "大便",
            "排便",
            "没大便",
            "没排便",
            "排不出来",
            "解不出来",
        ]
    ):
        return "bowel"

    if any(
        word in value
        for word in [
            "累",
            "乏力",
            "没精神",
            "疲劳",
            "容易累",
            "特别累",
            "精神差",
        ]
    ):
        return "fatigue"

    return "general_care"

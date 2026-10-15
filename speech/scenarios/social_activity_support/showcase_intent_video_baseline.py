#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import re
import time

import requests

from showcase_protocol import (
    ALLOWED_BY_STATE,
    ASK_AVAILABILITY,
    ASK_LOCATION,
    ASK_REGISTRATION,
    ASK_TIME,
    CONFIRM_NO,
    CONFIRM_YES,
    END,
    JOIN,
    OTHER,
    QUERY,
    REPEAT_DETAILS,
    SELECT,
)


DEFAULT_MODEL = os.getenv(
    "SOCIAL_ACTIVITY_INTENT_MODEL",
    os.getenv(
        "COMPANION_LLM_MODEL",
        "qwen3.7-flash",
    ),
)


END_WORDS = [
    "先这样吧",
    "就这样吧",
    "不用了",
    "不问了",
    "结束吧",
    "先不看了",
    "没事了",
    "到这里吧",
]


QUERY_WORDS = [
    "有什么活动",
    "有哪些活动",
    "有什么集体活动",
    "有什么社区活动",
    "有什么安排",
    "有哪些安排",
    "帮我看看活动",
    "看看有什么活动",
]


SELECT_HINTS = [
    "感兴趣",
    "想了解",
    "想看看",
    "看看那个",
    "了解一下",
    "那个活动",
    "第一个",
    "第二个",
    "第三个",
    "第1个",
    "第2个",
    "第3个",
]


ACTIVITY_HINTS = [
    "唱歌",
    "合唱",
    "手工",
    "讲座",
    "观影",
    "电影",
    "聊天",
    "棋牌",
    "书法",
    "太极",
    "活动",
]


TIME_WORDS = [
    "几点",
    "什么时候",
    "多会儿",
    "时间",
    "几点开始",
    "几点结束",
    "开始来着",
]


LOCATION_WORDS = [
    "在哪里",
    "在哪儿",
    "哪儿",
    "什么地方",
    "几楼",
    "哪一层",
    "地点",
]


AVAILABILITY_WORDS = [
    "还有名额",
    "有名额",
    "名额",
    "人数限制",
    "限人数",
    "多少人",
    "满了吗",
    "满了没",
    "还能参加",
    "可以参加吗",
]


REGISTRATION_WORDS = [
    "需要报名",
    "要报名",
    "报名吗",
    "怎么报名",
    "需要登记",
    "要登记",
    "提前登记",
    "提前报名",
    "预约",
]


REPEAT_WORDS = [
    "再说一遍",
    "再说一下",
    "再介绍一下",
    "重新说一下",
    "我没记住",
    "没记住",
    "再讲一下",
    "详细说一下",

    "再给我介绍一遍",
    "给我再介绍一遍",
    "再介绍一遍",
    "介绍一遍",
]


JOIN_WORDS = [
    "我想参加",
    "我要参加",
    "我去参加",
    "那我参加",
    "那我去",
    "那我就去",
    "我想去",
    "我要去",
    "就参加这个",
    "参加这个",
]


YES_WORDS = [
    "对",
    "对的",
    "是",
    "是的",
    "好",
    "好的",
    "可以",
    "行",
    "确认",
    "帮我登记",
]


NO_WORDS = [
    "不用登记",
    "先不登记",
    "不登记了",
    "不用报名",
    "先不用",
    "不要了",
    "算了",
    "不参加了",
]


SYSTEM_PROMPT = """
你是养老陪护机器人的“社区集体活动意图分类器”。

你的任务只是分类，不聊天，不推荐活动，不生成回答。

当前比赛演示采用严格状态机。
你只能从“当前允许意图”中选择一个意图，
否则必须返回 other。

可能出现的意图：

query
老人询问今天、明天、上午、下午有哪些社区或集体活动。

select
老人从机器人刚才介绍的活动中选择或表示对某一个活动感兴趣。

ask_time
老人询问当前选中活动几点开始、几点结束、什么时候举行。

ask_location
老人询问当前选中活动在哪里、几楼、什么地点举行。

ask_availability
老人询问当前活动有没有名额、是否限人数、还能不能参加。

ask_registration
老人询问当前活动是否需要报名、登记、预约。

repeat_details
老人说没记住，希望机器人把当前活动完整信息重新介绍。

join
老人明确表示想参加当前活动。
“还能参加吗”属于 ask_availability，不属于 join。

confirm_yes
在机器人要求确认登记时，老人明确同意。

confirm_no
在机器人要求确认登记时，老人明确拒绝登记。

end
老人明确表示结束这次活动咨询。

other
闲聊、背景说话、描述性陈述、当前状态不相关的话，
或者无法可靠识别的内容。

ASR语义恢复要求：

- 老人原话来自语音识别，ASR可能出现近音字、
  漏字、替换词或者不自然的措辞。
- 不能只按ASR文字表面机械分类，
  要结合当前状态理解老人真实意图。
- 当前状态为 wait_select 时，
  老人正在从机器人刚刚介绍的社区活动中选择。
- 此时如果ASR文字明显指向某一种刚介绍过的活动，
  并表达继续了解、选择、想要那个活动等意思，
  应分类为 select。
- 例如当前是 wait_select，
  机器人刚介绍过“集体唱歌”，
  ASR识别成“继续唱歌吧”，
  应理解为老人指向唱歌活动，
  分类为 select，
  不要把它理解成娱乐播放控制。
- 本模块只处理社区活动咨询，
  不执行播放音乐、继续播放等娱乐指令。
- 但不要仅仅因为出现“唱歌”“手工”等名词
  就自动判为 select；
  如果只是无关描述或语义不明确，仍然返回 other。

重要要求：

1. 不要因为一句话提到了“活动”就自动分类。
2. “这个活动听起来挺不错的”属于 other。
3. “刚才几点来着”属于 ask_time。
4. “在哪儿来着”属于 ask_location。
5. “再完整说一遍”属于 repeat_details。
6. “那我去参加”属于 join。
7. 必须严格服从当前允许意图。
8. 只输出 JSON，不要解释，不要 Markdown。

格式：

{
  "intent": "ask_time",
  "confidence": 0.95
}
"""


def normalize(text):
    value = str(
        text or ""
    ).strip()

    value = re.sub(
        r"[\s，。！？,.!?、；;：:]+",
        "",
        value,
    )

    return value


def _contains_any(
    value,
    words,
):
    return any(
        word in value
        for word in words
    )


def raw_rule_intent(text):
    """
    只判断语义，不考虑状态。

    状态门禁在外层执行。
    这样“错序但语义明确”的命令不会被 Qwen
    重新解释成其他合法动作。
    """

    value = normalize(
        text
    )

    if not value:
        return OTHER

    # -----------------------------------------------------
    # 确认阶段相关语句优先保留语义
    # -----------------------------------------------------

    if _contains_any(
        value,
        NO_WORDS,
    ):
        return CONFIRM_NO

    # -----------------------------------------------------
    # 结束
    # -----------------------------------------------------

    if _contains_any(
        value,
        END_WORDS,
    ):
        return END

    # -----------------------------------------------------
    # 详情追问
    # “刚才几点来着”必须先识别成时间，
    # 不能因为“刚才”误判成重复完整详情。
    # -----------------------------------------------------

    if _contains_any(
        value,
        TIME_WORDS,
    ):
        return ASK_TIME

    if _contains_any(
        value,
        LOCATION_WORDS,
    ):
        return ASK_LOCATION

    if _contains_any(
        value,
        AVAILABILITY_WORDS,
    ):
        return ASK_AVAILABILITY

    if _contains_any(
        value,
        REGISTRATION_WORDS,
    ):
        return ASK_REGISTRATION

    if _contains_any(
        value,
        REPEAT_WORDS,
    ):
        return REPEAT_DETAILS

    # -----------------------------------------------------
    # 参加
    # -----------------------------------------------------

    if _contains_any(
        value,
        JOIN_WORDS,
    ):
        return JOIN

    # -----------------------------------------------------
    # 确认同意
    # -----------------------------------------------------

    if value in YES_WORDS:
        return CONFIRM_YES

    # -----------------------------------------------------
    # 查询
    # -----------------------------------------------------

    if _contains_any(
        value,
        QUERY_WORDS,
    ):
        return QUERY

    if (
        "活动" in value
        and _contains_any(
            value,
            [
                "今天",
                "明天",
                "上午",
                "下午",
                "晚上",
                "最近",
            ],
        )
        and _contains_any(
            value,
            [
                "什么",
                "哪些",
                "看看",
                "有",
            ],
        )
    ):
        return QUERY

    # -----------------------------------------------------
    # 选择活动
    # -----------------------------------------------------

    if _contains_any(
        value,
        SELECT_HINTS,
    ):
        return SELECT

    if (
        _contains_any(
            value,
            ACTIVITY_HINTS,
        )
        and _contains_any(
            value,
            [
                "那个",
                "这个",
                "了解",
                "看看",
                "想听听",
            ],
        )
    ):
        return SELECT

    # 比赛过程中老人可能直接说：
    # “唱歌那个”
    if (
        _contains_any(
            value,
            ACTIVITY_HINTS,
        )
        and "那个" in value
    ):
        return SELECT

    return OTHER


def _extract_json(text):
    value = str(
        text or ""
    ).strip()

    try:
        return json.loads(
            value
        )
    except json.JSONDecodeError:
        pass

    match = re.search(
        r"\{.*\}",
        value,
        flags=re.S,
    )

    if not match:
        raise ValueError(
            "LLM没有返回JSON"
        )

    return json.loads(
        match.group(0)
    )


class SocialActivityIntentLLM:

    def __init__(
        self,
        *,
        model=DEFAULT_MODEL,
        timeout=10,
    ):
        api_key = os.getenv(
            "DASHSCOPE_API_KEY"
        )

        workspace_id = os.getenv(
            "DASHSCOPE_WORKSPACE_ID"
        )

        if not api_key:
            raise RuntimeError(
                "缺少环境变量 DASHSCOPE_API_KEY"
            )

        if not workspace_id:
            raise RuntimeError(
                "缺少环境变量 DASHSCOPE_WORKSPACE_ID"
            )

        self.api_key = (
            api_key
        )

        self.workspace_id = (
            workspace_id
        )

        self.model = model
        self.timeout = timeout

        self.url = (
            f"https://{workspace_id}"
            ".cn-beijing.maas.aliyuncs.com"
            "/compatible-mode/v1"
            "/chat/completions"
        )

    def classify(
        self,
        text,
        *,
        state,
        allowed_intents,
    ):
        allowed = sorted(
            set(
                allowed_intents
            )
        )

        user_content = (
            f"当前状态：{state}\n"
            "当前允许意图："
            f"{', '.join(allowed)}\n"
            "老人原话："
            f"{str(text).strip()}"
        )

        payload = {
            "model":
                self.model,

            "messages": [
                {
                    "role":
                        "system",

                    "content":
                        SYSTEM_PROMPT,
                },
                {
                    "role":
                        "user",

                    "content":
                        user_content,
                },
            ],

            "enable_thinking":
                False,

            "temperature":
                0.0,

            "max_tokens":
                80,

            "stream":
                False,
        }

        start = (
            time.perf_counter()
        )

        response = (
            requests.post(
                self.url,

                headers={
                    "Authorization":
                        f"Bearer {self.api_key}",

                    "Content-Type":
                        "application/json",
                },

                json=payload,

                timeout=
                    self.timeout,
            )
        )

        elapsed_ms = (
            (
                time.perf_counter()
                - start
            )
            * 1000
        )

        if not response.ok:
            raise RuntimeError(
                "社交活动意图LLM调用失败: "
                f"HTTP {response.status_code} "
                f"{response.text[:300]}"
            )

        data = (
            response.json()
        )

        try:
            raw = (
                data["choices"][0]
                ["message"]
                ["content"]
            )

        except Exception as exc:
            raise RuntimeError(
                "无法解析LLM响应: "
                f"{data}"
            ) from exc

        parsed = (
            _extract_json(
                raw
            )
        )

        intent = str(
            parsed.get(
                "intent",
                OTHER,
            )
        ).strip()

        try:
            confidence = float(
                parsed.get(
                    "confidence",
                    0.0,
                )
            )
        except (
            TypeError,
            ValueError,
        ):
            confidence = 0.0

        return {
            "intent":
                intent,

            "confidence":
                confidence,

            "llm_ms":
                elapsed_ms,
        }


def classify_showcase_intent(
    text,
    *,
    state,
    llm=None,
    confidence_threshold=0.82,
):
    allowed = (
        ALLOWED_BY_STATE.get(
            state,
            set(),
        )
    )

    rule_intent = (
        raw_rule_intent(
            text
        )
    )

    # -----------------------------------------------------
    # 明确识别到某个动作，但当前状态不允许：
    # 直接静默拦截。
    #
    # 不再调用 Qwen 重新解释。
    # -----------------------------------------------------

    if (
        rule_intent
        != OTHER
    ):
        if (
            rule_intent
            in allowed
        ):
            return {
                "intent":
                    rule_intent,

                "source":
                    "rule",

                "confidence":
                    1.0,
            }

        return {
            "intent":
                OTHER,

            "source":
                "state_gate",

            "confidence":
                1.0,
        }

    # -----------------------------------------------------
    # 规则完全无法判断时才走 Qwen fallback
    # -----------------------------------------------------

    if llm is None:
        return {
            "intent":
                OTHER,

            "source":
                "rule_only",

            "confidence":
                0.0,
        }

    try:
        result = (
            llm.classify(
                text,
                state=state,
                allowed_intents=(
                    allowed
                    | {OTHER}
                ),
            )
        )

    except Exception:
        return {
            "intent":
                OTHER,

            "source":
                "llm_error",

            "confidence":
                0.0,
        }

    intent = str(
        result.get(
            "intent",
            OTHER,
        )
    ).strip()

    try:
        confidence = float(
            result.get(
                "confidence",
                0.0,
            )
        )
    except (
        TypeError,
        ValueError,
    ):
        confidence = 0.0

    if (
        intent
        not in allowed
        and intent != OTHER
    ):
        return {
            "intent":
                OTHER,

            "source":
                "llm_state_gate",

            "confidence":
                confidence,
        }

    if (
        confidence
        < confidence_threshold
    ):
        return {
            "intent":
                OTHER,

            "source":
                "llm_low_confidence",

            "confidence":
                confidence,
        }

    return {
        "intent":
            intent,

        "source":
            "llm",

        "confidence":
            confidence,

        "llm_ms":
            result.get(
                "llm_ms"
            ),
    }

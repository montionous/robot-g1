from __future__ import annotations

import json
import os
import re
import time

import requests

from demo_protocol import (
    ALLOWED_BY_STATE,
    END,
    NEXT_MUSIC,
    OTHER,
    PLAY_MUSIC,
    SPECIFIC_MEDIA_REQUEST,
    SWITCH_NEWS,
    SWITCH_OPERA,
)


DEFAULT_MODEL = os.getenv(
    "ENTERTAINMENT_DEMO_INTENT_MODEL",
    os.getenv(
        "COMPANION_LLM_MODEL",
        "qwen3.7-flash",
    ),
)


END_WORDS = (
    "不想听了",
    "不想听",
    "不想再听了",
    "不想再听",
    "不听了",
    "不用了",
    "别放了",
    "停止播放",
    "停了吧",
    "关掉",
    "结束",
    "先这样吧",
)


NEXT_WORDS = (
    "下一首",
    "换一首",
    "换首",
    "换一个",
    "下一个",
    "再换一首",
)


# 泛类别：比赛流程允许。
GENERIC_MUSIC_WORDS = (
    "音乐",
    "歌曲",
    "歌",
)

GENERIC_NEWS_WORDS = (
    "新闻",
    "资讯",
)

GENERIC_OPERA_WORDS = (
    "戏曲",
    "唱戏",
)


# 更细的媒体类型：
# 在 showcase 中视为“指定内容请求”，不允许推动固定流程。
SPECIFIC_OPERA_WORDS = (
    "秦腔",
    "京剧",
    "黄梅戏",
    "越剧",
    "豫剧",
    "评剧",
)


SPECIFIC_NEWS_WORDS = (
    "体育新闻",
    "篮球新闻",
    "乒乓球新闻",
    "足球新闻",
)


REQUEST_PHRASES = (
    "给我放",
    "给我听",
    "帮我放",
    "帮我换",
    "我想听",
    "想听",
    "放点",
    "听点",
    "来点",
    "播放",
)


SWITCH_PHRASES = (
    "换成",
    "切换到",
    "切到",
    "换到",
    "换个",
    "改成",
)


ROBOT_PREFIXES = (
    "机器人",
)


# Qwen负责识别语义，
# 当前状态是否允许执行由外部状态机负责。
ALL_SHOWCASE_INTENTS = {
    PLAY_MUSIC,
    NEXT_MUSIC,
    SWITCH_NEWS,
    SWITCH_OPERA,
    END,
    SPECIFIC_MEDIA_REQUEST,
    OTHER,
}


def compact(text):
    return re.sub(
        r"[\s，,。！？!?、：:；;]",
        "",
        str(text or ""),
    )


def strip_robot_prefix(text):
    value = compact(text)

    for prefix in ROBOT_PREFIXES:
        if value.startswith(prefix):
            value = value[len(prefix):]
            break

    return value


def contains_any(
    value,
    words,
):
    return any(
        word in value
        for word in words
    )


def looks_like_request(
    value,
):
    return (
        contains_any(
            value,
            REQUEST_PHRASES,
        )
        or
        contains_any(
            value,
            SWITCH_PHRASES,
        )
    )


def rule_classify(
    text,
    *,
    state,
):
    value = strip_robot_prefix(
        text
    )

    if not value:
        return None

    allowed = set(
        ALLOWED_BY_STATE.get(
            state,
            set(),
        )
    )

    # 明确结束。
    if contains_any(
        value,
        END_WORDS,
    ):
        return END

    # 下一首只在当前状态允许时作为 next。
    if (
        NEXT_MUSIC in allowed
        and
        contains_any(
            value,
            NEXT_WORDS,
        )
    ):
        return NEXT_MUSIC

    # ------------------------
    # 更具体的媒体请求
    # ------------------------

    # “换成秦腔 / 京剧 / 黄梅戏”等，
    # 不是泛类别“换成戏曲”。
    if (
        contains_any(
            value,
            SPECIFIC_OPERA_WORDS,
        )
        and
        looks_like_request(
            value
        )
    ):
        return SPECIFIC_MEDIA_REQUEST

    if (
        contains_any(
            value,
            SPECIFIC_NEWS_WORDS,
        )
        and
        looks_like_request(
            value
        )
    ):
        return SPECIFIC_MEDIA_REQUEST

    # ------------------------
    # 泛类别控制
    # ------------------------

    if PLAY_MUSIC in allowed:

        if (
            contains_any(
                value,
                GENERIC_MUSIC_WORDS,
            )
            and
            looks_like_request(
                value
            )
        ):
            return PLAY_MUSIC

    if SWITCH_NEWS in allowed:

        if (
            contains_any(
                value,
                GENERIC_NEWS_WORDS,
            )
            and
            looks_like_request(
                value
            )
        ):
            return SWITCH_NEWS

    if SWITCH_OPERA in allowed:

        if (
            contains_any(
                value,
                GENERIC_OPERA_WORDS,
            )
            and
            looks_like_request(
                value
            )
        ):
            return SWITCH_OPERA

    return None


class ShowcaseIntentLLM:

    def __init__(
        self,
        *,
        model=DEFAULT_MODEL,
        timeout=8,
    ):
        api_key = os.getenv(
            "DASHSCOPE_API_KEY"
        )

        workspace_id = os.getenv(
            "DASHSCOPE_WORKSPACE_ID"
        )

        if not api_key:
            raise RuntimeError(
                "缺少 DASHSCOPE_API_KEY"
            )

        if not workspace_id:
            raise RuntimeError(
                "缺少 DASHSCOPE_WORKSPACE_ID"
            )

        self.api_key = api_key
        self.workspace_id = workspace_id
        self.model = model
        self.timeout = timeout

        self.url = (
            f"https://{workspace_id}"
            ".cn-beijing.maas.aliyuncs.com"
            "/compatible-mode/v1/"
            "chat/completions"
        )


    def classify(
        self,
        text,
        *,
        state,
        allowed_intents,
    ):
        # 意图识别和流程授权分离。
        #
        # Qwen始终可以识别全部showcase意图，
        # 不因为当前state提前隐藏某些标签。
        #
        # allowed_intents 参数暂时保留，
        # 兼容已有调用接口。
        model_intents = set(
            ALL_SHOWCASE_INTENTS
        )

        allowed_text = ", ".join(
            sorted(
                model_intents
            )
        )

        system_prompt = f"""
你是养老陪护机器人比赛演示中的媒体控制意图分类器。

你只负责理解用户当前一句话的控制意图。
你不能聊天，也不能决定流程。

当前状态：
{state}

允许识别的标签：
{allowed_text}

实时滚动转写额外规则：

当前输入来自机器人麦克风的滚动实时转写，
不保证整段文字全部来自老人。

输入中可能同时包含：
- 正在播放的歌曲歌词；
- 新闻正文；
- 戏曲唱词；
- 机器人扬声器残留声音；
- ASR产生的无意义短文本或英文幻觉；
- 老人真正说出的控制命令。

必须严格遵守：

1. 纯歌曲歌词、纯新闻正文、纯戏曲唱词，
即使出现“音乐”“新闻”“戏曲”等词，
也必须判断为 other。

2. “Thank you.”、“Good.”、“Hmm.”、“Oh.”、
“嗯”“嗯嗯”等没有明确控制含义的内容，
必须判断为 other。

3. 只有能够明确判断老人正在要求机器人
播放、切换、下一首或结束时，
才能返回控制意图。

4. 如果转写前半部分明显属于媒体内容，
但后面夹有明确的老人控制请求，
允许提取其中的控制意图。

例如：

“甜蜜蜜你笑得甜蜜蜜”
-> other

“甜蜜蜜你笑得甜蜜蜜，换一首”
-> next_music

“今天新闻报道天气晴朗”
-> other

“今天新闻报道天气晴朗，我不听了”
-> end

“新闻里说今天有戏曲演出”
-> other

“新闻里说天气不错，给我换成戏曲”
-> switch_opera

不要因为一句话中仅仅出现某个类别名称，
就认为老人发出了控制请求。

标签含义：

play_music：
用户要求播放“音乐”这一泛类别。
例如：
“放点音乐”
“我想听点歌”

next_music：
用户要求切换到下一首当前音乐。
例如：
“换一首”
“下一首”

switch_news：
用户要求切换到“新闻”这一泛类别。
例如：
“换成新闻”
“我想听点新闻”

switch_opera：
用户要求切换到“戏曲”这一泛类别。
例如：
“换成戏曲”
“听点戏曲”

specific_media_request：
用户进一步指定了具体作品、人物、
新闻细分类别或戏曲种类。
例如：
“换成秦腔”
“放段京剧”
“我想听黄梅戏”
“给我放甜蜜蜜”
“放点体育新闻”

这些都不是泛类别切换。

end：
明确要求停止、结束或不再播放。

other：
不是明确媒体控制请求，
或者只是描述、评论、背景讲话。

特别注意：

1. 不要求用户每句话都说“机器人”。
   “换一首”“换成新闻”“不听了”
   都可以是正常控制命令。

2. 但描述性语句不能当控制：
   “这个音乐挺好听”
   “今天新闻里说天气不错”
   “京剧演员唱得很好”
   都必须是 other。

3. “换成秦腔”不是 switch_opera，
   必须是 specific_media_request。

4. “换成京剧”不是 switch_opera，
   必须是 specific_media_request。

5. “换成戏曲”才是 switch_opera。

6. 如果一句话表达的控制不属于
   当前流程允许执行的控制，也仍然先准确识别语义。
   最终是否执行由外部状态机决定。

只输出 JSON：

{{
  "intent": "other",
  "confidence": 0.95
}}
""".strip()

        payload = {
            "model":
                self.model,

            "messages": [
                {
                    "role":
                        "system",

                    "content":
                        system_prompt,
                },
                {
                    "role":
                        "user",

                    "content":
                        (
                            "用户原话："
                            f"{str(text).strip()}"
                        ),
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

        start = time.perf_counter()

        response = requests.post(
            self.url,

            headers={
                "Authorization":
                    f"Bearer {self.api_key}",

                "Content-Type":
                    "application/json",
            },

            json=payload,

            timeout=self.timeout,
        )

        elapsed_ms = (
            time.perf_counter()
            - start
        ) * 1000

        if not response.ok:
            raise RuntimeError(
                "演示意图LLM调用失败: "
                f"HTTP {response.status_code} "
                f"{response.text[:300]}"
            )

        data = response.json()

        try:
            raw = (
                data["choices"][0]
                ["message"]
                ["content"]
            )
        except Exception as exc:
            raise RuntimeError(
                f"无法解析LLM响应: {data}"
            ) from exc

        match = re.search(
            r"\{.*\}",
            str(raw or ""),
            flags=re.S,
        )

        if not match:
            raise RuntimeError(
                "LLM没有返回JSON"
            )

        parsed = json.loads(
            match.group(0)
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
                max(
                    0.0,
                    min(
                        1.0,
                        confidence,
                    ),
                ),

            "llm_ms":
                elapsed_ms,

            "model":
                self.model,
        }


def classify_showcase_intent(
    text,
    *,
    state,
    llm=None,
    confidence_threshold=0.82,
):
    """
    Showcase意图识别。

    正常链路：
        ASR
        -> Qwen
        -> confidence检查
        -> 返回语义intent
        -> 外部ShowcaseController负责状态授权

    规则只在：
        1. --no-llm
        2. Qwen调用异常
    时作为fallback。
    """

    value = str(
        text or ""
    ).strip()

    if not value:
        return {
            "intent":
                OTHER,

            "confidence":
                0.0,

            "source":
                "empty",
        }

    # -----------------------------------------------------
    # 正常模式：Qwen作为主意图识别器
    # -----------------------------------------------------

    if llm is not None:

        try:
            result = llm.classify(
                value,
                state=state,

                # 这里不再只传当前状态允许的intent。
                # Qwen负责理解语义；
                # 外部状态机决定是否执行。
                allowed_intents=
                    ALL_SHOWCASE_INTENTS,
            )

        except Exception as exc:

            # ---------------------------------------------
            # Qwen异常时才启用规则fallback
            # ---------------------------------------------

            rule_intent = (
                rule_classify(
                    value,
                    state=state,
                )
            )

            if rule_intent is not None:

                return {
                    "intent":
                        rule_intent,

                    "confidence":
                        1.0,

                    "source":
                        "rule_fallback",

                    "llm_error":
                        str(exc),
                }

            return {
                "intent":
                    OTHER,

                "confidence":
                    0.0,

                "source":
                    "llm_error",

                "error":
                    str(exc),
            }


        raw_intent = str(
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


        # 模型输出了未知标签：
        # 不执行，但也不使用规则覆盖模型语义。
        if (
            raw_intent
            not in ALL_SHOWCASE_INTENTS
        ):
            return {
                **result,

                "raw_intent":
                    raw_intent,

                "intent":
                    OTHER,

                "confidence":
                    confidence,

                "source":
                    "llm_invalid_intent",
            }


        # 低置信度：
        # 静默OTHER。
        #
        # 不再因为低置信度转去跑规则，
        # 否则又会重新变成“规则抢答”。
        if (
            confidence
            < confidence_threshold
        ):
            return {
                **result,

                "raw_intent":
                    raw_intent,

                "intent":
                    OTHER,

                "confidence":
                    confidence,

                "source":
                    "llm_low_confidence",
            }


        # 注意：
        # 这里故意不判断
        #
        #     raw_intent in ALLOWED_BY_STATE[state]
        #
        # 是否允许执行完全交给
        # ShowcaseController.handle()。
        return {
            **result,

            "intent":
                raw_intent,

            "confidence":
                confidence,

            "source":
                "llm",
        }


    # -----------------------------------------------------
    # 没有LLM：规则模式
    # -----------------------------------------------------

    rule_intent = rule_classify(
        value,
        state=state,
    )

    if rule_intent is not None:

        return {
            "intent":
                rule_intent,

            "confidence":
                1.0,

            "source":
                "rule_only",
        }

    return {
        "intent":
            OTHER,

        "confidence":
            0.0,

        "source":
            "rule_only",
    }

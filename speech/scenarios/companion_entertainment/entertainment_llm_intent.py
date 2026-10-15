#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import re
import time

import requests


DEFAULT_MODEL = os.getenv(
    "ENTERTAINMENT_INTENT_MODEL",
    os.getenv(
        "COMPANION_LLM_MODEL",
        "qwen3.7-flash",
    ),
)


SYSTEM_PROMPT = """
你是养老陪护机器人中的娱乐意图分类模块。

你的任务不是和老人聊天，而是把老人的一句话转换成固定结构的控制指令。

非常重要：

输入可能来自正在播放的音乐、新闻、戏曲，
也可能包含扬声器残留、歌词、新闻正文、戏曲台词、
ASR幻觉或者老人真正说出的控制命令。

只有老人明确表达“想让机器人做什么”时，
才能输出控制 action。

如果一句话只是媒体内容、陈述句、歌词、新闻正文、
戏曲台词、闲聊碎片或无法确认是在控制播放，
必须输出 unknown。

不能仅仅因为句子里出现“新闻”“音乐”“戏曲”
或者与当前类别有关，就推断老人正在控制播放。

例如：

- “今天新闻里说天气不错”
  -> unknown

- “新闻报道今天有降雨”
  -> unknown

- “甜蜜蜜你笑得甜蜜蜜”
  -> unknown

- “夫妻双双把家还”
  -> unknown

- “今天有戏曲演出”
  -> unknown

- “我正在听新闻”
  -> unknown

- “这个新闻不错”
  -> unknown

但是：

- “这个新闻不错，继续放吧”
  -> continue

- “新闻听够了，换成戏曲吧”
  -> play_category / opera

- “这首不好听，换一首”
  -> next

- “别放了”
  -> stop

对 next 必须特别保守：

只有老人明确表达“切换当前内容”的意思，
才能输出 next。

例如：

- “换一首”
  -> next

- “换一个”
  -> next

- “下一首”
  -> next

- “这个不好听，来点别的”
  -> next

但是下面这些都不能理解成 next：

- “快点”
  -> unknown

- “快一点”
  -> unknown

- “赶紧”
  -> unknown

- “速度点”
  -> unknown

- “怎么这么慢”
  -> unknown

这些话可能是在要求加快速度，
也可能只是闲聊或ASR误识别。
当前系统没有“加速播放”功能，
因此必须使用 unknown，
绝对不能擅自解释成切换内容。


只允许以下 action：

1. ask_category
   老人有娱乐需求，但没有确定音乐、新闻或戏曲。

2. play_category
   老人想听某一类内容，但没有指定具体标题。
   category 必须是 music、news、opera 之一。

3. play_query
   老人指定了具体歌曲、歌手、戏曲、新闻内容或节目。
   query 必须保留真正需要搜索的关键词。

4. next
   老人希望换一个、下一首、下一个。

5. continue
   老人希望继续听同类内容。

6. stop
   老人希望停止播放。

7. unknown
   无法可靠判断。

category 只允许：
music
news
opera
null

必须注意：

- “放点音乐” -> play_category / music
- “播放点音乐” -> play_category / music
- “播放一点音乐” -> play_category / music
- “给我放点新闻” -> play_category / news
- “播放点戏曲” -> play_category / opera
- “换成戏曲” -> play_category / opera

- “我想听甜蜜蜜”
  -> play_query / music / 甜蜜蜜

- “来点邓丽君的歌”
  -> play_query / music / 邓丽君

- “我想听贵妃醉酒”
  -> play_query / opera / 贵妃醉酒

- “我想听京剧贵妃醉酒”
  -> play_query / opera / 贵妃醉酒

- “有点无聊”
  -> ask_category

- “换一个”
  -> next

- “不听了”
  -> stop

不要把“点”“一点”“个”“一个”“首”当成 query。

如果老人只是说“音乐”“新闻”“戏曲”等类别，
必须使用 play_category，而不是 play_query。

只输出 JSON，不要输出 Markdown，不要解释。

格式必须是：

{
  "action": "play_category",
  "category": "music",
  "query": null,
  "confidence": 0.95
}
"""


ALLOWED_ACTIONS = {
    "ask_category",
    "play_category",
    "play_query",
    "next",
    "continue",
    "stop",
    "unknown",
}


ALLOWED_CATEGORIES = {
    "music",
    "news",
    "opera",
    None,
}


class EntertainmentIntentLLM:

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

        self.api_key = api_key
        self.workspace_id = workspace_id
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
        current_category=None,
    ):

        user_content = (
            "当前正在播放的类别："
            f"{current_category or 'none'}\n"
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
                120,

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
                "娱乐意图LLM调用失败: "
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


        parsed = self._parse_json(
            raw
        )

        parsed[
            "llm_ms"
        ] = elapsed_ms

        parsed[
            "model"
        ] = self.model

        return parsed


    @staticmethod
    def _parse_json(
        raw,
    ):

        text = str(
            raw or ""
        ).strip()

        # 即使模型偶尔带 ```json，
        # 也只提取 JSON 对象。
        match = re.search(
            r"\{.*\}",
            text,
            flags=re.S,
        )

        if not match:

            raise RuntimeError(
                "LLM没有返回JSON: "
                f"{text[:300]}"
            )


        try:

            data = json.loads(
                match.group(0)
            )

        except json.JSONDecodeError as exc:

            raise RuntimeError(
                "LLM返回的JSON格式无效: "
                f"{text[:300]}"
            ) from exc


        action = data.get(
            "action"
        )

        category = data.get(
            "category"
        )

        query = data.get(
            "query"
        )

        confidence = data.get(
            "confidence",
            0.0,
        )


        if action not in ALLOWED_ACTIONS:

            raise RuntimeError(
                f"非法action: {action}"
            )


        if category not in ALLOWED_CATEGORIES:

            category = None


        if query is not None:

            query = str(
                query
            ).strip()

            if query in {
                "",
                "点",
                "一点",
                "个",
                "一个",
                "首",
                "一首",
            }:
                query = None


        try:

            confidence = float(
                confidence
            )

        except (
            TypeError,
            ValueError,
        ):

            confidence = 0.0


        confidence = max(
            0.0,
            min(
                1.0,
                confidence,
            ),
        )


        # 必要字段校验
        if (
            action == "play_category"
            and category is None
        ):

            action = "unknown"


        if (
            action == "play_query"
            and not query
        ):

            action = "unknown"


        return {
            "action":
                action,

            "category":
                category,

            "query":
                query,

            "confidence":
                confidence,
        }

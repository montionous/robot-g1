#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import re
import time

import requests


DEFAULT_MODEL = os.getenv(
    "SOCIAL_ACTIVITY_INTENT_MODEL",
    os.getenv(
        "COMPANION_LLM_MODEL",
        "qwen3.7-flash",
    ),
)


SYSTEM_PROMPT = """
你是养老陪护机器人的“社区活动语义匹配器”。

你的任务不是回答老人，
而是判断老人提到的活动需求，
最接近数据库中的哪一个真实活动。

必须严格遵守：

1. 只能从提供的数据库活动目录中选择。
2. 绝对不能创造数据库中不存在的活动。
3. 只根据活动语义进行匹配。
4. 不要判断活动日期、时间、地点、人数、
   是否满员或能否参加。
5. 这些信息之后全部由数据库查询。
6. 如果老人只是泛泛询问
   “最近有什么活动”
   “今天有什么活动”
   而没有指向具体活动，
   activity_id 必须为 null。
7. 如果数据库中没有合理对应活动，
   activity_id 必须为 null。
8. 可以理解日常自然说法、近义表达和口语。

例如：
“打牌”
可以对应数据库中的“棋牌交流”。

“大家一起唱唱歌”
可以对应“集体唱歌”。

“找人聊聊天”
可以对应“下午茶话会”。

“做点手工”
可以对应“手工兴趣小组”。

但最终必须以本次提供的数据库目录为准。

还需要判断老人是否明确指定了某一种活动需求。

specific_request:
- true：老人提到了某种具体活动需求，例如
  “打牌”“唱歌”“游泳”“做手工”“看看电影”。
- false：老人只是泛泛询问，例如
  “最近有什么活动”
  “这两天有什么安排”。

requested_activity:
- specific_request=true 时，
  提取老人自己的简短活动表达。
- 例如“最近有没有打牌的活动”
  返回“打牌”。
- 例如“有没有大家一起唱歌的”
  返回“唱歌”。
- 泛查询时必须为 null。

只输出 JSON：

{
  "specific_request": true,
  "requested_activity": "打牌",
  "activity_id": 27,
  "confidence": 0.96
}

如果老人指定了活动，
但数据库中没有对应活动：

{
  "specific_request": true,
  "requested_activity": "游泳",
  "activity_id": null,
  "confidence": 0.95
}

如果只是泛泛查询：

{
  "specific_request": false,
  "requested_activity": null,
  "activity_id": null,
  "confidence": 0.95
}
"""


class ActivitySemanticMatcher:

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


    @staticmethod
    def _catalog_text(
        activities,
    ):

        parts = []

        for item in activities:

            parts.append(
                "\n".join(
                    [
                        (
                            "activity_id="
                            + str(
                                item[
                                    "activity_id"
                                ]
                            )
                        ),
                        (
                            "name="
                            + str(
                                item.get(
                                    "name",
                                    "",
                                )
                            )
                        ),
                        (
                            "category="
                            + str(
                                item.get(
                                    "category",
                                    "",
                                )
                            )
                        ),
                        (
                            "description="
                            + str(
                                item.get(
                                    "description",
                                    "",
                                )
                            )
                        ),
                        (
                            "tags="
                            + str(
                                item.get(
                                    "tags",
                                    "",
                                )
                            )
                        ),
                    ]
                )
            )

        return "\n\n".join(
            parts
        )


    @staticmethod
    def _parse_json(
        raw,
    ):

        text = str(
            raw or ""
        ).strip()

        match = re.search(
            r"\{.*\}",
            text,
            flags=re.S,
        )

        if not match:
            raise RuntimeError(
                "活动匹配LLM没有返回JSON: "
                + text[:300]
            )

        data = json.loads(
            match.group(0)
        )

        activity_id = data.get(
            "activity_id"
        )

        if activity_id is not None:

            try:
                activity_id = int(
                    activity_id
                )

            except (
                TypeError,
                ValueError,
            ):
                activity_id = None

        specific_request = bool(
            data.get(
                "specific_request",
                False,
            )
        )

        requested_activity = (
            data.get(
                "requested_activity"
            )
        )

        if requested_activity is not None:

            requested_activity = str(
                requested_activity
            ).strip()

            if not requested_activity:
                requested_activity = None

        if not specific_request:
            requested_activity = None

        try:
            confidence = float(
                data.get(
                    "confidence",
                    0.0,
                )
            )

        except (
            TypeError,
            ValueError,
        ):
            confidence = 0.0

        confidence = max(
            0.0,
            min(
                confidence,
                1.0,
            ),
        )

        return {
            "specific_request":
                specific_request,

            "requested_activity":
                requested_activity,

            "activity_id":
                activity_id,

            "confidence":
                confidence,
        }


    def match(
        self,
        text,
        activities,
        *,
        threshold=0.80,
    ):

        activities = list(
            activities or []
        )

        if not activities:

            return {
                "matched": False,
                "activity": None,
                "confidence": 0.0,
                "source": "empty_catalog",
            }

        catalog_by_id = {
            int(
                item[
                    "activity_id"
                ]
            ):
                item

            for item in activities
        }

        user_content = (
            "数据库活动目录：\n\n"
            + self._catalog_text(
                activities
            )
            + "\n\n"
            + "老人原话：\n"
            + str(text).strip()
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

        started = (
            time.perf_counter()
        )

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
            - started
        ) * 1000

        if not response.ok:

            raise RuntimeError(
                "活动语义匹配LLM调用失败: "
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
                "无法解析活动匹配LLM响应: "
                f"{data}"
            ) from exc

        parsed = self._parse_json(
            raw
        )

        activity_id = parsed[
            "activity_id"
        ]

        confidence = parsed[
            "confidence"
        ]

        specific_request = parsed[
            "specific_request"
        ]

        requested_activity = parsed[
            "requested_activity"
        ]

        # 最关键的安全门：
        # 即使模型返回了一个不存在的 ID，
        # 也绝不接受。
        activity = (
            catalog_by_id.get(
                activity_id
            )
            if activity_id
            is not None
            else None
        )

        if (
            activity is None
            or confidence
            < threshold
        ):

            return {
                "matched": False,
                "activity": None,
                "specific_request":
                    specific_request,
                "requested_activity":
                    requested_activity,
                "confidence":
                    confidence,
                "source": "llm",
                "llm_ms":
                    elapsed_ms,
                "model":
                    self.model,
            }

        return {
            "matched": True,
            "activity":
                activity,
            "specific_request":
                specific_request,
            "requested_activity":
                requested_activity,
            "confidence":
                confidence,
            "source": "llm",
            "llm_ms":
                elapsed_ms,
            "model":
                self.model,
        }

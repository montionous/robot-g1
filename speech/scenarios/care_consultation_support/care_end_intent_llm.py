from __future__ import annotations

import json
import os
import re
import time

import requests

from llm_client import DEFAULT_MODEL


SYSTEM_PROMPT = """
你负责判断老人当前这句话是否明确表示：
“结束本次日常护理咨询对话”。

你不是护理回答模型，不回答老人问题。
只判断对话是否应该结束。

判断原则：

应该结束，例如：
- 那就先这样吧
- 好吧，那就到这里
- 差不多了，谢谢你
- 我没别的问题了
- 今天先这样
- 行，我知道了，谢谢
- 我先休息了
- 不问了
- 改天再说吧
- 好的，就这些

不能结束，例如：
- 那就这样走一会儿可以吗
- 好，那我要注意什么
- 我知道了，但是晚上怎么办
- 为什么会这样
- 行，那还需要做什么
- 那我现在能出去吗
- 我想休息一下会不会好一点

尤其注意：
“好”“行”“知道了”本身不一定意味着结束。
如果后面仍然有问题、请求、疑问或新的护理内容，必须判为继续。

只输出 JSON，不要输出 Markdown：

{
  "should_end": true,
  "confidence": 0.95,
  "reason": "老人明确表示本次咨询到此为止"
}
"""


class CareEndIntentLLM:

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
            "/compatible-mode/v1/chat/completions"
        )


    @staticmethod
    def _parse_json(text):

        raw = str(
            text or ""
        ).strip()

        raw = re.sub(
            r"^```(?:json)?\s*",
            "",
            raw,
            flags=re.I,
        )

        raw = re.sub(
            r"\s*```$",
            "",
            raw,
        )

        match = re.search(
            r"\{.*\}",
            raw,
            flags=re.S,
        )

        if match:
            raw = match.group(0)

        data = json.loads(
            raw
        )

        return {
            "should_end":
                bool(
                    data.get(
                        "should_end",
                        False,
                    )
                ),

            "confidence":
                float(
                    data.get(
                        "confidence",
                        0.0,
                    )
                    or 0.0
                ),

            "reason":
                str(
                    data.get(
                        "reason",
                        "",
                    )
                ).strip(),
        }


    def classify(
        self,
        text,
        *,
        history=None,
    ):

        text = str(
            text or ""
        ).strip()

        if not text:

            return {
                "should_end":
                    False,

                "confidence":
                    0.0,

                "reason":
                    "empty_text",

                "llm_ms":
                    0.0,

                "model":
                    self.model,
            }


        recent_context = ""

        if history:

            items = history[-4:]

            recent_context = "\n".join(
                (
                    "老人："
                    if item.get("role")
                    == "user"
                    else "机器人："
                )
                + str(
                    item.get(
                        "content",
                        "",
                    )
                )
                for item in items
            )


        user_content = (
            "最近对话：\n"
            f"{recent_context or '无'}\n\n"
            "老人当前原话：\n"
            f"{text}"
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
                100,

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
                "护理结束意图LLM调用失败: "
                f"HTTP {response.status_code} "
                f"{response.text[:300]}"
            )


        data = response.json()

        raw = (
            data["choices"][0]
            ["message"]
            ["content"]
        )

        result = (
            self._parse_json(
                raw
            )
        )

        result["llm_ms"] = (
            elapsed_ms
        )

        result["model"] = (
            self.model
        )

        return result

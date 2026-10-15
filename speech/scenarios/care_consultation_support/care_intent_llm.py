from __future__ import annotations

import json
import os
import re
import time

import requests

from llm_client import DEFAULT_MODEL


SYSTEM_PROMPT = """
你负责判断老人一句话是否表达了日常护理咨询需求。

这里的“日常护理咨询”包括：
- 身体某个部位不舒服
- 疼、痛、酸、胀、麻、乏力等身体感受
- 老人用词不准确但明显是在描述身体异常
- 睡眠、食欲、排便、疲劳、头晕、活动能力等护理问题
- ASR可能把“酸”识别成“伤”等近似或错误词，但结合身体部位仍能看出老人是在描述不适

例如：
“我膝盖有点酸” -> true
“我膝盖有点伤” -> true
“腿这里怪怪的” -> true
“这两天走路不太对劲” -> true
“昨晚没睡好” -> true

不是护理咨询：
“我想听秦腔” -> false
“给我女儿打电话” -> false
“今天有什么活动” -> false
“天气怎么样” -> false

不要进行疾病诊断。
只判断是否应该进入日常护理咨询场景。

只输出JSON：
{
  "is_care": true,
  "confidence": 0.95,
  "reason": "简短原因"
}
"""


class CareIntentLLM:

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
    def _parse_json(
        text,
    ):

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
            "is_care":
                bool(
                    data.get(
                        "is_care",
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
    ):

        text = str(
            text or ""
        ).strip()

        if not text:

            return {
                "is_care":
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
                        (
                            "老人原话："
                            f"{text}"
                        ),
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
                "护理意图LLM调用失败: "
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

        result[
            "llm_ms"
        ] = elapsed_ms

        result[
            "model"
        ] = self.model

        return result

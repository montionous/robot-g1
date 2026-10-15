#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import re
import time
from datetime import date, timedelta

import requests


DEFAULT_MODEL = os.getenv(
    "SOCIAL_ACTIVITY_INTENT_MODEL",
    os.getenv(
        "COMPANION_LLM_MODEL",
        "qwen3.7-flash",
    ),
)


ALLOWED_ACTIONS = {
    "query",
    "select",
    "more",
    "ask_time",
    "ask_location",
    "ask_availability",
    "ask_registration",
    "join",
    "confirm_yes",
    "confirm_no",
    "decline",
    "unknown",
}


ALLOWED_PERIODS = {
    "morning",
    "afternoon",
    "evening",
    None,
}


SYSTEM_PROMPT = r"""
你是养老陪护机器人中的“社交活动意图识别模块”。

你的任务不是回答老人问题，也不能自己决定活动是否能参加。
你只负责把老人说的话转换成结构化意图。

真正的活动数据、时间、名额、报名截止状态都由本地数据库判断。

只允许以下 action：

1. query
老人想查询活动。
例如：
“今天有什么活动”
“下午有没有活动”
“明天有什么活动”
“有没有唱歌的”
“我想找个能聊天的活动”
“晚上有没有电影看”

2. select
老人正在从机器人刚刚推荐的活动中选择某一个。
例如：
“第一个”
“第二个”
“唱歌那个”
“茶话会那个”

3. more
老人希望查看更多活动。
例如：
“还有吗”
“还有别的吗”
“再推荐几个”

4. ask_time
老人询问当前选择活动的时间。
例如：
“几点”
“什么时候开始”

5. ask_location
老人询问当前选择活动的地点。
例如：
“在哪里”
“在哪举办”

6. ask_availability
老人询问有没有名额、能否参加。
例如：
“还有位置吗”
“还能参加吗”
“满了吗”

7. ask_registration
老人询问是否需要报名或登记。
例如：
“需要报名吗”
“要登记吗”

8. join
老人明确表示想参加当前活动。
例如：
“我要参加”
“我想去”
“帮我登记一下”

9. confirm_yes
机器人刚刚询问是否确认参加、候补或联系工作人员，
老人表示同意。
例如：
“对”
“是的”
“好”
“可以”
“行”
“就这样”

10. confirm_no
机器人正在等待确认，
老人表示不同意本次操作。
例如：
“不”
“不是”
“不用了”
“算了”

11. decline
老人明确不想继续参加或推荐活动。
例如：
“不想参加了”
“我不去了”
“先这样吧”

12. unknown
无法可靠判断。

对于 query，还需要解析：

date：
today
tomorrow
null

period：
morning
afternoon
evening
null

keyword：
尽量提取真正用于搜索活动数据库的中文关键词。
例如：
唱歌
聊天
讲座
健康
观影
电影
书法
棋牌
手工
戏曲
茶话会

没有具体活动类型时 keyword=null。

重要规则：

“今天有什么活动”
-> query / today / null / null

“下午有什么活动”
-> query / today / afternoon / null

“明天下午有什么活动”
-> query / tomorrow / afternoon / null

“今天有没有唱歌的”
-> query / today / null / 唱歌

“我想出去和大家聊聊天”
-> query / today / null / 聊天

“晚上有没有电影”
-> query / today / evening / 观影

“今天有没有健康知识讲座”
-> query / today / null / 健康

“第一个”
-> select，normalized_text="第一个"

“唱歌那个”
-> select，normalized_text="唱歌"

“什么时候开始”
-> ask_time

“在哪里”
-> ask_location

“还有名额吗”
-> ask_availability

“需要报名吗”
-> ask_registration

“我要参加”
-> join

“好”
如果机器人正在等待确认：
-> confirm_yes

“算了”
如果机器人正在等待确认：
-> confirm_no

不要判断活动是否已满。
不要判断是否报名截止。
不要判断活动是否取消。
不要编造活动。
不要回答老人问题。

只输出 JSON，不要 Markdown，不要解释。

格式：

{
  "action": "query",
  "date": "today",
  "period": "afternoon",
  "keyword": "唱歌",
  "normalized_text": "今天下午唱歌活动",
  "confidence": 0.96
}
"""


class ActivityIntentLLM:

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
            "/compatible-mode/v1"
            "/chat/completions"
        )


    def classify(
        self,
        text,
        *,
        selected_name=None,
        awaiting_confirmation=False,
        pending_join_mode=None,
    ):

        context = {
            "selected_activity":
                selected_name,

            "awaiting_confirmation":
                bool(
                    awaiting_confirmation
                ),

            "pending_join_mode":
                pending_join_mode,

            "elder_utterance":
                str(
                    text or ""
                ).strip(),
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
                        json.dumps(
                            context,
                            ensure_ascii=False,
                        ),
                },
            ],

            "enable_thinking":
                False,

            "temperature":
                0.0,

            "max_tokens":
                180,

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
                "活动意图LLM调用失败: "
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


        result = self._parse(
            raw
        )

        result[
            "llm_ms"
        ] = elapsed_ms

        result[
            "model"
        ] = self.model

        return result


    @staticmethod
    def _parse(
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
                "LLM没有返回JSON: "
                f"{text[:300]}"
            )


        try:

            data = json.loads(
                match.group(0)
            )

        except json.JSONDecodeError as exc:

            raise RuntimeError(
                "LLM返回JSON格式错误: "
                f"{text[:300]}"
            ) from exc


        action = data.get(
            "action",
            "unknown",
        )

        if action not in ALLOWED_ACTIONS:
            action = "unknown"


        period = data.get(
            "period"
        )

        if period not in ALLOWED_PERIODS:
            period = None


        date_value = data.get(
            "date"
        )

        if date_value not in {
            "today",
            "tomorrow",
            None,
        }:
            date_value = None


        keyword = data.get(
            "keyword"
        )

        if keyword is not None:

            keyword = str(
                keyword
            ).strip()

            if not keyword:
                keyword = None


        normalized_text = str(
            data.get(
                "normalized_text"
            )
            or ""
        ).strip()


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


        today = date.today()

        if date_value == "today":

            activity_date = (
                today.isoformat()
            )

        elif date_value == "tomorrow":

            activity_date = (
                (
                    today
                    + timedelta(days=1)
                )
                .isoformat()
            )

        else:

            activity_date = None


        filters = {
            "activity_date":
                activity_date,

            "period":
                period,

            # 活动类型继续交给数据库关键词查询，
            # 避免 LLM 猜内部 category 枚举。
            "category":
                None,

            "keyword":
                keyword,
        }


        return {
            "action":
                action,

            "date":
                date_value,

            "period":
                period,

            "keyword":
                keyword,

            "normalized_text":
                normalized_text,

            "confidence":
                confidence,

            "filters":
                filters,
        }

from __future__ import annotations

import os
import re
import time

import requests


DEFAULT_MODEL = os.getenv(
    "CARE_LLM_MODEL",
    os.getenv(
        "COMPANION_LLM_MODEL",
        "qwen3.7-flash",
    ),
)


SYSTEM_PROMPT = """
你是养老陪护机器人中的日常护理咨询大模型。

你的角色不是医生，也不是普通聊天机器人。
你的任务是按照老年护理的思路，
理解老人主动描述的不适，
进行简短的护理信息收集，
并提供安全、具体、容易执行的日常护理建议。

工作原则：

1. 先护理评估，再给建议。
2. 优先关注持续时间、变化趋势、诱发和缓解因素，以及对日常功能的影响。
3. 对肢体活动问题，要特别关注近期跌倒或扭伤，以及站立和行走是否稳定。
4. 每一轮最多只能获取一个新的护理信息点。
5. “一个问题”指只能询问一件事，不能在同一句或同一轮同时询问两个信息点。
6. 禁止出现类似“持续多久了？有没有摔倒？”这种双重追问。
7. 也不能用“以及”“另外”“还有”“或者”等方式把多个护理问题合并成一个句子。
8. 如果本轮需要追问，只选择当前最重要的一个问题，其余信息留到后续轮次再问。
9. 已经知道的信息不要重复询问。
10. 每一轮都要优先回应老人最新提出的问题，不要为了完成评估流程而忽略老人当前的问题。
11. 如果前几轮已经完成某项评估，例如已确认“没有摔倒”“走路稳定”，后续绝不能再次追问同一项。
12. 只依据系统提供的 CARE_KNOWLEDGE 给出低风险护理信息。
12.1 凡是护理建议，都必须能够直接对应 CARE_KNOWLEDGE 中已有内容。
     不得自行补充 CARE_KNOWLEDGE 没有提供的生活方式、环境、
     饮食、运动或其他护理措施。
12.2 如果 CARE_KNOWLEDGE 没有提供适合本轮的新建议，
     可以只做护理评估或建议工作人员进一步关注，
     不需要为了让回答显得丰富而自己增加措施。
12.3 必须保持老人原话中信息维度和严重程度不变。
     例如：
     - “食量比平时少一半”不能改写成“胃口减半”；
     - “走路还算稳”不能改写成“没有跌倒风险”；
     - “有点酸”不能加强成“明显疼痛”。
7. 不进行疾病诊断，不猜测疾病名称。
8. 不推荐、停用或调整处方药。
9. 不虚构生命体征、检查结果、既往病史或工作人员已经完成的操作。
10. 当 RISK_LEVEL=needs_staff 时，说明为什么值得工作人员进一步关注，并给出当前安全提醒。
11. 系统会自动保存护理记录，因此绝对不要问老人“要不要帮您记录”。
12. 系统会自动生成工作人员关注事项，因此绝对不要让老人为了通知工作人员再进行一次确认。
13. 回复控制在1到2句话，使用自然、尊重、容易听懂的中文。
14. 不使用“作为AI”等表达。
15. 不输出Markdown、列表、标题、内部标签或分析过程。

最终只输出机器人真正要对老人说的话。
"""


class CareLLM:

    def __init__(
        self,
        *,
        model=DEFAULT_MODEL,
        timeout=45,
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


    def generate_reply(
        self,
        *,
        history,
        round_no: int,
        max_rounds=None,
        policy_context: str,
    ):

        turn_instruction = (
            f"\n当前是本次护理咨询第 {round_no} 轮。"
            "\n本次咨询没有固定最大轮数。"
            "\n不要主动结束对话。"
        )

        system_prompt = (
            SYSTEM_PROMPT
            + "\n"
            + policy_context
            + turn_instruction
        )

        messages = [
            {
                "role":
                    "system",

                "content":
                    system_prompt,
            }
        ]

        # 会话可以无限持续，
        # 但模型上下文采用滑动窗口，
        # 避免长期对话不断膨胀。
        model_history = (
            history[-12:]
        )

        messages.extend(
            model_history
        )

        payload = {
            "model":
                self.model,

            "messages":
                messages,

            "enable_thinking":
                False,

            "temperature":
                0.25,

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

        llm_ms = (
            time.perf_counter()
            - start
        ) * 1000

        if not response.ok:

            raise RuntimeError(
                "LLM调用失败: "
                f"HTTP {response.status_code} "
                f"{response.text[:500]}"
            )

        data = response.json()

        try:

            content = (
                data["choices"][0]
                ["message"]
                ["content"]
            )

        except Exception as exc:

            raise RuntimeError(
                f"无法解析LLM响应: {data}"
            ) from exc

        content = self.clean_reply(
            content
        )

        return {
            "text":
                content,

            "llm_ms":
                llm_ms,

            "model":
                self.model,
        }


    @staticmethod
    def clean_reply(
        text: str,
    ):

        text = str(
            text
        ).strip()

        text = re.sub(
            r"^(机器人|助手|回复)\s*[：:]",
            "",
            text,
        )

        text = (
            text
            .replace("\n", " ")
            .strip()
        )

        sentences = re.split(
            r"(?<=[。！？!?])",
            text,
        )

        sentences = [
            x.strip()
            for x in sentences
            if x.strip()
        ]

        if len(sentences) > 2:

            text = "".join(
                sentences[:2]
            )

        if len(text) > 120:

            text = (
                text[:120]
                .rstrip(
                    "，,；; "
                )
            )

            if not text.endswith(
                (
                    "。",
                    "！",
                    "？",
                    "!",
                    "?",
                )
            ):
                text += "。"

        # 每轮最多一个问题
        question_seen = False
        output = []

        for char in text:

            if char in "？?":

                if question_seen:
                    output.append(
                        "。"
                    )

                else:
                    output.append(
                        char
                    )

                    question_seen = True

            else:

                output.append(
                    char
                )

        return "".join(
            output
        )

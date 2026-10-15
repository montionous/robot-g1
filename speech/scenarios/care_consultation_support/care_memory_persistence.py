from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from datetime import datetime
from pathlib import Path

import requests

from llm_client import DEFAULT_MODEL


PROJECT_ROOT = (
    Path(__file__).resolve()
    .parents[2]
)

DB_PATH = (
    PROJECT_ROOT
    / "data"
    / "elder_companion.db"
)


def connect():

    conn = sqlite3.connect(
        DB_PATH
    )

    conn.row_factory = (
        sqlite3.Row
    )

    conn.execute(
        "PRAGMA foreign_keys = ON"
    )

    return conn


# =========================================================
# 初始化：
# 记录“哪些 session 已经沉淀过长期记忆”
#
# 目的：
# 即使结束处理函数因为异常被重复调用，
# 同一个 session 也不会把 occurrence_count 加两遍。
# =========================================================

def init_memory_persistence():

    with connect() as conn:

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS
            care_memory_ingestion (

                session_id INTEGER PRIMARY KEY,

                elderly_id INTEGER NOT NULL,

                memory_id INTEGER,

                memory_key TEXT,

                action TEXT NOT NULL,

                processed_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (session_id)
                    REFERENCES care_consultation_session(id),

                FOREIGN KEY (elderly_id)
                    REFERENCES elderly_person(id),

                FOREIGN KEY (memory_id)
                    REFERENCES elder_care_memory(id)
            )
            """
        )

        conn.commit()


# =========================================================
# 根据当前护理领域 + 对话内容生成稳定 key
#
# 这里故意不用大模型。
# =========================================================

def derive_memory_key(
    care_domain,
    text,
):

    text = str(
        text or ""
    )

    if care_domain == "mobility":

        body_rules = [
            (
                "knee_discomfort",
                [
                    "膝盖",
                    "膝部",
                    "膝关节",
                    "膝",
                ],
            ),
            (
                "waist_discomfort",
                [
                    "腰",
                    "腰部",
                ],
            ),
            (
                "leg_discomfort",
                [
                    "腿",
                    "腿部",
                ],
            ),
            (
                "shoulder_discomfort",
                [
                    "肩",
                    "肩膀",
                    "肩部",
                ],
            ),
            (
                "arm_discomfort",
                [
                    "胳膊",
                    "手臂",
                ],
            ),
            (
                "foot_discomfort",
                [
                    "脚",
                    "足部",
                ],
            ),
        ]

        for suffix, words in body_rules:

            if any(
                word in text
                for word in words
            ):

                return (
                    f"mobility:{suffix}"
                )

        return (
            "mobility:general_discomfort"
        )


    if care_domain == "dizziness":

        return "dizziness:dizziness"


    if care_domain == "sleep":

        return "sleep:sleep_problem"


    if care_domain == "appetite":

        return "appetite:reduced_appetite"


    if care_domain == "bowel":

        return "bowel:bowel_problem"


    if care_domain == "fatigue":

        return "fatigue:fatigue"


    return "general_care:consultation"


# =========================================================
# 护理记忆摘要模型
# =========================================================

class CareMemoryLLM:

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


    def summarize(
        self,
        *,
        care_domain,
        history,
        final_risk=None,
    ):

        dialogue = []

        for item in history or []:

            role = item.get(
                "role"
            )

            content = str(
                item.get(
                    "content",
                    "",
                )
            ).strip()

            if not content:
                continue

            role_name = (
                "老人"
                if role == "user"
                else "机器人"
            )

            dialogue.append(
                f"{role_name}: {content}"
            )


        dialogue_text = "\n".join(
            dialogue[-12:]
        )


        system_prompt = """
你负责把一次老年人日常护理咨询整理成长期护理记录摘要。

要求：

1. 只记录本次对话中明确出现的信息。
2. 不进行新的疾病诊断。
3. 不推测老人没有明确表达的症状。
4. 已存在的病史只能作为背景，不能写成“本次确诊”。
5. 优先保留：
   - 老人明确描述的主要不适；
   - 与老人本人平时状态相比是否发生变化；
   - 是否影响站立、行走、睡眠、饮食等日常功能；
   - 本次是否达到需要工作人员进一步关注的程度。

6. summary 只总结“老人当前情况”和“护理评估结果”。
   不要把机器人给出的普通护理建议写入长期记忆，
   例如“建议休息”“携带手杖”“减少活动”等不要保存。

7. 必须严格保持老人原始表述的严重程度。
   老人只说“酸”，不要擅自改成“疼痛”“酸痛”或“剧痛”。
   老人说“比平时明显一点”，优先写成“较平时明显”，
   不要自行加强成“明显加重”“严重加重”。

8. 绝不能从已有信息反推出老人没有说过的阴性结论。
   例如：
   - “走路还算稳”只能记录为“当前行走尚稳”，
     不能推断成“无跌倒风险”。
   - 没有提到发热，不能写“无发热”。
   - 没有提到外伤，不能写“无外伤”。
   只有老人明确否认过某项情况时，才可以记录对应阴性事实。

9. 不要记录寒暄、结束语等无长期价值内容。

9. summary 应为一段简洁中文，建议30到80字。

10. 如果这次对话没有值得形成长期护理记录的具体信息，
    should_store=false。

11. 只输出JSON，不输出Markdown。

格式：

{
  "should_store": true,
  "summary": "..."
}
"""


        user_prompt = f"""
护理领域：
{care_domain}

最终护理风险：
{final_risk or "unknown"}

本次护理咨询：
{dialogue_text}
"""


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
                        user_prompt,
                },
            ],

            "enable_thinking":
                False,

            "temperature":
                0.1,

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
                "护理记忆摘要模型调用失败: "
                f"HTTP {response.status_code} "
                f"{response.text[:500]}"
            )


        data = response.json()

        content = str(
            data[
                "choices"
            ][0][
                "message"
            ][
                "content"
            ]
        ).strip()


        # 容忍模型偶尔包 Markdown JSON fence
        content = re.sub(
            r"^```(?:json)?\s*",
            "",
            content,
            flags=re.I,
        )

        content = re.sub(
            r"\s*```$",
            "",
            content,
        )


        try:

            result = json.loads(
                content
            )

        except Exception as exc:

            raise RuntimeError(
                "无法解析护理记忆JSON: "
                f"{content}"
            ) from exc


        summary = str(
            result.get(
                "summary",
                "",
            )
        ).strip()


        return {
            "should_store":
                bool(
                    result.get(
                        "should_store",
                        False,
                    )
                )
                and bool(
                    summary
                ),

            "summary":
                summary,

            "llm_ms":
                llm_ms,

            "model":
                self.model,
        }


# =========================================================
# DB helpers
# =========================================================

def get_session_info(
    session_id,
):

    with connect() as conn:

        row = conn.execute(
            """
            SELECT *
            FROM care_consultation_session
            WHERE id = ?
            LIMIT 1
            """,
            (
                session_id,
            ),
        ).fetchone()


    return (
        dict(row)
        if row is not None
        else None
    )


def ingestion_exists(
    session_id,
):

    with connect() as conn:

        row = conn.execute(
            """
            SELECT *
            FROM care_memory_ingestion
            WHERE session_id = ?
            LIMIT 1
            """,
            (
                session_id,
            ),
        ).fetchone()


    return (
        dict(row)
        if row is not None
        else None
    )


def upsert_memory(
    *,
    elderly_id,
    care_domain,
    memory_key,
    summary,
    session_id,
    final_risk=None,
):

    now = datetime.now().isoformat(
        timespec="seconds"
    )


    with connect() as conn:

        old = conn.execute(
            """
            SELECT *
            FROM elder_care_memory

            WHERE elderly_id = ?
              AND care_domain = ?
              AND memory_key = ?

            LIMIT 1
            """,
            (
                elderly_id,
                care_domain,
                memory_key,
            ),
        ).fetchone()


        if old is None:

            cursor = conn.execute(
                """
                INSERT INTO elder_care_memory (
                    elderly_id,
                    care_domain,
                    memory_key,
                    summary,
                    occurrence_count,
                    first_observed_at,
                    last_observed_at,
                    source_type,
                    source_session_id,
                    verified
                )
                VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?, 1)
                """,
                (
                    elderly_id,
                    care_domain,
                    memory_key,
                    summary,
                    now,
                    now,
                    "consultation",
                    session_id,
                ),
            )

            memory_id = (
                cursor.lastrowid
            )

            action = "inserted"
            count = 1


        else:

            memory_id = old["id"]

            count = (
                int(
                    old[
                        "occurrence_count"
                    ]
                    or 0
                )
                + 1
            )

            conn.execute(
                """
                UPDATE elder_care_memory

                SET
                    summary = ?,
                    occurrence_count = ?,
                    last_observed_at = ?,
                    source_type = 'consultation',
                    source_session_id = ?,
                    updated_at = CURRENT_TIMESTAMP

                WHERE id = ?
                """,
                (
                    summary,
                    count,
                    now,
                    session_id,
                    memory_id,
                ),
            )

            action = "updated"


        # =================================================
        # 保存这一场真实护理咨询的历史明细。
        #
        # 聚合 memory 负责：
        #   “这个问题一共发生过几次”
        #
        # occurrence 负责：
        #   “每一次具体发生了什么”
        # =================================================

        source_ref = (
            f"session:{session_id}"
        )

        conn.execute(
            """
            INSERT OR IGNORE INTO
            elder_care_memory_occurrence (
                memory_id,
                elderly_id,
                care_domain,
                memory_key,
                summary,
                final_risk,
                observed_at,
                source_type,
                source_session_id,
                source_ref
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                memory_id,
                elderly_id,
                care_domain,
                memory_key,
                summary,
                final_risk,
                now,
                "consultation",
                session_id,
                source_ref,
            ),
        )


        conn.execute(
            """
            INSERT INTO care_memory_ingestion (
                session_id,
                elderly_id,
                memory_id,
                memory_key,
                action
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                session_id,
                elderly_id,
                memory_id,
                memory_key,
                action,
            ),
        )


        conn.commit()


    return {
        "action":
            action,

        "memory_id":
            memory_id,

        "memory_key":
            memory_key,

        "occurrence_count":
            count,

        "summary":
            summary,
    }


# =========================================================
# 对一次已经结束的护理咨询进行长期记忆沉淀
# =========================================================

def persist_consultation_memory(
    *,
    session_id,
    elderly_id,
    care_domain,
    history,
    final_risk=None,
    dry_run=False,
    llm=None,
):

    init_memory_persistence()


    # -----------------------------------------------------
    # 同一个 session 永远只允许处理一次
    # -----------------------------------------------------

    already = ingestion_exists(
        session_id
    )

    if already:

        return {
            "stored":
                False,

            "reason":
                "session_already_processed",

            "existing":
                already,
        }


    session = get_session_info(
        session_id
    )

    if session is None:

        return {
            "stored":
                False,

            "reason":
                "session_not_found",
        }


    # -----------------------------------------------------
    # 正式关闭长期记忆：
    #   不进行摘要，也不写库。
    #
    # dry_run / showcase：
    #   即使 persist_memory=0，
    #   仍允许生成“长期记忆预览”，
    #   但后面绝不执行 upsert_memory。
    # -----------------------------------------------------

    memory_enabled = bool(
        session.get(
            "persist_memory",
            1,
        )
    )

    if (
        not memory_enabled
        and not dry_run
    ):

        return {
            "stored":
                False,

            "reason":
                "session_memory_disabled",
        }


    user_text = "\n".join(
        str(
            item.get(
                "content",
                "",
            )
        )
        for item in history or []
        if item.get(
            "role"
        )
        == "user"
    )


    memory_key = (
        derive_memory_key(
            care_domain,
            user_text,
        )
    )


    llm = (
        llm
        if llm is not None
        else CareMemoryLLM()
    )


    summary_result = (
        llm.summarize(
            care_domain=
                care_domain,

            history=
                history,

            final_risk=
                final_risk,
        )
    )


    result = {
        "stored":
            False,

        "memory_key":
            memory_key,

        "summary":
            summary_result.get(
                "summary"
            ),

        "should_store":
            summary_result.get(
                "should_store"
            ),

        "llm_ms":
            summary_result.get(
                "llm_ms"
            ),

        "model":
            summary_result.get(
                "model"
            ),
    }


    if not summary_result.get(
        "should_store"
    ):

        result[
            "reason"
        ] = (
            "no_long_term_value"
        )

        return result


    # -----------------------------------------------------
    # dry_run：
    # 可以检查摘要，但绝不写库。
    # -----------------------------------------------------

    if dry_run:

        result[
            "reason"
        ] = "dry_run"

        # 已完成与正式模式相同的长期价值判断和摘要，
        # 这里只是不执行数据库持久化。
        result[
            "preview"
        ] = True

        return result


    stored = upsert_memory(
        elderly_id=
            elderly_id,

        care_domain=
            care_domain,

        memory_key=
            memory_key,

        summary=
            summary_result[
                "summary"
            ],

        session_id=
            session_id,

        final_risk=
            final_risk,
    )


    result.update(
        stored
    )

    result[
        "stored"
    ] = True

    return result

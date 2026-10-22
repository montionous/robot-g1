from __future__ import annotations


def _elder_friendly_summary(
    summary,
):

    text = str(
        summary or ""
    ).strip()

    if not text:
        return ""


    # 长期记忆摘要是内部护理记录语气，
    # 演示播报时稍微转换成面向老人的表达。
    if text.startswith(
        "老人本次"
    ):

        text = (
            "您本次"
            + text[
                len("老人本次"):
            ]
        )

    elif text.startswith(
        "老人"
    ):

        text = (
            "您"
            + text[
                len("老人"):
            ]
        )


    return text


def build_memory_announcement(
    finalize_result,
    *,
    showcase=False,
):

    result = (
        finalize_result
        if isinstance(
            finalize_result,
            dict,
        )
        else {}
    )

    memory = (
        result.get(
            "memory"
        )
        or {}
    )

    error = result.get(
        "memory_error"
    )


    if error:

        return {
            "text": None,
            "kind": "error",
            "summary": None,
            "memory_key": None,
        }


    summary = (
        _elder_friendly_summary(
            memory.get(
                "summary"
            )
        )
    )

    memory_key = (
        memory.get(
            "memory_key"
        )
    )


    # =====================================================
    # showcase：
    # 已完成正式流程同等级别的摘要判断，
    # 但没有写入长期护理数据库。
    # =====================================================

    if (
        showcase
        and memory.get(
            "preview"
        )
        and memory.get(
            "should_store"
        )
        and summary
    ):

        return {
            "text":
                (
                    "本次咨询中有长期护理价值的信息"
                    "已经整理完成："
                    + summary.rstrip(
                        "。！？!?"
                    )
                    + "。"
                    "这些信息以后可以作为"
                    "个体化护理参考。"
                ),

            "console_text": "当前为演示模式，不会写入正式护理档案。",

            "kind":
                "preview",

            "summary":
                summary,

            "memory_key":
                memory_key,
        }


    # =====================================================
    # 正式运行真正写入成功。
    #
    # 当前需求重点是 showcase，
    # 正式运行默认只返回简短确认，
    # 是否实际播报由上层决定。
    # =====================================================

    if (
        memory.get(
            "stored"
        )
        and summary
    ):

        return {
            "text":
                (
                    "本次咨询中有长期护理价值的信息"
                    "已经整理并保存，"
                    "以后可以作为个体化护理参考。"
                ),

            "kind":
                "stored",

            "summary":
                summary,

            "memory_key":
                memory_key,
        }


    return {
        "text": None,
        "kind":
            str(
                memory.get(
                    "reason"
                )
                or "none"
            ),
        "summary":
            summary or None,
        "memory_key":
            memory_key,
    }

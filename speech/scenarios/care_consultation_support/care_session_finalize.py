from __future__ import annotations

from care_db import (
    finish_session,
)

from care_memory_persistence import (
    persist_consultation_memory,
)


# =========================================================
# 只有“正常完成”的护理咨询才进入长期记忆。
#
# processing_error：
#   程序异常，记录可能不完整。
#
# manual_interrupt：
#   调试 / 人工中断。
#
# transfer：
#   对话已经交给其他场景，不在这里沉淀。
# =========================================================

MEMORY_ELIGIBLE_END_REASONS = {
    "user_requested",
    "no_response",
    "completed",
}


def finalize_care_session(
    *,
    session_id,
    consultation,
    end_reason,
):

    # =====================================================
    # 1. 无论长期记忆是否成功，
    #    session 都必须先正常结束。
    # =====================================================

    finish_session(
        session_id=
            session_id,

        completed_rounds=
            consultation.round_no,

        end_reason=
            end_reason,
    )


    # -------------------------------------------------
    # 自动收尾跨场景共享需求
    #
    # 共享需求失败不能影响护理 session
    # 和长期护理记忆的正常结束。
    #
    # CareNeedBridge 内部会根据最终风险决定：
    #
    # low
    #   -> completed
    #
    # needs_staff
    #   -> in_progress
    #      继续等待工作人员后续处理
    #
    # dry_run / showcase
    #   -> 不写公共 elder_need 表
    # -------------------------------------------------

    shared_need = None
    shared_need_error = None

    try:

        finalize_shared_need = getattr(
            consultation,
            "finalize_shared_need",
            None,
        )

        if finalize_shared_need is not None:

            shared_need = (
                finalize_shared_need(
                    end_reason
                )
            )

    except Exception as exc:

        # 共享需求属于跨模块辅助层。
        # 即使这里异常，也不能让已经完成的
        # 护理 session 被判定为结束失败。
        shared_need_error = (
            repr(exc)
        )



    result = {
        "session_finished":
            True,

        "end_reason":
            end_reason,

        "memory":
            None,

        "memory_error":
            None,
    }


    # =====================================================
    # 2. 非正常完成场景不沉淀长期护理记忆
    # =====================================================

    if (
        end_reason
        not in MEMORY_ELIGIBLE_END_REASONS
    ):

        result["memory"] = {
            "stored":
                False,

            "reason":
                "end_reason_not_eligible",
        }

        return result


    # =====================================================
    # 3. 没有形成实际护理对话时也不保存
    # =====================================================

    if not consultation.history:

        result["memory"] = {
            "stored":
                False,

            "reason":
                "empty_consultation_history",
        }

        return result


    # =====================================================
    # 4. 长期记忆沉淀
    #
    # persist_consultation_memory 内部还会继续判断：
    #
    # - session.persist_memory
    # - 同一 session 是否已经处理
    # - 摘要是否值得长期保存
    # - memory_key 去重
    #
    # 所以这里不重复实现这些规则。
    # =====================================================

    try:

        memory_result = (
            persist_consultation_memory(
                session_id=
                    session_id,

                elderly_id=
                    consultation.elderly_id,

                care_domain=(
                    consultation.care_domain
                    or "general_care"
                ),

                history=
                    consultation.history,

                final_risk=
                    consultation.risk_level,

                # controller 的 dry_run
                # 同样禁止长期护理记忆写库。
                dry_run=bool(
                    getattr(
                        consultation,
                        "dry_run",
                        False,
                    )
                ),
            )
        )

        result["memory"] = (
            memory_result
        )


    except Exception as exc:

        # 长期记忆是护理咨询结束后的附加能力。
        #
        # 即使云端摘要模型暂时调用失败，
        # 也不能让 session 保持在 consulting 状态。
        result["memory_error"] = (
            repr(exc)
        )

        result["memory"] = {
            "stored":
                False,

            "reason":
                "memory_persistence_error",
        }


    return result

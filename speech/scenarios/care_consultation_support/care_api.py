#!/usr/bin/env python3

from __future__ import annotations

import threading
from typing import Optional

import uvicorn

from fastapi import (
    FastAPI,
    HTTPException,
)

from pydantic import BaseModel


from care_controller import (
    CareConsultation,
)

from care_db import (
    add_message,
    create_session,
    finish_session,
    get_elderly,
    update_session_context,
)

from care_prompt import (
    build_policy_context,
)

from llm_client import (
    DEFAULT_MODEL,
)


app = FastAPI(
    title=(
        "Elder Companion "
        "Care Consultation API"
    ),

    version="1.0",
)


# =========================================================
# 当前活动会话
#
# 第一版使用进程内对象保存对话状态。
# SQLite 仍然保存完整消息记录。
# =========================================================

SESSIONS = {}

LOCK = threading.Lock()


class CareChatRequest(
    BaseModel
):

    elderly_id: int = 1

    session_id: Optional[int] = None

    text: str


def build_tags_if_needed(
    consultation,
    result,
):

    tags = result.get(
        "tags"
    )

    if tags:
        return tags

    care_domain = (
        result.get(
            "care_domain"
        )
        or consultation.care_domain
        or "general_care"
    )

    risk_level = (
        result.get(
            "risk_level"
        )
        or consultation.risk_level
        or "low"
    )

    return (
        build_policy_context(
            care_domain=
                care_domain,

            risk_level=
                risk_level,

            round_no=max(
                1,
                consultation.round_no,
            ),

            max_rounds=None,
        )[
            "tags"
        ]
    )


def save_turn(
    *,
    session_id,
    consultation,
    user_text,
    result,
):

    round_no = max(
        1,
        consultation.round_no,
    )

    add_message(
        session_id=
            session_id,

        round_no=
            round_no,

        role=
            "user",

        content=
            user_text,

        tags=None,
    )

    care_domain = result.get(
        "care_domain"
    )

    risk_level = result.get(
        "risk_level"
    )

    update_session_context(
        session_id=
            session_id,

        care_domain=
            care_domain,

        risk_level=
            risk_level,
    )

    reply = result.get(
        "reply"
    )

    tags = build_tags_if_needed(
        consultation,
        result,
    )

    if reply:

        add_message(
            session_id=
                session_id,

            round_no=
                round_no,

            role=
                "assistant",

            content=
                reply,

            tags=
                tags,
        )

    return tags


def finish_if_needed(
    session_id,
    consultation,
    result,
):

    state = result.get(
        "state"
    )

    transfer_to = result.get(
        "transfer_to"
    )

    should_end = (
        state
        in {
            "ENDED",
            "NOT_CARE_CONSULTATION",
        }
        or bool(
            transfer_to
        )
    )

    if not should_end:
        return False

    finish_session(
        session_id=
            session_id,

        completed_rounds=
            consultation.round_no,

        end_reason=
            result.get(
                "end_reason"
            )
            or (
                "transfer"
                if transfer_to
                else "ended"
            ),
    )

    with LOCK:

        SESSIONS.pop(
            session_id,
            None,
        )

    return True


@app.get(
    "/health"
)
def health():

    return {
        "ok":
            True,

        "service":
            "care-consultation-service",

        "model":
            DEFAULT_MODEL,

        "conversation_mode":
            "until_user_end",
    }


@app.post(
    "/v1/care/chat"
)
def care_chat(
    request: CareChatRequest,
):

    text = str(
        request.text
        or ""
    ).strip()

    if not text:

        raise HTTPException(
            status_code=400,
            detail="text_is_empty",
        )


    # -----------------------------------------------------
    # 新会话
    # -----------------------------------------------------

    if request.session_id is None:

        elderly = get_elderly(
            request.elderly_id
        )

        if elderly is None:

            raise HTTPException(
                status_code=404,
                detail="elderly_not_found",
            )

        # 数据库中的 0 表示：
        # 当前版本不使用固定最大轮数。
        session_id = create_session(
            request.elderly_id,
            0,
        )

        consultation = (
            CareConsultation(
                elderly_id=
                    request.elderly_id,

                session_id=
                    session_id,

                max_rounds=
                    None,
            )
        )

        with LOCK:

            SESSIONS[
                session_id
            ] = consultation

        try:

            result = (
                consultation.start(
                    text
                )
            )

        except Exception:

            with LOCK:
                SESSIONS.pop(
                    session_id,
                    None,
                )

            finish_session(
                session_id=
                    session_id,

                completed_rounds=
                    consultation.round_no,

                end_reason=
                    "processing_error",
            )

            raise


    # -----------------------------------------------------
    # 已有会话
    # -----------------------------------------------------

    else:

        session_id = (
            request.session_id
        )

        with LOCK:

            consultation = (
                SESSIONS.get(
                    session_id
                )
            )

        if consultation is None:

            raise HTTPException(
                status_code=404,
                detail=(
                    "session_not_active"
                ),
            )

        if (
            consultation.elderly_id
            != request.elderly_id
        ):

            raise HTTPException(
                status_code=409,
                detail=(
                    "elderly_id_mismatch"
                ),
            )

        result = (
            consultation
            .handle_user_text(
                text
            )
        )


    tags = save_turn(
        session_id=
            session_id,

        consultation=
            consultation,

        user_text=
            text,

        result=
            result,
    )


    should_end = (
        finish_if_needed(
            session_id,
            consultation,
            result,
        )
    )


    return {
        "ok":
            result.get(
                "ok",
                True,
            ),

        "session_id":
            session_id,

        "elderly_id":
            request.elderly_id,

        "state":
            result.get(
                "state"
            ),

        "reply":
            result.get(
                "reply"
            ),

        "turn":
            consultation.round_no,

        "care_domain":
            result.get(
                "care_domain"
            ),

        "risk_level":
            result.get(
                "risk_level"
            ),

        "response_mode":
            tags.get(
                "RESPONSE_MODE"
            ),

        "knowledge_used":
            result.get(
                "knowledge_used",
                [],
            ),

        "tags":
            tags,

        "transfer_to":
            result.get(
                "transfer_to"
            ),

        "transfer_text":
            result.get(
                "transfer_text"
            ),

        "matched_risk":
            result.get(
                "matched_risk"
            ),

        "assistance_request_id":
            result.get(
                "assistance_request_id"
            ),

        "should_end":
            should_end,

        "model":
            result.get(
                "model"
            ),

        "llm_ms":
            result.get(
                "llm_ms"
            ),
    }


@app.post(
    "/v1/care/session/{session_id}/end"
)
def end_session(
    session_id: int,
):

    with LOCK:

        consultation = (
            SESSIONS.pop(
                session_id,
                None,
            )
        )

    if consultation is None:

        raise HTTPException(
            status_code=404,
            detail="session_not_active",
        )

    finish_session(
        session_id=
            session_id,

        completed_rounds=
            consultation.round_no,

        end_reason=
            "external_end",
    )

    return {
        "ok":
            True,

        "session_id":
            session_id,

        "state":
            "ENDED",
    }


if __name__ == "__main__":

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8810,
        log_level="info",
    )

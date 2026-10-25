"""Persist the urgent handoff in the existing platform-facing care tables.

Committing this transaction is a database receipt, not a notification or an
acknowledgement from staff. The external platform owns subsequent processing.
"""
from __future__ import annotations

import json
from contextlib import closing
from datetime import datetime

import elder_need_registry as registry


URGENT_SUMMARY = "紧急护理求助：请工作人员立即查看"


def submit_urgent_assistance(*, elderly_id, session_id, care_domain, raw_text,
                             matched_risk, history=(), round_no=1, dry_run=False):
    receipt = {
        "status": "simulated" if dry_run else "failed",
        "need_id": None, "assistance_request_id": None,
        "notification_status": "unconfirmed", "owner": "external_platform",
    }
    if dry_run:
        return receipt
    try:
        # Serialize read/create/upgrade across processes. A failed second write
        # rolls back the first; retries use the existing care session key.
        with closing(registry.connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            session = conn.execute(
                "SELECT elderly_id FROM care_consultation_session WHERE id = ?",
                (session_id,),
            ).fetchone()
            if session is None or session["elderly_id"] != int(elderly_id):
                raise ValueError("urgent_session_elder_mismatch")
            key = f"care:{session_id}"
            existing = conn.execute(
                "SELECT * FROM elder_need WHERE dedupe_key = ?", (key,),
            ).fetchone()
            details = {}
            if existing is not None:
                if existing["elderly_id"] != int(elderly_id):
                    raise ValueError("urgent_need_elder_mismatch")
                try:
                    parsed = json.loads(existing["details_json"] or "{}")
                    details = parsed if isinstance(parsed, dict) else {}
                except (TypeError, ValueError):
                    pass
                # Do not reopen or overwrite a task already received/handled
                # by the platform when this scene retries its handoff.
                if details.get("urgent_assistance") is True:
                    request_id = details.get("assistance_request_id")
                    request = conn.execute(
                        "SELECT id FROM care_assistance_request "
                        "WHERE id = ? AND session_id = ? AND elderly_id = ?",
                        (request_id, session_id, elderly_id),
                    ).fetchone()
                    if request is None:
                        raise ValueError("urgent_linked_request_missing")
                    return {**receipt, "status": "recorded", "need_id": existing["id"],
                            "assistance_request_id": request_id, "reused": True}

            # Reuse an outstanding medium-risk staff item during escalation.
            request = conn.execute(
                "SELECT id FROM care_assistance_request WHERE session_id = ? "
                "AND elderly_id = ? AND status = 'pending' ORDER BY id LIMIT 1",
                (session_id, elderly_id),
            ).fetchone()
            domain = care_domain or "general_care"
            if request is None:
                cursor = conn.execute(
                    "INSERT INTO care_assistance_request "
                    "(session_id, elderly_id, care_domain, risk_level, "
                    "user_description, summary, status) VALUES (?, ?, ?, ?, ?, ?, 'pending')",
                    (session_id, elderly_id, domain, "external_route", raw_text, URGENT_SUMMARY),
                )
                request_id = cursor.lastrowid
            else:
                request_id = request["id"]
                conn.execute(
                    "UPDATE care_assistance_request SET care_domain = ?, risk_level = ?, "
                    "user_description = ?, summary = ? WHERE id = ?",
                    (domain, "external_route", raw_text, URGENT_SUMMARY, request_id),
                )
            # Preserve user evidence only; assistant questions are not symptoms.
            evidence = [str(item.get("content", ""))[:2000] for item in history[-12:]
                        if item.get("role") == "user"]
            if not evidence or evidence[-1] != raw_text:
                evidence.append(raw_text)
            details.update({
                "urgent_assistance": True, "target_scene": "URGENT_ASSISTANCE",
                "care_domain": domain, "risk_level": "external_route",
                "staff_follow_up": True, "assistance_request_id": request_id,
                "latest_raw_text": raw_text, "matched_risk": list(matched_risk),
                "reported_user_context": evidence[-12:],
                "notification_owner": "external_platform",
                "notification_status": "unconfirmed",
            })
            # An escalation can follow the initial record within one second.
            # Keep updated_at distinguishable for platform incremental polling.
            now = datetime.now(registry.CHINA_TZ).strftime("%Y-%m-%d %H:%M:%S.%f")
            encoded = json.dumps(details, ensure_ascii=False)
            if existing is None:
                cursor = conn.execute(
                    "INSERT INTO elder_need (elderly_id, need_category, need_code, summary, "
                    "raw_text, priority, status, source_scene, source_session_id, source_round_no, "
                    "details_json, dedupe_key, handled_by, created_at, updated_at) "
                    "VALUES (?, 'care', 'care_urgent_assistance', ?, ?, 'urgent', 'detected', "
                    "'CARE_CONSULTATION_SUPPORT', ?, ?, ?, ?, 'URGENT_ASSISTANCE', ?, ?)",
                    (elderly_id, URGENT_SUMMARY, raw_text, str(session_id), round_no,
                     encoded, key, now, now),
                )
                need_id = cursor.lastrowid
            else:
                need_id = existing["id"]
                conn.execute(
                    "UPDATE elder_need SET need_code = 'care_urgent_assistance', summary = ?, "
                    "raw_text = ?, priority = 'urgent', status = 'detected', source_round_no = ?, "
                    "details_json = ?, handled_by = 'URGENT_ASSISTANCE', updated_at = ?, "
                    "completed_at = NULL WHERE id = ?",
                    (URGENT_SUMMARY, raw_text, round_no, encoded, now, need_id),
                )
        return {**receipt, "status": "recorded", "need_id": need_id,
                "assistance_request_id": request_id, "reused": False}
    except Exception as exc:
        return {**receipt, "error": type(exc).__name__ + ": " + str(exc)}


def urgent_reply(receipt):
    if receipt["status"] == "recorded":
        return ("您描述的情况需要工作人员马上查看。"
                "我已记录紧急求助，等待工作人员处理。")
    if receipt["status"] == "simulated":
        return "您描述的情况需要工作人员马上查看，请现场人员立即联系工作人员。"
    return ("您描述的情况需要工作人员马上查看。"
            "紧急求助暂时未能提交，请现场人员立即联系工作人员。")

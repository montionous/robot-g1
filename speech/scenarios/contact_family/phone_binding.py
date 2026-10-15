from __future__ import annotations

import os


ANDROID_CONTACT_ID = "owner"


def configured_db_contact_id():
    raw = os.getenv(
        "G1_PHONE_OWNER_DB_CONTACT_ID",
        "",
    ).strip()

    if not raw:
        return None

    try:
        return int(raw)
    except ValueError as exc:
        raise RuntimeError(
            "G1_PHONE_OWNER_DB_CONTACT_ID 必须是整数"
        ) from exc


def binding_summary(contact):
    configured = (
        configured_db_contact_id()
    )

    if configured is None:
        return {
            "available": False,
            "provider_contact_id": None,
            "reason":
                "owner_db_contact_not_configured",
        }

    if contact is None:
        return {
            "available": False,
            "provider_contact_id": None,
            "reason":
                "selected_contact_missing",
        }

    if int(contact["id"]) != configured:
        return {
            "available": False,
            "provider_contact_id": None,
            "reason":
                "selected_contact_not_bound_to_owner",
        }

    return {
        "available": True,
        "provider_contact_id":
            ANDROID_CONTACT_ID,
        "reason": None,
    }

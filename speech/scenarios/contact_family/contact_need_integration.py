"""Shared elder-need records for the contact-family scene.

This is intentionally separate from call logs.  A shared need records that the
elder asked for contact and its high-level handling result; it never stores the
original contact utterance, contact name, phone number or final authorization
utterance.
"""

from __future__ import annotations

from uuid import uuid4

from elder_need_registry import (
    create_need,
    elderly_is_enabled,
    update_need,
)


SCENE = "CONTACT_FAMILY"
NEED_CATEGORY = "contact_family"
NEED_CODE = "contact_family_call"

# 共享表会被照护控制台直接查看，因此处理结果只能来自这份封闭枚举。
# 拨号后端返回的 operation_state、异常信息和识别文本都不能直接写入。
SAFE_OUTCOMES = frozenset(
    {
        "accepted",
        "connected_demo",
        "contact_confirmation_cancelled",
        "contact_confirmation_unclear",
        "contact_not_found",
        "dial_authorization_cancelled",
        "dial_authorization_unclear",
        "dial_authorized_safe_stub",
        "dial_failed",
        "phone_prepare_failed",
        "real_phone_binding_blocked",
        "scene_failed",
        "scene_interrupted",
    }
)


class ContactFamilyNeedSession:
    """Create one recoverable shared record for a contact request."""

    def __init__(
        self,
        *,
        elderly_id=None,
        record=False,
    ):
        self.session_id = uuid4().hex
        self.elderly_id = None
        self.record = False
        self.need_id = None
        self.details = None

        if elderly_id is None:
            print("共享需求：未指定老人ID，暂不关联老人", flush=True)
            return

        try:
            if not elderly_is_enabled(elderly_id):
                print(
                    f"共享需求：老人ID {elderly_id} 不存在或未启用",
                    flush=True,
                )
                return

        except Exception as exc:
            print(f"共享需求：身份校验失败 {exc!r}", flush=True)
            return

        self.elderly_id = int(elderly_id)
        self.record = bool(record)

        print(
            f"共享需求：elderly_id={self.elderly_id} "
            f"写入={'开启' if self.record else '关闭（只读）'}",
            flush=True,
        )

    @staticmethod
    def _contact_details(contact):
        """Retain only the relation needed for care coordination."""

        if not isinstance(contact, dict):
            return {
                "contact_matched": False,
            }

        relation = str(contact.get("relation") or "").strip()
        details = {
            "contact_matched": True,
        }

        if relation:
            details["contact_relation"] = relation

        return details

    @staticmethod
    def _safe_outcome(outcome):
        """Map untrusted backend output to a small, non-sensitive outcome."""

        value = str(outcome or "").strip()
        if value in SAFE_OUTCOMES:
            return value
        return "dial_failed"

    def begin(
        self,
        *,
        raw_text,
        contact=None,
    ):
        """Record an accepted contact intent before confirmation or dialing."""

        if (
            self.need_id is not None
            or not self.record
            or self.elderly_id is None
            or not str(raw_text or "").strip()
        ):
            return self.need_id

        details = self._contact_details(contact)
        summary = "老人请求联系家人"

        if details.get("contact_relation"):
            summary += f"：{details['contact_relation']}"

        try:
            row = create_need(
                elderly_id=self.elderly_id,
                need_category=NEED_CATEGORY,
                need_code=NEED_CODE,
                summary=summary,
                # 联系原话可能包含联系人姓名甚至号码。完整原话只由
                # 联系场景自己的受控日志处理，跨场景共享表只保存
                # 标准化摘要和 relation。
                raw_text=None,
                priority="normal",
                status="in_progress",
                source_scene=SCENE,
                source_session_id=self.session_id,
                source_round_no=1,
                details=details,
                dedupe_key=f"contact_family:{self.session_id}",
                handled_by=SCENE,
            )
            self.need_id = row["id"]
            self.details = details
            print(
                f"共享需求创建：id={self.need_id} {NEED_CODE}",
                flush=True,
            )
            return self.need_id

        except Exception as exc:
            print(
                f"共享需求写入异常（不影响联系家人）：{exc!r}",
                flush=True,
            )
            return None

    def finish(
        self,
        *,
        status,
        outcome,
        contact=None,
    ):
        """Persist a coarse outcome without contact phone or authorization text."""

        if self.need_id is None:
            return None

        details = dict(self.details or {})
        # 异常收尾通常不知道联系人对象；此时保留 begin() 时已验证的
        # 关系摘要，不能把已匹配联系人误改成未匹配。
        if contact is not None:
            details.update(self._contact_details(contact))
        details["outcome"] = self._safe_outcome(outcome)

        updated = False

        try:
            row = update_need(
                self.need_id,
                status=status,
                details=details,
                handled_by=SCENE,
            )
            updated = True
            print(
                f"共享需求更新：id={self.need_id} {status}",
                flush=True,
            )
            return row

        except Exception as exc:
            print(
                f"共享需求状态更新异常：{exc!r}",
                flush=True,
            )
            return None

        finally:
            # 数据库短暂锁定时保留 need_id，调用方可以重试 finish；
            # 不能把实际仍为 in_progress 的记录丢成无法更新的孤儿。
            # 每个联系请求只需要一次最终状态写入。包括 accepted 和
            # safe_stub 的 in_progress 在内，只要成功写库便不再让场景
            # 收尾覆盖该结果；写入失败则保留句柄以便 close()/重试。
            if updated:
                self.need_id = None
                self.details = None

    def close(self, *, outcome="scene_interrupted"):
        """Mark an unfinished confirmation flow as cancelled when the scene stops."""

        return self.finish(
            status="cancelled",
            outcome=outcome,
        )

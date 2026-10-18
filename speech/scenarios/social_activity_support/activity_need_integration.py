"""Shared elder-need records and preference ranking for social activities.

The activity tables remain the source of truth for schedules, registrations and
staff notifications.  This module only writes a compact cross-scene summary to
``elder_need`` and reads completed participation intentions to improve a later
generic recommendation for the same elder.
"""

from __future__ import annotations

from collections import Counter
from uuid import uuid4

from elder_need_registry import (
    connect as connect_shared_need_db,
    create_need,
    elderly_is_enabled,
    get_elder_need_history,
    update_need,
)


SCENE = "SOCIAL_ACTIVITY_SUPPORT"
NEED_CATEGORY = "social_activity"
QUERY_CODE = "activity_query"
INTEREST_CODE = "activity_interest"


class ActivityNeedSession:
    """Keep one scene run's shared records small, explicit and recoverable."""

    def __init__(
        self,
        *,
        elderly_id=None,
        record=False,
    ):
        self.session_id = uuid4().hex
        self.round_no = 0
        self.elderly_id = None
        self.record = False
        self.pending_need_id = None
        self.pending_details = None

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
    def _is_generic_query(filters):
        value = dict(filters or {})
        return not (
            value.get("category")
            or value.get("keyword")
        )

    @staticmethod
    def _item_details(item):
        if not isinstance(item, dict):
            return {}

        details = {}

        for source, target in (
            ("activity_id", "activity_id"),
            ("session_id", "session_id"),
            ("name", "activity_name"),
            ("category", "activity_category"),
            ("activity_date", "activity_date"),
            ("start_time", "start_time"),
            ("status", "activity_status"),
        ):
            value = item.get(source)
            if value is not None and str(value).strip():
                details[target] = value

        return details

    @staticmethod
    def _query_details(controller, result):
        filters = dict(getattr(controller, "last_filters", None) or {})
        safe_filters = {
            key: value
            for key, value in filters.items()
            if key in {
                "activity_date",
                "period",
                "category",
                "keyword",
                "scope",
            }
            and value is not None
        }

        return {
            "filters": safe_filters,
            "result_action": result.get("action"),
            "result_count": int(
                result.get("recommended_count", 0) or 0
            ),
        }

    def rank_recommendations(
        self,
        items,
        *,
        filters=None,
    ):
        """Rank generic recommendations by confirmed historical interest.

        Specific queries retain the requested database order.  A confirmed
        participation intention weighs an exact activity more strongly than
        its category, and original schedule order breaks ties.
        """

        original = list(items or [])

        if (
            self.elderly_id is None
            or not original
            or not self._is_generic_query(filters)
        ):
            return original

        try:
            history = get_elder_need_history(
                self.elderly_id,
                need_category=NEED_CATEGORY,
                need_code=INTEREST_CODE,
                status="completed",
                limit=200,
            )

            activity_scores = Counter()
            category_scores = Counter()

            for row in history:
                details = row.get("details") or {}
                activity_id = details.get("activity_id")
                category = details.get("activity_category")

                if activity_id is not None:
                    activity_scores[str(activity_id)] += 1

                if category:
                    category_scores[str(category)] += 1

            # 部署共享库之前，活动场景已经有自己的登记表。两份历史
            # 并存时也要保留旧表偏好；否则老人新增一次共享记录后，
            # 以前多次报名过的活动会突然失去权重。共享记录的 details
            # 保存了活动 session_id，遇到相同 session 时只计一次，避免
            # 新旧双写把同一意愿重复放大。
            shared_session_ids = {
                str(details["session_id"])
                for row in history
                for details in [row.get("details") or {}]
                if details.get("session_id") is not None
            }

            try:
                with connect_shared_need_db() as conn:
                    rows = conn.execute(
                        """
                        SELECT
                            i.session_id,
                            a.activity_id,
                            a.category

                        FROM social_activity_interest AS i

                        JOIN social_activity_session AS s
                          ON s.session_id = i.session_id

                        JOIN social_activity AS a
                          ON a.activity_id = s.activity_id

                        WHERE i.elder_id = ?
                          AND i.status IN (
                              'pending',
                              'waitlist',
                              'confirmed'
                          )
                        """,
                        (self.elderly_id,),
                    ).fetchall()

                for session_id, activity_id, category in rows:
                    if str(session_id) in shared_session_ids:
                        continue
                    if activity_id is not None:
                        activity_scores[str(activity_id)] += 1
                    if category:
                        category_scores[str(category)] += 1

            except Exception:
                # 旧数据库可能尚未初始化活动表；这不应影响当前活动
                # 查询或新的共享需求写入。
                pass

            if not activity_scores and not category_scores:
                return original

            ranked = [
                item
                for _, item in sorted(
                    enumerate(original),
                    key=lambda pair: (
                        -(
                            activity_scores.get(
                                str(pair[1].get("activity_id")),
                                0,
                            )
                            * 100
                            + category_scores.get(
                                str(pair[1].get("category") or ""),
                                0,
                            )
                        ),
                        pair[0],
                    ),
                )
            ]

            if ranked != original:
                print("历史活动偏好已用于推荐排序", flush=True)

            return ranked

        except Exception as exc:
            print(
                f"历史活动偏好读取失败，保留原推荐顺序：{exc!r}",
                flush=True,
            )
            return original

    def _create(
        self,
        *,
        need_code,
        summary,
        raw_text,
        status,
        details,
    ):
        if (
            not self.record
            or self.elderly_id is None
            or not str(raw_text or "").strip()
        ):
            return None

        self.round_no += 1

        try:
            row = create_need(
                elderly_id=self.elderly_id,
                need_category=NEED_CATEGORY,
                need_code=need_code,
                summary=summary,
                raw_text=str(raw_text).strip(),
                priority="normal",
                status=status,
                source_scene=SCENE,
                source_session_id=self.session_id,
                source_round_no=self.round_no,
                details=details,
                dedupe_key=(
                    f"social_activity:{self.session_id}:"
                    f"{self.round_no}:{need_code}"
                ),
                handled_by=SCENE,
            )
            print(
                f"共享需求创建：id={row['id']} {need_code}",
                flush=True,
            )
            return row

        except Exception as exc:
            print(
                f"共享需求写入异常（不影响活动咨询）：{exc!r}",
                flush=True,
            )
            return None

    def _begin_interest(
        self,
        *,
        raw_text,
        selected,
        mode,
    ):
        if self.pending_need_id is not None:
            return self.pending_need_id

        details = self._item_details(selected)
        if not details:
            return None

        details["request_mode"] = mode
        row = self._create(
            need_code=INTEREST_CODE,
            summary=(
                "老人表达参加活动意愿"
                + (
                    f"：{details['activity_name']}"
                    if details.get("activity_name")
                    else ""
                )
            ),
            raw_text=raw_text,
            status="in_progress",
            details=details,
        )

        if row is not None:
            self.pending_need_id = row["id"]
            self.pending_details = details

        return self.pending_need_id

    def _finish_interest(
        self,
        *,
        status,
        outcome,
        selected=None,
        raw_text=None,
    ):
        if self.pending_need_id is None:
            if status != "completed":
                return None

            # 展示版的无需报名活动会直接给出参与指引，
            # 没有中间确认状态；这里补一条已确认意愿。
            self._begin_interest(
                raw_text=raw_text,
                selected=selected,
                mode="direct_guidance",
            )

        if self.pending_need_id is None:
            return None

        details = dict(self.pending_details or {})

        pending_session_id = details.get("session_id")
        selected_details = self._item_details(selected)
        selected_session_id = selected_details.get("session_id")

        if (
            pending_session_id is not None
            and selected_session_id is not None
            and str(pending_session_id) != str(selected_session_id)
        ):
            print(
                "共享需求：活动确认目标不一致，保留原确认状态",
                flush=True,
            )
            return None

        details["outcome"] = outcome

        updated = False

        try:
            row = update_need(
                self.pending_need_id,
                status=status,
                details=details,
                handled_by=SCENE,
            )
            updated = True
            print(
                f"共享需求更新：id={self.pending_need_id} {status}",
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
            # 数据库更新失败时保留句柄，让场景收尾或后续动作可以重试，
            # 不把实际仍为 in_progress 的记录遗留在控制台中。
            if updated:
                self.pending_need_id = None
                self.pending_details = None

    def record_result(
        self,
        *,
        raw_text,
        result,
        controller,
    ):
        """Write only accepted business actions; ignored ASR is never stored."""

        if not self.record or not result:
            return None

        action = str(result.get("action") or "")
        selected = result.get("selected") or getattr(
            controller,
            "selected",
            None,
        )

        if action in {
            "recommend",
            "single_result",
            "selected_query",
            "not_found",
        }:
            return self._create(
                need_code=QUERY_CODE,
                summary="老人查询社区活动",
                raw_text=raw_text,
                status="completed",
                details=self._query_details(controller, result),
            )

        modes = {
            "confirm_join": "normal_registration",
            "confirm_waitlist": "waitlist",
            "confirm_late_inquiry": "late_registration_inquiry",
            "ask_join_confirmation": "normal_registration",
        }

        if action in modes:
            return self._begin_interest(
                raw_text=raw_text,
                selected=selected,
                mode=modes[action],
            )

        if action == "participation_guidance":
            return self._finish_interest(
                status="completed",
                outcome="participation_guidance",
                selected=selected,
                raw_text=raw_text,
            )

        if action == "interest_recorded":
            return self._finish_interest(
                status="completed",
                outcome="interest_recorded",
                selected=selected,
                raw_text=raw_text,
            )

        if action == "already_recorded":
            return self._finish_interest(
                status="completed",
                outcome="already_recorded",
                selected=selected,
                raw_text=raw_text,
            )

        if action == "join_cancelled":
            return self._finish_interest(
                status="cancelled",
                outcome="join_cancelled",
            )

        if action == "cannot_join":
            self._begin_interest(
                raw_text=raw_text,
                selected=selected,
                mode="unavailable",
            )
            return self._finish_interest(
                status="failed",
                outcome="cannot_join",
            )

        return None

    def close(self, *, outcome="scene_ended"):
        """Do not leave an unanswered participation confirmation in progress."""

        return self._finish_interest(
            status="cancelled",
            outcome=outcome,
        )

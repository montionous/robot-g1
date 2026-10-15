"""Read the interaction owner's business records without starting its owners."""

from __future__ import annotations

import json
import math
import sqlite3
from datetime import datetime


KIND_ORDER = ("care", "chat", "call", "activity", "notification", "assistance")
KINDS = set(KIND_ORDER)
MAX_ID = 2**63 - 1
MAX_LIMIT = 200
MAX_MESSAGE_LIMIT = 500
MAX_TEXT_BYTES = 64 * 1024
MAX_NAME_BYTES = 256
MAX_CURSOR_BYTES = 256
MAX_JSON_DEPTH = 64

TABLE_REQUIREMENTS = {
    "care_consultation_session": {
        "id", "elderly_id", "status", "started_at", "ended_at", "end_reason",
        "care_domain", "risk_level", "session_source", "persist_memory",
    },
    "care_consultation_message": {
        "id", "session_id", "round_no", "role", "content", "tags_json", "created_at",
    },
    "short_chat_session": {
        "id", "elderly_id", "status", "started_at", "ended_at", "end_reason",
    },
    "short_chat_message": {
        "id", "session_id", "round_no", "role", "content", "created_at",
    },
    "contact_call_log": {
        "id", "elderly_id", "contact_id", "recognized_text", "requested_relation",
        "confirmed", "call_status", "created_at",
    },
    "social_activity_interest": {
        "interest_id", "elder_id", "session_id", "status", "created_at", "updated_at",
    },
    "staff_notification": {
        "notification_id", "elder_id", "session_id", "notification_type", "message",
        "status", "created_at",
    },
    "care_assistance_request": {
        "id", "session_id", "elderly_id", "care_domain", "risk_level", "user_description",
        "summary", "status", "created_at",
    },
    "family_contact": {"id", "elderly_id", "name", "relation"},
    "social_activity_session": {
        "session_id", "activity_id", "activity_date", "start_time", "end_time", "status",
    },
    "social_activity": {"activity_id", "name"},
}

MAIN_TABLES = {
    "care": "care_consultation_session",
    "chat": "short_chat_session",
    "call": "contact_call_log",
    "activity": "social_activity_interest",
    "notification": "staff_notification",
    "assistance": "care_assistance_request",
}

MESSAGE_TABLES = {"care": "care_consultation_message", "chat": "short_chat_message"}


def _bounded_text(value, field, limit=MAX_TEXT_BYTES):
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} 不是文本")
    try:
        size = len(value.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise ValueError(f"{field} 不是有效 UTF-8 文本") from exc
    if size > limit:
        raise ValueError(f"{field} 超过 {limit} 字节")
    return value


def _short_excerpt(value, field, limit=MAX_NAME_BYTES):
    """Return a display-only UTF-8-safe excerpt without changing the source value."""
    value = _bounded_text(value, field)
    if value is None or len(value.encode("utf-8")) <= limit:
        return value
    suffix = "…"
    budget = limit - len(suffix.encode("utf-8"))
    return value.encode("utf-8")[:budget].decode("utf-8", "ignore") + suffix


def _bounded_id(value, field="id"):
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_ID:
        raise ValueError(f"{field} 超出 SQLite 整数范围")
    return str(value)


def _number(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} 不是有限数值")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"{field} 不是有限数值")
    return value


def _time(value, field):
    """Validate a stored timestamp while preserving its source spelling and zone."""
    value = _bounded_text(value, field, 80)
    if value is None:
        return None, None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} 时间格式不正确") from exc
    return value, "source_timezone_explicit" if parsed.tzinfo else "source_timezone_unspecified"


def _json_value(raw, field):
    if raw in (None, ""):
        return None, ""
    raw = _bounded_text(raw, field, MAX_TEXT_BYTES)

    def reject_constant(_):
        raise ValueError("禁止非有限数值")

    try:
        value = json.loads(raw, parse_constant=reject_constant)
        _check_json(value, field)
        json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
        return value, ""
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        return None, f"{field} 不可用：{exc}"


def _check_json(value, field, depth=0):
    if depth > MAX_JSON_DEPTH:
        raise ValueError(f"{field} 嵌套超过 {MAX_JSON_DEPTH} 层")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"{field} 含非有限数值")
    if isinstance(value, dict):
        for key, child in value.items():
            _bounded_text(key, f"{field}.key", 1024)
            _check_json(child, field, depth + 1)
    elif isinstance(value, list):
        for child in value:
            _check_json(child, field, depth + 1)


def _parse_id_cursor(value, field):
    if value is None:
        return None
    value = _bounded_text(value, field, MAX_CURSOR_BYTES)
    if not value or not value.isascii() or not value.isdecimal():
        raise ValueError(f"{field} 分页编号不正确")
    number = int(value)
    if not 1 <= number <= MAX_ID:
        raise ValueError(f"{field} 分页编号超出允许范围")
    return number


def _parse_record_cursor(value):
    if value is None:
        return None
    value = _bounded_text(value, "before", MAX_CURSOR_BYTES)
    parts = value.split(":")
    if len(parts) != 2 or parts[0] not in KINDS:
        raise ValueError("before 分页游标不正确")
    return parts[0], _parse_id_cursor(parts[1], "before")


def _parse_message_cursor(value):
    if value is None:
        return None
    value = _bounded_text(value, "after", MAX_CURSOR_BYTES)
    parts = value.split(":")
    if len(parts) == 1:
        return None, _parse_id_cursor(parts[0], "after")
    if len(parts) != 2:
        raise ValueError("after 分页游标不正确")
    round_no = int(parts[0]) if parts[0].isascii() and parts[0].isdecimal() else -1
    if round_no < 0 or round_no > 1_000_000_000:
        raise ValueError("after 分页轮次不正确")
    return round_no, _parse_id_cursor(parts[1], "after")


def _row_dict(row):
    return dict(row) if not isinstance(row, dict) else row


class BusinessRecords:
    """Read-only projections over the interaction database's existing tables."""

    def __init__(self, reader):
        self.reader = reader

    @staticmethod
    def _empty_list():
        return {
            "status": "ready",
            "error": "",
            "items": [],
            "total": 0,
            "next": None,
            "availability": {kind: "unavailable" for kind in KIND_ORDER},
        }

    @staticmethod
    def _empty_get():
        return {"status": "missing", "error": "", "item": None, "messages": [], "next_message": None}

    @staticmethod
    def _table_states(db):
        states = {}
        for table, required in TABLE_REQUIREMENTS.items():
            rows = db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchall()
            if not rows:
                states[table] = "unavailable"
                continue
            columns = {row[1] for row in db.execute(f"PRAGMA table_info({table})").fetchall()}
            states[table] = "available" if required <= columns else "unavailable"
        return states

    @staticmethod
    def _availability(states):
        result = {
            kind: ("available" if states.get(table) == "available" else "unavailable")
            for kind, table in MAIN_TABLES.items()
        }
        # Keep per-table detail so a missing message/join table is visible without
        # suppressing records from its still-readable primary table.
        result["tables"] = states
        return result

    @staticmethod
    def _bound_elders(elders, _source_key, elder_id=None):
        bindings = {}
        for elder in elders:
            if not isinstance(elder, dict):
                raise ValueError("本地老人档案格式不正确")
            if elder.get("interaction_elderly_id") in (None, ""):
                continue
            if elder_id is not None and str(elder.get("id")) != str(elder_id):
                continue
            if isinstance(elder["interaction_elderly_id"], bool):
                raise ValueError("interaction_elderly_id 不是整数")
            external_id = int(elder["interaction_elderly_id"])
            external_key = _bounded_id(external_id, "interaction_elderly_id")
            local_key = _bounded_id(int(elder.get("id")), "elder_id")
            name = _bounded_text(elder.get("name"), "elder_name", MAX_NAME_BYTES)
            if not name:
                raise ValueError("已绑定老人缺少姓名")
            bindings[external_id] = {"id": local_key, "name": name, "external_id": external_key}
        return bindings

    @staticmethod
    def _elder_ids(bindings):
        return list(bindings)

    @staticmethod
    def _in_clause(column, values):
        return f"{column} IN ({','.join('?' for _ in values)})"

    @staticmethod
    def _where_for_elder(column, bindings):
        return BusinessRecords._in_clause(column, BusinessRecords._elder_ids(bindings))

    @staticmethod
    def _item_id(kind, row):
        return _bounded_id(row["id"], f"{kind}.id")

    @staticmethod
    def _elder_id(kind, row):
        return _bounded_id(row["elderly_id"], f"{kind}.elder_id")

    @staticmethod
    def _raw_value(value, field):
        if value is None:
            return None
        if isinstance(value, str):
            return _bounded_text(value, field)
        if isinstance(value, (int, float)):
            return _number(value, field)
        raise ValueError(f"{field} 数据类型不受支持")

    @staticmethod
    def _base_time(row, fields):
        times = {}
        basis = {}
        for field in fields:
            value, field_basis = _time(row.get(field), field)
            times[field] = value
            if field_basis:
                basis[field] = field_basis
        return times, basis

    def _raw_row(self, row, field_names):
        raw = {}
        for field in field_names:
            value = row.get(field)
            if field in {"id", "elderly_id", "contact_id", "session_id", "interest_id", "notification_id", "elder_id", "activity_id"}:
                if value is not None:
                    value = _bounded_id(value, field)
            elif field in {"started_at", "ended_at", "created_at", "updated_at"}:
                value, _ = _time(value, field)
            elif field == "tags_json":
                value = _bounded_text(value, field)
            elif field == "persist_memory" or field == "confirmed":
                if value is not None:
                    value = _number(value, field)
                    if value not in (0, 1):
                        raise ValueError(f"{field} 不是 0/1")
            else:
                value = self._raw_value(value, field)
            raw[field] = value
        return raw

    def _message_summary(self, db, kind, session_id, states):
        table = MESSAGE_TABLES.get(kind)
        if not table or states.get(table) != "available":
            return ""
        row = db.execute(
            f"SELECT content FROM {table} WHERE session_id=? ORDER BY round_no ASC,id ASC LIMIT 1",
            (session_id,),
        ).fetchone()
        if not row:
            return ""
        return _bounded_text(row[0], f"{kind}.summary")

    @staticmethod
    def _daily_filter(kind, states, table):
        # Explicit owner markers exclude test history without rewriting the source.
        if kind == "care":
            return f"COALESCE({table}.session_source,'') NOT IN ('test','demo')"
        if kind == "call":
            return f"COALESCE({table}.call_status,'') NOT IN ('connected_demo','dial_authorized_safe_stub')"
        if kind == "assistance" and states.get("care_consultation_session") == "available":
            return f"""NOT EXISTS (SELECT 1 FROM care_consultation_session AS origin
                WHERE origin.id={table}.session_id AND origin.elderly_id={table}.elderly_id
                AND origin.session_source IN ('test','demo'))"""
        return "1"

    def _list_query(self, db, kind, bindings, before_id, states, limit):
        ids = self._elder_ids(bindings)
        params = list(ids)
        if kind == "care":
            alias, table, elder_column = "s", "care_consultation_session", "s.elderly_id"
            select = "s.id,s.elderly_id,s.status,s.started_at,s.ended_at,s.end_reason,s.care_domain,s.risk_level,s.session_source,s.persist_memory"
        elif kind == "chat":
            alias, table, elder_column = "s", "short_chat_session", "s.elderly_id"
            select = "s.id,s.elderly_id,s.status,s.started_at,s.ended_at,s.end_reason"
        elif kind == "call":
            alias, table, elder_column = "l", "contact_call_log", "l.elderly_id"
            contact = states.get("family_contact") == "available"
            join = " LEFT JOIN family_contact AS c ON c.id=l.contact_id AND c.elderly_id=l.elderly_id" if contact else ""
            select = "l.id,l.elderly_id,l.contact_id,l.recognized_text,l.requested_relation,l.confirmed,l.call_status,l.created_at"
            select += ",c.name AS contact_name,c.relation AS contact_relation" if contact else ",NULL AS contact_name,NULL AS contact_relation"
        elif kind == "activity":
            alias, table, elder_column = "i", "social_activity_interest", "i.elder_id"
            session = states.get("social_activity_session") == "available"
            activity = session and states.get("social_activity") == "available"
            join = ""
            if session:
                join += " LEFT JOIN social_activity_session AS s ON s.session_id=i.session_id"
            if activity:
                join += " LEFT JOIN social_activity AS a ON a.activity_id=s.activity_id"
            select = "i.interest_id AS id,i.interest_id,i.elder_id AS elderly_id,i.elder_id,i.session_id,i.status,i.created_at,i.updated_at"
            select += ",s.activity_date,s.start_time,s.end_time,s.status AS session_status" if session else ",NULL AS activity_date,NULL AS start_time,NULL AS end_time,NULL AS session_status"
            select += ",a.name AS activity_name" if activity else ",NULL AS activity_name"
        elif kind == "notification":
            alias, table, elder_column = "n", "staff_notification", "n.elder_id"
            session = states.get("social_activity_session") == "available"
            activity = session and states.get("social_activity") == "available"
            join = ""
            if session:
                join += " LEFT JOIN social_activity_session AS s ON s.session_id=n.session_id"
            if activity:
                join += " LEFT JOIN social_activity AS a ON a.activity_id=s.activity_id"
            select = "n.notification_id AS id,n.notification_id,n.elder_id AS elderly_id,n.elder_id,n.session_id,n.notification_type,n.message,n.status,n.created_at"
            select += ",s.activity_date,s.start_time,s.end_time" if session else ",NULL AS activity_date,NULL AS start_time,NULL AS end_time"
            select += ",a.name AS activity_name" if activity else ",NULL AS activity_name"
        else:
            alias, table, elder_column = "r", "care_assistance_request", "r.elderly_id"
            select = "r.id,r.session_id,r.elderly_id,r.care_domain,r.risk_level,r.user_description,r.summary,r.status,r.created_at"

        where = [self._where_for_elder(elder_column, bindings), self._daily_filter(kind, states, alias)]
        if before_id is not None:
            where.append(f"{alias}.{'interest_id' if kind == 'activity' else 'notification_id' if kind == 'notification' else 'id'} < ?")
            params.append(before_id)
        if kind in {"call", "activity", "notification"}:
            from_sql = f"{table} AS {alias}{join}"
        else:
            from_sql = f"{table} AS {alias}"
        return db.execute(
            f"SELECT {select} FROM {from_sql} WHERE {' AND '.join(where)} ORDER BY {alias}.{'interest_id' if kind == 'activity' else 'notification_id' if kind == 'notification' else 'id'} DESC LIMIT ?",
            [*params, limit + 1],
        ).fetchall()

    def _count(self, db, kind, bindings, states):
        table = MAIN_TABLES[kind]
        column = "elder_id" if kind in {"activity", "notification"} else "elderly_id"
        return db.execute(
            f"SELECT COUNT(*) FROM {table} WHERE {self._in_clause(column, self._elder_ids(bindings))} AND {self._daily_filter(kind, states, table)}",
            self._elder_ids(bindings),
        ).fetchone()[0]

    def _item_from_row(self, db, kind, row, elder, states, source_key):
        row = _row_dict(row)
        record_id = self._item_id(kind, row)
        external_id = self._elder_id(kind, row)
        if external_id != elder["external_id"]:
            raise ValueError("记录老人身份与绑定不一致")
        raw_fields = {
            "care": ["id", "elderly_id", "status", "started_at", "ended_at", "end_reason", "care_domain", "risk_level", "session_source", "persist_memory"],
            "chat": ["id", "elderly_id", "status", "started_at", "ended_at", "end_reason"],
            "call": ["id", "elderly_id", "contact_id", "recognized_text", "requested_relation", "confirmed", "call_status", "created_at", "contact_name", "contact_relation"],
            "activity": ["id", "interest_id", "elderly_id", "elder_id", "session_id", "status", "created_at", "updated_at", "activity_date", "start_time", "end_time", "session_status", "activity_name"],
            "notification": ["id", "notification_id", "elderly_id", "elder_id", "session_id", "notification_type", "message", "status", "created_at", "activity_date", "start_time", "end_time", "activity_name"],
            "assistance": ["id", "session_id", "elderly_id", "care_domain", "risk_level", "user_description", "summary", "status", "created_at"],
        }[kind]
        raw = self._raw_row(row, raw_fields)
        time_fields = {
            "care": ["started_at", "ended_at"],
            "chat": ["started_at", "ended_at"],
            "call": ["created_at"],
            "activity": ["created_at", "updated_at"],
            "notification": ["created_at"],
            "assistance": ["created_at"],
        }[kind]
        times, time_basis = self._base_time(row, time_fields)
        started_at = times.get("started_at", times.get("created_at"))
        ended_at = times.get("ended_at")
        if started_at is not None and "started_at" not in time_basis and "created_at" in time_basis:
            time_basis["started_at"] = time_basis["created_at"]
        if kind == "activity":
            started_basis = ended_basis = None
            activity_date = _bounded_text(row.get("activity_date"), "activity_date", 40)
            start_time = _bounded_text(row.get("start_time"), "start_time", 40)
            end_time = _bounded_text(row.get("end_time"), "end_time", 40)
            if activity_date is not None and start_time is not None:
                started_at = f"{activity_date} {start_time}"
                _, started_basis = _time(started_at, "activity.started_at")
            if activity_date is not None and end_time is not None:
                ended_at = f"{activity_date} {end_time}"
                _, ended_basis = _time(ended_at, "activity.ended_at")
            if started_basis:
                time_basis["started_at"] = started_basis
            if ended_basis:
                time_basis["ended_at"] = ended_basis

        summary = ""
        if kind in {"care", "chat"}:
            summary = self._message_summary(db, kind, row["id"], states)
        elif kind == "call":
            summary = row.get("recognized_text") or row.get("requested_relation") or ""
        elif kind == "activity":
            summary = row.get("activity_name") or row.get("status") or ""
        elif kind == "notification":
            summary = row.get("message") or ""
        elif kind == "assistance":
            summary = row.get("summary") or row.get("user_description") or ""
        summary = _bounded_text(summary, f"{kind}.summary") or ""
        title_sources = {
            "care": (row.get("care_domain"), "护理咨询"),
            # A chat's first message can be a long, valid utterance.  Keep the
            # list title stable and leave the complete text in summary/messages.
            "chat": ("短聊会话", "短聊会话"),
            "call": (row.get("contact_name") or row.get("requested_relation"), "家人联系"),
            "activity": (row.get("activity_name"), "活动意愿"),
            "notification": (row.get("notification_type"), "工作人员通知"),
            "assistance": (row.get("care_domain"), "护理协助"),
        }[kind]
        title = _short_excerpt(title_sources[0], f"{kind}.title", MAX_NAME_BYTES) or title_sources[1]
        item = {
            "key": f"{kind}:{record_id}",
            "kind": kind,
            "elder_id": elder["id"],
            "elderly_id": external_id,
            "elder_name": elder["name"],
            "title": title,
            "status": _bounded_text(row.get("status", row.get("call_status")), f"{kind}.status", 256),
            "started_at": started_at,
            "ended_at": ended_at,
            "summary": summary,
            "time_basis": time_basis,
            "source_key": source_key,
        }
        if kind == 'assistance' and states.get('care_consultation_session') == 'available':
            parent = db.execute("""SELECT id FROM care_consultation_session
                WHERE id=? AND elderly_id=? AND COALESCE(session_source,'') NOT IN ('test','demo')""",
                                (row['session_id'], external_id)).fetchone()
            if parent:
                item['parent_key'] = f'care:{parent[0]}'
        elif kind == 'notification' and states.get('social_activity_interest') == 'available':
            parents = db.execute('SELECT interest_id FROM social_activity_interest WHERE session_id=? AND elder_id=? LIMIT 2',
                                 (row.get('session_id'), external_id)).fetchall()
            if len(parents) == 1:
                item['parent_key'] = f'activity:{parents[0][0]}'
        item["_record_id"] = int(record_id)
        item["_raw"] = raw
        item["_row"] = row
        item["_source_table"] = MAIN_TABLES[kind]
        item["_source_key"] = source_key
        return item

    @staticmethod
    def _public_item(item):
        return {key: value for key, value in item.items() if not key.startswith("_")}

    def list(self, elders: list[dict], elder_id=None, kind=None, before=None, limit=30):
        result = self._empty_list()
        try:
            if kind is not None and kind not in KINDS:
                raise ValueError("kind 不受支持")
            if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_LIMIT:
                raise ValueError("limit 超出允许范围")
            cursor = _parse_record_cursor(before)
            if cursor and kind is not None and cursor[0] != kind:
                raise ValueError("before 与 kind 不一致")
            selected = [kind] if kind else list(KIND_ORDER)
            with self.reader.connect() as (db, source_key):
                self.reader.check_bindings(elders, source_key)
                bindings = self._bound_elders(elders, source_key, elder_id)
                states = self._table_states(db)
                result["availability"] = self._availability(states)
                if not bindings:
                    return result
                available = [entry for entry in selected if states.get(MAIN_TABLES[entry]) == "available"]
                result["total"] = sum(self._count(db, entry, bindings, states) for entry in available)
                candidates = []
                cursor_kind, cursor_id = cursor or (None, None)
                for entry in available:
                    entry_rank = KIND_ORDER.index(entry)
                    if cursor_kind is not None and entry_rank < KIND_ORDER.index(cursor_kind):
                        continue
                    entry_before = cursor_id if entry == cursor_kind else None
                    for row in self._list_query(db, entry, bindings, entry_before, states, limit):
                        candidates.append((entry_rank, -int(row["id"] if entry not in {"activity", "notification"} else row["id"]), entry, row))
                candidates.sort(key=lambda value: (value[0], value[1]))
                page = candidates[:limit]
                for _, _, entry, row in page:
                    binding = bindings[int(row["elderly_id"])]
                    result["items"].append(self._public_item(self._item_from_row(db, entry, row, binding, states, source_key)))
                if len(candidates) > limit and page:
                    last = page[-1]
                    last_row = last[3]
                    last_id = _bounded_id(last_row["id"], f"{last[2]}.id")
                    result["next"] = f"{last[2]}:{last_id}"
        except (OSError, ValueError, TypeError, OverflowError, UnicodeError, RecursionError, sqlite3.Error) as exc:
            result.update(status="error", error=f"互动档案读取失败：{exc}", items=[], total=None, next=None)
        return result

    def _detail_item(self, db, item, kind, states, source_key):
        result = self._public_item(item)
        raw = item["_raw"]
        facts = dict(raw)
        if kind in {"care", "chat"}:
            message_table = MESSAGE_TABLES[kind]
            facts["messages_availability"] = states.get(message_table, "unavailable")
        if kind == "care":
            facts["tags_are_message_facts"] = True
        result["source"] = {
            "table": item["_source_table"],
            "source_key": source_key,
            "row": raw,
            "time_basis": item.get("time_basis", {}),
        }
        result["facts"] = facts
        return result

    def _messages(self, db, kind, session_id, states, after, limit):
        table = MESSAGE_TABLES.get(kind)
        if not table or states.get(table) != "available":
            return [], None
        after_cursor = _parse_message_cursor(after)
        clauses = ["session_id=?"]
        params = [session_id]
        if after_cursor:
            round_no, message_id = after_cursor
            if round_no is None:
                clauses.append("id > ?")
                params.append(message_id)
            else:
                clauses.append("(round_no > ? OR (round_no=? AND id>?))")
                params.extend([round_no, round_no, message_id])
        rows = db.execute(
            f"SELECT id,round_no,role,content,created_at{',tags_json' if kind == 'care' else ''} FROM {table} WHERE {' AND '.join(clauses)} ORDER BY round_no ASC,id ASC LIMIT ?",
            [*params, limit + 1],
        ).fetchall()
        messages = []
        for row in rows[:limit]:
            row = _row_dict(row)
            message_id = _bounded_id(row["id"], f"{kind}.message.id")
            round_no = _number(row["round_no"], f"{kind}.message.round_no")
            if isinstance(round_no, float) or round_no < 0 or round_no > 1_000_000_000:
                raise ValueError(f"{kind}.message.round_no 不正确")
            created_at, time_basis = _time(row["created_at"], f"{kind}.message.created_at")
            message = {
                "id": message_id,
                "round_no": round_no,
                "role": _bounded_text(row["role"], f"{kind}.message.role", 128),
                "content": _bounded_text(row["content"], f"{kind}.message.content"),
                "created_at": created_at,
                "time_basis": time_basis,
            }
            if kind == "care":
                tags_json = _bounded_text(row.get("tags_json"), f"{kind}.message.tags_json")
                tags, tags_error = _json_value(tags_json, f"{kind}.message.tags_json")
                message["tags_json"] = tags_json
                message["tags"] = tags
                if tags_error:
                    message["tags_error"] = tags_error
            messages.append(message)
        next_message = None
        if len(rows) > limit and messages:
            last = messages[-1]
            next_message = f"{last['round_no']}:{last['id']}"
        return messages, next_message

    def get(self, elders: list[dict], key: str, after=None, limit=100):
        result = self._empty_get()
        try:
            key = _bounded_text(key, "key", MAX_CURSOR_BYTES)
            parts = key.split(":") if key else []
            if len(parts) != 2 or parts[0] not in KINDS:
                raise ValueError("档案 key 不正确")
            kind = parts[0]
            record_id = _parse_id_cursor(parts[1], "key")
            if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_MESSAGE_LIMIT:
                raise ValueError("limit 超出允许范围")
            if after is not None:
                _parse_message_cursor(after)
            with self.reader.connect() as (db, source_key):
                self.reader.check_bindings(elders, source_key)
                bindings = self._bound_elders(elders, source_key)
                states = self._table_states(db)
                if states.get(MAIN_TABLES[kind]) != "available":
                    result.update(status="error", error=f"{MAIN_TABLES[kind]} 不可用")
                    return result
                if not bindings:
                    return result
                table = MAIN_TABLES[kind]
                elder_column = "elder_id" if kind in {"activity", "notification"} else "elderly_id"
                daily_filter = self._daily_filter(kind, states, table)
                if kind == "activity":
                    detail_query = "SELECT interest_id AS id,interest_id,elder_id AS elderly_id,elder_id,session_id,status,created_at,updated_at FROM social_activity_interest WHERE interest_id=? AND elder_id IN ({})".format(
                        ",".join("?" for _ in bindings)
                    )
                elif kind == "notification":
                    detail_query = "SELECT notification_id AS id,notification_id,elder_id AS elderly_id,elder_id,session_id,notification_type,message,status,created_at FROM staff_notification WHERE notification_id=? AND elder_id IN ({})".format(
                        ",".join("?" for _ in bindings)
                    )
                elif kind == "call":
                    detail_query = "SELECT * FROM contact_call_log WHERE id=? AND elderly_id IN ({})".format(
                        ",".join("?" for _ in bindings)
                    )
                else:
                    detail_query = f"SELECT * FROM {table} WHERE id=? AND {elder_column} IN ({','.join('?' for _ in bindings)})"
                detail_query += f" AND {daily_filter} LIMIT 1"
                row = db.execute(
                    detail_query,
                    [record_id, *self._elder_ids(bindings)],
                ).fetchone()
                if not row:
                    return result
                row_dict = _row_dict(row)
                if kind == "call" and states.get("family_contact") == "available":
                    contact_row = db.execute(
                        "SELECT name AS contact_name,relation AS contact_relation FROM family_contact WHERE id=? AND elderly_id=? LIMIT 1",
                        (row_dict.get("contact_id"), row_dict["elderly_id"]),
                    ).fetchone()
                    if contact_row:
                        row_dict.update(_row_dict(contact_row))
                elif kind == "activity" and states.get("social_activity_session") == "available":
                    if states.get("social_activity") == "available":
                        activity_row = db.execute(
                            """SELECT s.activity_date,s.start_time,s.end_time,s.status AS session_status,
                                      a.name AS activity_name
                               FROM social_activity_session AS s
                               LEFT JOIN social_activity AS a ON a.activity_id=s.activity_id
                               WHERE s.session_id=? LIMIT 1""",
                            (row_dict["session_id"],),
                        ).fetchone()
                    else:
                        activity_row = db.execute(
                            "SELECT activity_date,start_time,end_time,status AS session_status FROM social_activity_session WHERE session_id=? LIMIT 1",
                            (row_dict["session_id"],),
                        ).fetchone()
                    if activity_row:
                        row_dict.update(_row_dict(activity_row))
                elif kind == "notification" and states.get("social_activity_session") == "available":
                    if states.get("social_activity") == "available":
                        activity_row = db.execute(
                            """SELECT s.activity_date,s.start_time,s.end_time,
                                      a.name AS activity_name
                               FROM social_activity_session AS s
                               LEFT JOIN social_activity AS a ON a.activity_id=s.activity_id
                               WHERE s.session_id=? LIMIT 1""",
                            (row_dict["session_id"],),
                        ).fetchone()
                    else:
                        activity_row = db.execute(
                            "SELECT activity_date,start_time,end_time FROM social_activity_session WHERE session_id=? LIMIT 1",
                            (row_dict["session_id"],),
                        ).fetchone()
                    if activity_row:
                        row_dict.update(_row_dict(activity_row))
                bound = bindings[int(row_dict["elderly_id"])]
                item = self._item_from_row(db, kind, row_dict, bound, states, source_key)
                detail = self._detail_item(db, item, kind, states, source_key)
                if kind in {"care", "chat"}:
                    messages, next_message = self._messages(db, kind, int(row_dict["id"]), states, after, limit)
                else:
                    messages, next_message = [], None
                related_business = []
                if kind in {'care', 'activity'}:
                    related_kind = 'assistance' if kind == 'care' else 'notification'
                    related_table = MAIN_TABLES[related_kind]
                    related_elder_column = 'elderly_id' if kind == 'care' else 'elder_id'
                    related_session = row_dict['id'] if kind == 'care' else row_dict['session_id']
                    if states.get(related_table) == 'available':
                        projection = ('*' if related_kind == 'assistance' else
                                      'notification_id AS id,notification_id,elder_id AS elderly_id,elder_id,session_id,notification_type,message,status,created_at')
                        related_rows = db.execute(
                            f'SELECT {projection} FROM {related_table} WHERE {related_elder_column}=? AND session_id=? ORDER BY 1 DESC LIMIT ?',
                            (int(detail['elderly_id']), related_session, MAX_LIMIT + 1)).fetchall()
                        for related_row in related_rows[:MAX_LIMIT]:
                            related_item = self._item_from_row(
                                db, related_kind, related_row, bindings[int(detail['elderly_id'])], states, source_key)
                            related_business.append(self._detail_item(db, related_item, related_kind, states, source_key))
                        result['related_business_more'] = len(related_rows) > MAX_LIMIT
                result.update(status="ready", item=detail, messages=messages, next_message=next_message,
                              related_business=related_business)
        except (OSError, ValueError, TypeError, OverflowError, UnicodeError, RecursionError, sqlite3.Error) as exc:
            result.update(status="error", error=f"互动档案读取失败：{exc}", item=None, messages=[], next_message=None)
        return result

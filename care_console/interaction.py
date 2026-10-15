"""Read the interaction owner's database without importing or starting its runtime."""
import json
import math
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from .ingest import LOCAL_ZONE, number, text

STATUSES = {"detected", "in_progress", "completed", "cancelled", "failed"}
PRIORITIES = {"normal", "high", "urgent"}
TEXT_LIMITS = {"need_category": 80, "need_code": 160, "summary": 2000, "raw_text": 8000,
               "source_scene": 160, "source_session_id": 256, "handled_by": 160,
               "created_at": 30, "updated_at": 30, "completed_at": 30,
               "status": 40, "priority": 40, "details_json": 65536}


class InteractionReader:
    def __init__(self, path):
        self.path = Path(path)

    def source_key(self):
        path = self.path.resolve(strict=True)
        stat = path.stat()
        # shortcut: path/inode detects replacement, not in-place whole-database rewrites; restore only through the owner.
        return f"{path}:{stat.st_dev}:{stat.st_ino}"

    @contextmanager
    def connect(self):
        if not self.path.is_file():
            raise ValueError("交互数据库不存在，请检查模块数据文件")
        source_key = self.source_key()
        db = sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True, timeout=1)
        try:
            if self.source_key() != source_key:
                raise ValueError("交互数据库在读取期间被替换，请核对数据来源")
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA query_only=ON")
            deadline = time.monotonic() + 2
            db.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
            yield db, source_key
            if self.source_key() != source_key:
                raise ValueError("交互数据库在读取期间被替换，请核对数据来源")
        finally:
            db.close()

    def people(self):
        with self.connect() as (db, source_key):
            columns = {row[1] for row in db.execute('PRAGMA table_info(elderly_person)')}
            gender = 'substr(gender,1,33)' if 'gender' in columns else 'NULL'
            rows = db.execute(f"SELECT id,substr(name,1,81) AS name,{gender} AS gender,age,substr(room,1,81) AS room,enabled FROM elderly_person ORDER BY id LIMIT 501").fetchall()
            if len(rows) > 500:
                raise ValueError("交互档案超过本机工作台的 500 人上限")
            people = [dict(row) for row in rows]
            for person in people:
                if person['enabled'] not in (0, 1):
                    raise ValueError('交互老人启用状态不符合共享合同')
                text(person["name"], 80)
                if person['gender'] is not None:
                    text(person['gender'], 32)
                if person["room"] is not None:
                    text(person["room"], 80)
                if person["age"] is not None:
                    number(person["age"], maximum=120)
            return people, source_key

    def check_bindings(self, elders, key):
        if any(elder.get("interaction_source_key") != key for elder in elders if elder.get("interaction_elderly_id")):
            raise ValueError("交互数据库来源已变化，已暂停读取；请核对老人身份及原数据库")

    def profiles(self, elders):
        """Project current owner fields while keeping local identity and care notes."""
        bound = [elder for elder in elders if elder.get('interaction_elderly_id') and elder['data_mode'] == 'real']
        for elder in elders:
            elder.update(profile_source='local', profile_status='ready', profile_error='', gender=None)
        if not bound:
            return elders
        try:
            people, source_key = self.people()
            people = {person['id']: person for person in people}
            error = ''
        except (OSError, ValueError, sqlite3.Error) as exc:
            people, source_key, error = {}, None, f'交互基础资料读取失败：{exc}'
        for elder in bound:
            elder['profile_source'] = 'interaction'
            try:
                if error:
                    raise ValueError(error)
                self.check_bindings([elder], source_key)
                person = people.get(elder['interaction_elderly_id'])
                if not person or not person['enabled']:
                    raise ValueError('交互老人档案不存在或已停用')
                elder.update(name=person['name'], gender=person['gender'], age=person['age'], room=person['room'] or '')
            except ValueError as exc:
                elder.update(name='资料暂不可用', age=None, room='', profile_status='error', profile_error=str(exc))
        return elders

    def summary(self, elders):
        try:
            people, people_key = self.people()
            bindings = {elder["interaction_elderly_id"]: elder for elder in elders if elder.get("interaction_elderly_id")}
            with self.connect() as (db, source_key):
                if source_key != people_key:
                    raise ValueError("交互数据库在读取期间被替换，请刷新后核对")
                self.check_bindings(elders, source_key)
                counts = db.execute("SELECT elderly_id,COUNT(*) FROM elder_need WHERE status IN ('detected','in_progress') GROUP BY elderly_id").fetchall()
            return {"status": "ready", "error": "", "people": [{**person, "id": str(person["id"])} for person in people], "bound_elders": len(bindings),
                    "open_needs": sum(row[1] for row in counts if row[0] in bindings), "source_key": source_key}
        except (OSError, ValueError, sqlite3.Error) as exc:
            return {"status": "error", "error": f"交互数据读取失败：{exc}", "people": [],
                    "bound_elders": 0, "open_needs": None}

    @staticmethod
    def decode(row, elder):
        result = dict(row)
        if result["status"] not in STATUSES or result["priority"] not in PRIORITIES:
            raise ValueError("需求状态或优先级不符合共享合同")
        for field in ("created_at", "updated_at", "completed_at"):
            if result[field]:
                result[field] = datetime.strptime(text(result[field], 30), "%Y-%m-%d %H:%M:%S").replace(tzinfo=LOCAL_ZONE).isoformat()
        for field, cap in TEXT_LIMITS.items():
            if field == "details_json":
                continue
            if result[field] is not None:
                text(result[field], cap)
        raw_details = result.pop("details_json")
        result.update(elder_id=elder["id"], elder_name=elder["name"], details=None, details_error="")
        result.update(id=str(result["id"]), elderly_id=str(result["elderly_id"]))
        if raw_details:
            try:
                if len(text(raw_details, 65536).encode("utf-8")) > 65536:
                    raise ValueError("详情超过 64 KiB")
                result["details"] = json.loads(raw_details, parse_float=lambda value: number(float(value), -math.inf, math.inf), parse_constant=lambda _: (_ for _ in ()).throw(ValueError("非有限数值")))
                if not isinstance(result["details"], dict):
                    raise ValueError("详情须为 JSON 对象")
                pending = [(result["details"], 0)]
                while pending:
                    value, depth = pending.pop()
                    if depth > 64:
                        raise ValueError("详情嵌套超过 64 层")
                    if isinstance(value, (dict, list)):
                        pending.extend((item, depth + 1) for item in (value.values() if isinstance(value, dict) else value))
                json.dumps(result["details"], ensure_ascii=False, allow_nan=False).encode("utf-8")
            except (ValueError, TypeError, RecursionError) as exc:
                result.update(details=None, details_error=f"扩展详情不可用：{exc}")
        return result

    def needs(self, elders, elder_id=None, category=None, status=None, before=None, limit=50, need_id=None,
              source_scene=None, source_session_id=None):
        bindings = {elder["interaction_elderly_id"]: elder for elder in elders
                    if elder.get("interaction_elderly_id") and (elder_id is None or elder["id"] == elder_id)}
        result = {"status": "ready", "error": "", "items": [], "total": 0, "next": None}
        try:
            with self.connect() as (db, source_key):
                self.check_bindings(elders, source_key)
                # Check the contract even when no local profile is bound.
                db.execute("SELECT id,elderly_id,status FROM elder_need LIMIT 0")
                if not bindings:
                    return result
                clauses, args = [f"elderly_id IN ({','.join('?' for _ in bindings)})"], list(bindings)
                for field, value in [("need_category", category), ("id", need_id),
                                     ("source_scene", source_scene), ("source_session_id", source_session_id)]:
                    if value is not None:
                        clauses.append(f"{field}{' COLLATE NOCASE' if field == 'source_scene' else ''}=?")
                        args.append(value)
                if status == "open":
                    clauses.append("status IN ('detected','in_progress')")
                elif status:
                    clauses.append("status=?")
                    args.append(status)
                where = " AND ".join(clauses)
                result["total"] = db.execute(f"SELECT COUNT(*) FROM elder_need WHERE {where}", args).fetchone()[0]
                rank = "CASE priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 ELSE 2 END" if status == "open" else "0"
                if before:
                    cursor_rank, cursor_id = map(int, before.split(":"))
                    if not 1 <= cursor_id <= 2**63 - 1:
                        raise ValueError("需求分页编号超出允许范围")
                    where += f" AND (({rank}) > ? OR (({rank}) = ? AND id < ?))"
                    args.extend([cursor_rank, cursor_rank, cursor_id])
                # Read one character beyond each bound so oversized data is rejected, not silently truncated.
                projection = ",".join(f"substr({field},1,{cap+1}) AS {field}" for field, cap in TEXT_LIMITS.items())
                rows = db.execute(f"""SELECT id,elderly_id,{projection},
                    ({rank}) AS sort_rank FROM elder_need WHERE {where} ORDER BY sort_rank,id DESC LIMIT ?""", [*args, limit + 1]).fetchall()
                for row in rows[:limit]:
                    result["items"].append(self.decode(row, bindings[row["elderly_id"]]))
                if len(rows) > limit:
                    result["next"] = f"{rows[limit-1]['sort_rank']}:{rows[limit-1]['id']}"
        except (OSError, ValueError, TypeError, OverflowError, sqlite3.Error) as exc:
            result.update(status="error", error=f"交互数据读取失败：{exc}", items=[], total=None, next=None)
        return result

import hashlib
import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .ingest import now, read_batch
from .interaction import InteractionReader
from . import records

TRANSITIONS = {"new": {"acknowledged", "false_alarm"}, "acknowledged": {"handling", "false_alarm"},
               "handling": {"closed", "false_alarm"}, "closed": set(), "false_alarm": set()}


class ConflictError(ValueError):
    pass


class Store:
    def __init__(self, path, roots, interaction_db):
        self.path, self.roots = Path(path), roots
        self.interaction = InteractionReader(interaction_db)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.sync_lock = threading.Lock()
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS elders (
                    id INTEGER PRIMARY KEY, name TEXT NOT NULL, age INTEGER, room TEXT NOT NULL DEFAULT '',
                    notes TEXT NOT NULL DEFAULT '', data_mode TEXT NOT NULL DEFAULT 'real', created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS sources (
                    id INTEGER PRIMARY KEY, elder_id INTEGER NOT NULL REFERENCES elders(id), module TEXT NOT NULL,
                    path TEXT NOT NULL, mode TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
                    offset INTEGER NOT NULL DEFAULT 0, generation INTEGER NOT NULL DEFAULT 0,
                    fingerprint TEXT NOT NULL DEFAULT '', rejected INTEGER NOT NULL DEFAULT 0,
                    error TEXT NOT NULL DEFAULT '', synced_at TEXT, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY, source_id INTEGER NOT NULL REFERENCES sources(id),
                    source_session TEXT NOT NULL, external_id TEXT NOT NULL, elder_id INTEGER NOT NULL REFERENCES elders(id),
                    module TEXT NOT NULL, mode TEXT NOT NULL, title TEXT NOT NULL, detail TEXT NOT NULL,
                    emotion TEXT, level TEXT, observed_at TEXT, source_seconds REAL, received_at TEXT NOT NULL,
                    score REAL, inference TEXT NOT NULL, notification TEXT NOT NULL, raw_json TEXT NOT NULL,
                    status TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(source_id, source_session, external_id));
                CREATE INDEX IF NOT EXISTS events_elder_time ON events(elder_id, observed_at DESC);
                CREATE TABLE IF NOT EXISTS snapshots (
                    source_id INTEGER PRIMARY KEY REFERENCES sources(id), elder_id INTEGER NOT NULL REFERENCES elders(id),
                    mode TEXT NOT NULL, emotion TEXT NOT NULL, input_state TEXT NOT NULL,
                    inference TEXT NOT NULL, observed_at TEXT NOT NULL, received_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS actions (
                    id INTEGER PRIMARY KEY, event_id INTEGER NOT NULL REFERENCES events(id), status TEXT NOT NULL,
                    operator TEXT NOT NULL, note TEXT NOT NULL, created_at TEXT NOT NULL);
            """)
            if "boundary" not in {r[1] for r in db.execute("PRAGMA table_info(sources)")}:
                db.execute("ALTER TABLE sources ADD COLUMN boundary TEXT NOT NULL DEFAULT ''")
            if "interaction_elderly_id" not in {r[1] for r in db.execute("PRAGMA table_info(elders)")}:
                db.execute("ALTER TABLE elders ADD COLUMN interaction_elderly_id INTEGER")
            if "interaction_source_key" not in {r[1] for r in db.execute("PRAGMA table_info(elders)")}:
                db.execute("ALTER TABLE elders ADD COLUMN interaction_source_key TEXT")
            db.execute("CREATE UNIQUE INDEX IF NOT EXISTS elders_interaction_identity ON elders(interaction_elderly_id) WHERE interaction_elderly_id IS NOT NULL")
            records.initialize(db)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA busy_timeout=5000")
        try:
            with db:
                yield db
        finally:
            db.close()

    def save_elder(self, body, elder_id=None):
        with self.connect() as db:
            if elder_id is None:
                cursor = db.execute("INSERT INTO elders(name,age,room,notes,created_at) VALUES(?,?,?,?,?)",
                                    (body.name, body.age, body.room, body.notes, now()))
                elder_id = cursor.lastrowid
            else:
                elder = db.execute("SELECT * FROM elders WHERE id=? AND data_mode='real'", (elder_id,)).fetchone()
                if elder and elder['interaction_elderly_id'] is not None:
                    raise ConflictError('基础资料由交互模块维护，工作台只能修改照护备注')
                result = db.execute("UPDATE elders SET name=?,age=?,room=?,notes=? WHERE id=? AND data_mode='real'",
                                    (body.name, body.age, body.room, body.notes, elder_id))
                if not result.rowcount:
                    raise ValueError("老人档案不存在或为演示档案")
            return dict(db.execute("SELECT * FROM elders WHERE id=?", (elder_id,)).fetchone())

    def save_notes(self, elder_id, notes):
        with self.connect() as db:
            result = db.execute("UPDATE elders SET notes=? WHERE id=? AND data_mode='real'", (notes, elder_id))
            if not result.rowcount:
                raise ValueError('老人档案不存在或为演示档案')
            elder = dict(db.execute('SELECT * FROM elders WHERE id=?', (elder_id,)).fetchone())
        return self.interaction.profiles([elder])[0]

    def elders(self, data_mode=None):
        with self.connect() as db:
            rows = db.execute('SELECT * FROM elders ORDER BY id' if data_mode is None else
                              'SELECT * FROM elders WHERE data_mode=? ORDER BY id', () if data_mode is None else (data_mode,))
            elders = [dict(row) for row in rows]
        return self.interaction.profiles(elders)

    def with_profiles(self, items):
        if not items:
            return items
        elders = {str(elder['id']): elder for elder in self.elders()}
        for item in items:
            elder = elders[str(item['elder_id'])]
            item.update(elder_name=elder['name'], **{key: elder[key] for key in ('profile_source', 'profile_status', 'profile_error')})
            if 'room' in item:
                item['room'] = elder['room']
        return items

    def add_source(self, body, path):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            elder = db.execute("SELECT * FROM elders WHERE id=?", (body.elder_id,)).fetchone()
            if not elder or elder["data_mode"] != "real":
                raise ValueError("请先选择真实老人档案")
            if body.module == 'interaction':
                self._check_journal_identity(elder)
            if db.execute("SELECT 1 FROM sources WHERE path=? AND enabled=1", (str(path),)).fetchone():
                raise ValueError("该文件已经绑定，请使用新的采集文件")
            if db.execute("SELECT 1 FROM sources WHERE path=? AND elder_id<>?", (str(path), body.elder_id)).fetchone():
                raise ValueError("该文件的历史已归属其他老人；更换老人必须使用新的采集文件")
            previous = db.execute("SELECT * FROM sources WHERE path=? ORDER BY id DESC LIMIT 1", (str(path),)).fetchone()
            if previous:
                if previous["module"] != body.module or previous["mode"] != body.mode:
                    raise ValueError("重新接入同一文件须保留原模块与采集类型")
                db.execute("UPDATE sources SET enabled=1 WHERE id=?", (previous["id"],))
                return dict(db.execute("SELECT * FROM sources WHERE id=?", (previous["id"],)).fetchone())
            cursor = db.execute("INSERT INTO sources(elder_id,module,path,mode,created_at) VALUES(?,?,?,?,?)",
                                (body.elder_id, body.module, str(path), body.mode, now()))
            return dict(db.execute("SELECT * FROM sources WHERE id=?", (cursor.lastrowid,)).fetchone())

    def _check_journal_identity(self, elder):
        if not elder or elder['interaction_elderly_id'] is None:
            raise ValueError('请先关联交互模块老人身份，再绑定会话日志')
        try:
            self.interaction.check_bindings([dict(elder)], self.interaction.source_key())
        except OSError as exc:
            raise ValueError('交互数据库不可读取，已暂停会话导入') from exc

    def bind_interaction(self, elder_id, elderly_id, expected_source_key, initial_notes=""):
        people, source_key = self.interaction.people()
        if source_key != expected_source_key:
            raise ConflictError("交互数据库已变化，请刷新后重新核对要关联的老人")
        person = next((person for person in people if person['id'] == elderly_id and person['enabled']), None)
        if person is None:
            raise ValueError("交互老人不存在或已停用")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if elder_id is None:
                existing = db.execute("SELECT * FROM elders WHERE interaction_elderly_id=?", (elderly_id,)).fetchone()
                elder_id = existing['id'] if existing else db.execute(
                    "INSERT INTO elders(name,age,room,notes,created_at) VALUES(?,?,?,?,?)",
                    (person['name'], person['age'], person['room'] or '', initial_notes, now())).lastrowid
            elder = db.execute("SELECT * FROM elders WHERE id=? AND data_mode='real'", (elder_id,)).fetchone()
            if not elder:
                raise ValueError("请先选择真实老人档案")
            if elder["interaction_elderly_id"] not in (None, elderly_id):
                raise ConflictError("已绑定的交互身份不能改派给其他老人")
            if elder["interaction_elderly_id"] and elder["interaction_source_key"] != source_key:
                raise ConflictError("原交互数据库已被替换，请先核对原数据库和老人身份")
            if db.execute("SELECT 1 FROM elders WHERE interaction_elderly_id=? AND id<>?", (elderly_id, elder_id)).fetchone():
                raise ConflictError("该交互身份已绑定其他老人档案")
            db.execute("UPDATE elders SET interaction_elderly_id=?,interaction_source_key=? WHERE id=?", (elderly_id, source_key, elder_id))
            result = dict(db.execute("SELECT * FROM elders WHERE id=?", (elder_id,)).fetchone())
            if self.interaction.source_key() != source_key:
                raise ConflictError("交互数据库已变化，请刷新后重新核对要关联的老人")
        return self.interaction.profiles([result])[0]

    def interaction_needs(self, data_mode="real", **filters):
        if data_mode == "demo":
            return {"status": "demo", "error": "", "items": [], "total": 0, "next": None}
        return self.interaction.needs(self.elders('real'), **filters)

    def sources(self, data_mode="real"):
        with self.connect() as db:
            items = [dict(row) for row in db.execute("""SELECT s.*, e.name AS elder_name FROM sources s
                JOIN elders e ON e.id=s.elder_id WHERE e.data_mode=? ORDER BY s.id DESC""", (data_mode,))]
        return self.with_profiles(items)

    def disable_source(self, source_id):
        with self.connect() as db:
            if not db.execute("UPDATE sources SET enabled=0 WHERE id=?", (source_id,)).rowcount:
                raise ValueError("数据源不存在")

    def _insert(self, db, source, row):
        received_at = now()
        if row['kind'] == 'session_record':
            records.insert(db,source,row)
            return
        if row["kind"] == "snapshot":
            if row.get('external_id'):
                db.execute('''INSERT INTO emotion_observations(source_id,generation,elder_id,external_id,mode,emotion,inference,observed_at,source_seconds,received_at,raw_json)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(source_id,generation,external_id) DO NOTHING''',
                    (source['id'],source['generation'],source['elder_id'],row['external_id'],row['mode'],row['emotion'],
                     row['inference'],row['observed_at'],row.get('source_seconds'),received_at,row['raw_json']))
            if row["mode"] == "replay":
                return
            db.execute("""INSERT INTO snapshots VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(source_id) DO UPDATE SET
                mode=excluded.mode,emotion=excluded.emotion,input_state=excluded.input_state,
                inference=excluded.inference,observed_at=excluded.observed_at,received_at=excluded.received_at
                WHERE excluded.observed_at >= snapshots.observed_at""",
                       (source["id"], source["elder_id"], row["mode"], row["emotion"], row["input_state"],
                        row["inference"], row["observed_at"], received_at))
            return
        # Audio owner resets its event sequence on restart while appending to the same file.
        digest = hashlib.sha256(row["raw_json"].encode()).hexdigest() if row["module"] == "anomaly" else ""
        session = f"{source['id']}:{source['generation']}:{digest}"
        if db.execute("SELECT 1 FROM events WHERE source_id=? AND source_session=? AND external_id=?",
                      (source["id"], session, row["external_id"])).fetchone():
            return
        data = {**row, "source_id": source["id"], "elder_id": source["elder_id"],
                "source_session": session, "received_at": received_at,
                "status": "new" if row["module"] == "anomaly" and row["level"] in {"L2", "L3"} else "recorded"}
        data = {key: value for key, value in data.items() if key not in {"kind", "input_state"}}
        columns = ",".join(data)
        db.execute(f"INSERT INTO events({columns}) VALUES({','.join('?' for _ in data)}) ON CONFLICT(source_id,source_session,external_id) DO NOTHING",
                   tuple(data.values()))

    def sync(self):
        with self.sync_lock:
            for source in self.sources():
                if not source["enabled"]:
                    continue
                try:
                    rows, changes = read_batch(source, self.roots)
                    with self.connect() as db:
                        db.execute("BEGIN IMMEDIATE")
                        if not db.execute("SELECT 1 FROM sources WHERE id=? AND enabled=1", (source["id"],)).fetchone():
                            continue
                        if source['module']=='interaction':
                            elder=db.execute('SELECT * FROM elders WHERE id=?',(source['elder_id'],)).fetchone()
                            self._check_journal_identity(elder)
                        # Offset and event writes commit together, so retry cannot lose records.
                        for row in rows:
                            db.execute('SAVEPOINT source_row')
                            try:
                                self._insert(db, {**source, "generation": changes["generation"]}, row)
                            except ValueError as exc:
                                db.execute('ROLLBACK TO source_row')
                                changes['rejected'] += 1
                                changes['error'] = f'记录被拒绝：{exc}'
                                if row['kind']=='session_record':
                                    db.execute("UPDATE companion_sessions SET gaps=gaps+1,status='incomplete' WHERE source_id=? AND generation=? AND session_key=? AND elderly_id=?",
                                               (source['id'],changes['generation'],row['session_key'],row['elderly_id']))
                            finally:
                                db.execute('RELEASE source_row')
                        if source['module']=='interaction':
                            self._check_journal_identity(elder)
                            if changes['rejected'] > source['rejected']:
                                db.execute("UPDATE companion_sessions SET status='incomplete',gaps=MAX(gaps,1) WHERE source_id=? AND generation=?",
                                           (source['id'],changes['generation']))
                        db.execute("""UPDATE sources SET offset=?,fingerprint=?,generation=?,rejected=?,error=?,boundary=?,synced_at=?
                            WHERE id=?""", (*changes.values(), now(), source["id"]))
                except (OSError, ValueError, sqlite3.Error) as exc:
                    with self.connect() as db:
                        db.execute("UPDATE sources SET error=?,synced_at=? WHERE id=?", (str(exc)[:500], now(), source["id"]))

    def events(self, data_mode="real", module=None, elder_id=None, status=None, before=None, limit=50):
        clauses, args = ["p.data_mode=?"], [data_mode]
        for column, value in [("module", module), ("elder_id", elder_id), ("status", status)]:
            if value:
                if column == "status" and value == "open":
                    clauses.append("e.status IN ('new','acknowledged','handling')")
                    continue
                clauses.append(f"e.{column}=?")
                args.append(value)
        where = " AND ".join(clauses)
        with self.connect() as db:
            total = db.execute(f"SELECT COUNT(*) FROM events e JOIN elders p ON p.id=e.elder_id WHERE {where}", args).fetchone()[0]
            if before:
                where += " AND e.id < ?"
                args = [*args, before]
            rows = db.execute(f"""SELECT e.id,e.elder_id,p.name AS elder_name,p.room,e.module,e.mode,e.title,e.detail,e.emotion,
                e.level,e.observed_at,e.source_seconds,e.received_at,e.score,e.inference,e.status,e.version,e.notification
                FROM events e JOIN elders p ON p.id=e.elder_id WHERE {where} ORDER BY e.id DESC LIMIT ?""", [*args, limit]).fetchall()
            return {"items": self.with_profiles([dict(r) for r in rows]), "total": total,
                    "next": rows[-1]["id"] if len(rows) == limit else None}

    def sessions(self, data_mode='real', elder_id=None, before=None, limit=30):
        with self.connect() as db:
            result = records.list_sessions(db,data_mode,elder_id,before,limit)
        self.with_profiles(result['items'])
        return result

    def session(self, session_id, after=None, limit=100):
        with self.connect() as db:
            result = records.detail(db,session_id,after,limit)
            item = result['item']
            event_id = item['initial'].get('event_id')
            source_run_id = item['initial'].get('source_run_id')
            matches = db.execute("""SELECT id FROM events WHERE elder_id=? AND module='emotion'
                AND mode=? AND external_id=? AND json_extract(raw_json,'$.source_run_id')=? LIMIT 2""",
                                 (item['elder_id'], item['mode'], event_id, source_run_id)).fetchall() if isinstance(event_id, str) and source_run_id else []
            result['related_event_id'] = matches[0]['id'] if len(matches) == 1 else None
        self.with_profiles([result['item']])
        return result

    def observations(self, data_mode='real', elder_id=None, before=None, limit=50):
        clauses,args=['e.data_mode=?'],[data_mode]
        if elder_id is not None:clauses.append('o.elder_id=?');args.append(elder_id)
        where=' AND '.join(clauses)
        with self.connect() as db:
            total=db.execute(f'SELECT COUNT(*) FROM emotion_observations o JOIN elders e ON e.id=o.elder_id WHERE {where}',args).fetchone()[0]
            if before is not None:where+=' AND o.id<?';args.append(before)
            rows=db.execute(f'SELECT o.*,e.name AS elder_name FROM emotion_observations o JOIN elders e ON e.id=o.elder_id WHERE {where} ORDER BY o.id DESC LIMIT ?',[*args,limit+1]).fetchall()
            items=[]
            for row in rows[:limit]:
                item=dict(row);item['raw']=json.loads(item.pop('raw_json'));items.append(item)
            return dict(items=self.with_profiles(items),total=total,next=rows[limit-1]['id'] if len(rows)>limit else None)

    def event(self, event_id):
        with self.connect() as db:
            row = db.execute("SELECT e.*,p.name AS elder_name,p.room FROM events e JOIN elders p ON p.id=e.elder_id WHERE e.id=?", (event_id,)).fetchone()
            if not row:
                raise ValueError("事件不存在")
            result = dict(row)
            result["raw"] = json.loads(result.pop("raw_json"))
            result["actions"] = [dict(r) for r in db.execute("SELECT * FROM actions WHERE event_id=? ORDER BY id", (event_id,))]
            if row['module'] == 'emotion':
                source_run_id = result['raw'].get('source_run_id')
                event_matches = db.execute("""SELECT id FROM events WHERE elder_id=? AND module='emotion'
                    AND mode=? AND external_id=? AND json_extract(raw_json,'$.source_run_id')=? LIMIT 2""",
                                           (row['elder_id'], row['mode'], row['external_id'], source_run_id)).fetchall() if source_run_id else []
                sessions = db.execute("""SELECT id,status FROM companion_sessions WHERE elder_id=? AND mode=?
                    AND json_extract(initial_json,'$.event_id')=? AND json_extract(initial_json,'$.source_run_id')=?
                    ORDER BY id DESC LIMIT 101""", (row['elder_id'], row['mode'], row['external_id'], source_run_id)).fetchall() if len(event_matches) == 1 else []
                result['related_sessions'] = [dict(session) for session in sessions[:100]]
                result['related_sessions_more'] = len(sessions) > 100
            return self.with_profiles([result])[0]

    def act(self, event_id, body):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
            if not row:
                raise ValueError("事件不存在")
            if row["version"] != body.version:
                raise ConflictError("其他操作已更新这条记录，请刷新后重试")
            if body.status not in TRANSITIONS.get(row["status"], set()):
                raise ValueError("该记录不支持此处理状态")
            db.execute("UPDATE events SET status=?,version=version+1 WHERE id=?", (body.status, event_id))
            db.execute("INSERT INTO actions(event_id,status,operator,note,created_at) VALUES(?,?,?,?,?)",
                       (event_id, body.status, body.operator, body.note, now()))
        return self.event(event_id)

    def overview(self, data_mode="real"):
        elders = self.elders(data_mode)
        with self.connect() as db:
            for elder in elders:
                emotion = db.execute("SELECT * FROM emotion_observations WHERE elder_id=? AND emotion<>'unknown' ORDER BY id DESC LIMIT 1", (elder['id'],)).fetchone()
                if emotion is None:
                    emotion = db.execute("SELECT * FROM events WHERE elder_id=? AND module='emotion' ORDER BY id DESC LIMIT 1", (elder["id"],)).fetchone()
                snapshot = db.execute("""SELECT n.* FROM snapshots n JOIN sources s ON s.id=n.source_id
                    WHERE n.elder_id=? AND n.mode IN ('live','demo') AND s.enabled=1
                    AND n.observed_at<=? ORDER BY n.observed_at DESC LIMIT 1""", (elder["id"], now())).fetchone()
                snapshot = dict(snapshot) if snapshot else None
                fresh = snapshot and (snapshot["mode"] == "demo" or 0 <= (datetime.now(timezone.utc) - datetime.fromisoformat(snapshot["observed_at"])).total_seconds() <= 15)
                elder.update(current_emotion=snapshot["emotion"] if fresh else "unknown", snapshot=snapshot,
                             last_emotion={k: emotion[k] for k in ["emotion", "observed_at", "source_seconds", "mode", "inference"]} if emotion else None,
                             open_alerts=db.execute("SELECT COUNT(*) FROM events WHERE elder_id=? AND status IN ('new','acknowledged','handling')", (elder["id"],)).fetchone()[0])
            counts = db.execute("""SELECT COUNT(*) AS events, SUM(e.module='emotion') AS emotions,
                SUM(e.status IN ('new','acknowledged','handling')) AS open_alerts FROM events e
                JOIN elders p ON p.id=e.elder_id WHERE p.data_mode=?""", (data_mode,)).fetchone()
            interaction = self.interaction.summary(elders) if data_mode == "real" else {
                "status": "demo", "error": "", "people": [], "bound_elders": 0, "open_needs": 0}
            for elder in elders:
                if elder["interaction_elderly_id"] is not None:
                    elder["interaction_elderly_id"] = str(elder["interaction_elderly_id"])
            return {"elders": elders, "stats": {k: counts[k] or 0 for k in counts.keys()}, "updated_at": now(),
                    "sources": self.sources(data_mode), "interaction": interaction}

    def seed_demo(self):
        with self.connect() as db:
            if db.execute("SELECT 1 FROM elders WHERE data_mode='demo'").fetchone():
                return
            for name, age, room in [("陈阿姨", 76, "示例 201"), ("李伯伯", 81, "示例 203")]:
                elder_id = db.execute("INSERT INTO elders(name,age,room,notes,data_mode,created_at) VALUES(?,?,?,?,'demo',?)",
                                      (name, age, room, "虚构演示档案", now())).lastrowid
                for module in ["emotion", "anomaly"]:
                    source_id = db.execute("INSERT INTO sources(elder_id,module,path,mode,created_at) VALUES(?,?,?,'demo',?)",
                                           (elder_id, module, "演示数据", now())).lastrowid
                    source = {"id": source_id, "elder_id": elder_id, "generation": 0}
                    for i in range(3):
                        emotion = ["sad", "calm", "happy"][i] if module == "emotion" else None
                        row = {"external_id": f"demo-{module}-{i}", "module": module, "kind": "event", "mode": "demo",
                               "title": {"sad": "悲伤", "calm": "平静", "happy": "开心"}.get(emotion, ["夜间起身", "疑似跌倒", "长时间静卧"][i]),
                               "detail": "虚构记录，仅用于体验工作台流程", "emotion": emotion,
                               "level": ["L2", "L3", "L1"][i] if module == "anomaly" else None,
                               "observed_at": (datetime.now(timezone.utc) - timedelta(minutes=45-i*12)).isoformat(),
                               "source_seconds": None, "score": 0.86, "inference": "stable_face" if emotion else "",
                               "notification": "unknown", "raw_json": '{"demo":true}'}
                        self._insert(db, source, row)
                    if module == "emotion":
                        self._insert(db, source, {"kind": "snapshot", "mode": "demo", "emotion": "happy",
                                                 "input_state": "demo", "inference": "stable_face", "observed_at": now()})

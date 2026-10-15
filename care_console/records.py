"""Persist the companion's factual journal; summaries are traceable quotations."""
import json
from datetime import datetime, timezone

from .ingest import EMOTIONS, now, text, timestamp

KINDS = {'session_start', 'console', 'receipt', 'session_end', 'recording_gap'}
END_STATUSES = {'completed', 'no_event', 'failed', 'interrupted', 'incomplete'}


def normalize(raw, mode):
    if raw.get('schema_version') != 'care_session_record_v1':
        raise ValueError('不是详细会话记录')
    for key in ('record_id', 'session_id', 'elderly_id'):
        if not text(raw.get(key, ''), 160):
            raise ValueError('会话记录缺少关联标识')
    if not raw['elderly_id'].isascii() or not raw['elderly_id'].isdigit() or not 1 <= int(raw['elderly_id']) <= 2**63-1:
        raise ValueError('会话老人编号不正确')
    seq = raw.get('seq')
    if type(seq) is not int or not 1 <= seq <= 100000:
        raise ValueError('会话记录序号不正确')
    if raw.get('kind') not in KINDS or raw.get('mode') not in {'live', 'replay'}:
        raise ValueError('会话记录类别不正确')
    value = text(raw.get('recorded_at'), 80)
    if datetime.fromisoformat(value.replace('Z', '+00:00')).tzinfo is None:
        raise ValueError('新会话记录时间必须标注时区')
    recorded_at = timestamp(value)
    effective_mode = 'replay' if mode == 'replay' or raw['mode'] == 'replay' else 'live'
    if effective_mode == 'live' and (datetime.fromisoformat(recorded_at)-datetime.now(timezone.utc)).total_seconds() > 5:
        raise ValueError('会话记录时间超前')
    payload = raw.get('payload')
    if not isinstance(payload, dict):
        raise ValueError('会话内容必须是对象')
    pending = [(payload, 0)]
    while pending:
        item, depth = pending.pop()
        if depth > 64:
            raise ValueError('会话内容嵌套过深')
        if isinstance(item, (dict, list)):
            pending.extend((child, depth+1) for child in (item.values() if isinstance(item,dict) else item))
    payload_json = json.dumps(payload, ensure_ascii=False, allow_nan=False, sort_keys=True)
    if len(payload_json.encode('utf-8')) > 65536:
        raise ValueError('会话内容超过 64 KiB')
    if 'text' in payload:
        text(payload['text'], 65536)
    for field in ('stage','status','event_id'):
        if field in payload:text(payload[field],160)
    if payload.get('source_run_id') is not None:
        text(payload['source_run_id'],160)
    if 'error' in payload:text(payload['error'],2000)
    if payload.get('stage')=='检测到情绪策略' and payload.get('emotion') not in EMOTIONS:
        raise ValueError('会话初始情绪类别不正确')
    if raw['kind'] == 'session_end' and payload.get('status') not in END_STATUSES:
        raise ValueError('会话结束状态不正确')
    return {'kind':'session_record', 'external_id':raw['record_id'], 'session_key':raw['session_id'],
            'elderly_id':str(int(raw['elderly_id'])), 'seq':seq, 'record_kind':raw['kind'],
            'recorded_at':recorded_at, 'mode':effective_mode, 'payload_json':payload_json}


def initialize(db):
    db.executescript('''
        CREATE TABLE IF NOT EXISTS companion_sessions(
            id INTEGER PRIMARY KEY,source_id INTEGER NOT NULL REFERENCES sources(id),generation INTEGER NOT NULL,
            session_key TEXT NOT NULL,elder_id INTEGER NOT NULL REFERENCES elders(id),elderly_id TEXT NOT NULL,
            mode TEXT NOT NULL,started_at TEXT NOT NULL,ended_at TEXT,status TEXT NOT NULL DEFAULT 'active',
            initial_emotion TEXT NOT NULL DEFAULT 'unknown',initial_json TEXT NOT NULL DEFAULT '{}',
            end_emotion TEXT NOT NULL DEFAULT 'unknown',end_reason TEXT NOT NULL DEFAULT '',
            last_seq INTEGER NOT NULL DEFAULT 0,gaps INTEGER NOT NULL DEFAULT 0,
            summary TEXT NOT NULL DEFAULT '',summary_refs TEXT NOT NULL DEFAULT '[]',last_user_text TEXT NOT NULL DEFAULT '',
            UNIQUE(source_id,generation,session_key));
        CREATE INDEX IF NOT EXISTS companion_sessions_elder ON companion_sessions(elder_id,id DESC);
        CREATE TABLE IF NOT EXISTS companion_records(
            id INTEGER PRIMARY KEY,session_id INTEGER NOT NULL REFERENCES companion_sessions(id),
            seq INTEGER NOT NULL,record_id TEXT NOT NULL,kind TEXT NOT NULL,recorded_at TEXT NOT NULL,
            payload_json TEXT NOT NULL,UNIQUE(session_id,seq),UNIQUE(session_id,record_id));
        CREATE TABLE IF NOT EXISTS emotion_observations(
            id INTEGER PRIMARY KEY,source_id INTEGER NOT NULL REFERENCES sources(id),generation INTEGER NOT NULL,
            elder_id INTEGER NOT NULL REFERENCES elders(id),external_id TEXT NOT NULL,mode TEXT NOT NULL,
            emotion TEXT NOT NULL,inference TEXT NOT NULL,observed_at TEXT,source_seconds REAL,received_at TEXT NOT NULL,
            raw_json TEXT NOT NULL,UNIQUE(source_id,generation,external_id));
    ''')


def insert(db, source, row):
    elder = db.execute('SELECT interaction_elderly_id FROM elders WHERE id=?',(source['elder_id'],)).fetchone()
    if not elder or str(elder[0]) != row['elderly_id']:
        raise ValueError('记录的老人身份与数据源绑定不一致')
    session = db.execute('SELECT * FROM companion_sessions WHERE source_id=? AND generation=? AND session_key=?',
                         (source['id'],source['generation'],row['session_key'])).fetchone()
    if not session:
        if row['seq'] != 1 or row['record_kind'] != 'session_start':
            raise ValueError('缺少本次会话的开始记录')
        db.execute('INSERT INTO companion_sessions(source_id,generation,session_key,elder_id,elderly_id,mode,started_at) VALUES(?,?,?,?,?,?,?)',
                   (source['id'],source['generation'],row['session_key'],source['elder_id'],row['elderly_id'],row['mode'],row['recorded_at']))
        session = db.execute('SELECT * FROM companion_sessions WHERE source_id=? AND generation=? AND session_key=?',
                             (source['id'],source['generation'],row['session_key'])).fetchone()
    previous = db.execute('SELECT * FROM companion_records WHERE session_id=? AND (seq=? OR record_id=?)',
                          (session['id'],row['seq'],row['external_id'])).fetchone()
    if previous:
        if previous['seq'] != row['seq'] or previous['record_id'] != row['external_id'] or previous['payload_json'] != row['payload_json'] or previous['kind'] != row['record_kind'] or previous['recorded_at'] != row['recorded_at'] or session['mode'] != row['mode']:
            db.execute('UPDATE companion_sessions SET gaps=gaps+1,status=\'incomplete\' WHERE id=?',(session['id'],))
            raise ValueError('相同会话序号内容发生冲突')
        return
    if row['mode'] != session['mode'] or row['seq'] <= session['last_seq'] or session['ended_at']:
        raise ValueError('会话记录采集类型变化、乱序或发生在结束之后')
    last=db.execute('SELECT recorded_at FROM companion_records WHERE session_id=? ORDER BY seq DESC LIMIT 1',(session['id'],)).fetchone()
    if last and row['recorded_at'] < last['recorded_at']:
        raise ValueError('会话记录时间倒退')
    gaps = session['gaps'] + int(row['seq'] != session['last_seq'] + 1)
    cursor = db.execute('INSERT INTO companion_records(session_id,seq,record_id,kind,recorded_at,payload_json) VALUES(?,?,?,?,?,?)',
                        (session['id'],row['seq'],row['external_id'],row['record_kind'],row['recorded_at'],row['payload_json']))
    db.execute('UPDATE companion_sessions SET last_seq=?,gaps=? WHERE id=?',(row['seq'],gaps,session['id']))
    data = json.loads(row['payload_json'])
    if row['record_kind'] == 'recording_gap':
        db.execute('UPDATE companion_sessions SET gaps=gaps+1,status=\'incomplete\' WHERE id=?',(session['id'],))
    if data.get('stage') == '检测到情绪策略' and session['initial_json'] == '{}':
        if data.get('emotion') not in EMOTIONS:
            raise ValueError('会话初始情绪类别不正确')
        db.execute('UPDATE companion_sessions SET initial_emotion=?,initial_json=? WHERE id=?',
                   (data['emotion'],row['payload_json'],session['id']))
    if (data.get('stage') == '检测到老人说的内容' or data.get('kind') in {'companion_interaction_asr','emotion_dialogue_interrupt_command'}) and data.get('text') and data.get('input_source') != 'derived_interrupt_instruction':
        refs = json.loads(session['summary_refs'])
        if len(refs) < 3:
            excerpt = data['text'][:240] + ('…' if len(data['text'])>240 else '')
            summary = session['summary'] + ('\n' if refs else '') + '语音转写：' + excerpt
            refs.append(str(cursor.lastrowid))
            db.execute('UPDATE companion_sessions SET summary=?,summary_refs=? WHERE id=?',
                       (summary,json.dumps(refs),session['id']))
        db.execute('UPDATE companion_sessions SET last_user_text=? WHERE id=?',(data['text'],session['id']))
    if data.get('status') in {'quiet_requested','session_ended'}:
        db.execute('UPDATE companion_sessions SET end_reason=? WHERE id=?',(data['status'],session['id']))
    if row['record_kind'] == 'session_end':
        status = 'incomplete' if gaps else data['status']
        db.execute('UPDATE companion_sessions SET status=?,ended_at=?,end_reason=CASE WHEN end_reason=\'\' THEN ? ELSE end_reason END WHERE id=?',
                   (status,row['recorded_at'],data.get('error') or data['status'],session['id']))


def list_sessions(db, mode, elder_id=None, before=None, limit=30):
    where, args = ['e.data_mode=?'],[mode]
    if elder_id is not None:
        where.append('s.elder_id=?');args.append(elder_id)
    clause = ' AND '.join(where)
    total = db.execute(f'SELECT COUNT(*) FROM companion_sessions s JOIN elders e ON e.id=s.elder_id WHERE {clause}',args).fetchone()[0]
    if before is not None:
        clause+=' AND s.id<?';args.append(before)
    rows = db.execute(f'SELECT s.*,e.name AS elder_name FROM companion_sessions s JOIN elders e ON e.id=s.elder_id WHERE {clause} ORDER BY s.id DESC LIMIT ?',[*args,limit+1]).fetchall()
    items = []
    for row in rows[:limit]:
        item = dict(row);item['id']=str(item['id']);item['summary_method']='extractive'
        item['summary_refs']=json.loads(item['summary_refs']);item['initial']=json.loads(item.pop('initial_json'))
        items.append(item)
    return dict(items=items,total=total,next=str(rows[limit-1]['id']) if len(rows)>limit else None)


def detail(db, session_id, after=None, limit=100):
    row=db.execute('SELECT s.*,e.name AS elder_name FROM companion_sessions s JOIN elders e ON e.id=s.elder_id WHERE s.id=?',(session_id,)).fetchone()
    if not row:
        raise ValueError('会话不存在')
    item=dict(row);item['id']=str(item['id']);item['initial']=json.loads(item.pop('initial_json'))
    item['summary_method']='extractive';item['summary_refs']=json.loads(item['summary_refs'])
    rows=db.execute('SELECT * FROM companion_records WHERE session_id=? AND seq>? ORDER BY seq LIMIT ?',
                    (session_id,after or 0,limit+1)).fetchall()
    records=[{**dict(row),'id':str(row['id']),'payload':json.loads(row['payload_json'])} for row in rows[:limit]]
    for record in records:record.pop('payload_json')
    return dict(item=item,records=records,next_record=rows[limit-1]['seq'] if len(rows)>limit else None)

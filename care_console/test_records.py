import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from care_console.server import create_app

HEADERS = {"X-Care-Console": "1"}


@pytest.fixture
def records(tmp_path):
    external = tmp_path / "interaction.db"
    with sqlite3.connect(external) as db:
        db.executescript("CREATE TABLE elderly_person(id INTEGER PRIMARY KEY,name TEXT,age INTEGER,room TEXT,enabled INTEGER); INSERT INTO elderly_person VALUES(7,'测试老人',76,'201',1);")
    app = create_app(tmp_path / "console.db", roots=[tmp_path], background=False, interaction_db=external)
    with TestClient(app) as client:
        elder_id = client.post('/api/elders', headers=HEADERS, json={'name': '工作台老人'}).json()['id']
        response = client.post(f'/api/elders/{elder_id}/interaction-binding', headers=HEADERS,
                              json={'elderly_id': '7', 'source_key': app.state.store.interaction.source_key()})
        assert response.status_code == 200
        yield client, tmp_path, elder_id


def row(seq, kind, payload, session='session-a', elderly_id='7'):
    return dict(schema_version='care_session_record_v1', record_id=f'{session}-{seq}', session_id=session,
                elderly_id=elderly_id, seq=seq, recorded_at=f'2026-10-13T01:00:{seq:02d}+00:00',
                mode='replay', kind=kind, payload=payload)


def attach(client, path, elder_id, module='interaction', mode='replay'):
    result = client.post('/api/sources', headers=HEADERS, json=dict(elder_id=elder_id,module=module,path=str(path),mode=mode))
    assert result.status_code == 200, result.text
    client.post('/api/sync', headers=HEADERS)
    return result.json()['id']


def test_emotion_session_links_require_unambiguous_detector_source(records):
    client, root, elder = records
    event = dict(schema_version='emotion_strategy_v1', event_id='local-event-1', source_run_id='detector-a',
                 observed_at='2026-10-13T01:00:00+00:00', emotion='sad', inference_level='possible')
    event_path = root / 'emotion-a.jsonl'
    event_path.write_text(json.dumps(event)+'\n')
    attach(client, event_path, elder, module='emotion')
    journal = root / 'session-source.jsonl'
    journal.write_text('\n'.join(json.dumps(entry) for entry in [
        row(1, 'session_start', {}),
        row(2, 'console', {'stage':'检测到情绪策略','emotion':'sad',
                           'event_id':'local-event-1','source_run_id':'detector-a'}),
    ])+'\n')
    attach(client, journal, elder)
    assert client.get('/api/events/1').json()['related_sessions'][0]['id'] == 1
    assert client.get('/api/sessions/1').json()['related_event_id'] == 1

    other = root / 'emotion-b.jsonl'
    other.write_text(json.dumps({**event, 'source_run_id':'detector-b'})+'\n')
    attach(client, other, elder, module='emotion')
    assert client.get('/api/events/2').json()['related_sessions'] == []
    assert client.get('/api/sessions/1').json()['related_event_id'] == 1

    duplicate = root / 'emotion-duplicate.jsonl'
    duplicate.write_text(json.dumps(event)+'\n')
    attach(client, duplicate, elder, module='emotion')
    assert client.get('/api/events/1').json()['related_sessions'] == []
    assert client.get('/api/sessions/1').json()['related_event_id'] is None


def test_full_session_keeps_transcripts_generation_receipts_and_unknown_end(records):
    client, root, elder = records
    path = root / 'session.jsonl'
    long_reply='可回查的完整模型内容：'+'x'*21000
    entries = [row(1,'session_start',{'scene':'dialogue'}),
               row(2,'console',{'stage':'检测到情绪策略','emotion':'sad','inference_level':'possible','event_id':'emotion-a','observed_at':'2026-10-13T00:59:59+00:00'}),
               row(3,'console',{'stage':'检测到老人说的内容','round_no':1,'text':'我今天有点想家'}),
               row(4,'console',{'stage':'模型输出','round_no':1,'text':long_reply}),
               row(5,'receipt',{'kind':'emotion_dialogue_turn','round_no':1,'status':'interrupted','g1_played':True}),
               row(6,'console',{'stage':'检测到老人说的内容','round_no':2,'text':'先不聊了'}),
               row(7,'receipt',{'kind':'emotion_dialogue_turn','round_no':2,'status':'quiet_requested'}),
               row(8,'session_end',{'status':'completed'})]
    path.write_text(''.join(json.dumps(item,ensure_ascii=False)+'\n' for item in entries))
    original = path.read_bytes()
    source = attach(client,path,elder)
    result = client.get('/api/sessions').json()
    assert result['total'] == 1
    session = result['items'][0]
    assert session['initial_emotion'] == 'sad' and session['end_emotion'] == 'unknown'
    assert session['end_reason'] == 'quiet_requested' and session['status'] == 'completed'
    detail = client.get(f"/api/sessions/{session['id']}?limit=3").json()
    assert len(detail['records']) == 3 and detail['next_record'] is not None
    more = client.get(f"/api/sessions/{session['id']}?after={detail['next_record']}&limit=100").json()
    assert any(item['payload'].get('text') == '我今天有点想家' for item in detail['records']+more['records'])
    assert any(item['payload'].get('text') == long_reply for item in more['records'])
    assert any(item['payload'].get('status') == 'interrupted' for item in more['records'])
    assert '我今天有点想家' in session['summary'] and session['summary_method'] == 'extractive'
    client.post('/api/sync',headers=HEADERS)
    assert client.get('/api/sessions').json()['total'] == 1 and path.read_bytes() == original
    client.post('/api/demo',headers=HEADERS)
    assert client.get('/api/sessions?data_mode=demo').json()['total'] == 0


def test_missing_sequence_and_identity_mismatch_cannot_claim_complete(records):
    client, root, elder = records
    path=root/'gaps.jsonl'
    entries=[row(1,'session_start',{}),row(3,'console',{'stage':'检测到老人说的内容','text':'先休息'}),
             row(4,'session_end',{'status':'completed'}),row(1,'session_start',{},session='other',elderly_id='8')]
    path.write_text(''.join(json.dumps(item)+'\n' for item in entries))
    attach(client,path,elder)
    items=client.get('/api/sessions').json()['items']
    assert len(items)==1 and items[0]['status']=='incomplete'
    assert client.get('/api/sources').json()[0]['rejected'] >= 1


def test_snapshot_history_preserves_replay_axis_without_current_state(records):
    client,root,elder=records
    path=root/'snapshots.jsonl'
    path.write_text(''.join(json.dumps({'schema_version':'emotion_snapshot_v1','event_id':f'state-{i}','emotion':emotion,
        'observed_at':'2026-10-13T01:00:00+00:00','source_kind':'video','source_seconds':i})+'\n'
        for i,emotion in enumerate(['sad','unknown','happy'])))
    attach(client,path,elder,'emotion')
    history=client.get(f'/api/emotion-observations?elder_id={elder}').json()
    assert history['total']==3 and all(item['observed_at'] is None for item in history['items'])
    assert client.get('/api/overview').json()['elders'][0]['current_emotion']=='unknown'


def test_anomaly_attachments_are_bounded_and_cannot_escape_roots(records):
    client,root,elder=records
    audio=root/'audio.wav';audio.write_bytes(b'RIFF'+b'0'*100)
    path=root/'events.jsonl'
    path.write_text(json.dumps({'event_id':'anomaly-a','type':'audio_distress','level':'L3','time':1,
         'evidence':{'audio_clip':str(audio),'transcript':'帮帮我'},'actions_taken':['notify_l3']})+'\n')
    attach(client,path,elder,'anomaly')
    event=client.get('/api/events').json()['items'][0]
    url=f"/api/events/{event['id']}/attachments/audio"
    assert client.get(url).status_code==200
    assert client.get(url,headers={'Range':'bytes=0-3'}).content==b'RIFF'
    audio.unlink();audio.symlink_to('/etc/passwd')
    assert client.get(url).status_code in {400,404}


def test_bad_record_never_partially_commits_and_duplicate_time_is_immutable(records):
    client,root,elder=records
    path=root/'invalid.jsonl'
    entries=[row(1,'session_start',{}),row(2,'console',{'stage':'检测到情绪策略','emotion':'invalid'}),
             row(3,'session_end',{'status':'completed'})]
    path.write_text(''.join(json.dumps(item)+'\n' for item in entries))
    attach(client,path,elder)
    session=client.get('/api/sessions').json()['items'][0]
    detail=client.get(f"/api/sessions/{session['id']}").json()
    assert session['status']=='incomplete' and [r['seq'] for r in detail['records']]==[1,3]
    altered={**entries[0],'recorded_at':'2026-10-13T01:00:02+00:00'}
    with path.open('a') as stream:stream.write(json.dumps(altered)+'\n')
    client.post('/api/sync',headers=HEADERS)
    assert client.get('/api/sources').json()[0]['rejected']==2
    assert client.get(f"/api/sessions/{session['id']}").json()['records'][0]['recorded_at']=='2026-10-13T01:00:01.000+00:00'


def test_owner_database_replacement_pauses_journal_import_and_binding(records):
    client,root,elder=records
    path=root/'bound.jsonl';path.write_text(json.dumps(row(1,'session_start',{}))+'\n')
    attach(client,path,elder)
    external=root/'interaction.db';external.rename(root/'original.db')
    with sqlite3.connect(external) as db:
        db.executescript("CREATE TABLE elderly_person(id INTEGER PRIMARY KEY,name TEXT,age INTEGER,room TEXT,enabled INTEGER); INSERT INTO elderly_person VALUES(7,'另一位老人',76,'202',1);")
    with path.open('a') as stream:stream.write(json.dumps(row(2,'console',{'stage':'检测到老人说的内容','text':'另一人'}))+'\n')
    client.post('/api/sync',headers=HEADERS)
    source=client.get('/api/sources').json()[0]
    assert '来源已变化' in source['error']
    session=client.get('/api/sessions').json()['items'][0]
    assert len(client.get(f"/api/sessions/{session['id']}").json()['records'])==1
    newpath=root/'new.jsonl';newpath.write_text(json.dumps(row(1,'session_start',{},session='new'))+'\n')
    response=client.post('/api/sources',headers=HEADERS,json=dict(elder_id=elder,module='interaction',path=str(newpath),mode='replay'))
    assert response.status_code==400


def test_business_route_accepts_compound_message_cursor(records):
    from care_console.test_business_records import SCHEMA
    client,root,elder=records
    with sqlite3.connect(root/'interaction.db') as db:
        db.executescript(SCHEMA)
        db.execute("INSERT INTO short_chat_session VALUES(1,7,'chatting','2026-10-13 03:00:00',NULL,NULL)")
        db.executemany("INSERT INTO short_chat_message VALUES(?,1,?, 'user',?, '2026-10-13 03:00:01')",[(1,1,'想聊天'),(2,1,'聊聊以前'),(3,2,'先休息')])
    first=client.get('/api/business-records/chat:1?limit=1').json()
    assert first['status']=='ready' and first['next_message']=='1:1'
    second=client.get('/api/business-records/chat:1',params={'after':first['next_message'],'limit':1})
    assert second.status_code==200 and second.json()['messages'][0]['id']=='2'


def test_synthetic_task_instruction_is_not_summarized_as_elder_speech(records):
    client,root,elder=records
    path=root/'replacement.jsonl'
    entries=[row(1,'session_start',{}),row(2,'console',{'kind':'emotion_dialogue_interrupt_command','text':'这一个不好听，换另外一个吧'}),
             row(3,'console',{'stage':'检测到老人说的内容','text':'换一个故事','input_source':'derived_interrupt_instruction'}),
             row(4,'session_end',{'status':'completed'})]
    path.write_text(''.join(json.dumps(item,ensure_ascii=False)+'\n' for item in entries))
    attach(client,path,elder)
    session=client.get('/api/sessions').json()['items'][0]
    assert session['last_user_text']=='这一个不好听，换另外一个吧'
    assert '换一个故事' not in session['summary'] and '这一个不好听' in session['summary']

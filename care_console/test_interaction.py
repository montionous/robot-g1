import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from care_console.server import create_app

HEADERS = {"X-Care-Console": "1"}


@pytest.fixture
def interaction(tmp_path):
    path = tmp_path / "interaction.db"
    with sqlite3.connect(path) as db:
        db.executescript("""
            CREATE TABLE elderly_person(id INTEGER PRIMARY KEY, name TEXT, age INTEGER, room TEXT, enabled INTEGER);
            INSERT INTO elderly_person VALUES(7, '交互老人甲', 76, '201', 1), (8, '交互老人乙', 80, '202', 1);
            CREATE TABLE elder_need(id INTEGER PRIMARY KEY, elderly_id INTEGER, need_category TEXT, need_code TEXT,
                summary TEXT, raw_text TEXT, priority TEXT, status TEXT, source_scene TEXT, source_session_id TEXT,
                details_json TEXT, handled_by TEXT, created_at TEXT, updated_at TEXT, completed_at TEXT);
        """)
        for need_id, elderly_id, priority, status in [(1, 7, "urgent", "in_progress"), (2, 7, "normal", "completed"), (3, 8, "high", "detected")]:
            db.execute("INSERT INTO elder_need VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                need_id, elderly_id, "care", "care_consultation", "行动咨询", "我想咨询走路问题", priority,
                status, "care_consultation_support", "ended-session", json.dumps({"staff_follow_up": True}),
                "care_staff_follow_up", "2026-10-12 10:17:09", "2026-10-12 10:18:09", None))
    with TestClient(create_app(tmp_path / "console.db", roots=[tmp_path], background=False, interaction_db=path)) as client:
        elder = client.post("/api/elders", headers=HEADERS, json={"name": "本地老人"}).json()
        yield client, path, elder["id"]


def bind(client, elder_id, elderly_id=7):
    key = client.app.state.store.interaction.source_key()
    return client.post(f"/api/elders/{elder_id}/interaction-binding", headers=HEADERS, json={"elderly_id": elderly_id, "source_key": key})


def test_related_needs_require_both_scene_and_session(interaction):
    client, _, elder_id = interaction
    assert bind(client, elder_id).status_code == 200
    matching = client.get('/api/interaction', params={
        'elder_id': elder_id, 'source_scene': 'care_consultation_support',
        'source_session_id': 'ended-session',
    }).json()
    assert matching['total'] == 2
    assert client.get('/api/interaction', params={
        'source_scene': 'other-source', 'source_session_id': 'ended-session',
    }).json()['total'] == 0


def test_bound_profiles_read_owner_updates_and_keep_local_notes(interaction):
    client, path, elder_id = interaction
    original = path.read_bytes()
    assert bind(client, elder_id).status_code == 200
    elder = client.get('/api/overview').json()['elders'][0]
    assert (elder['name'], elder['age'], elder['room']) == ('交互老人甲', 76, '201')
    assert elder['profile_source'] == 'interaction' and elder['profile_status'] == 'ready'
    assert path.read_bytes() == original
    assert client.put(f'/api/elders/{elder_id}', headers=HEADERS, json={'name': '本地覆盖'}).status_code == 409
    result = client.put(f'/api/elders/{elder_id}/notes', headers=HEADERS, json={'notes': '喜欢安静'})
    assert result.status_code == 200
    with sqlite3.connect(path) as db:
        db.execute("UPDATE elderly_person SET name='更新后的姓名',age=77,room='301' WHERE id=7")
    elder = client.get('/api/overview').json()['elders'][0]
    assert (elder['name'], elder['age'], elder['room'], elder['notes']) == ('更新后的姓名', 77, '301', '喜欢安静')
    with TestClient(create_app(client.app.state.store.path, roots=[path.parent], background=False, interaction_db=path)) as reopened:
        assert reopened.get('/api/overview').json()['elders'][0]['name'] == '更新后的姓名'


def test_profile_gender_comes_from_owner_and_missing_legacy_column_is_optional(interaction):
    client, path, elder_id = interaction
    assert bind(client, elder_id).status_code == 200
    assert client.get('/api/overview').json()['elders'][0].get('gender') is None
    with sqlite3.connect(path) as db:
        db.execute('ALTER TABLE elderly_person ADD COLUMN gender TEXT')
        db.execute("UPDATE elderly_person SET gender='男' WHERE id=7")
    original = path.read_bytes()
    assert client.get('/api/overview').json()['elders'][0]['gender'] == '男'
    assert path.read_bytes() == original


@pytest.mark.parametrize('failure', ['missing', 'replaced', 'disabled', 'deleted'])
def test_unavailable_profile_is_explicit_and_preserves_local_records(interaction, failure):
    client, path, elder_id = interaction
    assert bind(client, elder_id).status_code == 200
    if failure == 'missing':
        path.unlink()
    elif failure == 'replaced':
        replacement = path.with_name('replacement-profile.db')
        with sqlite3.connect(path) as original, sqlite3.connect(replacement) as changed:
            original.backup(changed)
            changed.execute("UPDATE elderly_person SET name='另一位老人' WHERE id=7")
        replacement.replace(path)
    else:
        with sqlite3.connect(path) as db:
            db.execute('UPDATE elderly_person SET enabled=0 WHERE id=7' if failure == 'disabled' else 'DELETE FROM elderly_person WHERE id=7')
    elder = client.get('/api/overview').json()['elders'][0]
    assert elder['profile_status'] == 'error' and elder['profile_error']
    assert elder['name'] == '资料暂不可用' and elder['age'] is None and not elder['room']
    assert elder['id'] == elder_id and elder['interaction_elderly_id'] == '7'
    assert client.put(f'/api/elders/{elder_id}/notes', headers=HEADERS, json={'notes': '保留跟进'}).status_code == 200


def test_import_owner_profile_is_idempotent_and_checks_source(interaction):
    client, path, elder_id = interaction
    original = path.read_bytes()
    body = {'elderly_id': '8', 'source_key': client.app.state.store.interaction.source_key(), 'notes': '保留初始照护备注'}
    first = client.post('/api/elders/from-interaction', headers=HEADERS, json=body)
    assert first.status_code == 200 and first.json()['name'] == '交互老人乙'
    assert first.json()['notes'] == body['notes']
    second = client.post('/api/elders/from-interaction', headers=HEADERS, json={**body, 'notes': '重复请求不能覆盖'})
    assert second.json()['id'] == first.json()['id']
    assert second.json()['notes'] == body['notes']
    assert len(client.get('/api/overview').json()['elders']) == 2
    assert bind(client, elder_id, 8).status_code == 409
    assert client.post('/api/elders/from-interaction', headers=HEADERS, json={**body, 'source_key': 'stale'}).status_code == 409
    assert client.post('/api/elders/from-interaction', headers=HEADERS, json={**body, 'elderly_id': '999'}).status_code == 400
    assert path.read_bytes() == original


def test_import_existing_binding_keeps_notes_and_rejects_oversized_notes(interaction):
    client, path, elder_id = interaction
    assert bind(client, elder_id).status_code == 200
    assert client.put(f'/api/elders/{elder_id}/notes', headers=HEADERS, json={'notes': '原照护备注'}).status_code == 200
    body = {'elderly_id': '7', 'source_key': client.app.state.store.interaction.source_key(), 'notes': '新表单备注'}
    result = client.post('/api/elders/from-interaction', headers=HEADERS, json=body)
    assert result.status_code == 200 and result.json()['id'] == elder_id
    assert result.json()['notes'] == '原照护备注'
    assert client.post('/api/elders/from-interaction', headers=HEADERS, json={**body, 'notes': 'x' * 2001}).status_code == 422


def test_source_replaced_after_people_read_rolls_back_binding(interaction, monkeypatch):
    client, path, elder_id = interaction
    reader = client.app.state.store.interaction
    key = reader.source_key()
    replacement = path.with_name('replace-before-binding.db')
    with sqlite3.connect(path) as original, sqlite3.connect(replacement) as changed:
        original.backup(changed)
    people = reader.people

    def replace_after_people():
        result = people()
        replacement.replace(path)
        return result

    monkeypatch.setattr(reader, 'people', replace_after_people)
    result = client.post(f'/api/elders/{elder_id}/interaction-binding', headers=HEADERS,
                         json={'elderly_id': '7', 'source_key': key})
    assert result.status_code == 409
    with client.app.state.store.connect() as db:
        assert db.execute('SELECT interaction_elderly_id FROM elders WHERE id=?', (elder_id,)).fetchone()[0] is None


@pytest.mark.parametrize('enabled', [2, -1, None, 'invalid'])
def test_invalid_owner_enabled_state_is_rejected(interaction, enabled):
    client, path, elder_id = interaction
    with sqlite3.connect(path) as db:
        db.execute('UPDATE elderly_person SET enabled=? WHERE id=7', (enabled,))
    assert bind(client, elder_id).status_code == 400


def test_profile_names_are_consistent_across_records(interaction):
    from care_console.test_console import attach
    from care_console.test_records import row

    client, path, elder_id = interaction
    assert bind(client, elder_id).status_code == 200
    anomaly = path.parent / 'profile-anomaly.jsonl'
    anomaly.write_text(json.dumps({'event_id': 'profile-event', 'type': 'fall', 'level': 'L2', 'time': 1}) + '\n')
    attach(client, anomaly, elder_id)
    emotion = path.parent / 'profile-emotion.jsonl'
    emotion.write_text(json.dumps({'schema_version': 'emotion_snapshot_v1', 'event_id': 'profile-state',
                                  'emotion': 'sad', 'source_kind': 'video', 'source_seconds': 1,
                                  'observed_at': '2026-10-13T01:00:00+00:00'}) + '\n')
    attach(client, emotion, elder_id, 'emotion')
    session = path.parent / 'profile-session.jsonl'
    session.write_text(json.dumps(row(1, 'session_start', {})) + '\n')
    attach(client, session, elder_id, 'interaction')
    with sqlite3.connect(path) as db:
        db.execute("UPDATE elderly_person SET name='实时姓名',room='新房间' WHERE id=7")
    for endpoint in ['/api/events', '/api/emotion-observations', '/api/sessions', '/api/interaction']:
        result = client.get(endpoint).json()
        assert result['items'], (endpoint, result)
        assert all(item['elder_name'] == '实时姓名' for item in result['items'])
    assert all(item['elder_name'] == '实时姓名' for item in client.get('/api/sources').json())
    event = client.get('/api/events').json()['items'][0]
    assert client.get(f"/api/events/{event['id']}").json()['room'] == '新房间'
    session = client.get('/api/sessions').json()['items'][0]
    assert client.get(f"/api/sessions/{session['id']}").json()['item']['elder_name'] == '实时姓名'


def test_identity_is_explicit_read_only_and_survives_restart(interaction):
    client, path, elder_id = interaction
    original = path.read_bytes()
    assert client.get("/api/interaction").json()["total"] == 0
    assert bind(client, elder_id).status_code == 200
    result = client.get("/api/interaction?status=open").json()
    assert result["total"] == 1 and result["items"][0]["status"] == "in_progress"
    assert result["items"][0]["handled_by"] == "care_staff_follow_up"
    assert result["items"][0]["created_at"] == "2026-10-12T10:17:09+08:00"
    assert client.get("/api/interaction?elder_id=999").json()["total"] == 0
    assert client.get("/api/interaction/3").status_code == 404
    assert client.post("/api/interaction/1/actions", headers=HEADERS, json={"status": "completed"}).status_code in {404, 405}
    assert path.read_bytes() == original
    with TestClient(create_app(client.app.state.store.path, background=False, interaction_db=path)) as reopened:
        assert reopened.get("/api/interaction").json()["total"] == 2
    assert path.read_bytes() == original


def test_owner_updates_are_visible_without_duplicates_or_terminal_overrides(interaction):
    client, path, elder_id = interaction
    assert bind(client, elder_id).status_code == 200
    assert client.get("/api/overview").json()["interaction"]["open_needs"] == 1
    with sqlite3.connect(path) as db:
        db.execute("UPDATE elder_need SET status='completed', completed_at='2026-10-12 11:00:00' WHERE id=1")
    for _ in range(2):
        result = client.get("/api/interaction").json()
        assert result["total"] == 2 and result["items"][0]["status"] == "completed"
    assert client.get("/api/overview").json()["interaction"]["open_needs"] == 0
    assert client.get("/api/interaction/1").json()["details"]["staff_follow_up"] is True


def test_bindings_cannot_reassign_or_share_an_external_identity(interaction):
    client, path, elder_id = interaction
    assert bind(client, elder_id, 999).status_code == 400
    assert bind(client, elder_id).status_code == 200
    assert bind(client, elder_id).status_code == 200
    assert bind(client, elder_id, 8).status_code == 409
    second = client.post("/api/elders", headers=HEADERS, json={"name": "另一个老人"}).json()["id"]
    assert bind(client, second).status_code == 409
    client.post("/api/demo", headers=HEADERS)
    demo_id = client.get("/api/overview?data_mode=demo").json()["elders"][0]["id"]
    assert bind(client, demo_id, 8).status_code == 400
    assert client.get("/api/interaction?data_mode=demo").json()["total"] == 0


def test_missing_locked_or_invalid_database_is_visible_and_does_not_create_it(interaction):
    client, path, elder_id = interaction
    assert bind(client, elder_id).status_code == 200
    path.unlink()
    for endpoint in ["/api/overview", "/api/interaction"]:
        result = client.get(endpoint)
        assert result.status_code == 200
        data = result.json().get("interaction", result.json())
        assert data["status"] == "error" and data["error"]
    assert not path.exists()
    path.write_text("not a database")
    assert client.get("/api/interaction").json()["status"] == "error"


def test_need_filters_pagination_and_malformed_details(interaction):
    client, path, elder_id = interaction
    assert bind(client, elder_id).status_code == 200
    first = client.get("/api/interaction?limit=1").json()
    second = client.get(f"/api/interaction?limit=1&before={first['next']}").json()
    assert first["total"] == 2 and len(first["items"]) == 1
    assert second["items"][0]["id"] != first["items"][0]["id"]
    assert client.get("/api/interaction?need_category=entertainment").json()["total"] == 0
    assert client.get("/api/interaction?status=invalid").status_code == 422
    with sqlite3.connect(path) as db:
        db.execute("UPDATE elder_need SET details_json='invalid' WHERE id=1")
    detail = client.get("/api/interaction/1").json()
    assert detail["details"] is None and detail["details_error"]
    assert detail["status"] == "in_progress"


def test_source_database_replacement_cannot_reassign_private_needs(interaction):
    client, path, elder_id = interaction
    assert bind(client, elder_id).status_code == 200
    replacement = path.with_name("replacement.db")
    with sqlite3.connect(path) as original, sqlite3.connect(replacement) as changed:
        original.backup(changed)
        changed.execute("UPDATE elderly_person SET name='另一位老人' WHERE id=7")
    replacement.replace(path)
    result = client.get("/api/interaction").json()
    assert result["status"] == "error" and not result["items"]
    assert client.get("/api/overview").json()["interaction"]["status"] == "error"
    assert bind(client, elder_id).status_code == 409


def test_large_ids_corrupt_time_and_nonfinite_json_are_visible(interaction):
    client, path, elder_id = interaction
    assert bind(client, elder_id).status_code == 200
    assert client.get("/api/interaction?before=0:9223372036854775808").json()["status"] == "error"
    assert client.get("/api/interaction/9223372036854775808").status_code == 422
    assert bind(client, elder_id, 9223372036854775808).status_code == 422
    with sqlite3.connect(path) as db:
        db.execute("UPDATE elder_need SET details_json=? WHERE id=1", ('{"n":1e999}',))
    detail = client.get("/api/interaction/1").json()
    assert detail["details"] is None and detail["details_error"]
    with sqlite3.connect(path) as db:
        db.execute("UPDATE elder_need SET created_at=? WHERE id=1", (b'bad-time',))
    result = client.get("/api/interaction").json()
    assert result["status"] == "error" and result["error"]


def test_bad_or_locked_database_binding_is_a_json_failure(interaction):
    client, path, elder_id = interaction
    with sqlite3.connect(path) as db:
        db.execute("BEGIN EXCLUSIVE")
        assert bind(client, elder_id).status_code == 503
    path.write_bytes(b'bad database')
    result = bind(client, elder_id)
    assert result.status_code == 503 and isinstance(result.json()["detail"], str)


def test_open_priority_pagination_cannot_skip_lower_id_urgent_needs(interaction):
    client, path, elder_id = interaction
    assert bind(client, elder_id).status_code == 200
    with sqlite3.connect(path) as db:
        db.execute("UPDATE elder_need SET status='detected' WHERE id=2")
    first = client.get("/api/interaction?status=open&limit=1").json()
    second = client.get(f"/api/interaction?status=open&limit=1&before={first['next']}").json()
    assert [first["items"][0]["id"], second["items"][0]["id"]] == ['1', '2']


def test_database_replacement_during_identity_read_cannot_capture_new_origin(interaction, monkeypatch):
    client, path, elder_id = interaction
    replacement = path.with_name("replace-during-read.db")
    with sqlite3.connect(path) as original, sqlite3.connect(replacement) as changed:
        original.backup(changed)
        changed.execute("UPDATE elderly_person SET name='另一位老人' WHERE id=7")
    reader = client.app.state.store.interaction
    source_key, calls = reader.source_key, []
    expected_key = source_key()
    def replace_after_open_guard():
        key = source_key()
        calls.append(key)
        if len(calls) == 2:
            replacement.replace(path)
        return key
    monkeypatch.setattr(reader, "source_key", replace_after_open_guard)
    result = client.post(f"/api/elders/{elder_id}/interaction-binding", headers=HEADERS,
                         json={"elderly_id": 7, "source_key": expected_key})
    assert result.status_code == 400
    assert client.get("/api/interaction").json()["total"] == 0


def test_stale_identity_form_cannot_bind_a_replaced_database(interaction):
    client, path, elder_id = interaction
    old_key = client.get("/api/overview").json()["interaction"]["source_key"]
    replacement = path.with_name("stale-form.db")
    with sqlite3.connect(path) as original, sqlite3.connect(replacement) as changed:
        original.backup(changed)
    replacement.replace(path)
    result = client.post(f"/api/elders/{elder_id}/interaction-binding", headers=HEADERS,
                         json={"elderly_id": 7, "source_key": old_key})
    assert result.status_code == 409


def test_int64_ids_reach_the_browser_as_exact_strings(interaction):
    client, path, elder_id = interaction
    large = 9007199254740993
    with sqlite3.connect(path) as db:
        db.execute("UPDATE elderly_person SET id=? WHERE id=7", (large,))
        db.execute("UPDATE elder_need SET elderly_id=?,id=? WHERE id=1", (large, large))
    person = client.get("/api/overview").json()["interaction"]["people"][1]
    assert person["id"] == str(large)
    result = client.post(f"/api/elders/{elder_id}/interaction-binding", headers=HEADERS,
                         json={"elderly_id": person["id"], "source_key": client.app.state.store.interaction.source_key()})
    assert result.status_code == 200
    assert client.get("/api/overview").json()["elders"][0]["interaction_elderly_id"] == str(large)
    assert client.get("/api/interaction").json()["items"][0]["id"] == str(large)


def test_valid_deep_json_cannot_break_api_response_serialization(interaction):
    client, path, elder_id = interaction
    assert bind(client, elder_id).status_code == 200
    with sqlite3.connect(path) as db:
        db.execute("UPDATE elder_need SET details_json=? WHERE id=1", ('{"n":' * 970 + '0' + '}' * 970,))
    detail = client.get("/api/interaction/1").json()
    assert detail["details"] is None and detail["details_error"]
    assert client.get("/api/interaction").status_code == 200


def test_invalid_unicode_and_oversized_details_keep_the_need_visible(interaction):
    client, path, elder_id = interaction
    assert bind(client, elder_id).status_code == 200
    for details in ['{"s":"\\ud800"}', json.dumps({"large": "x" * 1000000}),
                    json.dumps({"large": "中" * 30000}, ensure_ascii=False), b'{}']:
        with sqlite3.connect(path) as db:
            db.execute("UPDATE elder_need SET details_json=? WHERE id=1", (details,))
        detail = client.get("/api/interaction/1").json()
        assert detail["status"] == "in_progress" and detail["details"] is None and detail["details_error"]
        assert client.get("/api/interaction").status_code == 200

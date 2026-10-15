import json
import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from care_console.server import SourceBody, create_app
from care_console.ingest import MAX_LINE


HEADERS = {"X-Care-Console": "1"}


@pytest.fixture
def console(tmp_path):
    app = create_app(tmp_path / "console.db", roots=[tmp_path], background=False)
    with TestClient(app) as client:
        yield client, tmp_path


def test_cloud_host_preserves_origin_and_write_boundary(tmp_path):
    host = "care.82.157.186.52.sslip.io"
    salt = bytes.fromhex('20' * 16)
    auth_file = tmp_path / 'auth.json'
    auth_file.write_text(json.dumps({'username': 'careadmin', 'password_salt': salt.hex(),
                                   'password_hash': hashlib.pbkdf2_hmac('sha256', b'test-password', salt, 600_000).hex()}))
    auth_file.chmod(0o600)
    app = create_app(tmp_path / "cloud.db", roots=[tmp_path], background=False,
                     allowed_hosts=[host], deployment="cloud", auth_file=auth_file)
    with TestClient(app, base_url=f"https://{host}") as client:
        assert client.post('/api/auth/login', headers={**HEADERS, 'Origin': f'https://{host}'},
                           json={'username': 'careadmin', 'password': 'test-password'}).status_code == 200
        assert client.get('/api/health').json()['deployment'] == 'cloud'
        assert client.get('/api/health', headers={'Host': 'untrusted.example'}).status_code == 400
        assert client.post('/api/demo').status_code == 403
        assert client.post('/api/demo', headers={**HEADERS, 'Origin': 'https://untrusted.example'}).status_code == 403
        assert client.post('/api/demo', headers={**HEADERS, 'Origin': f'https://{host}'}).status_code == 200
    with TestClient(create_app(tmp_path / 'local.db', background=False)) as local:
        assert local.get('/api/health').json()['deployment'] == 'local'
        assert local.get('/api/health', headers={'Host': host}).status_code == 400


def profile(client):
    response = client.post("/api/elders", json={"name": "测试老人", "room": "101"}, headers=HEADERS)
    assert response.status_code == 200
    return response.json()["id"]


def test_optional_file_discovery_survives_inaccessible_local_monitor(console, monkeypatch):
    from pathlib import Path
    from care_console import server

    client, _ = console
    original = Path.is_file

    def inaccessible(path):
        if path.parent == server.MONITOR_ROOT:
            raise PermissionError('home directory is hidden by the cloud service')
        return original(path)

    monkeypatch.setattr(Path, 'is_file', inaccessible)
    response = client.get('/api/candidates')
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_optional_run_discovery_survives_inaccessible_directory(console, monkeypatch):
    from pathlib import Path
    from care_console import server

    client, _ = console
    original = Path.is_dir

    def inaccessible(path):
        if path == server.ROOT / 'runs':
            raise PermissionError('run directory is inaccessible')
        return original(path)

    monkeypatch.setattr(Path, 'is_dir', inaccessible)
    assert client.get('/api/candidates').status_code == 200


def attach(client, path, elder_id, module="anomaly", mode="replay"):
    response = client.post("/api/sources", headers=HEADERS, json={
        "elder_id": elder_id, "module": module, "path": str(path), "mode": mode,
    })
    assert response.status_code == 200, response.text
    assert client.post("/api/sync", headers=HEADERS).status_code == 200
    return response.json()["id"]


def test_latest_recognized_emotion_survives_unknown_and_expiry(console):
    client, root = console
    elder_id = profile(client)
    path = root / 'observations.jsonl'
    observed = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()
    def snapshot(event_id, emotion, seconds):
        return {'schema_version': 'emotion_snapshot_v1', 'event_id': event_id, 'emotion': emotion,
                'observed_at': observed, 'input_state': 'available', 'inference_level': 'confirmed',
                'source_seconds': seconds}
    path.write_text('\n'.join(json.dumps(row) for row in [snapshot('known','happy',1), snapshot('missing','unknown',2)])+'\n')
    attach(client, path, elder_id, 'emotion', 'replay')
    assert client.get('/api/emotion-observations').json()['total'] == 2
    elder = client.get('/api/overview').json()['elders'][0]
    assert elder['current_emotion'] == 'unknown'
    assert elder['last_emotion']['emotion'] == 'happy'
    assert elder['last_emotion']['source_seconds'] == 1


def test_detection_to_nurse_resolution_survives_restart(console):
    client, root = console
    elder_id = profile(client)
    path = root / "events.jsonl"
    raw = {"event_id": "fall-1", "type": "fall", "level": "L3", "time": 9.2,
           "confidence": 0.8, "reason": "离线回放", "actions_taken": ["notify_l3"]}
    original = json.dumps(raw).encode() + b"\n"
    path.write_bytes(original)
    attach(client, path, elder_id)
    event = client.get("/api/events").json()["items"][0]
    assert event["mode"] == "replay" and event["observed_at"] is None
    assert event["status"] == "new" and event["notification"] == "requested"
    for status in ["acknowledged", "handling", "closed"]:
        response = client.post(f"/api/events/{event['id']}/actions", headers=HEADERS,
                               json={"status": status, "operator": "测试护士", "note": "已现场核实",
                                     "version": event["version"]})
        assert response.status_code == 200
        event = response.json()
    assert path.read_bytes() == original
    with TestClient(create_app(root / "console.db", roots=[root], background=False)) as reopened:
        detail = reopened.get(f"/api/events/{event['id']}").json()
        assert detail["status"] == "closed" and len(detail["actions"]) == 3


def test_duplicate_partial_line_and_source_restart(console):
    client, root = console
    elder_id = profile(client)
    path = root / "audio.jsonl"
    raw = {"event_id": "aud-thud-0001", "type": "audio_distress", "level": "L1", "time": 3}
    line = json.dumps(raw)
    path.write_text(line + "\n" + line[:12])
    attach(client, path, elder_id)
    assert client.get("/api/events").json()["total"] == 1
    with path.open("a") as stream:
        stream.write(line[12:] + "\n")
    client.post("/api/sync", headers=HEADERS)
    assert client.get("/api/events").json()["total"] == 1
    path.write_text(json.dumps({**raw, "time": 4}) + "\n")
    client.post("/api/sync", headers=HEADERS)
    assert client.get("/api/events").json()["total"] == 2


def test_sparse_emotion_is_not_current_and_replay_never_live(console):
    client, root = console
    elder_id = profile(client)
    path = root / "emotion.jsonl"
    raw = {"schema_version": "emotion_strategy_v1", "event_id": "emotion-1", "emotion": "sad",
           "observed_at": datetime.now(timezone.utc).isoformat(), "inference_level": "possible"}
    path.write_text(json.dumps(raw) + "\n")
    attach(client, path, elder_id, "emotion", "live")
    elder = client.get("/api/overview").json()["elders"][0]
    assert elder["current_emotion"] == "unknown" and elder["last_emotion"]["emotion"] == "sad"
    snapshot = {"schema_version": "emotion_snapshot_v1", "event_id": "state-1", "emotion": "happy",
                "observed_at": raw["observed_at"], "source_kind": "video", "input_state": "face_ok"}
    with path.open("a") as stream:
        stream.write(json.dumps(snapshot) + "\n")
    client.post("/api/sync", headers=HEADERS)
    assert client.get("/api/overview").json()["elders"][0]["current_emotion"] == "unknown"


def test_fresh_snapshot_expires_and_old_snapshot_cannot_replace_new(console):
    client, root = console
    elder_id = profile(client)
    path = root / "state.jsonl"
    raw = {"schema_version": "emotion_snapshot_v1", "event_id": "fresh", "emotion": "calm",
           "observed_at": datetime.now(timezone.utc).isoformat(), "source_kind": "camera"}
    path.write_text(json.dumps(raw) + "\n")
    attach(client, path, elder_id, "emotion", "live")
    assert client.get("/api/overview").json()["elders"][0]["current_emotion"] == "calm"
    with path.open("a") as stream:
        stream.write(json.dumps({**raw, "event_id": "old", "emotion": "angry", "observed_at": "2020-01-01T00:00:00Z"}) + "\n")
    client.post("/api/sync", headers=HEADERS)
    assert client.get("/api/overview").json()["elders"][0]["current_emotion"] == "calm"


def test_input_security_and_visible_parse_failure(console):
    client, root = console
    assert client.post("/api/elders", json={"name": "x"}).status_code == 403
    elder_id = profile(client)
    assert client.post("/api/elders", headers={**HEADERS, "Origin": "https://evil.example"}, json={"name": "x"}).status_code == 403
    assert client.post("/api/sources", headers=HEADERS, json={"elder_id": elder_id, "module": "emotion", "path": "/etc/passwd"}).status_code == 400
    path = root / "bad.jsonl"
    path.write_text('{"event_id": "bad", "type": "fall", "level": "L3", "confidence": NaN}\n')
    attach(client, path, elder_id)
    source = client.get("/api/sources").json()[0]
    assert source["rejected"] == 1 and source["error"]
    assert client.get("/api/events").json()["total"] == 0


def test_action_conflict_and_demo_isolation(console):
    client, root = console
    client.post("/api/demo", headers=HEADERS)
    assert not client.get("/api/overview").json()["elders"]
    events = client.get("/api/events?data_mode=demo").json()["items"]
    event = next(item for item in events if item["module"] == "anomaly" and item["level"] == "L3")
    body = {"status": "acknowledged", "operator": "护士", "note": "核实", "version": event["version"]}
    assert client.post(f"/api/events/{event['id']}/actions", json=body, headers=HEADERS).status_code == 200
    assert client.post(f"/api/events/{event['id']}/actions", json=body, headers=HEADERS).status_code == 409
    client.post("/api/demo", headers=HEADERS)
    assert client.get("/api/events?data_mode=demo").json()["total"] == len(events)


def test_audio_sequence_reset_is_not_a_duplicate(console):
    client, root = console
    path = root / "append-audio.jsonl"
    raw = {"event_id": "aud-thud-0001", "type": "audio_distress", "level": "L3", "time": 3}
    path.write_text(json.dumps(raw) + "\n")
    attach(client, path, profile(client))
    with path.open("a") as stream:
        stream.write(json.dumps({**raw, "time": 7}) + "\n")
        stream.write(json.dumps({**raw, "time": 7}) + "\n")
    client.post("/api/sync", headers=HEADERS)
    assert client.get("/api/events").json()["total"] == 2


def test_video_strategy_preserves_axis_and_never_claims_processing_time(console):
    client, root = console
    path = root / "video.jsonl"
    raw = {"schema_version": "emotion_strategy_v1", "event_id": "video-1", "emotion": "happy",
           "source_kind": "video", "source_seconds": 23.4, "observed_at": datetime.now(timezone.utc).isoformat()}
    path.write_text(json.dumps(raw) + "\n")
    attach(client, path, profile(client), "emotion", "live")
    event = client.get("/api/events").json()["items"][0]
    assert event["mode"] == "replay" and event["source_seconds"] == 23.4 and event["observed_at"] is None
    assert client.get(f"/api/events/{event['id']}").json()["raw"]["observed_at"] == raw["observed_at"]


def test_binding_is_serialized_and_history_cannot_change_elder(console):
    client, root = console
    elder_ids = [profile(client), profile(client)]
    path = root / "ownership.jsonl"
    store = client.app.state.store
    def bind(elder_id):
        try:
            return store.add_source(SourceBody(elder_id=elder_id, module="anomaly", path=str(path)), path)
        except ValueError:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(bind, elder_ids))
    assert sum(result is not None for result in results) == 1
    source = next(result for result in results if result)
    store.disable_source(source["id"])
    other = next(elder_id for elder_id in elder_ids if elder_id != source["elder_id"])
    assert bind(other) is None


def test_future_snapshot_does_not_poison_fresh_state_and_expiry_is_real(console):
    client, root = console
    path = root / "future.jsonl"
    raw = {"schema_version": "emotion_snapshot_v1", "event_id": "future", "emotion": "sad",
           "source_kind": "camera", "observed_at": "2099-01-01T00:00:00Z"}
    path.write_text(json.dumps(raw) + "\n")
    attach(client, path, profile(client), "emotion", "live")
    with path.open("a") as stream:
        stream.write(json.dumps({**raw, "event_id": "normal", "emotion": "happy",
                                "observed_at": datetime.now(timezone.utc).isoformat()}) + "\n")
    client.post("/api/sync", headers=HEADERS)
    assert client.get("/api/overview").json()["elders"][0]["current_emotion"] == "happy"
    with client.app.state.store.connect() as db:
        db.execute("UPDATE snapshots SET observed_at=?", ((datetime.now(timezone.utc) - timedelta(seconds=16)).isoformat(),))
    assert client.get("/api/overview").json()["elders"][0]["current_emotion"] == "unknown"


def test_mixed_emotion_batch_commits_snapshots_and_unique_events(console):
    client, root = console
    elder_id = profile(client)
    path = root / "mixed.jsonl"
    raw = {"schema_version": "emotion_strategy_v1", "event_id": "a", "emotion": "happy",
           "observed_at": datetime.now(timezone.utc).isoformat()}
    line = json.dumps(raw) + "\n"
    path.write_text(line)
    attach(client, path, elder_id, "emotion", "live")
    snapshot = {"schema_version": "emotion_snapshot_v1", "event_id": "fresh", "emotion": "calm",
                "observed_at": datetime.now(timezone.utc).isoformat()}
    with path.open("a") as stream:
        stream.write(line + json.dumps(snapshot) + "\n" + json.dumps({**raw, "event_id": "b"}) + "\n")
    client.post("/api/sync", headers=HEADERS)
    assert client.get("/api/overview").json()["elders"][0]["current_emotion"] == "calm"
    assert client.get("/api/events").json()["total"] == 2
    assert all(not source["error"] for source in client.get("/api/sources").json())


def test_resume_source_preserves_resolved_history(console):
    client, root = console
    path = root / "resume.jsonl"
    path.write_text(json.dumps({"event_id": "a", "type": "fall", "level": "L3", "time": 9}) + "\n")
    elder_id = profile(client)
    source_id = attach(client, path, elder_id)
    event = client.get("/api/events").json()["items"][0]
    client.post(f"/api/events/{event['id']}/actions", headers=HEADERS,
                json={"status": "false_alarm", "operator": "测试护士", "note": "已核实误报", "version": 0})
    client.delete(f"/api/sources/{source_id}", headers=HEADERS)
    assert attach(client, path, elder_id) == source_id
    items = client.get("/api/events").json()["items"]
    assert len(items) == 1 and items[0]["status"] == "false_alarm"


def test_same_header_same_size_rewrite_changes_generation(console):
    client, root = console
    path = root / "rewrite.jsonl"
    first = json.dumps({"event_id": "one", "type": "fall", "level": "L3", "time": 1}) + "\n"
    second = json.dumps({"event_id": "two", "type": "fall", "level": "L3", "time": 2}) + "\n"
    path.write_text(first + second)
    attach(client, path, profile(client))
    path.write_text(first + second.replace('"two"', '"new"'))
    client.post("/api/sync", headers=HEADERS)
    assert client.get("/api/sources").json()[0]["generation"] == 1
    assert any(event["external_id"] == "new" for event in [client.get(f"/api/events/{item['id']}").json() for item in client.get("/api/events").json()["items"]])


def test_open_alerts_and_person_history_are_independent_of_recent_events(console):
    client, root = console
    elder_id = profile(client)
    path = root / "buried.jsonl"
    lines = [{"event_id": "danger", "type": "fall", "level": "L3", "time": 1}]
    lines += [{"event_id": f"ordinary-{i}", "type": "out_of_view", "level": "L1", "time": i + 2} for i in range(101)]
    path.write_text("".join(json.dumps(raw) + "\n" for raw in lines))
    attach(client, path, elder_id)
    assert not any(row["level"] == "L3" for row in client.get("/api/events?limit=100").json()["items"])
    assert client.get("/api/events?status=open").json()["items"][0]["title"] == "疑似跌倒"


def test_oversized_complete_line_is_visible(console):
    client, root = console
    path = root / "large.jsonl"
    path.write_text('x' * MAX_LINE + '\n')
    attach(client, path, profile(client))
    source = client.get("/api/sources").json()[0]
    assert source["offset"] == 0 and "64 KiB" in source["error"]


def test_nested_bad_json_cannot_block_other_sources(console):
    client, root = console
    elder_id = profile(client)
    good, bad = root / "good.jsonl", root / "nested.jsonl"
    good.write_text(json.dumps({"event_id": "valid", "type": "fall", "level": "L3", "time": 1}) + "\n")
    # Bind healthy first, so the newest malformed source is read before it.
    for path in (good, bad):
        assert client.post("/api/sources", headers=HEADERS, json={"elder_id": elder_id, "module": "anomaly", "path": str(path)}).status_code == 200
    bad.write_text('[' * 1100 + '0' + ']' * 1100 + '\n')
    assert client.post("/api/sync", headers=HEADERS).status_code == 200
    assert client.get("/api/events").json()["total"] == 1
    source = client.get("/api/sources").json()[0]
    assert source["rejected"] == 1 and source["error"]


def test_recovered_source_clears_io_error_but_retains_rejection_count(console):
    client, root = console
    path = root / "restore.jsonl"
    path.write_text('invalid\n')
    attach(client, path, profile(client))
    original = path.read_bytes()
    path.unlink()
    client.post("/api/sync", headers=HEADERS)
    path.write_bytes(original + (json.dumps({"event_id": "a", "type": "fall", "level": "L3", "time": 1}) + '\n').encode())
    client.post("/api/sync", headers=HEADERS)
    source = client.get("/api/sources").json()[0]
    assert not source["error"] and source["rejected"] >= 1
    assert client.get("/api/events").json()["total"] == 1


def test_live_anomaly_future_timestamp_is_rejected(console):
    client, root = console
    path = root / "future-alert.jsonl"
    path.write_text(json.dumps({"event_id": "future", "type": "fall", "level": "L3", "time": 4070908800}) + '\n')
    attach(client, path, profile(client), mode="live")
    assert client.get("/api/events").json()["total"] == 0
    assert "时钟" in client.get("/api/sources").json()[0]["error"]

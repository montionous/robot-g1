import sqlite3

from care_console.business_records import BusinessRecords
from care_console.interaction import InteractionReader


SCHEMA = """
CREATE TABLE care_consultation_session (
    id INTEGER PRIMARY KEY, elderly_id INTEGER NOT NULL, status TEXT NOT NULL,
    started_at TEXT NOT NULL, ended_at TEXT, end_reason TEXT, care_domain TEXT,
    risk_level TEXT, session_source TEXT NOT NULL, persist_memory INTEGER NOT NULL
);
CREATE TABLE care_consultation_message (
    id INTEGER PRIMARY KEY, session_id INTEGER NOT NULL, round_no INTEGER NOT NULL,
    role TEXT NOT NULL, content TEXT NOT NULL, tags_json TEXT, created_at TEXT NOT NULL
);
CREATE TABLE short_chat_session (
    id INTEGER PRIMARY KEY, elderly_id INTEGER NOT NULL, status TEXT NOT NULL,
    started_at TEXT NOT NULL, ended_at TEXT, end_reason TEXT
);
CREATE TABLE short_chat_message (
    id INTEGER PRIMARY KEY, session_id INTEGER NOT NULL, round_no INTEGER NOT NULL,
    role TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE contact_call_log (
    id INTEGER PRIMARY KEY, elderly_id INTEGER NOT NULL, contact_id INTEGER,
    recognized_text TEXT, requested_relation TEXT, confirmed INTEGER NOT NULL,
    call_status TEXT, created_at TEXT NOT NULL
);
CREATE TABLE family_contact (
    id INTEGER PRIMARY KEY, elderly_id INTEGER NOT NULL, name TEXT NOT NULL, relation TEXT NOT NULL
);
CREATE TABLE social_activity_interest (
    interest_id INTEGER PRIMARY KEY, elder_id INTEGER NOT NULL, session_id INTEGER NOT NULL,
    status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE social_activity_session (
    session_id INTEGER PRIMARY KEY, activity_id INTEGER NOT NULL, activity_date TEXT NOT NULL,
    start_time TEXT NOT NULL, end_time TEXT NOT NULL, status TEXT NOT NULL
);
CREATE TABLE social_activity (
    activity_id INTEGER PRIMARY KEY, name TEXT NOT NULL
);
CREATE TABLE staff_notification (
    notification_id INTEGER PRIMARY KEY, elder_id INTEGER NOT NULL, session_id INTEGER,
    notification_type TEXT NOT NULL, message TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE care_assistance_request (
    id INTEGER PRIMARY KEY, session_id INTEGER NOT NULL, elderly_id INTEGER NOT NULL,
    care_domain TEXT NOT NULL, risk_level TEXT NOT NULL, user_description TEXT NOT NULL,
    summary TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL
);
"""


def _fixture(tmp_path):
    path = tmp_path / "interaction.db"
    with sqlite3.connect(path) as db:
        db.executescript(SCHEMA)
        db.executemany(
            "INSERT INTO care_consultation_session VALUES(?,?,?,?,?,?,?,?,?,?)",
            [
                (3, 1, "ended", "2026-10-13 01:00:00", "2026-10-13T09:00:00", "user_requested", "mobility", "low", "runtime", 1),
                (4, 1, "consulting", "2026-10-13 02:00:00", None, None, "sleep", "low", "runtime", 1),
            ],
        )
        db.executemany(
            "INSERT INTO care_consultation_message VALUES(?,?,?,?,?,?,?)",
            [
                (1, 3, 1, "user", "腿酸", '{"ROUND":"1"}', "2026-10-13 01:00:01"),
                (2, 3, 1, "assistant", "先休息", "{}", "2026-10-13 01:00:02"),
            ],
        )
        db.execute("INSERT INTO short_chat_session VALUES(1,1,'chatting','2026-10-13 03:00:00',NULL,NULL)")
        db.execute("INSERT INTO short_chat_message VALUES(3,1,1,'user','陪我聊聊','2026-10-13 03:00:01')")
        db.execute("INSERT INTO contact_call_log VALUES(2,1,8,'我想找女儿','女儿',1,'initiated','2026-10-13 04:00:00')")
        db.execute("INSERT INTO family_contact VALUES(8,1,'女儿','女儿')")
        db.execute("INSERT INTO social_activity VALUES(1,'唱歌')")
        db.execute("INSERT INTO social_activity_session VALUES(6,1,'2026-10-14','10:00','11:00','open')")
        db.execute("INSERT INTO social_activity_interest VALUES(7,1,6,'interested','2026-10-13 05:00:00','2026-10-13 05:01:00')")
        db.execute("INSERT INTO staff_notification VALUES(9,1,6,'activity_interest','已记录','pending','2026-10-13 05:02:00')")
        db.execute("INSERT INTO care_assistance_request VALUES(10,3,1,'mobility','needs_staff','腿酸','请工作人员关注','pending','2026-10-13 05:03:00')")
    reader = InteractionReader(path)
    key = reader.source_key()
    elders = [
        {"id": 101, "name": "本地甲", "interaction_elderly_id": 1, "interaction_source_key": key},
        {"id": 102, "name": "本地乙", "interaction_elderly_id": 2, "interaction_source_key": key},
    ]
    return reader, elders


def test_explicit_binding_kind_order_and_compound_cursor(tmp_path):
    reader, elders = _fixture(tmp_path)
    records = BusinessRecords(reader)

    empty = records.list([], limit=2)
    assert empty["status"] == "ready" and empty["items"] == []
    assert empty["availability"]["care"] == "available"

    result = records.list(elders, limit=4)
    assert result["status"] == "ready" and result["total"] == 7
    assert [item["key"] for item in result["items"]] == ["care:4", "care:3", "chat:1", "call:2"]
    assert all(isinstance(item["key"], str) and isinstance(item["elder_id"], str) for item in result["items"])
    next_page = records.list(elders, before=result["next"], limit=4)
    assert [item["key"] for item in next_page["items"]] == ["activity:7", "notification:9", "assistance:10"]


def test_detail_preserves_owner_status_times_and_loads_messages(tmp_path):
    reader, elders = _fixture(tmp_path)
    records = BusinessRecords(reader)

    first = records.get(elders, "care:3", limit=1)
    assert first["status"] == "ready"
    assert first["item"]["elder_id"] == "101"
    assert first["item"]["status"] == "ended"
    assert first["item"]["started_at"] == "2026-10-13 01:00:00"
    assert first["item"]["source"]["time_basis"]["started_at"] == "source_timezone_unspecified"
    assert [message["id"] for message in first["messages"]] == ["1"]
    assert first["next_message"] == "1:1"

    second = records.get(elders, "care:3", after=first["next_message"], limit=1)
    assert [message["id"] for message in second["messages"]] == ["2"]
    assert records.get(elders, "call:2")["item"]["status"] == "initiated"
    assert records.get(elders, "care:3")["status"] == "ready"
    assert records.get([elders[1]], "care:3")["status"] == "missing"


def test_assistance_links_only_to_its_same_source_and_elder_session(tmp_path):
    reader, elders = _fixture(tmp_path)
    records = BusinessRecords(reader)
    assert records.get(elders, 'assistance:10')['item']['parent_key'] == 'care:3'
    assert [item['key'] for item in records.get(elders, 'care:3')['related_business']] == ['assistance:10']
    assert records.get(elders, 'care:3')['related_business'][0]['facts']['user_description'] == '腿酸'
    notification = records.get(elders, 'activity:7')['related_business'][0]
    assert notification['key'] == 'notification:9'
    assert notification['facts']['message'] == '已记录'
    with sqlite3.connect(reader.path) as db:
        db.execute('UPDATE care_assistance_request SET elderly_id=2 WHERE id=10')
    assert records.get(elders, 'assistance:10')['item'].get('parent_key') is None
    assert records.get(elders, 'care:3')['related_business'] == []


def test_daily_archive_excludes_explicit_test_and_simulated_records(tmp_path):
    reader, elders = _fixture(tmp_path)
    with sqlite3.connect(reader.path) as db:
        db.execute("UPDATE care_consultation_session SET session_source='test' WHERE id=4")
        db.execute("INSERT INTO care_assistance_request VALUES(11,4,1,'sleep','low','测试','测试','pending','2026-10-13 05:04:00')")
        db.executemany(
            "INSERT INTO contact_call_log VALUES(?,1,8,'联系家人','女儿',1,?,'2026-10-13 04:00:00')",
            [(3, 'connected_demo'), (4, 'dial_authorized_safe_stub')],
        )
    records = BusinessRecords(reader)
    keys = []
    cursor = None
    while True:
        page = records.list(elders, before=cursor, limit=2)
        assert page['status'] == 'ready' and page['total'] == 6
        keys.extend(item['key'] for item in page['items'])
        cursor = page['next']
        if cursor is None:
            break
    assert keys == ['care:3', 'chat:1', 'call:2', 'activity:7', 'notification:9', 'assistance:10']
    for key in ['care:4', 'call:3', 'call:4', 'assistance:11']:
        assert records.get(elders, key)['status'] == 'missing'
    with sqlite3.connect(reader.path) as db:
        assert db.execute('SELECT COUNT(*) FROM contact_call_log').fetchone()[0] == 3


def test_long_chinese_emoji_text_keeps_full_summary_and_safe_titles(tmp_path):
    reader, elders = _fixture(tmp_path)
    records = BusinessRecords(reader)
    long_text = "老人想听戏🙂" * 1800

    with sqlite3.connect(reader.path) as db:
        db.execute("UPDATE care_consultation_message SET content=? WHERE id=1", (long_text,))
        db.execute("UPDATE short_chat_message SET content=? WHERE id=3", (long_text,))
        db.execute("UPDATE contact_call_log SET recognized_text=? WHERE id=2", (long_text,))
        db.execute("UPDATE social_activity SET name=? WHERE activity_id=1", (long_text,))
        db.execute("UPDATE staff_notification SET message=? WHERE notification_id=9", (long_text,))
        db.execute("UPDATE care_assistance_request SET summary=? WHERE id=10", (long_text,))

    for kind, key in (
        ("care", "care:3"),
        ("chat", "chat:1"),
        ("call", "call:2"),
        ("activity", "activity:7"),
        ("notification", "notification:9"),
        ("assistance", "assistance:10"),
    ):
        listing = records.list(elders, kind=kind)
        assert listing["status"] == "ready"
        item = next(item for item in listing["items"] if item["key"] == key)
        assert item["summary"] == long_text
        assert len(item["title"].encode("utf-8")) <= 256

    chat = records.get(elders, "chat:1", limit=1)
    assert chat["status"] == "ready"
    assert chat["item"]["title"] == "短聊会话"
    assert chat["item"]["summary"] == long_text
    assert chat["messages"][0]["content"] == long_text


def test_message_cursor_orders_round_then_id(tmp_path):
    reader, elders = _fixture(tmp_path)
    records = BusinessRecords(reader)
    with sqlite3.connect(reader.path) as db:
        db.executemany(
            "INSERT INTO care_consultation_message VALUES(?,?,?,?,?,?,?)",
            [
                (4, 3, 2, "user", "第二轮", None, "2026-10-13 01:00:03"),
                (5, 3, 2, "assistant", "第二轮回复", None, "2026-10-13 01:00:04"),
            ],
        )

    first = records.get(elders, "care:3", limit=2)
    assert [message["id"] for message in first["messages"]] == ["1", "2"]
    assert first["next_message"] == "1:2"
    second = records.get(elders, "care:3", after=first["next_message"], limit=2)
    assert [message["id"] for message in second["messages"]] == ["4", "5"]
    assert second["next_message"] is None


def test_missing_child_table_is_reported_without_hiding_other_kinds(tmp_path):
    path = tmp_path / "partial.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE care_consultation_session (id INTEGER PRIMARY KEY, elderly_id INTEGER, status TEXT, started_at TEXT, ended_at TEXT, end_reason TEXT, care_domain TEXT, risk_level TEXT, session_source TEXT, persist_memory INTEGER)")
        db.execute("INSERT INTO care_consultation_session VALUES(1,1,'consulting','2026-10-13 01:00:00',NULL,NULL,'mobility','low','runtime',1)")
        db.execute("CREATE TABLE short_chat_session (id INTEGER PRIMARY KEY, elderly_id INTEGER, status TEXT, started_at TEXT, ended_at TEXT, end_reason TEXT)")
    reader = InteractionReader(path)
    key = reader.source_key()
    elders = [{"id": 1, "name": "甲", "interaction_elderly_id": 1, "interaction_source_key": key}]
    result = BusinessRecords(reader).list(elders)
    assert result["status"] == "ready"
    assert result["availability"]["care"] == "available"
    assert result["availability"]["tables"]["care_consultation_message"] == "unavailable"
    assert result["availability"]["chat"] == "available"
    assert [item["key"] for item in result["items"]] == ["care:1"]
    detail = BusinessRecords(reader).get(elders, "care:1")
    assert detail["status"] == "ready" and detail["messages"] == []
    assert detail["item"]["facts"]["messages_availability"] == "unavailable"


def test_missing_join_tables_degrade_names_without_hiding_main_records(tmp_path):
    reader, elders = _fixture(tmp_path)
    records = BusinessRecords(reader)
    with sqlite3.connect(reader.path) as db:
        db.execute("DROP TABLE family_contact")
        db.execute("DROP TABLE social_activity_session")
        db.execute("DROP TABLE social_activity")

    call = records.list(elders, kind="call")
    assert call["status"] == "ready"
    assert call["availability"]["call"] == "available"
    assert call["availability"]["tables"]["family_contact"] == "unavailable"
    assert call["items"][0]["title"] == "女儿"

    activity = records.list(elders, kind="activity")
    assert activity["status"] == "ready"
    assert activity["availability"]["activity"] == "available"
    assert activity["availability"]["tables"]["social_activity_session"] == "unavailable"
    assert activity["availability"]["tables"]["social_activity"] == "unavailable"
    assert activity["items"][0]["title"] == "活动意愿"
    assert activity["items"][0]["summary"] == "interested"

    notification = records.get(elders, "notification:9")
    assert notification["status"] == "ready"
    assert notification["item"]["title"] == "activity_interest"
    assert notification["item"]["source"]["row"]["activity_name"] is None


def test_bad_tags_are_visible_and_source_replacement_is_rejected(tmp_path):
    reader, elders = _fixture(tmp_path)
    with sqlite3.connect(reader.path) as db:
        db.execute("UPDATE care_consultation_message SET tags_json=? WHERE id=1", ('{"x":NaN}',))
    detail = BusinessRecords(reader).get(elders, "care:3", limit=1)
    assert detail["status"] == "ready"
    assert detail["messages"][0]["tags"] is None
    assert detail["messages"][0]["tags_error"]

    replacement = reader.path.with_name("replacement.db")
    with sqlite3.connect(reader.path) as original, sqlite3.connect(replacement) as changed:
        original.backup(changed)
    replacement.replace(reader.path)
    result = BusinessRecords(reader).list(elders)
    assert result["status"] == "error" and result["items"] == []


def test_bad_cursor_and_cross_kind_key_are_bounded(tmp_path):
    reader, elders = _fixture(tmp_path)
    records = BusinessRecords(reader)
    assert records.list(elders, before="care:9223372036854775808")["status"] == "error"
    assert records.list(elders, kind="unknown")["status"] == "error"
    assert records.get(elders, "care:3:extra")["status"] == "error"
    assert records.get(elders, "care:999")["status"] == "missing"
    assert records.get(elders, "care:3", after="1000000001:1")["status"] == "error"


def test_invalid_time_and_oversized_content_are_not_silently_truncated(tmp_path):
    reader, elders = _fixture(tmp_path)
    with sqlite3.connect(reader.path) as db:
        db.execute("UPDATE care_consultation_session SET started_at='not-a-time' WHERE id=3")
    assert BusinessRecords(reader).list(elders, kind="care")["status"] == "error"

    with sqlite3.connect(reader.path) as db:
        db.execute("UPDATE care_consultation_session SET started_at='2026-10-13 01:00:00' WHERE id=3")
        db.execute("UPDATE care_consultation_message SET content=? WHERE id=1", ("x" * (64 * 1024 + 1),))
    detail = BusinessRecords(reader).get(elders, "care:3")
    assert detail["status"] == "error" and detail["messages"] == []

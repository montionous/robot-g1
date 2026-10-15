"""The retired test-record feature must not expose archived data."""
import subprocess
import sys

from fastapi.testclient import TestClient

from care_console.server import create_app
from care_console.test_auth import ORIGIN, auth_file, login


def test_test_record_routes_are_removed_and_archive_is_untouched(tmp_path):
    archive = tmp_path / 'replay.db'
    archive.write_bytes(b'archived test data stays offline')
    before = archive.read_bytes()
    with TestClient(create_app(tmp_path / 'console.db', background=False)) as client:
        for path in ('/api/replays', '/api/replays/events/1', '/api/replays/sessions/1'):
            assert client.get(path).status_code == 404
        assert client.get('/api/sources').status_code == 200
    assert archive.read_bytes() == before


def test_retired_routes_remain_unavailable_after_cloud_login(tmp_path, auth_file):
    app = create_app(tmp_path / 'console.db', background=False, deployment='cloud', auth_file=auth_file, allowed_hosts=['82.157.186.52'])
    with TestClient(app, base_url=ORIGIN) as client:
        assert client.get('/api/sources').status_code == 401
        assert login(client).status_code == 200
        assert client.get('/api/sources').status_code == 200
        for path in ('/api/replays', '/api/replays/events/1', '/api/replays/sessions/1'):
            assert client.get(path).status_code == 404


def test_startup_does_not_offer_test_database_configuration():
    result = subprocess.run([sys.executable, '-m', 'care_console', '--help'], capture_output=True, text=True, check=True)
    assert '--replay-db' not in result.stdout

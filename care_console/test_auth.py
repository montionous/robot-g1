import hashlib
import json

import pytest
from fastapi.testclient import TestClient

from care_console.server import create_app


ORIGIN = 'https://82.157.186.52:8443'
HEADERS = {'X-Care-Console': '1', 'Origin': ORIGIN}
PASSWORD = 'test-password-for-auth'


@pytest.fixture
def auth_file(tmp_path):
    salt = bytes.fromhex('19' * 16)
    path = tmp_path / 'auth.json'
    path.write_text(json.dumps({
        'username': 'careadmin',
        'password_salt': salt.hex(),
        'password_hash': hashlib.pbkdf2_hmac('sha256', PASSWORD.encode(), salt, 600_000).hex(),
    }))
    path.chmod(0o600)
    return path


@pytest.fixture
def authenticated_app(tmp_path, auth_file):
    return create_app(tmp_path / 'console.db', roots=[tmp_path], background=False,
                      allowed_hosts=['82.157.186.52'], deployment='cloud', auth_file=auth_file)


def login(client, password=PASSWORD, username='careadmin'):
    return client.post('/api/auth/login', headers=HEADERS,
                       json={'username': username, 'password': password})


@pytest.mark.parametrize('missing_path', [None, ''])
def test_cloud_requires_private_auth_configuration(tmp_path, auth_file, missing_path):
    with pytest.raises(ValueError, match='认证'):
        create_app(tmp_path / 'missing.db', deployment='cloud', background=False, auth_file=missing_path)
    auth_file.chmod(0o644)
    with pytest.raises(ValueError, match='权限'):
        create_app(tmp_path / 'unsafe.db', deployment='cloud', background=False, auth_file=auth_file)


def test_login_page_is_public_but_records_are_protected(authenticated_app):
    with TestClient(authenticated_app, base_url=ORIGIN) as client:
        response = client.get('/', follow_redirects=False)
        assert response.status_code == 303 and response.headers['location'] == '/login'
        page = client.get('/login').text
        assert '登录护理工作台' in page
        assert 'method="post" action="/api/auth/login"' in page
        native_submit = client.post('/api/auth/login', data={'username': 'careadmin', 'password': PASSWORD})
        assert native_submit.status_code == 403 and PASSWORD not in native_submit.text
        assert client.get('/static/login.js').status_code == 200
        for path in ('/api/health', '/api/overview', '/api/sessions', '/api/events', '/api/sources'):
            response = client.get(path)
            assert response.status_code == 401
            assert 'www-authenticate' not in response.headers
            assert response.headers['cache-control'] == 'no-store'


def test_bad_credentials_do_not_issue_a_session(authenticated_app):
    with TestClient(authenticated_app, base_url=ORIGIN) as client:
        wrong_password = login(client, password='wrong')
        wrong_user = login(client, username='unknown')
        assert wrong_password.status_code == wrong_user.status_code == 401
        assert wrong_password.json() == wrong_user.json()
        assert not client.cookies
        too_long = login(client, password='private-value-' * 100)
        assert too_long.status_code == 422
        assert 'private-value' not in too_long.text


def test_login_cookie_and_private_page(authenticated_app):
    with TestClient(authenticated_app, base_url=ORIGIN) as client:
        response = login(client)
        assert response.status_code == 200
        cookie = response.headers['set-cookie'].lower()
        assert 'httponly' in cookie and 'secure' in cookie and 'samesite=strict' in cookie
        assert PASSWORD not in cookie
        assert client.get('/api/health').json()['deployment'] == 'cloud'
        assert '护理工作台' in client.get('/').text
        assert client.get('/login', follow_redirects=False).headers['location'] == '/'
        assert client.get('/api/auth/session').json() == {
            'enabled': True, 'authenticated': True, 'username': 'careadmin',
        }


def test_logout_revokes_cookie_and_forged_cookie_is_rejected(authenticated_app):
    with TestClient(authenticated_app, base_url=ORIGIN) as client:
        login(client)
        old_cookie = client.cookies.get('care_console_session')
        assert client.post('/api/auth/logout', headers=HEADERS).status_code == 200
        assert client.get('/api/health', headers={'Cookie': 'care_console_session=' + old_cookie}).status_code == 401
        assert client.get('/api/health', headers={'Cookie': 'care_console_session=' + 'x' * 43}).status_code == 401


def test_session_expires_and_backend_restart_requires_login(authenticated_app, tmp_path, auth_file, monkeypatch):
    with TestClient(authenticated_app, base_url=ORIGIN) as client:
        login(client)
        cookie = client.cookies.get('care_console_session')
        restarted = create_app(tmp_path / 'console.db', roots=[tmp_path], background=False,
                               allowed_hosts=['82.157.186.52'], deployment='cloud', auth_file=auth_file)
        with TestClient(restarted, base_url=ORIGIN) as fresh:
            assert fresh.get('/api/health', headers={'Cookie': 'care_console_session=' + cookie}).status_code == 401
        monkeypatch.setattr('care_console.auth.time.monotonic', lambda: float('inf'))
        assert client.get('/api/health').status_code == 401


def test_login_and_logout_keep_origin_boundary(authenticated_app):
    with TestClient(authenticated_app, base_url=ORIGIN) as client:
        body = {'username': 'careadmin', 'password': PASSWORD}
        assert client.post('/api/auth/login', json=body).status_code == 403
        assert client.post('/api/auth/login', json=body, headers={**HEADERS, 'Origin': 'https://untrusted.example'}).status_code == 403
        assert login(client).status_code == 200
        assert client.post('/api/auth/logout', headers={**HEADERS, 'Origin': 'https://untrusted.example'}).status_code == 403
        assert client.get('/api/health').status_code == 200
        assert client.get('/login', headers={'Host': 'untrusted.example'}).status_code == 400


def test_session_store_is_bounded(authenticated_app, monkeypatch):
    monkeypatch.setattr('care_console.auth.MAX_SESSIONS', 3)
    auth = authenticated_app.state.auth
    tokens = [auth.create_session() for _ in range(4)]
    assert not auth.authenticated(tokens[0])
    assert all(auth.authenticated(token) for token in tokens[1:])


def test_change_password_persists_and_revokes_all_sessions(authenticated_app, tmp_path, auth_file):
    new_password = 'a memorable phrase 2026'
    with TestClient(authenticated_app, base_url=ORIGIN) as client:
        login(client)
        first_cookie = client.cookies.get('care_console_session')
        login(client)
        second_cookie = client.cookies.get('care_console_session')
        another_session = authenticated_app.state.auth.create_session()
        response = client.post('/api/auth/password', headers=HEADERS, json={
            'current_password': PASSWORD, 'new_password': new_password, 'confirm_password': new_password,
        })
        assert response.status_code == 200
        assert not client.cookies
        for cookie in (first_cookie, second_cookie, another_session):
            assert client.get('/api/health', headers={'Cookie': 'care_console_session=' + cookie}).status_code == 401
        assert new_password not in auth_file.read_text()
        assert auth_file.stat().st_mode & 0o777 == 0o600
        assert login(client).status_code == 401
        assert login(client, password=new_password).status_code == 200
        restarted = create_app(tmp_path / 'console.db', background=False, auth_file=auth_file,
                               allowed_hosts=['82.157.186.52'], deployment='cloud')
        with TestClient(restarted, base_url=ORIGIN) as fresh:
            assert login(fresh).status_code == 401
            assert login(fresh, password=new_password).status_code == 200


def test_change_password_requires_session_current_password_and_matching_input(authenticated_app):
    body = {'current_password': PASSWORD, 'new_password': 'simple long phrase', 'confirm_password': 'simple long phrase'}
    with TestClient(authenticated_app, base_url=ORIGIN) as client:
        assert client.post('/api/auth/password', headers=HEADERS, json=body).status_code == 401
        login(client)
        for changes, status in [({'current_password': 'wrong-private-value'}, 400),
                                ({'confirm_password': 'a different phrase'}, 400),
                                ({'new_password': 'too-short'}, 422)]:
            response = client.post('/api/auth/password', headers=HEADERS, json={**body, **changes})
            assert response.status_code == status
            assert 'wrong-private-value' not in response.text and PASSWORD not in response.text
        assert client.post('/api/auth/password', json=body).status_code == 403
        assert client.post('/api/auth/password', headers={**HEADERS, 'Origin': 'https://untrusted.example'}, json=body).status_code == 403
        assert client.get('/api/health').status_code == 200


def test_failed_password_save_preserves_credentials_sessions_and_private_file(authenticated_app, auth_file, monkeypatch):
    import os
    previous = auth_file.read_bytes()
    def fail_replace(*_args):
        raise OSError('simulated write failure')
    monkeypatch.setattr(os, 'replace', fail_replace)
    with TestClient(authenticated_app, base_url=ORIGIN) as client:
        login(client)
        response = client.post('/api/auth/password', headers=HEADERS, json={
            'current_password': PASSWORD, 'new_password': 'simple long phrase', 'confirm_password': 'simple long phrase',
        })
        assert response.status_code == 500
        assert 'simple long phrase' not in response.text
        assert auth_file.read_bytes() == previous
        assert client.get('/api/health').status_code == 200
        assert login(client).status_code == 200
        assert not list(auth_file.parent.glob('.auth-*'))


def test_cancelled_password_change_finishes_committed_state(authenticated_app, monkeypatch):
    import asyncio
    import os
    import threading
    started, release, committed = threading.Event(), threading.Event(), threading.Event()
    replace = os.replace
    def delayed_replace(source, target):
        started.set()
        assert release.wait(3)
        replace(source, target)
        committed.set()
    monkeypatch.setattr(os, 'replace', delayed_replace)
    auth = authenticated_app.state.auth
    token = auth.create_session()
    async def change_and_cancel():
        task = asyncio.create_task(auth.change_password('a memorable phrase 2026'))
        assert await asyncio.to_thread(started.wait, 3)
        task.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert await asyncio.to_thread(committed.wait, 3)
        assert auth.verify('careadmin', 'a memorable phrase 2026')
        assert not auth.verify('careadmin', PASSWORD)
        assert not auth.authenticated(token)
    asyncio.run(change_and_cancel())

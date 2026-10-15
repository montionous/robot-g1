import asyncio
import hashlib
import hmac
import json
import os
import secrets
import stat
import tempfile
import time
from pathlib import Path


COOKIE_NAME = 'care_console_session'
SESSION_SECONDS = 8 * 60 * 60
MAX_SESSIONS = 256
PASSWORD_ITERATIONS = 600_000


class ConsoleAuth:
    def __init__(self, path: Path):
        self.path = path
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
            raise ValueError('认证文件权限必须为 0600，仅供服务账号读取。')
        if info.st_size > 16_384:
            raise ValueError('认证文件过大。')
        try:
            config = json.loads(path.read_text())
            self.username = config['username']
            self.salt = bytes.fromhex(config['password_salt'])
            self.password_hash = bytes.fromhex(config['password_hash'])
            if not isinstance(self.username, str) or not 1 <= len(self.username) <= 80:
                raise ValueError
            if len(self.salt) != 16 or len(self.password_hash) != 32:
                raise ValueError
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError('认证文件格式无效。') from exc
        # shortcut: 会话只存于单进程内存；需要多进程或重启保留时改为共享存储。
        self._sessions: dict[str, float] = {}

    def verify(self, username: str, password: str) -> bool:
        candidate = hashlib.pbkdf2_hmac('sha256', password.encode(), self.salt, PASSWORD_ITERATIONS)
        password_ok = hmac.compare_digest(candidate, self.password_hash)
        username_ok = hmac.compare_digest(username.encode(), self.username.encode())
        return password_ok and username_ok

    def create_session(self) -> str:
        now = time.monotonic()
        self._sessions = {token: expires for token, expires in self._sessions.items() if expires > now}
        if len(self._sessions) >= MAX_SESSIONS:
            self._sessions.pop(next(iter(self._sessions)))
        token = secrets.token_urlsafe(32)
        self._sessions[token] = now + SESSION_SECONDS
        return token

    def authenticated(self, token: str | None) -> bool:
        if not token or len(token) != 43:
            return False
        expires = self._sessions.get(token, 0)
        if expires <= time.monotonic():
            self._sessions.pop(token, None)
            return False
        return True

    def logout(self, token: str | None) -> None:
        self._sessions.pop(token, None)

    async def change_password(self, password: str) -> None:
        def save():
            salt = secrets.token_bytes(16)
            digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, PASSWORD_ITERATIONS)
            descriptor, temporary = tempfile.mkstemp(prefix='.auth-', dir=self.path.parent)
            try:
                with os.fdopen(descriptor, 'w') as output:
                    json.dump({'username': self.username, 'password_salt': salt.hex(),
                               'password_hash': digest.hex()}, output)
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(temporary, self.path)
            finally:
                Path(temporary).unlink(missing_ok=True)
            return salt, digest

        operation = asyncio.create_task(asyncio.to_thread(save))
        cancelled = False
        # 密码已经提交时必须同步内存并撤销会话，再把请求取消向上传播。
        while not operation.done():
            try:
                await asyncio.shield(operation)
            except asyncio.CancelledError:
                cancelled = True
        self.salt, self.password_hash = operation.result()
        self._sessions.clear()
        if cancelled:
            raise asyncio.CancelledError

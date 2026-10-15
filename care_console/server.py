import asyncio
import logging
import sqlite3
import re
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Path as ApiPath, Query, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .ingest import allowed_path
from .store import ConflictError, Store
from .attachments import open_attachment
from .business_records import BusinessRecords
from .auth import COOKIE_NAME, SESSION_SECONDS, ConsoleAuth

ROOT = Path(__file__).resolve().parents[1]
MONITOR_ROOT = Path("/home/user/zhangxu/elderly_monitor")
STATIC = Path(__file__).parent / "static"
LOGGER = logging.getLogger(__name__)


class ElderBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=80)
    age: int | None = Field(default=None, ge=0, le=120)
    room: str = Field(default="", max_length=80)
    notes: str = Field(default="", max_length=2000)


class ElderNotesBody(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    notes: str = Field(max_length=2000)


class SourceBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    elder_id: int = Field(ge=1)
    module: Literal["emotion", "anomaly", "interaction"]
    path: str = Field(min_length=1, max_length=2048)
    mode: Literal["live", "replay"] = "replay"


class ActionBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    status: Literal["acknowledged", "handling", "closed", "false_alarm"]
    operator: str = Field(min_length=1, max_length=80)
    note: str = Field(min_length=2, max_length=2000)
    version: int = Field(ge=0)


class InteractionBindingBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    elderly_id: int = Field(ge=1, le=2**63-1)
    source_key: str = Field(min_length=1, max_length=4096)


class InteractionImportBody(InteractionBindingBody):
    notes: str = Field(default="", max_length=2000)


class LoginBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=256)


class PasswordBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=12, max_length=256)
    confirm_password: str = Field(min_length=12, max_length=256)


def create_app(db_path=None, roots=None, background=True, interaction_db=None, allowed_hosts=None, deployment="local", auth_file=None):
    if deployment == 'cloud' and not auth_file:
        raise ValueError('云端部署必须配置认证文件。')
    auth = ConsoleAuth(Path(auth_file)) if auth_file else None
    auth_lock = asyncio.Lock()
    store = Store(db_path or Path(__file__).parent / "runtime" / "console.db", roots or [ROOT / "runs", MONITOR_ROOT],
                  interaction_db or ROOT / "speech" / "data" / "elder_companion.db")
    async def collect():
        while True:
            try:
                await asyncio.to_thread(store.sync)
            except Exception:
                LOGGER.exception("Console collector failed; original module records remain untouched")
            await asyncio.sleep(2)

    @asynccontextmanager
    async def lifespan(_app):
        task = asyncio.create_task(collect()) if background else None
        try:
            yield
        finally:
            if task:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

    app = FastAPI(title="老人陪伴护理工作台", lifespan=lifespan)
    app.state.store = store
    app.state.auth = auth

    @app.middleware("http")
    async def local_boundary(request: Request, call_next):
        origin = request.headers.get('origin')
        public_paths = {'/login', '/static/style.css', '/static/login.css', '/static/login.js',
                        '/api/auth/login', '/api/auth/session'}
        if request.method not in {'GET', 'HEAD', 'OPTIONS'} and (
            request.headers.get('x-care-console') != '1' or (origin and urlparse(origin).netloc != request.url.netloc)
        ):
            response = JSONResponse({'detail': '请从护理工作台执行此操作'}, status_code=403)
        elif auth and request.url.path not in public_paths and not auth.authenticated(request.cookies.get(COOKIE_NAME)):
            response = (JSONResponse({'detail': '请先登录护理工作台'}, status_code=401)
                        if request.url.path.startswith('/api/') else RedirectResponse('/login', status_code=303))
        else:
            response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid_input(request: Request, exc: RequestValidationError):
        if request.url.path == '/api/auth/password':
            return JSONResponse({'detail': '请填写当前密码，并输入 12–256 个字符的新密码。'}, status_code=422)
        if request.url.path == '/api/auth/login':
            return JSONResponse({'detail': '请输入有效的账号和密码。'}, status_code=422)
        return await request_validation_exception_handler(request, exc)

    @app.get('/login')
    async def login_page(request: Request):
        if not auth or auth.authenticated(request.cookies.get(COOKIE_NAME)):
            return RedirectResponse('/', status_code=303)
        return FileResponse(STATIC / 'login.html')

    @app.get('/api/auth/session')
    async def current_session(request: Request):
        authenticated = bool(auth and auth.authenticated(request.cookies.get(COOKIE_NAME)))
        return {'enabled': auth is not None, 'authenticated': authenticated,
                'username': auth.username if authenticated else None}

    @app.post('/api/auth/login')
    async def login(body: LoginBody, request: Request):
        if not auth:
            raise HTTPException(404, '本机工作台未启用账号登录。')
        if deployment == 'cloud' and request.url.scheme != 'https':
            raise HTTPException(400, '请通过 HTTPS 登录。')
        async with auth_lock:
            if not await asyncio.to_thread(auth.verify, body.username, body.password):
                raise HTTPException(401, '账号或密码不正确，请重新输入。')
            auth.logout(request.cookies.get(COOKIE_NAME))
            response = JSONResponse({'ok': True})
            response.set_cookie(COOKIE_NAME, auth.create_session(), max_age=SESSION_SECONDS,
                                httponly=True, secure=deployment == 'cloud', samesite='strict', path='/')
            return response

    @app.post('/api/auth/password')
    async def change_password(body: PasswordBody, request: Request):
        if not auth:
            raise HTTPException(404, '本机工作台未启用账号登录。')
        if deployment == 'cloud' and request.url.scheme != 'https':
            raise HTTPException(400, '请通过 HTTPS 修改密码。')
        async with auth_lock:
            if not auth.authenticated(request.cookies.get(COOKIE_NAME)):
                raise HTTPException(401, '请重新登录护理工作台。')
            if body.new_password != body.confirm_password:
                raise HTTPException(400, '两次输入的新密码不一致。')
            if body.new_password == body.current_password:
                raise HTTPException(400, '新密码应与当前密码不同。')
            if not await asyncio.to_thread(auth.verify, auth.username, body.current_password):
                raise HTTPException(400, '当前密码不正确，请重新输入。')
            try:
                await auth.change_password(body.new_password)
            except OSError:
                LOGGER.exception('Unable to save care-console password')
                raise HTTPException(500, '密码未能保存，请稍后重试。') from None
        response = JSONResponse({'ok': True})
        response.delete_cookie(COOKIE_NAME, path='/', secure=deployment == 'cloud', httponly=True, samesite='strict')
        return response

    @app.post('/api/auth/logout')
    async def logout(request: Request):
        if auth:
            auth.logout(request.cookies.get(COOKIE_NAME))
        response = JSONResponse({'ok': True})
        response.delete_cookie(COOKIE_NAME, path='/', secure=deployment == 'cloud', httponly=True, samesite='strict')
        return response

    @app.exception_handler(ValueError)
    async def invalid(_request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=409 if isinstance(exc, ConflictError) else 400)

    @app.get("/api/health")
    def health():
        return {"ok": True, "service": "care-console", "deployment": deployment, "robot_control": False}

    @app.get("/api/overview")
    def overview(data_mode: Literal["real", "demo"] = "real"):
        return store.overview(data_mode)

    @app.post("/api/elders")
    def add_elder(body: ElderBody):
        return store.save_elder(body)

    @app.post('/api/elders/from-interaction')
    def import_interaction(body: InteractionImportBody):
        try:
            return store.bind_interaction(None, body.elderly_id, body.source_key, initial_notes=body.notes.strip())
        except (OSError, sqlite3.Error) as exc:
            raise HTTPException(status_code=503, detail=f"交互数据读取失败：{exc}") from exc

    @app.put("/api/elders/{elder_id}")
    def edit_elder(elder_id: int, body: ElderBody):
        return store.save_elder(body, elder_id)

    @app.put('/api/elders/{elder_id}/notes')
    def edit_notes(elder_id: Annotated[int, ApiPath(ge=1, le=2**63-1)], body: ElderNotesBody):
        return store.save_notes(elder_id, body.notes)

    @app.post("/api/elders/{elder_id}/interaction-binding")
    def bind_interaction(elder_id: Annotated[int, ApiPath(ge=1, le=2**63-1)], body: InteractionBindingBody):
        try:
            return store.bind_interaction(elder_id, body.elderly_id, body.source_key)
        except (OSError, sqlite3.Error) as exc:
            raise HTTPException(status_code=503, detail=f"交互数据读取失败：{exc}") from exc

    @app.get("/api/interaction")
    def interaction(data_mode: Literal["real", "demo"] = "real", elder_id: int | None = Query(default=None, ge=1, le=2**63-1),
                    need_category: str | None = Query(default=None, max_length=80),
                    source_scene: str | None = Query(default=None, max_length=160),
                    source_session_id: str | None = Query(default=None, max_length=256),
                    status: Literal["open", "detected", "in_progress", "completed", "cancelled", "failed"] | None = None,
                    before: str | None = Query(default=None, max_length=40, pattern=r"^[0-2]:[1-9][0-9]*$"),
                    limit: int = Query(default=50, ge=1, le=100)):
        return store.interaction_needs(data_mode, elder_id=elder_id, category=need_category, status=status,
                                       before=before, limit=limit, source_scene=source_scene, source_session_id=source_session_id)

    @app.get("/api/interaction/{need_id}")
    def need(need_id: Annotated[int, ApiPath(ge=1, le=2**63-1)]):
        result = store.interaction_needs(need_id=need_id)
        if result["status"] == "error":
            raise HTTPException(status_code=503, detail=result["error"])
        if not result["items"]:
            raise HTTPException(status_code=404, detail="需求不存在或尚未绑定对应的老人档案")
        return result["items"][0]

    @app.get("/api/sources")
    def sources(data_mode: Literal["real", "demo"] = "real"):
        return store.sources(data_mode)

    @app.post("/api/sources")
    def add_source(body: SourceBody):
        return store.add_source(body, allowed_path(body.path, store.roots))

    @app.delete("/api/sources/{source_id}")
    def stop_source(source_id: int):
        store.disable_source(source_id)
        return {"ok": True}

    @app.post("/api/sync")
    def sync():
        store.sync()
        return {"ok": True}

    @app.get("/api/events")
    def events(data_mode: Literal["real", "demo"] = "real", module: Literal["emotion", "anomaly"] | None = None,
               elder_id: int | None = None, status: str | None = Query(default=None, max_length=30),
               before: int | None = None, limit: int = Query(default=50, ge=1, le=100)):
        return store.events(data_mode, module, elder_id, status, before, limit)

    @app.get("/api/events/{event_id}")
    def event(event_id: int):
        result=store.event(event_id)
        with store.connect() as db:
            source=db.execute('SELECT path FROM sources WHERE id=?',(result['source_id'],)).fetchone()
        evidence=result['raw'].get('evidence')
        result['attachments']=[]
        if isinstance(evidence,dict):
            for kind in ('audio','video'):
                raw_path=evidence.get(kind+'_clip')
                if not raw_path:continue
                try:
                    handle,size,mime=open_attachment(raw_path,source['path'],store.roots,kind)
                    handle.close()
                    result['attachments'].append(dict(kind=kind,available=True,bytes=size,url=f'/api/events/{event_id}/attachments/{kind}'))
                except (OSError,ValueError) as exc:
                    result['attachments'].append(dict(kind=kind,available=False,error=str(exc)))
        return result

    @app.get('/api/events/{event_id}/attachments/{kind}')
    def attachment(event_id:Annotated[int,ApiPath(ge=1,le=2**63-1)],kind:Literal['audio','video'],request:Request):
        event=store.event(event_id)
        evidence=event['raw'].get('evidence')
        if not isinstance(evidence,dict):raise HTTPException(404,'上游未提供附件')
        with store.connect() as db:
            source=db.execute('SELECT path FROM sources WHERE id=?',(event['source_id'],)).fetchone()
        try:
            handle,size,mime=open_attachment(evidence.get(kind+'_clip'),source['path'],store.roots,kind)
        except (OSError,ValueError) as exc:
            raise HTTPException(404,f'附件不可读取：{exc}') from exc
        start,end,status=0,size-1,200
        headers={'Accept-Ranges':'bytes','Content-Disposition':'inline'}
        requested=request.headers.get('range')
        if requested:
            match=re.fullmatch(r'bytes=(\d{1,20})-(\d{0,20})',requested)
            if not match:
                handle.close();raise HTTPException(416,'仅支持单段字节范围')
            start=int(match[1]);end=min(int(match[2]) if match[2] else size-1,size-1)
            if start>end:
                handle.close();raise HTTPException(416,'附件范围不可用')
            status=206;headers['Content-Range']=f'bytes {start}-{end}/{size}'
        headers['Content-Length']=str(end-start+1)
        def chunks():
            try:
                handle.seek(start);remaining=end-start+1
                while remaining:
                    part=handle.read(min(65536,remaining))
                    if not part:break
                    remaining-=len(part);yield part
            finally:handle.close()
        return StreamingResponse(chunks(),status_code=status,media_type=mime,headers=headers)

    @app.get('/api/sessions')
    def sessions(data_mode: Literal['real','demo']='real', elder_id: int|None=Query(default=None,ge=1,le=2**63-1),
                 before: int|None=Query(default=None,ge=1,le=2**63-1),limit:int=Query(default=30,ge=1,le=100)):
        return store.sessions(data_mode,elder_id,before,limit)

    @app.get('/api/sessions/{session_id}')
    def session(session_id:Annotated[int,ApiPath(ge=1,le=2**63-1)],after:int|None=Query(default=None,ge=0,le=100000),limit:int=Query(default=100,ge=1,le=100)):
        return store.session(session_id,after,limit)

    @app.get('/api/emotion-observations')
    def observations(data_mode:Literal['real','demo']='real',elder_id:int|None=Query(default=None,ge=1,le=2**63-1),
                     before:int|None=Query(default=None,ge=1,le=2**63-1),limit:int=Query(default=50,ge=1,le=100)):
        return store.observations(data_mode,elder_id,before,limit)

    def business_elders():
        return store.elders('real')

    @app.get('/api/business-records')
    def business_records(data_mode:Literal['real','demo']='real',elder_id:int|None=Query(default=None,ge=1,le=2**63-1),
                         kind:Literal['care','chat','call','activity','notification','assistance']|None=None,
                         before:str|None=Query(default=None,max_length=100),limit:int=Query(default=30,ge=1,le=100)):
        if data_mode=='demo':return dict(status='demo',error='',items=[],total=0,next=None,availability={})
        return BusinessRecords(store.interaction).list(business_elders(),elder_id,kind,before,limit)

    @app.get('/api/business-records/{key}')
    def business_record(key:str,after:str|None=Query(default=None,max_length=100),limit:int=Query(default=100,ge=1,le=100)):
        return BusinessRecords(store.interaction).get(business_elders(),key,after,limit)

    @app.post("/api/events/{event_id}/actions")
    def act(event_id: int, body: ActionBody):
        return store.act(event_id, body)

    @app.post("/api/demo")
    def demo():
        store.seed_demo()
        return {"ok": True}

    @app.get("/api/candidates")
    def candidates():
        result = []
        for filename in ["events.jsonl", "events_audio.jsonl"]:
            path = MONITOR_ROOT / filename
            try:
                if path.is_file():
                    result.append({"path": str(path), "module": "anomaly", "label": f"异常模块 / {filename}", "mode": "replay"})
            except OSError:
                LOGGER.warning('Optional monitor file is inaccessible: %s', path)
        try:
            for path in sorted((ROOT / "runs" / "care-console").glob("*.jsonl"), reverse=True)[:6]:
                result.append({"path": str(path), "module": "emotion", "label": f"情绪工作台日志 / {path.name}", "mode": "replay"})
            # Bounded discovery: no recursive scan of model assets or arbitrary user files.
            directories = sorted((ROOT / "runs").glob("elder-companion*")) if (ROOT / "runs").is_dir() else []
            for directory in directories[:20]:
                for path in sorted(directory.glob("*/*.jsonl"), reverse=True)[:6]:
                    if path.name == 'care-session.jsonl':
                        result.append({"path":str(path),"module":"interaction","label":f"交流会话 / {path.parent.name} / {path.name}","mode":"replay"})
                    elif "dashboard" in path.name or "emotion" in path.name or "strategy" in path.name:
                        result.append({"path": str(path), "module": "emotion", "label": f"情绪模块 / {path.parent.name} / {path.name}", "mode": "replay"})
        except OSError:
            LOGGER.warning('Optional run directories are inaccessible: %s', ROOT / 'runs')
        return result[:60]

    @app.get("/api/knowledge")
    def knowledge():
        return {"status": "pending_review", "items": [
            {"title": "肢体不适时的跌倒预防", "source": "CDC Older Adult Fall Prevention", "url": "https://www.cdc.gov/falls/"},
            {"title": "头晕相关照护", "source": "MedlinePlus Dizziness", "url": "https://medlineplus.gov/dizzinessandvertigo.html"},
        ], "note": "现有护理知识库中的来源条目；尚未审核为本工作台的处置规则。"}

    app.mount("/static", StaticFiles(directory=STATIC, check_dir=False), name="static")

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver", *(allowed_hosts or [])])
    return app

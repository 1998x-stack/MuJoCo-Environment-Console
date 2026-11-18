"""HTTP-only LAN console; terminate all simulation/training workers on shutdown."""
from __future__ import annotations

from contextlib import asynccontextmanager
import asyncio
import os
import secrets
import threading
import time
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.catalog import discover, get_env
from app.jobs import JobManager, fingerprint, RUNS
from app.sessions import SessionManager

STATIC = Path(__file__).parent / 'static'
MJPEG_BOUNDARY = 'frame'
PASSWORD = os.getenv('MUJOCO_CONSOLE_PASSWORD', '')
LOGIN_TTL = 12 * 3600
COOKIE_SECURE = os.getenv('COOKIE_SECURE', '0').strip().lower() in ('1', 'true', 'yes')
LOGIN_MAX_ATTEMPTS = max(3, int(os.getenv('LOGIN_MAX_ATTEMPTS', '8')))
LOGIN_WINDOW_SECONDS = max(30, int(os.getenv('LOGIN_WINDOW_SECONDS', '300')))
AUTH = {}
LOGIN_FAILURES = {}
AUTH_LOCK = threading.RLock()
manager = SessionManager(
    limit=int(os.getenv('MAX_VIEWERS', '3')),
    idle_seconds=int(os.getenv('SESSION_IDLE_SECONDS', '900')),
)
jobs = JobManager()


@asynccontextmanager
async def lifespan(_app):
    jobs.start_accepting()
    manager.start_reaper()
    try:
        yield
    finally:
        try:
            jobs.stop_all()
        finally:
            try:
                manager.stop_all()
            finally:
                with AUTH_LOCK:
                    AUTH.clear()


app = FastAPI(title='MuJoCo Environment Console', docs_url=None, redoc_url=None, lifespan=lifespan)


class Credentials(BaseModel):
    password: str = Field(min_length=1, max_length=1024)


class StartSession(BaseModel):
    env_id: str


class Command(BaseModel):
    mode: str
    run_id: str | None = None


class Pause(BaseModel):
    paused: bool


class StartTraining(BaseModel):
    env_id: str
    algorithm: str
    timesteps: int = Field(ge=1000, le=5000000)


@app.middleware('http')
async def secure_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; img-src 'self' data:; style-src 'self'; "
        "script-src 'self'; connect-src 'self'; object-src 'none'; frame-ancestors 'none'"
    )
    return response


def authenticated(request: Request):
    token = request.cookies.get('mujoco_session', '')
    now = time.monotonic()
    with AUTH_LOCK:
        expiry = AUTH.get(token)
        if expiry is None or expiry <= now:
            AUTH.pop(token, None)
            raise HTTPException(status_code=401, detail='Authentication required')
    return True


def _prune_auth(now):
    for token, expiry in list(AUTH.items()):
        if expiry <= now:
            AUTH.pop(token, None)


def _prune_login_failures(now):
    for ip, failures in list(LOGIN_FAILURES.items()):
        recent = [stamp for stamp in failures if now - stamp < LOGIN_WINDOW_SECONDS]
        if recent:
            LOGIN_FAILURES[ip] = recent
        else:
            LOGIN_FAILURES.pop(ip, None)


def badrequest(exc):
    if isinstance(exc, KeyError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    raise HTTPException(status_code=400, detail=str(exc)) from exc


def mjpeg_part(jpeg):
    """Encode one JPEG as an RFC 2046 multipart body part.

    The part must be terminated by a real CRLF; the delimiter line that follows it is
    ``--frame``. Emitting an escaped ``b'\\r\\n'`` literal instead of CRLF makes the stream
    unparseable for spec-conformant clients (ffmpeg, OpenCV, VLC), even though lenient
    browser MJPEG parsers still recover the frames.
    """
    return (
        b'--' + MJPEG_BOUNDARY.encode()
        + b'\r\nContent-Type: image/jpeg\r\nContent-Length: '
        + str(len(jpeg)).encode() + b'\r\n\r\n' + jpeg + b'\r\n'
    )


@app.get('/')
def root():
    return FileResponse(STATIC / 'index.html')


@app.get('/app.css')
def css():
    return FileResponse(STATIC / 'app.css', media_type='text/css')


@app.get('/app.js')
def javascript():
    return FileResponse(STATIC / 'app.js', media_type='application/javascript')


@app.get('/healthz')
def health():
    return {'ok': True, 'service': 'mujoco-console'}


@app.post('/api/login')
def login(values: Credentials, request: Request, response: Response):
    if not PASSWORD:
        raise HTTPException(status_code=503, detail='Set MUJOCO_CONSOLE_PASSWORD on the server')
    client_ip = request.client.host if request.client else 'unknown'
    now = time.monotonic()
    with AUTH_LOCK:
        _prune_auth(now)
        _prune_login_failures(now)
        failures = LOGIN_FAILURES.get(client_ip, [])
        if len(failures) >= LOGIN_MAX_ATTEMPTS:
            raise HTTPException(status_code=429, detail='Too many failed login attempts; try again later')
        if not secrets.compare_digest(values.password, PASSWORD):
            LOGIN_FAILURES[client_ip] = failures + [now]
            raise HTTPException(status_code=401, detail='Incorrect password')
        LOGIN_FAILURES.pop(client_ip, None)
        key = secrets.token_urlsafe(32)
        AUTH[key] = now + LOGIN_TTL
    response.set_cookie(
        'mujoco_session', key, httponly=True, secure=COOKIE_SECURE,
        samesite='strict', max_age=LOGIN_TTL, path='/',
    )
    return {'ok': True}


@app.post('/api/logout')
def logout(request: Request, response: Response, _: bool = Depends(authenticated)):
    with AUTH_LOCK:
        AUTH.pop(request.cookies.get('mujoco_session', ''), None)
    response.delete_cookie('mujoco_session', path='/')
    return {'ok': True}


@app.get('/api/me')
def me(_: bool = Depends(authenticated)):
    return {'ok': True}


@app.get('/api/catalog')
def catalog(_: bool = Depends(authenticated)):
    return {'environments': discover()}


@app.post('/api/sessions')
def new_session(values: StartSession, _: bool = Depends(authenticated)):
    try:
        descriptor = get_env(values.env_id)
        session = manager.start(descriptor)
        return session.status()
    except (KeyError, ValueError) as exc:
        badrequest(exc)


@app.get('/api/sessions/{sid}')
def session_status(sid: str, _: bool = Depends(authenticated)):
    try:
        return manager.get(sid).status()
    except KeyError as exc:
        badrequest(exc)


@app.post('/api/sessions/{sid}/stop')
def session_stop(sid: str, _: bool = Depends(authenticated)):
    manager.stop(sid)
    return {'stopped': True}


@app.post('/api/sessions/{sid}/reset')
def session_reset(sid: str, _: bool = Depends(authenticated)):
    try:
        manager.get(sid).command({'op': 'reset'})
        return {'ok': True}
    except (KeyError, ValueError) as exc:
        badrequest(exc)


@app.post('/api/sessions/{sid}/pause')
def session_pause(sid: str, values: Pause, _: bool = Depends(authenticated)):
    try:
        manager.get(sid).command({'op': 'pause', 'value': values.paused})
        return {'ok': True}
    except (KeyError, ValueError) as exc:
        badrequest(exc)


@app.post('/api/sessions/{sid}/driver')
def session_driver(sid: str, values: Command, _: bool = Depends(authenticated)):
    try:
        session = manager.get(sid)
        if values.mode == 'random':
            session.command({'op': 'random'})
        elif values.mode == 'policy' and values.run_id:
            descriptor = get_env(session.env_id)
            folder, run = jobs.model(values.run_id, session.env_id, fingerprint(descriptor))
            session.command({'op': 'policy', 'run_dir': str(folder), 'algorithm': run['algorithm']})
        else:
            raise ValueError('Select random or a completed policy model')
        return {'ok': True}
    except (ValueError, KeyError) as exc:
        badrequest(exc)


@app.get('/api/sessions/{sid}/stream')
async def session_stream(sid: str, _: bool = Depends(authenticated)):
    try:
        session = manager.get(sid)
    except KeyError as exc:
        badrequest(exc)

    async def gen():
        seq = 0
        while True:
            next_seq, jpeg = await asyncio.to_thread(session.wait_frame, seq, 3)
            if next_seq > seq and jpeg:
                seq = next_seq
                yield mjpeg_part(jpeg)
            elif not session.process.is_alive() or session._closed:
                return

    return StreamingResponse(
        gen(), media_type=f'multipart/x-mixed-replace; boundary={MJPEG_BOUNDARY}'
    )


@app.post('/api/training')
def training_start(values: StartTraining, _: bool = Depends(authenticated)):
    try:
        descriptor = get_env(values.env_id)
        if not descriptor.get('trainable', True):
            raise ValueError('This environment is a visual scene without a defined trainable task')
        return jobs.start(descriptor, values.algorithm, values.timesteps)
    except (ValueError, KeyError) as exc:
        badrequest(exc)


@app.get('/api/training')
def training_list(_: bool = Depends(authenticated)):
    return {'runs': jobs.list()}


@app.get('/api/training/{run_id}/log')
def training_log(run_id: str, _: bool = Depends(authenticated)):
    try:
        jobs.get(run_id)
        file = RUNS / run_id / 'output.log'
        if not file.is_file():
            return {'text': ''}
        with file.open('rb') as fp:
            fp.seek(0, 2)
            fp.seek(max(0, fp.tell() - 16000))
            return {'text': fp.read().decode('utf8', errors='replace')}
    except KeyError as exc:
        badrequest(exc)


@app.post('/api/training/{run_id}/cancel')
def training_cancel(run_id: str, _: bool = Depends(authenticated)):
    try:
        return jobs.cancel(run_id)
    except (KeyError, ValueError) as exc:
        badrequest(exc)

from __future__ import annotations

import multiprocessing as mp
import os
import queue
import threading
import time
import uuid

from app.worker import run_worker

VIEWER_FPS_DEFAULT = 12
VIEWER_WIDTH_DEFAULT = 640
VIEWER_HEIGHT_DEFAULT = 480
VIEWER_FPS_RANGE = (1, 60)
VIEWER_SIZE_RANGE = (64, 1920)


def _bounded(value, default, low, high):
    """Parse an env-style string into an int inside [low, high], falling back to the default."""
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return min(high, max(low, parsed))


def viewer_config(fps=None, width=None, height=None):
    """Resolve viewer frame rate and render size from explicit values or the environment."""
    return {
        'fps': _bounded(fps if fps is not None else os.getenv('VIEWER_FPS'),
                        VIEWER_FPS_DEFAULT, *VIEWER_FPS_RANGE),
        'width': _bounded(width if width is not None else os.getenv('VIEWER_WIDTH'),
                          VIEWER_WIDTH_DEFAULT, *VIEWER_SIZE_RANGE),
        'height': _bounded(height if height is not None else os.getenv('VIEWER_HEIGHT'),
                           VIEWER_HEIGHT_DEFAULT, *VIEWER_SIZE_RANGE),
    }


class ViewerSession:
    """One simulation process plus its frame/state plumbing.

    Frames are only produced while at least one consumer is *subscribed*: call
    :meth:`subscribe` before reading frames (the MJPEG endpoint does this for every connected
    browser) and :meth:`unsubscribe` when done. Without a subscriber the worker still steps
    the physics and reports state, but it never creates the software rasteriser, which is what
    keeps abandoned sessions from consuming whole cores.
    """

    def __init__(self, descriptor, fps=12, width=640, height=480, ctx=None):
        self.id = uuid.uuid4().hex
        self.env_id = descriptor['id']
        self.fps = fps
        self.width = width
        self.height = height
        self.created = time.monotonic()
        self.last_seen = self.created
        self._lock = threading.RLock()
        self._changed = threading.Condition(self._lock)
        self._frame = None
        self._frame_seq = 0
        self._subscribers = 0
        self._status = {'state': 'starting', 'mode': 'random', 'paused': False, 'render': False,
                        'steps': 0, 'episodes': 0, 'reward': 0.0, 'error': None}
        ctx = ctx if ctx is not None else mp.get_context('spawn')
        self.commands = ctx.Queue(maxsize=16)
        self.frames = ctx.Queue(maxsize=2)
        self.states = ctx.Queue(maxsize=32)
        self.process = ctx.Process(
            target=run_worker,
            args=(descriptor, self.commands, self.frames, self.states, fps, width, height),
            daemon=True,
        )
        self._closed = False
        self.process.start()
        self._reader = threading.Thread(target=self._receive, name='viewer-' + self.id[:8], daemon=True)
        self._reader.start()

    def _receive(self):
        while not self._closed:
            try:
                raw = self.frames.get(timeout=0.15)
                with self._changed:
                    self._frame = raw
                    self._frame_seq += 1
                    self._changed.notify_all()
            except queue.Empty:
                pass
            except (ValueError, OSError, EOFError):
                break
            while True:
                try:
                    message = self.states.get_nowait()
                except queue.Empty:
                    break
                except (ValueError, OSError, EOFError):
                    break
                with self._changed:
                    self._status.update(message)
                    self._changed.notify_all()
            if not self.process.is_alive():
                with self._changed:
                    if self._status['state'] not in ('error', 'stopped'):
                        self._status.update({'state': 'error', 'error': 'Simulation worker exited'})
                    self._changed.notify_all()
                break

    def touch(self):
        self.last_seen = time.monotonic()

    def subscribe(self):
        """Register a MJPEG client. Rendering starts on the first subscriber."""
        self.touch()
        with self._lock:
            self._subscribers += 1
            active = self._subscribers
        if active == 1:
            self._set_render(True)
        return active

    def unsubscribe(self):
        """Drop a MJPEG client. Rendering stops once the last one leaves."""
        self.touch()
        with self._lock:
            self._subscribers = max(0, self._subscribers - 1)
            active = self._subscribers
        if active == 0:
            self._set_render(False)
        return active

    def _set_render(self, value):
        # A worker that has already exited must not turn a client disconnect into an error.
        try:
            self.command({'op': 'render', 'value': bool(value)})
        except ValueError:
            pass

    def status(self):
        self.touch()
        with self._lock:
            return {'id': self.id, 'env_id': self.env_id, 'alive': self.process.is_alive(),
                    'subscribers': self._subscribers, 'fps': self.fps,
                    'width': self.width, 'height': self.height, **self._status}

    def command(self, cmd):
        self.touch()
        if not self.process.is_alive():
            raise ValueError('Simulation worker is not running')
        try:
            self.commands.put_nowait(cmd)
        except queue.Full as exc:
            raise ValueError('Command queue full') from exc

    def wait_frame(self, seq, timeout=5):
        self.touch()
        with self._changed:
            self._changed.wait_for(
                lambda: self._frame_seq > seq or self._closed or not self.process.is_alive(),
                timeout=timeout,
            )
            return self._frame_seq, self._frame

    def close(self):
        with self._changed:
            if self._closed:
                return
            self._closed = True
            self._subscribers = 0
            self._changed.notify_all()
        try:
            self.commands.put_nowait({'op': 'stop'})
        except (queue.Full, ValueError):
            pass
        self.process.join(timeout=2)
        if self.process.is_alive():
            self.process.terminate()
            self.process.join(timeout=2)
        if self.process.is_alive():
            self.process.kill()
            self.process.join(timeout=1)
        if self._reader.is_alive() and threading.current_thread() is not self._reader:
            self._reader.join(timeout=1)
        with self._changed:
            self._status['state'] = 'stopped'
            self._changed.notify_all()
        for q in (self.commands, self.frames, self.states):
            try:
                q.close()
                q.cancel_join_thread()
            except (ValueError, OSError):
                pass


class SessionManager:
    def __init__(self, limit=4, idle_seconds=900, fps=None, width=None, height=None):
        self.sessions = {}
        self.limit = max(1, int(limit))
        self.idle_seconds = max(1, int(idle_seconds))
        self.viewer = viewer_config(fps, width, height)
        self.lock = threading.RLock()
        self._stop_event = threading.Event()
        self._reaper = None

    def start_reaper(self):
        with self.lock:
            if self._reaper is not None and self._reaper.is_alive():
                return
            self._stop_event.clear()
            self._reaper = threading.Thread(target=self._reap_loop, name='viewer-session-reaper', daemon=True)
            self._reaper.start()

    def _reap_loop(self):
        interval = min(30.0, max(1.0, self.idle_seconds / 3))
        while not self._stop_event.wait(interval):
            try:
                self.cleanup()
            except Exception:
                # A single failed close must not permanently stop idle-session cleanup.
                continue

    def cleanup(self):
        now = time.monotonic()
        with self.lock:
            stale_ids = [
                sid for sid, session in self.sessions.items()
                if now - session.last_seen > self.idle_seconds
            ]
            stale = [self.sessions.pop(sid) for sid in stale_ids]
        for session in stale:
            try:
                session.close()
            except Exception:
                continue

    def start(self, descriptor):
        self.cleanup()
        with self.lock:
            if len(self.sessions) >= self.limit:
                raise ValueError(f'Viewer limit reached ({self.limit}); stop an existing session')
            session = ViewerSession(descriptor, **self.viewer)
            self.sessions[session.id] = session
            return session

    def get(self, sid):
        with self.lock:
            session = self.sessions.get(sid)
        if session is None:
            raise KeyError('Viewer session not found')
        session.touch()
        return session

    def stop(self, sid):
        with self.lock:
            session = self.sessions.pop(sid, None)
        if session is not None:
            session.close()

    def stop_all(self):
        self._stop_event.set()
        reaper = self._reaper
        if reaper is not None and reaper.is_alive() and threading.current_thread() is not reaper:
            reaper.join(timeout=2)
        with self.lock:
            sessions = list(self.sessions.values())
            self.sessions.clear()
        for session in sessions:
            try:
                session.close()
            except Exception:
                continue

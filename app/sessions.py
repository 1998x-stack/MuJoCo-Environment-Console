from __future__ import annotations
import multiprocessing as mp
import queue
import threading
import time
import uuid
from app.worker import run_worker

class ViewerSession:
    def __init__(self, descriptor, fps=12, width=640, height=480):
        self.id = uuid.uuid4().hex
        self.env_id = descriptor['id']
        self.created = time.monotonic()
        self.last_seen = self.created
        self._lock = threading.RLock()
        self._changed = threading.Condition(self._lock)
        self._frame = None
        self._frame_seq = 0
        self._status = {'state': 'starting', 'mode': 'random', 'paused': False, 'steps': 0,
                        'episodes': 0, 'reward': 0.0, 'error': None}
        ctx = mp.get_context('spawn')
        self.commands = ctx.Queue(maxsize=16)
        self.frames = ctx.Queue(maxsize=2)
        self.states = ctx.Queue(maxsize=32)
        self.process = ctx.Process(target=run_worker,
                                   args=(descriptor, self.commands, self.frames, self.states,
                                         fps, width, height), daemon=True)
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

    def status(self):
        self.touch()
        with self._lock:
            return {'id': self.id, 'env_id': self.env_id, 'alive': self.process.is_alive(), **self._status}

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
            self._changed.wait_for(lambda: self._frame_seq > seq or self._closed or
                                   not self.process.is_alive(), timeout=timeout)
            return self._frame_seq, self._frame

    def close(self):
        if self._closed:
            return
        self._closed = True
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
        with self._changed:
            self._status['state'] = 'stopped'
            self._changed.notify_all()
        for q in (self.commands, self.frames, self.states):
            q.close()
            q.cancel_join_thread()

class SessionManager:
    def __init__(self, limit=4, idle_seconds=900):
        self.sessions = {}
        self.limit = limit
        self.idle_seconds = idle_seconds
        self.lock = threading.RLock()

    def cleanup(self):
        with self.lock:
            stale = [sid for sid, sess in self.sessions.items()
                     if time.monotonic() - sess.last_seen > self.idle_seconds]
            for sid in stale:
                self.sessions.pop(sid).close()

    def start(self, descriptor):
        self.cleanup()
        with self.lock:
            if len(self.sessions) >= self.limit:
                raise ValueError(f'Viewer limit reached ({self.limit}); stop an existing session')
            session = ViewerSession(descriptor)
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
        with self.lock:
            for sid in list(self.sessions):
                self.sessions.pop(sid).close()

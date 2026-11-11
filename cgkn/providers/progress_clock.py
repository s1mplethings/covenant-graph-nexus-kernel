"""Read-only observation of the existing budgeted call, never a retry authority.

SSE callbacks update memory only. One bounded writer per active request coalesces
snapshots; queries never write, start a process, reserve budget or open a socket.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re
import threading
import time
from datetime import datetime, timezone

TERMINAL = {'COMPLETED', 'FAILED', 'UNKNOWN', 'CANCELLED', 'BLOCKED', 'STALLED'}


def key(value):
    return hashlib.sha256(str(value).encode()).hexdigest()


def timestamp(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


def process_identity():
    import psutil
    return psutil.Process().create_time()


class ProgressClock:
    def __init__(self, root, *, identity, call_id, job_id, attempt_id, provider,
                 model, phase, gateway_state=None, initial=180, idle=120,
                 monotonic=time.monotonic, wall=time.time, interval=1, stages=None):
        self.root = Path(root)
        self.path = self.root / key(job_id) / (key(call_id) + '.json')
        self.clock, self.wall = monotonic, wall
        self.begin = monotonic()
        self.submitted = self.last = None
        self.lock = threading.Lock()
        self.write_lock = threading.Lock()
        self.stop = threading.Event()
        self.changed = threading.Event()
        self.interval = max(1, interval)
        now = wall()
        self.row = dict(schema_version='1.0', request_identity=identity, call_id=call_id,
            job_id=job_id, attempt_id=attempt_id, provider=provider, model=model,
            phase=phase, status='QUEUED', started_at=timestamp(now), started_unix=now,
            first_meaningful_output_at=None, last_meaningful_output_at=None,
            last_meaningful_unix=None, meaningful_event_count=0, output_bytes=0,
            reasoning_char_count=0, heartbeat_count=0, upstream_http_status=None,
            gateway_session_id=None, finish_reason=None, usage_complete=False,
            error_type=None, submitted=False, initial_timeout=initial, idle_timeout=idle,
            transitions=[], stages=dict(stages or {}), _pid=os.getpid(), _process_created=process_identity(),
            _gateway_observed=bool(gateway_state))
        self.write_error = None
        self._save()  # establish observable intent before any POST
        self.writer = threading.Thread(target=self._write_loop, name='cgkn-progress-snapshot', daemon=True)
        self.writer.start()

    def _status(self, value):
        if self.row['status'] != value:
            self.row['status'] = value
            self.row['transitions'] = (self.row['transitions'] +
                [dict(status=value, at=timestamp(self.wall()))])[-32:]
            self.changed.set()

    def observe(self, event):
        with self.lock:
            if self.row['status'] in TERMINAL:
                return
            phase = event.get('phase')
            if phase in ('queued','connecting','gateway_started','submitted','upstream_headers','completing','result_saved'):
                self.row['stages'].setdefault(phase, dict(utc_unix=self.wall(),monotonic=self.clock(),pid=os.getpid()))
            if event.get('session_id'):
                self.row['gateway_session_id'] = event['session_id']
            if event.get('requested_model'):
                self.row['model'] = event['requested_model']
            if phase == 'queued':
                self._status('QUEUED')
            elif phase in ('connecting', 'gateway_started'):
                self._status('CONNECTING')
            elif phase == 'submitted' and self.submitted is None:
                self.submitted = self.clock() - max(0, event.get('age', 0))
                self.row.update(submitted=True, submitted_unix=self.wall()-max(0,event.get('age',0)),
                    initial_timeout=event.get('initial_timeout', self.row['initial_timeout']),
                    idle_timeout=event.get('idle_timeout', self.row['idle_timeout']))
                self._status('WAITING_FIRST_OUTPUT')
            if event.get('upstream_http_status') is not None:
                self.row['upstream_http_status'] = event['upstream_http_status']
            self.row['heartbeat_count'] = max(self.row['heartbeat_count'], event.get('heartbeat_count', 0))
            if 'text_bytes' in event:self.row['output_bytes'] = event['text_bytes']
            if 'reasoning_chars' in event:self.row['reasoning_char_count'] = event['reasoning_chars']
            count = event.get('meaningful_events', 0)
            if count > self.row['meaningful_event_count']:
                age = max(0, event.get('age', 0))
                self.last = self.clock() - age
                at = self.wall() - age
                self.row.update(meaningful_event_count=count, last_meaningful_unix=at,
                    last_meaningful_output_at=timestamp(at),
                    output_bytes=event.get('text_bytes', self.row['output_bytes']),
                    reasoning_char_count=event.get('reasoning_chars', self.row['reasoning_char_count']))
                if self.row['first_meaningful_output_at'] is None:
                    self.row['first_meaningful_output_at'] = timestamp(at)
                self._status('GENERATING')
            if phase == 'completing':
                self._status('COMPLETING')

    def snapshot(self):
        with self.lock:
            row = json.loads(json.dumps(self.row))
            row.update(updated_unix=self.wall(), elapsed_seconds=max(0, self.clock()-self.begin))
            origin = self.last if self.last is not None else self.submitted
            row['seconds_since_meaningful_output'] = max(0, self.clock()-origin) if origin is not None else 0
            if row['status'] == 'GENERATING' and row['seconds_since_meaningful_output'] > 1:
                row['status'] = 'IDLE_WAITING'
            row['persistence_error'] = self.write_error
            return row

    def _save(self):
        with self.write_lock:
            row = self.snapshot()
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix('.tmp')
            temporary.write_text(json.dumps(row, ensure_ascii=False), encoding='utf-8')
            # Windows readers may briefly hold a non-delete-sharing handle.
            # Retry only the observation write, never the Provider request.
            for attempt in range(10):
                try:
                    os.replace(temporary, self.path)
                    return
                except PermissionError:
                    if attempt == 9:raise
                    time.sleep(.01)

    def _write_loop(self):
        while not self.stop.is_set():
            self.changed.wait(self.interval)
            self.changed.clear()
            if self.stop.is_set():break
            try:
                self._save()
            except OSError:
                self.write_error = 'PROGRESS_SNAPSHOT_WRITE_FAILED'

    def finish(self, status, *, error=None, response=None):
        with self.lock:
            self._status(status)
            # Bounded identifiers only, never arbitrary exception messages.
            self.row['error_type'] = error if error and re.fullmatch(r'[A-Za-z0-9_]{1,100}', error) else None
            if response:
                route = response.get('cgkn_model_identity') or {}
                if not isinstance(route, dict):route = {}
                self.row['actual_model'] = route.get('actual_model') or response.get('model')
                choices = response.get('choices') or [{}]
                choice = choices[0] if isinstance(choices,list) and isinstance(choices[0],dict) else {}
                self.row['finish_reason'] = choice.get('finish_reason') or response.get('status')
                usage = response.get('usage') or {}
                if not isinstance(usage,dict):usage={}
                self.row['usage_complete'] = all(type(usage.get(k, usage.get(other))) is int
                    for k, other in [('prompt_tokens','input_tokens'), ('completion_tokens','output_tokens')])
            self.row['ended_unix'] = self.wall()
        self.stop.set()
        self.changed.set()
        self.writer.join(timeout=2)
        if not self.writer.is_alive():
            try:
                self._save()
            except OSError:
                self.write_error = 'PROGRESS_SNAPSHOT_WRITE_FAILED'


def read_progress(root, job_id, *, attempt_id=None, now=None, gateway_state=None):
    """Pure local read. Stale observations become UNKNOWN, never retryable work."""
    import psutil
    now = time.time() if now is None else now
    rows = []
    for path in sorted((Path(root) / key(job_id)).glob('*.json')):
        if path.stat().st_size > 65536:
            raise ValueError('PROGRESS_SNAPSHOT_TOO_LARGE')
        for read_attempt in range(10):
            try:
                row = json.loads(path.read_text(encoding='utf-8'))
                break
            except PermissionError:
                if read_attempt == 9:raise ValueError('PROGRESS_SNAPSHOT_READ_UNAVAILABLE') from None
                time.sleep(.01)
        if row['job_id'] != job_id or (attempt_id is not None and row['attempt_id'] != attempt_id):
            continue
        if row['status'] not in TERMINAL:
            try:
                alive = abs(psutil.Process(row['_pid']).create_time()-row['_process_created']) < .001
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                alive = False
            gateway_changed = False
            if row.get('_gateway_observed') and row.get('gateway_session_id'):
                try:
                    if gateway_state is None:
                        from .application_network import settings
                        configured = settings()
                        current_state = configured.get('gateway_state_dir') if configured else None
                    else:
                        current_state = gateway_state
                    if not current_state:raise ValueError('GATEWAY_STATE_UNAVAILABLE')
                    state = json.loads((Path(current_state)/'status.json').read_text(encoding='utf-8'))
                    gateway_changed = state.get('session_id') != row['gateway_session_id'] or not state.get('running')
                except (OSError, ValueError, RuntimeError):
                    gateway_changed = True
            if not alive or gateway_changed or now-row['updated_unix'] > 5:
                row.update(status='UNKNOWN', observation_error='OWNER_OR_SESSION_NOT_CURRENT')
            else:
                origin = row.get('last_meaningful_unix') or row.get('submitted_unix')
                age = max(0, now-origin) if origin else 0
                row['seconds_since_meaningful_output'] = age
                row['elapsed_seconds'] = max(0, now-row['started_unix'])
                if row['status'] not in ('COMPLETING', 'QUEUED', 'CONNECTING'):
                    limit = row['idle_timeout'] if row['meaningful_event_count'] else row['initial_timeout']
                    if age >= limit:
                        row['status'] = 'STALLED'
                    elif row['meaningful_event_count'] and age > 1:
                        row['status'] = 'IDLE_WAITING'
        rows.append({k:v for k,v in row.items() if not k.startswith('_')})
    return dict(job_id=job_id, calls=rows, found=bool(rows), read_only=True,
                generation_posts=0, status='RUNNING' if any(r['status'] not in TERMINAL for r in rows) else 'TERMINAL' if rows else 'NOT_OBSERVED')

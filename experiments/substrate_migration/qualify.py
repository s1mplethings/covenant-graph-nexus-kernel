"""Offline substrate experiments; never imported by the production runtime."""
from __future__ import annotations

import concurrent.futures
from contextlib import closing
import json
import pathlib
import sqlite3
import tempfile
import time


def reserve(database, identity):
    with closing(sqlite3.connect(database, timeout=10)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        if db.execute('SELECT 1 FROM calls WHERE id=?', (identity,)).fetchone():
            return False
        if db.execute('SELECT count(*) FROM calls').fetchone()[0] >= 7:
            return False
        db.execute('INSERT INTO calls VALUES (?, ?, ?)', (identity, 'RESERVED', 1))
        return True


def sqlite_trial(root):
    database = str(root / 'trial.sqlite')
    with closing(sqlite3.connect(database)) as db, db:
        assert db.execute('PRAGMA journal_mode=WAL').fetchone()[0] == 'wal'
        db.execute('CREATE TABLE calls(id TEXT PRIMARY KEY, state TEXT NOT NULL, cost INTEGER NOT NULL CHECK(cost>=0))')
        db.execute('PRAGMA user_version=1')
    with concurrent.futures.ProcessPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(reserve, [database] * 24, map(str, range(24))))
    assert sum(results) == 7
    with closing(sqlite3.connect(database)) as db, db:
        identity = db.execute('SELECT id FROM calls LIMIT 1').fetchone()[0]
    assert not reserve(database, identity)
    try:
        with closing(sqlite3.connect(database)) as db, db:
            db.execute("UPDATE calls SET state='REQUEST_STARTED'")
            raise RuntimeError('transaction fault')
    except RuntimeError:
        pass
    with closing(sqlite3.connect(database)) as db, db:
        assert db.execute("SELECT count(*) FROM calls WHERE state='RESERVED'").fetchone()[0] == 7
        db.execute("UPDATE calls SET state='INTERRUPTED_UNKNOWN' WHERE id=?", (identity,))
    with closing(sqlite3.connect(database)) as db, db:
        assert db.execute('SELECT state FROM calls WHERE id=?', (identity,)).fetchone()[0] == 'INTERRUPTED_UNKNOWN'
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    return {'status': 'PASS', 'checks': ['WAL', 'multiprocess_budget', 'duplicate_identity', 'rollback', 'restart_unknown', 'integrity'], 'scope': 'isolated prototype; no production ledger migration'}


def main():
    started = time.perf_counter()
    with tempfile.TemporaryDirectory() as directory:
        results = {'sqlite': sqlite_trial(pathlib.Path(directory))}
    results['seconds'] = time.perf_counter() - started
    output = pathlib.Path('artifacts/substrate-migration/sqlite-trial.json')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(results, indent=2), encoding='utf-8')
    print(json.dumps(results))


if __name__ == '__main__':
    main()

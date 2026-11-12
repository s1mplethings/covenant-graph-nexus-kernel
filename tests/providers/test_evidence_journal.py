import json
import logging
from concurrent.futures import ThreadPoolExecutor

import pytest

from cgkn.providers.evidence_journal import EvidenceJournal
from scripts.product_direction_gate import has_active_content


def record(value):
    return logging.LogRecord('test', logging.INFO, '', 0, json.dumps(value), (), None)


@pytest.mark.boundary
@pytest.mark.happy_path
def test_retains_beyond_old_rotation_limit_and_reopen(tmp_path):
    path = tmp_path / 'events.jsonl'
    handler = EvidenceJournal(path)
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda n: handler.emit(record({'id': n, 'body': 'x' * 600000})), range(10)))
    handler.close()
    handler = EvidenceJournal(path)
    handler.emit(record({'id': 10}))
    handler.close()
    rows = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
    assert sorted(row['id'] for row in rows) == list(range(11))
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.boundary
@pytest.mark.negative
def test_write_failure_is_not_silently_accepted(tmp_path, monkeypatch):
    handler = EvidenceJournal(tmp_path / 'events.jsonl')
    def fail(_):
        raise OSError('disk unavailable')
    monkeypatch.setattr(handler.stream, 'write', fail)
    with pytest.raises(OSError, match='disk unavailable'):
        handler.emit(record({'id': 1}))
    handler.close()


def test_gate_distinguishes_cache_from_implementation(tmp_path):
    cache = tmp_path / 'pkg' / '__pycache__'
    cache.mkdir(parents=True)
    (cache / 'old.cpython-313.pyc').write_bytes(b'old')
    assert not has_active_content(tmp_path)
    for path in (tmp_path / 'old.pyc', cache / 'hidden.py', tmp_path / 'README.md'):
        path.write_text('active', encoding='utf-8')
        assert has_active_content(tmp_path)
        path.unlink()

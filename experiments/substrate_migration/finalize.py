"""Seal local review material; never stage, commit, publish, or alter the source tree."""
import difflib
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('D:/CGKN')
OUT = ROOT / 'artifacts/substrate-migration'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write(name, value):
    (OUT / name).write_text(json.dumps(value, indent=2), encoding='utf-8')


def main():
    xml = OUT / 'regression.xml'
    start = json.loads((OUT / 'final-run-start.json').read_text(encoding='utf-8'))
    if xml.stat().st_mtime < start['started_epoch']:
        raise RuntimeError('Final regression is not completed')
    tree = ET.parse(xml)  # Complete XML required before touching logs.
    secrets = set()
    for case in tree.findall('.//testcase'):
        if any(name in case.get('classname', '') for name in
               ('test_provider_credentials', 'test_qwen_provider_alignment')):
            for node in list(case):
                secrets.update(re.findall(r'\+\s+([A-Za-z0-9_-]{24,})',
                                          node.get('message', '') + (node.text or '')))
    receipt = []
    for path in (xml, OUT / 'regression.log'):
        before = path.read_bytes()
        text = before.decode('utf-8')
        for value in secrets:
            text = text.replace(value, '[REDACTED_CREDENTIAL_ASSERTION]')
        if secrets:
            path.write_text(text, encoding='utf-8')
        receipt.append({'file': path.name, 'before_sha256': sha(before),
                        'after_sha256': sha(path.read_bytes())})
    if secrets or not (OUT / 'regression-redaction-receipt.json').exists():
        write('regression-redaction-receipt.json', {'redacted_values': len(secrets), 'files': receipt})

    snapshots = json.loads((OUT / 'baseline/source-snapshot.json').read_text(encoding='utf-8'))
    changed = []
    for row in snapshots:
        path = SOURCE / row['path']
        actual = sha(path.read_bytes()) if path.is_file() else None
        if actual != row['sha256']:
            changed.append({'path': row['path'], 'expected': row['sha256'], 'actual': actual})
    write('original-tree-verification.json', {'checked_files': len(snapshots),
          'differences': changed, 'scope': 'original tracked/nonignored snapshot files; no source writes'})

    paths = ['.gitignore', 'scripts/customer_runtime_runner.py',
             'tests/test_agent_conversation_mainline.py', 'tests/test_owned_runtime_processes.py']
    paths += [p.relative_to(ROOT).as_posix() for p in (ROOT / 'tools/substrate').iterdir() if p.is_file()]
    paths += [p.relative_to(ROOT).as_posix() for p in (ROOT / 'experiments/substrate_migration').glob('*.py')]
    rows, patch = [], []
    for rel in sorted(paths):
        old = (SOURCE / rel).read_bytes() if (SOURCE / rel).exists() else None
        new = (ROOT / rel).read_bytes()
        if old == new:
            continue
        rows.append({'path': rel, 'baseline_sha256': sha(old) if old is not None else None,
                     'sha256': sha(new)})
        patch.extend(difflib.unified_diff((old or b'').decode('utf-8').splitlines(True),
                     new.decode('utf-8').splitlines(True), fromfile='a/' + rel if old is not None else '/dev/null',
                     tofile='b/' + rel))
    (OUT / 'task-only.patch').write_text(''.join(patch), encoding='utf-8', newline='\n')
    write('task-change-inventory.json', {'kind': 'TaskChangeInventory',
          'publication_authority': False, 'files': rows})
    print(json.dumps({'original_files_checked': len(snapshots), 'original_differences': len(changed),
                      'task_files': len(rows), 'redacted_values': len(secrets)}))


if __name__ == '__main__':
    main()

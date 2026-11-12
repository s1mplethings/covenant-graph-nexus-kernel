"""Explicit hash-guarded CODE rollback only; does not alter running proxy/network."""
import argparse
import hashlib
import json
from pathlib import Path

def main():
    p=argparse.ArgumentParser();p.add_argument('--manifest',type=Path,required=True)
    p.add_argument('--apply',action='store_true');a=p.parse_args()
    doc=json.loads(a.manifest.read_text())
    for row in doc['restore']:
        for key,expected in [('target',row['current_sha256']),('backup',row['backup_sha256'])]:
            if hashlib.sha256(Path(row[key]).read_bytes()).hexdigest()!=expected:
                raise RuntimeError('HASH_CHANGED_REFUSE_ROLLBACK: '+row[key])
    if a.apply:
        for row in doc['restore']:Path(row['target']).write_bytes(Path(row['backup']).read_bytes())
    print('CODE_RESTORED; proxy unchanged' if a.apply else 'HASHES_VALID; no writes; proxy unchanged')

if __name__=='__main__':main()

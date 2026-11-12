"""Controlled side-effect probe for exactly-once nested observation."""
from pathlib import Path
import json
import sys

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from cgkn.telemetry.lean import observed

root=ROOT/'artifacts/leanloop-v1'/sys.argv[1];root.mkdir(exist_ok=False)
@observed('inner',lambda a:root)
def inner():
    with (root/'effects.txt').open('a',encoding='utf-8') as handle:handle.write('effect\n')
    raise RuntimeError('UNKNOWN controlled local failure')

@observed('outer',lambda a:root)
def outer():return inner()

try:outer()
except RuntimeError:pass
result={'expected_calls':1,'actual_calls':len((root/'effects.txt').read_text().splitlines()),'real_API_calls':0}
(root/'evidence.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps(result))

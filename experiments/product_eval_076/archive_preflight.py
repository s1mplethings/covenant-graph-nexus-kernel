"""Archive this preflight through the historical canonical Corpus implementation.

Only reads the newly written entry when verifying. Never scans existing corpus.
"""
import hashlib
import importlib
import json
import pathlib
import sqlite3
import subprocess
import sys
import types

ROOT=pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
REV='feaf6c10ccac1a6f54175040e8c25f38d7ded40e'
out=pathlib.Path(sys.argv[1]).resolve()
corpus=pathlib.Path(sys.argv[2]).resolve()
if not (corpus/'corpus.json').is_file():
    raise SystemExit('Existing corpus marker required; refusing to create a parallel corpus')
module_dir=out/'canonical-corpus-source'
module_dir.mkdir(exist_ok=True)
source_hashes={}
for name in ('contracts.py','store.py'):
    raw=subprocess.check_output(['git','show',f'{REV}:cgkn/application/project_corpus/{name}'],cwd=ROOT)
    target=module_dir/name
    if target.exists() and target.read_bytes()!=raw:
        raise SystemExit('Historical source mismatch')
    target.write_bytes(raw)
    source_hashes[name]=hashlib.sha256(raw).hexdigest()
import cgkn.application
package=types.ModuleType('cgkn.application.project_corpus')
package.__path__=[str(module_dir)]
sys.modules[package.__name__]=package
store=importlib.import_module(package.__name__+'.store')
contracts=importlib.import_module(package.__name__+'.contracts')
status=json.loads((out/'status.json').read_text())
status.update(isolation_status='FAIL_EXISTING_COMMAND_EXECUTOR',hard_stop='PROTOCOL_INTEGRITY',formal_runs=0)
(out/'status.json').write_text(json.dumps(status,indent=2)+'\n',encoding='utf-8')
safe_files={name:(out/name).read_text(encoding='utf-8') for name in ('status.json','matrix.json')}
entry='entry-iter076-preflight-20261027'
receipt=store.ProjectCorpus(corpus).capture_attempt(
    family_id='iter076-evaluation-infrastructure',attempt_id='iter076-preflight-20261027',run_id='iter076-preflight-20261027',
    source_version=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
    generator_version='product-eval-076-preflight-v1',status='BLOCKED_POLICY',provenance='generated_original',
    public_packet={'goal':'Preflight for real product evaluation; no candidate or model execution','formal_runs':0,'isolation':'existing executor read synthetic external canary'},
    snapshots=[{'stage':'ABORTED','files':safe_files}],split='DEVELOPMENT',corpus_entry_id=entry,
    metadata={'record_kind':'EVALUATION_PREFLIGHT_NOT_PRODUCT_ATTEMPT','canonical_corpus_source':REV,'planned_formal_runs':32,'provider_calls':0},
    failures=[{'id':'ISO-001','classification':'ENVIRONMENT_FAILURE','description':'Existing CommandExecutor can read evaluator-created outside-workspace synthetic canary'}])
manifest_path=corpus/'manifests'/f'{entry}.json'
doc=json.loads(manifest_path.read_text())
snaps=[contracts.SnapshotManifest.from_dict(json.loads((corpus/'snapshots'/f"{ref['snapshot_id']}.json").read_text())) for ref in doc['snapshot_refs']]
validated=contracts.AttemptManifest.from_dict(doc,snapshots=snaps)
objects=0
for snap in snaps:
    for record in snap.files:
        digest=record.content_hash.removeprefix('sha256:')
        raw=(corpus/'objects'/digest[:2]/digest[2:]).read_bytes()
        assert hashlib.sha256(raw).hexdigest()==digest
        objects+=1
with sqlite3.connect(corpus/'catalog.sqlite3') as db:
    indexed=db.execute('SELECT entry_id FROM attempts WHERE entry_id=?',(entry,)).fetchone()
assert indexed and indexed[0]==entry
result={'receipt':receipt.as_dict(),'verification':'PASS_THIS_ENTRY_ONLY','objects_verified':objects,'canonical_source_hashes':source_hashes,'manifest_hash':validated.manifest_hash}
(out/'corpus-receipt.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
hashes={str(f.relative_to(out)):hashlib.sha256(f.read_bytes()).hexdigest() for f in out.rglob('*') if f.is_file() and f.name!='hashes.json' and '__pycache__' not in f.parts}
(out/'hashes.json').write_text(json.dumps(hashes,indent=2)+'\n',encoding='utf-8')
print(json.dumps(result))

"""Fail-closed admission for frozen benchmark artifacts, never a planner."""
import hashlib,json,pathlib

REQUIRED=('route_conformance','initial_snapshot_validation','reference_behavior','negative_variants','dev_calibration')
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def validate(path,run_id,route):
 p=pathlib.Path(path).resolve();seal=json.loads(p.read_text(encoding='utf-8'))
 if seal.get('status')!='FROZEN':raise RuntimeError('FORMAL_FREEZE_REQUIRED')
 for name in REQUIRED:
  item=seal.get('evidence',{}).get(name)
  if not item or item.get('status')!='PASS':raise RuntimeError('FORMAL_GATE_MISSING: '+name)
  if sha(pathlib.Path(item['path']))!=item['sha256']:raise RuntimeError('FORMAL_EVIDENCE_CHANGED: '+name)
 for file,digest in seal['source_hashes'].items():
  if sha(pathlib.Path(__file__).parent/file)!=digest:raise RuntimeError('FORMAL_SOURCE_CHANGED: '+file)
 for file,digest in seal['artifact_hashes'].items():
  if sha(pathlib.Path(file))!=digest:raise RuntimeError('FORMAL_ARTIFACT_CHANGED: '+file)
 matches=[r for r in seal['matrix'] if r['run_id']==run_id and r['route']==route]
 if len(matches)!=1:raise RuntimeError('FORMAL_RUN_NOT_REGISTERED')
 return seal,matches[0]

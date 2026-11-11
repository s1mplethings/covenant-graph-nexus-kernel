"""Append only ITER-076's own completed records to the existing Corpus."""
import argparse
import hashlib
import importlib
import json
import os
import pathlib
import sqlite3
import subprocess
import sys
import types
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[2]))
from experiments.product_eval_076_v8.isolation import verify_audit

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=pathlib.Path,required=True);p.add_argument('--corpus',type=pathlib.Path,required=True);p.add_argument('--output',type=pathlib.Path,required=True);args=p.parse_args()
    root=args.root.resolve();corpus=args.corpus.resolve();out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    if not (corpus/'corpus.json').exists():raise RuntimeError('Existing canonical corpus required')
    source=root/'preflight-20261027/canonical-corpus-source'
    expected={'contracts.py':'0b05c341dbe9b534d063a8993b27cc4cbd58b191f38c3d20121968104b9365ac','store.py':'ccf425647e874b495bb96bffb6b8fd7a6473c0364ae67a8fd9f7e74341a4fa21'}
    for name,h in expected.items():assert sha(source/name)==h
    import cgkn.application
    package=types.ModuleType('cgkn.application.project_corpus');package.__path__=[str(source)];sys.modules[package.__name__]=package
    store=importlib.import_module(package.__name__+'.store');contracts=importlib.import_module(package.__name__+'.contracts')
    version=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
    targets=[]
    for d in sorted(root.glob('dev-*')):
        if d.is_dir() and (d/'dev-result.json').is_file():targets.append((d,'dev-result.json','REAL_DEV'))
    for d in sorted(root.glob('conformance-*')):
        if d.is_dir():targets.append((d,'conformance.json','HARNESS_CONFORMANCE_ONLY'))
    for d in sorted(root.glob('media-check-*')):
        if (d/'media-check.json').exists():targets.append((d,'media-check.json','HARNESS_CONFORMANCE_ONLY'))
    for d in sorted(root.glob('dev-acceptance-*')):
        if d.is_dir() and (d/'acceptance.json').exists():targets.append((d,'acceptance.json','INDEPENDENT_DEV_ACCEPTANCE'))
    for d in sorted(root.glob('closeout-*')):
        if d.is_dir() and (d/'summary.json').exists():targets.append((d,'summary.json','EVALUATION_CLOSEOUT'))
    for d in sorted(root.glob('formal-v8/formal-*')):
        if (d/'formal-result.json').is_file():targets.append((d,'formal-result.json','FORMAL_PRODUCT_RUN'))
    for d in sorted(root.glob('protocol-v8-*')):
        if (d/'protocol-result.json').exists():targets.append((d,'protocol-result.json','REAL_PROTOCOL_CALIBRATION'))
    receipts=[]
    for d,result_name,kind in targets:
        entry='entry-iter076-'+d.name
        manifest_path=corpus/'manifests'/f'{entry}.json'
        evidence={};audits=[]
        # Enumerate only this evaluator-created run directory; never other corpus records.
        exclusions=[]
        for folder,dirs,names in os.walk(d,followlinks=False):
            # Candidate files are captured by freeze_candidate inside a restricted
            # reader container. Host archival never descends candidate workspaces.
            dirs[:]=[n for n in dirs if n not in {'workspace','__pycache__'} and not (pathlib.Path(folder)/n).is_symlink() and not (pathlib.Path(folder)/n).is_junction()]
            for name in names:
                path=pathlib.Path(folder)/name
                try:
                    if path.is_symlink() or path.is_junction() or not path.is_file():continue
                    evidence[str(path.relative_to(d)).replace('\\','/')]=sha(path)
                    if path.name=='audit.jsonl':audits.append(verify_audit(path))
                except OSError as e:exclusions.append({'path':str(path.relative_to(d)),'reason':type(e).__name__})
        result=json.loads((d/result_name).read_text(encoding='utf-8')) if (d/result_name).exists() else {'status':'EVALUATOR_INVALID','reason':'Harness assertion failed; retained raw audit'}
        end=result.get('receipt',{}).get('result',{})
        calls=result.get('calls',0) if kind in {'REAL_DEV','FORMAL_PRODUCT_RUN','REAL_PROTOCOL_CALIBRATION'} else 0
        actual_input=actual_output=unknown_usage=0;models=[]
        for path in (d/'provider').glob('*.result.json'):
            raw=json.loads(path.read_text(encoding='utf-8'));usage=raw.get('usage') or {}
            if raw.get('upstream_model'):models.append(raw['upstream_model'])
            i=usage.get('prompt_tokens');o=usage.get('completion_tokens')
            if isinstance(i,int) and isinstance(o,int):actual_input+=i;actual_output+=o
            else:unknown_usage+=1
        timeout='timed out' in end.get('error','').lower()
        status='TIMEOUT' if timeout else 'PARTIAL' if kind in {'REAL_DEV','FORMAL_PRODUCT_RUN','REAL_PROTOCOL_CALIBRATION','INDEPENDENT_DEV_ACCEPTANCE','EVALUATION_CLOSEOUT'} else 'PASS' if (d/result_name).exists() else 'ABORTED'
        acceptance_path=d/'acceptance/acceptance.json'
        acceptance=json.loads(acceptance_path.read_text(encoding='utf-8')) if acceptance_path.exists() else None
        formal_started=1 if kind=='FORMAL_PRODUCT_RUN' else 0
        summary={'record_kind':kind,'record_id':d.name,'source_version':version,'result':result,'actual_known_input_tokens':actual_input,'actual_known_output_tokens':actual_output,'unknown_usage_calls':unknown_usage,'actual_response_models':sorted(set(models)),'provider_requests':calls,'formal_started':formal_started,'product_acceptance':acceptance['status'] if acceptance else 'UNVERIFIED','acceptance':acceptance,'audit_checks':audits,'evidence_hashes':evidence,'linked_original_blocker':'entry-iter076-preflight-20261027','candidate_code_host_authored':False,'initial_scaffold_host_authored':kind=='FORMAL_PRODUCT_RUN'}
        summary_file=out/(d.name+'.json');summary_file.write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
        if not manifest_path.exists():
            receipt=store.ProjectCorpus(corpus).capture_attempt(family_id='iter076-'+('formal-'+acceptance['task_id'].split('-')[1] if acceptance else 'dev-promotion' if 'promo' in d.name else 'dev-video' if 'video' in d.name else 'infrastructure'),attempt_id='iter076-'+d.name,run_id='iter076-'+d.name,source_version=version,generator_version='iter076-isolation-v8',status=status,provenance='generated_original',public_packet={'goal':'Record retained ITER-076 '+kind,'formal_started':formal_started,'provider_requests':calls},snapshots=[{'stage':'ABORTED' if status in ('TIMEOUT','ABORTED') else 'POST_MATERIALIZATION','files':{'summary.json':json.dumps(summary,ensure_ascii=False,indent=2)}}],split='DEVELOPMENT',corpus_entry_id=entry,metadata={'record_kind':kind,'linked_original_blocker':'entry-iter076-preflight-20261027','not_product_success':True,'split_note':'Known product/source scenarios; no cross-project holdout claim'})
            receipt=receipt.as_dict()
        else:receipt={'status':'EXISTING_IMMUTABLE_ENTRY','corpus_entry_id':entry}
        doc=json.loads(manifest_path.read_text(encoding='utf-8'))
        snaps=[contracts.SnapshotManifest.from_dict(json.loads((corpus/'snapshots'/f"{ref['snapshot_id']}.json").read_text(encoding='utf-8'))) for ref in doc['snapshot_refs']]
        valid=contracts.AttemptManifest.from_dict(doc,snapshots=snaps)
        for snap in snaps:
            for item in snap.files:
                h=item.content_hash.removeprefix('sha256:');assert sha(corpus/'objects'/h[:2]/h[2:])==h
        with sqlite3.connect(corpus/'catalog.sqlite3') as db:assert db.execute('SELECT entry_id FROM attempts WHERE entry_id=?',(entry,)).fetchone()==(entry,)
        receipts.append({'receipt':receipt,'manifest_hash':valid.manifest_hash,'verification':'PASS_THIS_ENTRY_ONLY'})
    (out/'corpus-receipts.json').write_text(json.dumps(receipts,indent=2),encoding='utf-8');print(json.dumps(receipts,indent=2))

if __name__=='__main__':main()

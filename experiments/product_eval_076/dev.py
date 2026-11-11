"""Real Provider DEV through the conformance-checked shared route entrypoint."""
import argparse
import hashlib
import json
import pathlib
import sys
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[2]))
from experiments.product_eval_076.runner import run_route
from experiments.product_eval_076.live_provider import LiveClient
from experiments.product_eval_076.isolation import verify_audit
from scripts import provider_api_budget as budget

GOAL='''Build a working browser application for a local announcement draft notebook. This is a development calibration task, not a public publishing task. The raw evidence is in /input. Users must be able to create an announcement from those source facts, review and edit its text in the GUI, approve a specific version, and reopen the application to see saved drafts and approvals. Changing the approved text must require approval again. Do not assert facts absent from the evidence or publish externally. Supply your own meaningful automated tests and instructions for starting and operating the app. The deliverable is the files you create in /workspace. You must choose and perform all implementation and validation actions independently. A working GUI and persistent business state are required; a static page is insufficient.'''
EVIDENCE='''Calibration fixture: Meadow Club bulletin, October 2026.
Release 1.2 of the club lending register shipped on 2026-10-20.
It adds a due-date view and fixes a display bug for empty book titles.
The maintainer recorded 7 local tests passing on one laptop.
No large-scale deployment, user-growth result, accessibility audit or performance benchmark has been performed.
Next-month plans include multilingual labels; they are not shipped features.
This fixture is invented for independent DEV and makes no claim about CGKN.
'''
VIDEO_GOAL='''Build a working browser application for a small oral-history video collection. A new public-domain video is supplied in /input. Through the GUI a user must import the video, obtain a real speech transcription, search words in that transcription, jump to and preview a matching time, choose start/end times and export an actual playable clip. Saved media metadata, search positions and exported clips must survive closing and reopening the application. Invalid time ranges must be rejected without damaging prior work. Do not hard-code the transcript or use an externally supplied answer. Supply meaningful automated tests and user startup/operation instructions. Implement and validate independently in /workspace. This is an independent DEV calibration task, not a formal sample.'''

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',required=True,type=pathlib.Path);p.add_argument('--conformance',required=True,type=pathlib.Path);p.add_argument('--route',required=True,choices=['R_DIRECT','R_CGNK']);p.add_argument('--lab-root',required=True);p.add_argument('--ledger',required=True);p.add_argument('--run-id',required=True)
    p.add_argument('--domain',choices=['promotion','video'],default='promotion');p.add_argument('--media',type=pathlib.Path)
    p.add_argument('--honor-reasoning-none',action='store_true')
    p.add_argument('--run-cost-cap',type=float,default=10)
    args=p.parse_args()
    seal=json.loads(args.conformance.read_text())
    if seal['mode']!='HARNESS_CONFORMANCE_ONLY' or {r['route'] for r in seal['results'] if r['status']=='PASS'}!={'R_DIRECT','R_CGNK'}:raise RuntimeError('CONFORMANCE_REQUIRED')
    for name in ('isolation.py','routes.py','runner.py','browser.py','Dockerfile'):
        if hashlib.sha256((pathlib.Path(__file__).parent/name).read_bytes()).hexdigest()!=seal['source_hashes'][name]:raise RuntimeError('CONFORMANCE_SOURCE_CHANGED: '+name)
    # A continuation does not acquire another eight development attempts.
    ledger=pathlib.Path(args.ledger).resolve();admission=ledger.parent/'dev-admission.json'
    with budget._locked(admission):
        admitted=json.loads(admission.read_text(encoding='utf-8')) if admission.exists() else {'limit':8,'runs':[]}
        prior=json.loads(ledger.read_text(encoding='utf-8')) if ledger.exists() else {'calls':[]}
        known=set(admitted['runs'])|{c['run_id'] for c in prior['calls'] if c.get('run_id','').startswith('dev-')}
        if args.run_id in known:raise RuntimeError('DEV_RUN_ID_ALREADY_USED: create no duplicate or overwrite')
        if len(known)>=admitted['limit']:raise RuntimeError(f"DEV_LIMIT_EXHAUSTED: {admitted['limit']} authorized DEV runs already admitted")
        known.add(args.run_id);admitted['runs']=sorted(known)
        admission.write_text(json.dumps(admitted,indent=2),encoding='utf-8')
    root=args.output.resolve();root.mkdir(parents=True,exist_ok=False)
    if not 0<args.run_cost_cap<=10:raise ValueError('DEV cost cap outside authorized calibration range')
    client=LiveClient(args.lab_root,args.ledger,root/'provider',args.run_id,run_cap_cny=args.run_cost_cap,honor_reasoning_none=args.honor_reasoning_none)
    goal=GOAL if args.domain=='promotion' else VIDEO_GOAL
    inputs={'evidence.txt':EVIDENCE} if args.domain=='promotion' else {'video.mp4':args.media.read_bytes(),'environment.txt':'Offline media dependencies: ffmpeg, ffprobe, whisper-cli, model /opt/asr/ggml-tiny.en.bin. Use installed command help or package documentation. This file contains no transcript. Source: Wikimedia Commons John F. Kennedy Inauguration Speech.ogv; public-domain federal-government work. Input is a 75-second prepared excerpt; source and excerpt provenance retained by evaluator.'}
    (root/'public-task.json').write_text(json.dumps({'goal':goal,'input_hashes':{k:hashlib.sha256(v if isinstance(v,bytes) else v.encode()).hexdigest() for k,v in inputs.items()},'kind':'DEV','lineage':'meadow-club-dev' if args.domain=='promotion' else 'oral-history-dev','not_formal':True},ensure_ascii=False,indent=2),encoding='utf-8')
    b,receipt=run_route(root=root/'run',run_id=args.run_id,route=args.route,image=seal['image'],client=client,goal=goal,public_files=inputs,mode='DEV',keep_alive=False)
    result={'receipt':receipt,'calls':client.calls,'tokens':client.tokens,'upper_tariff_cost_cny':client.run_cost,'bill':'NOT_QUERIED','audit':verify_audit(b.audit_path),'conformance_sha256':hashlib.sha256(args.conformance.read_bytes()).hexdigest(),'product_acceptance':'NOT_YET_EVALUATED','host_semantic_assistance_count':0,'formal_started':0}
    (root/'dev-result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()

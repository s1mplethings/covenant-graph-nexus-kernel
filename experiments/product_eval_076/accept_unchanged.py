"""Independent inspection for byte-identical, unimplemented baseline candidates.

Refuses changed candidates; never substitutes baseline for candidate.
"""
import argparse,hashlib,json,pathlib,subprocess,sys,zipfile
p=argparse.ArgumentParser();p.add_argument('--run',required=True,type=pathlib.Path);p.add_argument('--seal',required=True,type=pathlib.Path);a=p.parse_args()
run=a.run;seal=json.loads(a.seal.read_text());row=next(r for r in seal['matrix'] if r['run_id']==run.name)
def files(p):
 with zipfile.ZipFile(p) as z:return {n:z.read(n) for n in z.namelist() if not n.endswith('/')}
snapshot=run/'frozen/candidate.zip';assert files(snapshot)==files(row['initial_snapshot']),'CHANGED_CANDIDATE_REQUIRES_FULL_INDEPENDENT_INSPECTION'
out=run/'acceptance';base=pathlib.Path(__file__).parent
def call(script,args):
 x=subprocess.run([sys.executable,str(base/script),*args],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=120)
 print(x.stdout,flush=True)
 if x.returncode:raise RuntimeError(x.stderr)
 return x
call('inspect_candidate.py',['--root',str(out),'setup','--snapshot',str(snapshot),'--public',str(run/'run/public'),'--argv',json.dumps(['python','app.py'])])
view=call('inspection_action.py',['--root',str(out),'--url','http://127.0.0.1:5000','--screenshot','home.png'])
value=json.loads(json.loads(view.stdout)['stdout'])['result']['result'].get('value','')
assert 'Source Cabinet' in value,value
call('inspect_candidate.py',['--root',str(out),'restart'])
view2=call('inspection_action.py',['--root',str(out),'--url','http://127.0.0.1:5000','--screenshot','reopened.png'])
value2=json.loads(json.loads(view2.stdout)['stdout'])['result']['result'].get('value','');assert 'Source Cabinet' in value2
call('inspect_candidate.py',['--root',str(out),'close'])
card=json.loads(pathlib.Path(row['task_path']).read_text(encoding='utf-8'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
evidence=[{'path':str(snapshot),'sha256':sha(snapshot)},{'path':str(out/'operator.jsonl'),'sha256':sha(out/'operator.jsonl')}]
records=[]
missing={'asr','search','export','multi','evidence','content','approve','publish','schedule','campaign','tests'}
for ob in card['public_requirements']:
 suffix=ob['id'].rsplit('-',1)[-1]
 absent=suffix in missing
 records.append({'obligation_id':ob['id'],'task_id':row['task_id'],'run_id':run.name,'requirement_version':'ITER-076-v7','user_goal':ob['requirement'],'must':ob['must'],'initial_state':'Frozen Source Cabinet baseline','action':'Independent browser launch/reopen and exact candidate-vs-start snapshot comparison','expected_result_tolerance':card['tolerances'],'boundary_object':'Frozen candidate and its independent inspection copy','primary_score':ob['primary_score'],'actual_observation':'Candidate byte-identical to baseline: only archival GUI, no required domain processing or candidate tests' if absent else 'Archive UI launches and reopens; this full requirement was not evaluated','status':'FAIL' if absent else 'UNTESTED','evidence':evidence,'missing_items':[] if absent else ['Full obligation execution'],'defect_id':'NO_CANDIDATE_TESTS' if suffix=='tests' else 'MISSING_DOMAIN_IMPLEMENTATION' if absent else None,'root_cause':'PRODUCT_DEFECT' if absent else 'UNKNOWN'})
scores={f'{d}{i}':None for d in 'ABCDEF' for i in range(1,5)};scores['B1']=0;scores['D1']=0
result={'run_id':run.name,'task_id':row['task_id'],'route':row['route'],'status':'NOT_DELIVERABLE','candidate_sha256':sha(snapshot),'same_as_initial':True,'engineering':scores,'confirmed_points':0,'evaluated_weight':10,'pending_weight':90,'possible_total_range':[0,90],'domain_quality':{f'Q{i}':None for i in range(1,5)},'domain_status':'UNTESTED','gates':{'G1':'PARTIAL','G2':'FAIL','G3':'FAIL','G4':'UNTESTED','G5':'BLOCKED_DEP' if card['domain']=='promotion' else 'FAIL','G6':'UNTESTED'},'obligations':records,'defects':[{'id':'MISSING_DOMAIN_IMPLEMENTATION','primary_score':'B1','reason':'Scaffold unchanged; no domain workflow delivered. Other affected items not automatically double-scored.'},{'id':'NO_CANDIDATE_TESTS','primary_score':'D1','reason':'No test artifacts delivered.'}],'host_semantic_assistance_count':0,'human_review':'PENDING_HUMAN','source_cabinet_capabilities_not_credited':True,'backend_database_media_acceptance':'No domain pipeline exists; not assessed as successful','inspection_paid_calls':0}
(out/'acceptance.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({'run_id':run.name,'status':result['status']}))

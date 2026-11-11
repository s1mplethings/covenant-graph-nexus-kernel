"""Record a CREATE candidate containing only the neutral scaffold/raw copies.

No launch command or GUI is invented when the model delivered no application.
"""
import json,pathlib,zipfile,hashlib
root=pathlib.Path('F:/CGKN-ITER-076/formal-v8');seal=json.loads(pathlib.Path('F:/CGKN-ITER-076/benchmark-v8/freeze-v8.json').read_text())
def files(p):
 with zipfile.ZipFile(p) as z:return {n:z.read(n) for n in z.namelist() if not n.endswith('/')}
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
for row in seal['matrix']:
 if not row['task_id'].startswith('CREATE'):continue
 run=root/row['run_id'];snap=run/'frozen/candidate.zip'
 if not (run/'freeze-command.json').exists() or (run/'acceptance').exists():continue
 actual=files(snap);initial=files(row['initial_snapshot']);allowed={}
 for p in row['inputs'].values():
  if pathlib.Path(p).suffix=='.zip':allowed.update(files(p))
 extras={n:v for n,v in actual.items() if n not in initial}
 if not all(actual.get(n)==v for n,v in initial.items()) or not all('/' in n and allowed.get(n.split('/',1)[1])==v for n,v in extras.items()):
  print(json.dumps({'needs_full_inspection':str(run)}));continue
 card=json.loads(pathlib.Path(row['task_path']).read_text(encoding='utf-8'));out=run/'acceptance';out.mkdir()
 evidence=[{'path':str(snap),'sha256':sha(snap)},{'path':str(run/'frozen/manifest.json'),'sha256':sha(run/'frozen/manifest.json')}]
 scores={f'{d}{i}':None for d in 'ABCDEF' for i in range(1,5)};scores.update(B1=0,D1=0)
 obs=[]
 for o in card['public_requirements']:
  suffix=o['id'].rsplit('-',1)[-1];failed=suffix in {'startup','gui','asr','search','export','content','approval','publish','schedule','campaign','tests'}
  obs.append({'obligation_id':o['id'],'task_id':row['task_id'],'run_id':run.name,'requirement_version':'ITER-076-v8','user_goal':o['requirement'],'must':o['must'],'initial_state':'Neutral scaffold only','action':'Read original frozen file manifest and README; compare every byte against neutral scaffold and allowed raw evidence','expected_result_tolerance':card['tolerances'],'boundary_object':'Original frozen candidate archive','primary_score':o['primary_score'],'actual_observation':'No application or candidate-authored tests supplied; only original neutral README and optional verbatim input copies','status':'FAIL' if failed else 'UNTESTED','evidence':evidence,'missing_items':[] if failed else ['Requires an application to evaluate'],'defect_id':'NO_CANDIDATE_TESTS' if suffix=='tests' else 'NO_APPLICATION' if failed else None,'root_cause':'PRODUCT_DEFECT' if failed else 'UNKNOWN'})
 result={'run_id':run.name,'task_id':row['task_id'],'route':row['route'],'status':'NOT_DELIVERABLE','candidate_sha256':sha(snap),'same_as_initial':not extras,'verbatim_public_input_copy_files':len(extras),'engineering':scores,'confirmed_points':0,'evaluated_weight':10,'pending_weight':90,'possible_total_range':[0,90],'domain_quality':{f'Q{i}':None for i in range(1,5)},'gates':{'G1':'FAIL','G2':'FAIL','G3':'FAIL','G4':'UNTESTED','G5':'BLOCKED_DEP' if card['domain']=='promotion' else 'FAIL','G6':'UNTESTED'},'obligations':obs,'gui':'BLOCKED_DEP_NO_APPLICATION; no screenshot claimed','host_semantic_assistance_count':0,'inspection_paid_calls':0,'human_review':'PENDING_HUMAN'}
 (out/'acceptance.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({'run':run.name,'status':'NOT_DELIVERABLE','gui':'No application to launch'}))

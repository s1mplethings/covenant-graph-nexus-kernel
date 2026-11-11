"""Freeze explicitly authorized budget/protocol amendment without replacing v7."""
import json,pathlib,hashlib,copy,sys
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[2]))
from experiments.product_eval_076_v8.routes import TOOL_POLICY
from experiments.product_eval_076_v8.formal_contract import validate
root=pathlib.Path('F:/CGKN-ITER-076');out=root/'benchmark-v8';out.mkdir(exist_ok=False)
read=lambda p:json.loads(p.read_text(encoding='utf-8'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf-8')
old=root/'benchmark-v5/freeze-v7.json';s=copy.deepcopy(read(old));conf=root/'conformance-v8-01/conformance.json';c=read(conf)
assert all(x['status']=='PASS' for x in c['results'])
src=pathlib.Path(__file__).parent
for n in ['routes.py','runner.py','isolation.py','browser.py','sidecar.py','controlled_target.py','live_provider.py']:assert sha(src/n)==c['source_hashes'][n],n
records={};notes={};calibrations=[]
for route in ['R_DIRECT','R_CGNK']:
 d=root/('protocol-v8-'+route.lower().replace('_','-'));v=read(d/'verification.json');calibrations.append(v)
 # Mechanical complete public self-history only; excludes host scoring/diagnosis.
 own={'route':route,'goal':v['goal'],'calls':[{'request':read(p),'result':read(p.with_name(p.name.replace('.request.json','.result.json')))} for p in sorted((d/'provider').glob('call-*.request.json'))],'raw_end':v['receipt']}
 target=out/(route+'-own-protocol-calibration.json');save(target,own);records[route]=str(target)
 if (d/'model-protocol-note.txt').exists():notes[route]=str(d/'model-protocol-note.txt')
calib=out/'calibration.json';save(calib,{'status':'PASS','scope':'Calibration executed with both real routes; NOT both models passed. Direct copy/readback PASS; CGNK raw DAG-state mismatch retained, no runtime state repair.','prior_dev_calibration':s['evidence']['dev_calibration'],'protocol_runs':calibrations,'host_semantic_repairs':0})
s.update(benchmark_version='ITER-076-v8',parent_seal=str(old),parent_sha256=sha(old),tool_policy=TOOL_POLICY,global_cap_cny=50,development_ceiling_cny=50,per_run_cost_cap_cny=2.5,minimum_admissible_run_cap_cny=.8)
s['rules'].update(budget_authority=str(root/'budget-authorization-v8.json'),acceptance_reserve_cny=0,tail_pair_allocation='Before each pair: identical cap=min(2.5,remaining_global/2). Admit if cap>=0.8 to reserve a bounded first request on each route. No outcome-based allocation.',protocol='Generic API format clarified; raw request-construction ValueError becomes FAILED node feedback in existing Agent loop. No model output repair, no kernel change.',prior_results='First four v7 formal attempts retained, not replaced or restarted. Remaining original 28 cells use v8 and must be reported separately.',self_history='Each route receives its entire own public protocol calibration request/response history and own authored note if present. No host summary or private feedback.')
for r in s['matrix']:
 r['status']='PRIOR_VERSION_COMPLETED' if r['order']<=4 else 'NOT_RUN'
 if r['order']<=4:r['prior_result']=str(root/'formal-v7'/r['run_id']/'formal-result.json')
 else:
  r['inputs']['own-protocol-calibration.json']=records[r['route']]
  if r['route'] in notes:r['inputs']['own-protocol-note.txt']=notes[r['route']]
s['evidence']['route_conformance']={'status':'PASS','path':str(conf),'sha256':sha(conf)}
s['evidence']['dev_calibration']={'status':'PASS','path':str(calib),'sha256':sha(calib)}
s['source_hashes']={n:sha(src/n) for n in s['source_hashes']}
for p in [calib,root/'budget-authorization-v8.json',*map(pathlib.Path,records.values()),*map(pathlib.Path,notes.values())]:s['artifact_hashes'][str(p)]=sha(p)
dest=out/'freeze-v8.json';save(dest,s)
for r in s['matrix']:validate(dest,r['run_id'],r['route'])
print(json.dumps({'seal':str(dest),'sha256':sha(dest),'pending_original_cells':28,'preserved_v7':4,'global_limit':50,'reserved_for_acceptance':0}))

"""Freeze prepared DEV only; freeze does not authorize paid calls."""
import json
import shutil
import subprocess
import zipfile
from pathlib import Path
from .capture import ROOT,OLD,save,sha
from .real_path_replay import IMAGE

def main():
    packet=ROOT/'dev-packet';public=packet/'public';private=packet/'private'
    drafts=private/'draft-before-freeze';drafts.mkdir(exist_ok=False)
    for n in ['task.json','scoring-contract.json']:shutil.copy2(public/n,drafts/n)
    task=json.loads((public/'task.json').read_text());task['formal_frozen']=False;task['packet_frozen']=True
    task['FAQ']={'Which input is mandatory?':'Import scenario.mp4 through GUI; no recording or public publishing required.','What if a requirement is unclear?':'State a reasonable business assumption in handoff; no implementation advice or private evaluation feedback.','Can existing tests be reused?':'Yes, when they effectively test this target workflow; unrelated copied tests do not qualify.'}
    task['score_mapping']['D1']['specific_rubric']='Effective candidate tests, newly written or validly reused, cover actual public workflow obligations.'
    save(public/'task.json',task)
    scoring=json.loads((public/'scoring-contract.json').read_text())
    for k in ['planned_formal','dev_max','budget_cny','acceptance_reserved_cny','formal_order']:scoring.pop(k,None)
    scoring.update(formal_frozen=False,dev_planned=2,paid_authorization='Required separately; freeze is not approval')
    save(public/'scoring-contract.json',scoring)
    plan=json.loads((packet/'cost-plan.json').read_text())
    save(public/'execution-policy.json',{'version':'ITER088-DEV-v1','route_cap_cny':plan['route_cap_cny'],'limits':plan['limits'],'output_policy':'Actual max output is limited to affordable 1024..8192 tokens using full raw context; no semantic compression. Unaffordable next request stops the run.','tool_lifecycle':'Each tool <=120 seconds; timeout kills whole container and children, no host fallback. Application backgrounding is agent responsibility. Local services allowed; /workspace writable, /input readonly, no external network.','graph_commit':'CGNK may append nodes and change unfinished nodes through the canonical loop. A changed succeeded node needs explicit retry_node invalidating its dependent subgraph. Goal changes and node removal within a saved run are rejected. Ordinary resume requires same graph.','known_bound':'CGNK canonical AgentProjectLoop still has four decisions. Same aggregate request/time/token/cost ceilings do not remove this system-specific limit.'})
    shutil.copy2('experiments/diagnostic_088/acceptance_protocol.md',private/'acceptance-protocol.md')
    validation=json.loads((ROOT/'reference-validation-v2/validation.json').read_text())
    assert validation['status']=='PASS' and json.loads((ROOT/'media-verification/result.json').read_text())['status']=='PASS'
    assert json.loads((ROOT/'verification-v2/regression.json').read_text())['exit']==0
    files=list(public.iterdir())+[packet/'initial.zip',packet/'cost-plan.json',private/'acceptance-protocol.md',private/'reference.py',private/'new-media-asr-oracle-v2.json']
    tracked=[Path(p) for p in subprocess.check_output(['git','ls-files'],text=True).splitlines() if Path(p).is_file()]
    source=tracked+list(Path('experiments/diagnostic_088').glob('*.py'))+list(Path('experiments/product_eval_076_v8').glob('*.py'))+[Path('tests/runtime/test_graph_commit.py')]
    with zipfile.ZipFile(ROOT/'source-after.zip','x',zipfile.ZIP_DEFLATED) as z:
        for p in source:z.write(p,p.as_posix())
    (ROOT/'tracked-changes.patch').write_bytes(subprocess.check_output(['git','diff','--binary']))
    files+=source+[ROOT/'source-after.zip',ROOT/'reference-validation-v2/validation.json',ROOT/'media-verification/result.json',ROOT/'verification-v2/regression.json',ROOT/'actual-route-replay-v2/results.json']
    save(packet/'freeze.json',{'version':'ITER088-DEV-v1','paid_authorization':False,'image':IMAGE,'reference_validation':'PASS','order':plan['order'],'seed':plan['seed'],'files':{str(p.resolve()):sha(p) for p in files},'source_head':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'source_zip_sha256':sha(ROOT/'source-after.zip'),'local_changes_sha256':sha(ROOT/'tracked-changes.patch'),'old_sources_preserved':True,'conformance':'Previous complete isolation verification retained; this version actually replayed both route entries on same backend/image. No tool or mount policy change.'})
    print(sha(packet/'freeze.json'))
if __name__=='__main__':main()

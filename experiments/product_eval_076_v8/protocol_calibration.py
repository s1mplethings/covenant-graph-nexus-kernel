"""Paid, independent protocol task; no product answers or host response repair."""
import json,pathlib,subprocess,sys,hashlib
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[2]))
from experiments.product_eval_076_v8.runner import run_route
from experiments.product_eval_076_v8.live_provider import LiveClient
from experiments.product_eval_076_v8.isolation import verify_audit
root=pathlib.Path('F:/CGKN-ITER-076');conf=json.loads((root/'conformance-v8-01/conformance.json').read_text());assert all(r['status']=='PASS' for r in conf['results'])
goal='This is an independent tool-protocol calibration, not a business implementation task. Use the documented registered tools to read /input/probe.txt, save exactly its contents to /workspace/probe-copy.txt and read the saved file back. Then save your own brief tool-protocol usage notes to /workspace/protocol-note.txt, based only on this task and your observed calls. Correct your own outgoing format if raw tool or runtime feedback reports an error. Do not ask the host to repair messages. Finish after these artifacts are saved. No business product code is requested.'
for route in ['R_DIRECT','R_CGNK']:
 run_id='protocol-v8-'+route.lower().replace('_','-');out=root/run_id;out.mkdir(exist_ok=False)
 client=LiveClient('D:/cgkn-provider-api-lab',root/'global-provider-budget.json',out/'provider',run_id,run_cap_cny=1.2,honor_reasoning_none=True)
 b,receipt=run_route(root=out/'run',run_id=run_id,route=route,image=conf['image'],client=client,goal=goal,public_files={'probe.txt':'PUBLIC-PROTOCOL-CALIBRATION-076-V8\n'},mode='DEV')
 result={'kind':'REAL_PROVIDER_PROTOCOL_CALIBRATION_NOT_PRODUCT_DEV','receipt':receipt,'calls':client.calls,'cost':client.run_cost,'tokens':client.tokens,'audit':verify_audit(b.audit_path),'host_response_rewrites':0,'goal':goal}
 (out/'protocol-result.json').write_text(json.dumps(result,indent=2))
 # Host inspects only no-follow file metadata for this simple synthetic task.
 import zipfile
 from experiments.product_eval_076_v8.freeze_candidate import main
 # Existing freezer only accepts dev/formal receipt names; provide an explicitly
 # labelled copy for mechanical capture, never count it as product DEV.
 (out/'dev-result.json').write_text(json.dumps({**result,'not_product_dev':True},indent=2))
 x=subprocess.run([sys.executable,str(pathlib.Path(__file__).with_name('freeze_candidate.py')),'--dev-root',str(out),'--output',str(out/'frozen'),'--image',conf['image']],capture_output=True,text=True)
 (out/'freeze-command.json').write_text(json.dumps({'exit':x.returncode,'stdout':x.stdout,'stderr':x.stderr}));assert x.returncode==0
 with zipfile.ZipFile(out/'frozen/candidate.zip') as z:
  result['copy_verified']=z.read('probe-copy.txt')==b'PUBLIC-PROTOCOL-CALIBRATION-076-V8\n' if 'probe-copy.txt' in z.namelist() else False
  result['model_note_present']='protocol-note.txt' in z.namelist()
  if result['model_note_present']:(out/'model-protocol-note.txt').write_bytes(z.read('protocol-note.txt'))
 (out/'verification.json').write_text(json.dumps(result,indent=2));print(json.dumps(result),flush=True)

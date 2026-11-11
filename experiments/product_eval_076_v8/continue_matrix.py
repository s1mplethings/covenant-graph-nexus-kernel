"""Execute only the frozen next pair until registered cells or budget end."""
import json,pathlib,subprocess,sys
root=pathlib.Path('F:/CGKN-ITER-076/formal-v8')
argv=[sys.executable,str(pathlib.Path(__file__).with_name('formal_run.py')),'--seal','F:/CGKN-ITER-076/benchmark-v8/freeze-v8.json','--root',str(root),'--ledger','F:/CGKN-ITER-076/global-provider-budget.json','--lab-root','D:/cgkn-provider-api-lab']
for n in range(14):
 before=(root/'matrix-state.json').read_bytes()
 x=subprocess.run(argv,capture_output=True,text=True,encoding='utf-8',errors='replace')
 with (root/'pair-driver.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps({'argv':argv,'exit':x.returncode,'stdout':x.stdout,'stderr':x.stderr})+'\n')
 print(x.stdout,flush=True)
 if x.returncode:raise RuntimeError(x.stderr)
 after=(root/'matrix-state.json').read_bytes()
 if before==after or not any(r['status']=='NOT_RUN' for r in json.loads(after)['rows']):break

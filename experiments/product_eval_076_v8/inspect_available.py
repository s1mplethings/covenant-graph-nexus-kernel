"""Schedule frozen, byte-identical candidates for independent GUI inspection."""
import json,pathlib,zipfile,subprocess,sys
root=pathlib.Path('F:/CGKN-ITER-076/formal-v8');seal=pathlib.Path('F:/CGKN-ITER-076/benchmark-v8/freeze-v8.json');rows=json.loads(seal.read_text())['matrix']
def contents(p):
 with zipfile.ZipFile(p) as z:return {n:z.read(n) for n in z.namelist() if not n.endswith('/')}
for row in rows:
 run=root/row['run_id'];snap=run/'frozen/candidate.zip'
 if not snap.exists() or not (run/'freeze-command.json').exists() or (run/'acceptance').exists():continue
 if json.loads((run/'freeze-command.json').read_text())['exit']!=0:continue
 initial_path=pathlib.Path(row['initial_snapshot'])
 if row['task_id'].startswith('SELF_EVOLVE'):
  initial_path=pathlib.Path(json.loads((root/row['predecessor_run_id']/'public-predecessor.json').read_text())['snapshot'])
 if row['task_id'].startswith('CREATE'):
  print(json.dumps({'create_candidate_requires_inspection':str(run)}),flush=True);continue
 actual=contents(snap);initial=contents(initial_path);allowed={}
 for p in row['inputs'].values():
  if pathlib.Path(p).suffix=='.zip':allowed.update(contents(p))
 extras={n:v for n,v in actual.items() if n not in initial}
 if not all(actual.get(n)==v for n,v in initial.items()) or not all('/' in n and allowed.get(n.split('/',1)[1])==v for n,v in extras.items()):
  print(json.dumps({'changed_candidate_requires_inspection':str(run)}),flush=True);continue
 argv=[sys.executable,str(pathlib.Path(__file__).with_name('accept_unchanged.py')),'--run',str(run),'--seal',str(seal)]
 x=subprocess.run(argv,capture_output=True,text=True,encoding='utf-8',errors='replace')
 (run/'acceptance-command.json').write_text(json.dumps({'argv':argv,'exit':x.returncode,'stdout':x.stdout,'stderr':x.stderr},indent=2))
 print(json.dumps({'run':row['run_id'],'exit':x.returncode,'error':x.stderr if x.returncode else ''}),flush=True)

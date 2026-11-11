"""Isolated independent GUI operator; private logs never mounted in candidate."""
import argparse,hashlib,json,pathlib,re,subprocess,zipfile
IMAGE='sha256:1059097764b634a5b1e2ed4bf035700d6ce47dfd206044c1b9bf63300523ee20'
def main():
 p=argparse.ArgumentParser();p.add_argument('--root',type=pathlib.Path,required=True);p.add_argument('operation',choices=['setup','browser','restart','command','close']);p.add_argument('--snapshot',type=pathlib.Path);p.add_argument('--public',type=pathlib.Path);p.add_argument('--argv',help='JSON array, executes inside candidate only');p.add_argument('--request',type=pathlib.Path);a=p.parse_args();r=a.root.resolve()
 if a.operation=='setup':r.mkdir(parents=True,exist_ok=False)
 app='eval076-i-'+hashlib.sha256(str(r).encode()).hexdigest()[:12];browser=app+'-browser'
 def run(argv,stdin=None,timeout=120):
  x=subprocess.run(argv,input=stdin,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=timeout)
  row={'argv':argv,'stdin':stdin,'exit_code':x.returncode,'stdout':x.stdout,'stderr':x.stderr}
  with (r/'operator.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(row)+'\n')
  print(json.dumps(row));return x
 if a.operation=='setup':
  work=r/'workspace';work.mkdir();screen=r/'browser';screen.mkdir()
  with zipfile.ZipFile(a.snapshot) as z:
   for item in z.infolist():
    rel=pathlib.PurePosixPath(item.filename)
    if rel.is_absolute() or '..' in rel.parts or ':' in item.filename or (item.external_attr>>16)&0o170000==0o120000:raise ValueError('Unsafe snapshot')
    if item.is_dir():continue
    dst=work.joinpath(*rel.parts);dst.parent.mkdir(parents=True,exist_ok=True);dst.write_bytes(z.read(item))
  common=['--read-only','--cap-drop','ALL','--security-opt','no-new-privileges','--user','65534:65534','--pids-limit','256','--memory','1536m','--cpus','2','--init','--tmpfs','/tmp:rw,nosuid,nodev,size=536870912']
  x=run(['docker','run','-d','--name',app,'--network','none',*common,'--mount',f'type=bind,source={work},target=/workspace','--mount',f'type=bind,source={a.public.resolve()},target=/input,readonly',IMAGE,*json.loads(a.argv)])
  if x.returncode:raise SystemExit(x.returncode)
  x=run(['docker','run','-d','--name',browser,'--network','container:'+app,*common,'--mount',f'type=bind,source={screen},target=/workspace','--mount',f'type=bind,source={a.public.resolve()},target=/input,readonly',IMAGE])
  if x.returncode:raise SystemExit(x.returncode)
  run(['docker','exec',browser,'python','-c',"import socket,time\nfor i in range(25):\n try:\n  s=socket.create_connection(('127.0.0.1',5000),timeout=.2);s.close();print('STARTUP_PORT_READY');break\n except OSError:time.sleep(.2)\nelse:print('STARTUP_PORT_NOT_READY')"])
  (r/'identity.json').write_text(json.dumps({'app':app,'browser':browser,'snapshot_sha256':hashlib.sha256(a.snapshot.read_bytes()).hexdigest(),'startup':json.loads(a.argv),'public':str(a.public.resolve())},indent=2))
 elif a.operation=='browser':
  value=json.loads(a.request.read_text(encoding='utf-8'))
  if value.get('screenshot'):
   name=pathlib.PurePosixPath(value['screenshot']).name
   if (r/'browser'/name).exists():raise RuntimeError('SCREENSHOT_OVERWRITE_REFUSED')
  run(['docker','exec','-i',browser,'python','/opt/evaltools/browser.py'],json.dumps(value))
 elif a.operation=='restart':
  run(['docker','stop',browser]);run(['docker','restart',app]);run(['docker','start',browser])
  run(['docker','exec',browser,'python','-c',"import socket,time\nfor i in range(25):\n try:\n  s=socket.create_connection(('127.0.0.1',5000),timeout=.2);s.close();print('STARTUP_PORT_READY');break\n except OSError:time.sleep(.2)\nelse:print('STARTUP_PORT_NOT_READY')"])
 elif a.operation=='command':run(['docker','exec',app,*json.loads(a.argv)])
 else:
  run(['docker','rm','-f',browser,app]);run(['docker','inspect',app,browser])
if __name__=='__main__':main()

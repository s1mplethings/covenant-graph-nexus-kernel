"""Independent operator's generic DOM file picker and raw action recorder."""
import argparse,json,pathlib,subprocess

p=argparse.ArgumentParser();p.add_argument('--root',required=True,type=pathlib.Path);p.add_argument('--file');p.add_argument('--selector',default='input[type=file]');p.add_argument('--javascript');p.add_argument('--screenshot');p.add_argument('--url');a=p.parse_args()
r=a.root;ident=json.loads((r/'identity.json').read_text());browser=ident['browser']
if a.file:
 script='''import json,urllib.request,websocket
pages=json.load(urllib.request.urlopen('http://127.0.0.1:9222/json'));page=next(x for x in pages if x['type']=='page');ws=websocket.create_connection(page['webSocketDebuggerUrl'],origin='http://localhost');seq=0
def call(method,params):
 global seq
 seq+=1;ws.send(json.dumps({'id':seq,'method':method,'params':params}))
 while True:
  x=json.loads(ws.recv())
  if x.get('id')==seq:
   if 'error' in x:raise RuntimeError(x)
   return x['result']
doc=call('DOM.getDocument',{})
node=call('DOM.querySelector',{'nodeId':doc['root']['nodeId'],'selector':SELECTOR})['nodeId']
print(call('DOM.setFileInputFiles',{'nodeId':node,'files':[FILE]}));ws.close()
'''.replace('SELECTOR',repr(a.selector)).replace('FILE',repr(a.file))
 argv=['docker','exec','-i',browser,'python','-'];stdin=script
else:
 if a.screenshot and (r/'browser'/a.screenshot).exists():raise RuntimeError('Screenshot overwrite refused')
 request={'javascript':a.javascript or 'document.body.innerText'}
 if a.screenshot:request['screenshot']='/workspace/'+a.screenshot
 if a.url:request.update(url=a.url,wait_seconds=2)
 argv=['docker','exec','-i',browser,'python','/opt/evaltools/browser.py'];stdin=json.dumps(request)
x=subprocess.run(argv,input=stdin,text=True,encoding='utf-8',errors='replace',capture_output=True,timeout=60)
row={'argv':argv,'stdin':stdin,'exit_code':x.returncode,'stdout':x.stdout,'stderr':x.stderr}
with (r/'operator.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(row)+'\n')
print(json.dumps(row))

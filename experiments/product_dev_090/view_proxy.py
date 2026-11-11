"""Local viewer transport to one isolated candidate. No host file/API endpoints."""
import argparse,base64,hashlib,json,re,subprocess,threading
from pathlib import Path
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
p=argparse.ArgumentParser();p.add_argument('--root',required=True,type=Path);p.add_argument('--port',type=int,default=5090);a=p.parse_args()
identity=json.loads((a.root/'identity.json').read_text());container=identity['app']
if not re.fullmatch(r'eval076-i-[a-f0-9]{12}',container):raise ValueError('Unrecognized fixed inspection container')
PAYLOAD='''import json,sys,http.client,base64
p=json.load(sys.stdin);c=http.client.HTTPConnection('127.0.0.1',5000,timeout=115)
c.request(p['method'],p['path'],body=base64.b64decode(p['body']),headers=p['headers']);r=c.getresponse();data=r.read()
print(json.dumps({'status':r.status,'headers':r.getheaders(),'body':base64.b64encode(data).decode()}));c.close()
'''
lock=threading.Lock()
class Handler(BaseHTTPRequestHandler):
 def do_GET(self):self.forward()
 def do_POST(self):self.forward()
 def do_HEAD(self):self.forward()
 def forward(self):
  try:
   if not self.path.startswith('/') or self.path.startswith('//'):self.send_error(400);return
   n=int(self.headers.get('Content-Length','0'))
   if n<0 or n>50_000_000:self.send_error(413);return
   body=self.rfile.read(n);payload={'method':self.command,'path':self.path,'body':base64.b64encode(body).decode(),'headers':{k:v for k,v in self.headers.items() if k.lower() in {'content-type','range','if-range','if-none-match','if-modified-since'}}}
   r=subprocess.run(['docker','exec','-i',container,'python','-c',PAYLOAD],input=json.dumps(payload),capture_output=True,text=True,timeout=120,shell=False)
   if r.returncode:raise RuntimeError('Isolated app transport unavailable')
   out=json.loads(r.stdout);data=base64.b64decode(out['body'])
   if any(k.lower()=='location' and (not v.startswith('/') or v.startswith('//')) for k,v in out['headers']):raise RuntimeError('External redirect blocked')
   self.send_response(out['status'])
   for k,v in out['headers']:
    if k.lower() not in {'connection','transfer-encoding','content-length','server','date'}:self.send_header(k,v)
   self.send_header('Content-Length',str(len(data)));self.end_headers()
   if self.command!='HEAD':self.wfile.write(data)
   with lock:
    with (a.root/'viewer-transport.jsonl').open('a') as f:f.write(json.dumps({'method':self.command,'path':self.path,'input_sha256':hashlib.sha256(body).hexdigest(),'status':out['status'],'output_sha256':hashlib.sha256(data).hexdigest(),'container':container})+'\n')
  except Exception:self.send_error(502,'Isolated candidate unavailable')
 def log_message(self,*args):pass
print(json.dumps({'listen':f'http://127.0.0.1:{a.port}','container':container}),flush=True)
ThreadingHTTPServer(('127.0.0.1',a.port),Handler).serve_forever()

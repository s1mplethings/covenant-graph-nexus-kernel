"""Run-scoped controlled publication transport. Not a real social platform."""
import argparse, json, pathlib, socket, sqlite3, uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

def main():
 p=argparse.ArgumentParser();p.add_argument('--account',required=True);a=p.parse_args()
 root=pathlib.Path('/state');db=root/'target.sqlite'
 with sqlite3.connect(db) as c:c.execute('create table receipts(id text primary key,correlation text,payload text)')
 class Handler(BaseHTTPRequestHandler):
  def reply(self,status,obj):
   raw=json.dumps(obj).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
  def do_GET(self):
   u=urlparse(self.path)
   if u.path=='/health':return self.reply(200,{'account':a.account,'kind':'CONTROLLED_TEST_TARGET_NOT_REAL_PLATFORM'})
   if u.path!='/receipts':return self.reply(404,{'error':'not found'})
   q=parse_qs(u.query);correlation=q.get('correlation',[None])[0]
   with sqlite3.connect(db) as c:
    rows=c.execute('select id,payload from receipts'+(' where correlation=?' if correlation else ''),(correlation,) if correlation else ()).fetchall()
   self.reply(200,[{'remote_id':rid,**json.loads(raw)} for rid,raw in rows])
  def do_POST(self):
   if self.path!='/posts':return self.reply(404,{'error':'not found'})
   try:
    length=int(self.headers.get('Content-Length','0'))
    if not 0<length<=2_000_000:raise ValueError('body size')
    value=json.loads(self.rfile.read(length))
    if not isinstance(value,dict) or value.get('account')!=a.account:raise ValueError('wrong account')
    if any(not value.get(k) for k in ('correlation','text','media','version')):raise ValueError('required fields')
   except (ValueError,TypeError) as e:return self.reply(400,{'error':str(e)})
   fault=root/'fault.json';mode=json.loads(fault.read_text()) if fault.exists() else {}
   if mode.get('reject'):return self.reply(503,{'error':'controlled rejection'})
   rid=uuid.uuid4().hex
   with sqlite3.connect(db) as c:c.execute('insert into receipts values(?,?,?)',(rid,value['correlation'],json.dumps(value)))
   with (root/'events.jsonl').open('a') as f:f.write(json.dumps({'event':'ACCEPTED_COMMITTED','id':rid,'correlation':value['correlation']})+'\n')
   if mode.get('drop_after_accept'):
    fault.write_text('{}')
    with (root/'events.jsonl').open('a') as f:f.write(json.dumps({'event':'RESPONSE_DROPPED_AFTER_COMMIT','id':rid})+'\n')
    self.connection.shutdown(socket.SHUT_RDWR);self.connection.close();return
   self.reply(201,{'remote_id':rid,'status':'accepted','account':a.account})
 HTTPServer(('127.0.0.1',9001),Handler).serve_forever()

if __name__=='__main__':main()

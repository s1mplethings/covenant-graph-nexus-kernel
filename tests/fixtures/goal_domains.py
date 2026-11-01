"""Host-authored synthetic integration fixture, never a CGKN product candidate."""
import json, sqlite3, uuid, argparse
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path

PAGE="""<!doctype html><meta charset=utf-8><title>Mechanism fixture</title>
<h1>Synthetic mechanism fixture</h1><button id=reserve>Reserve resource A slot 1</button>
<button id=send>Send draft v1 to local receiver</button><pre id=result></pre>
<script>async function act(path,body){let r=await fetch(path,{method:'POST',body:JSON.stringify(body)});document.querySelector('#result').textContent=await r.text()}
reserve.onclick=()=>act('/reserve',{resource:'A',slot:'1'});send.onclick=()=>act('/send',{draft:'draft',version:1,target:'local',key:'gui-v1'});</script>"""

def server(path,variant='',port=0):
    def db():return sqlite3.connect(str(path),timeout=10)
    with db() as c:
        c.executescript('CREATE TABLE IF NOT EXISTS reservations(id TEXT PRIMARY KEY,resource TEXT,slot TEXT,status TEXT); CREATE TABLE IF NOT EXISTS deliveries(key TEXT PRIMARY KEY,draft TEXT,version INTEGER,target TEXT,status TEXT,effects INTEGER);')
        if variant!='overbook':c.execute("CREATE UNIQUE INDEX IF NOT EXISTS capacity ON reservations(resource,slot) WHERE status='confirmed'")
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def reply(self,value,code=200):
            raw=json.dumps(value).encode();self.send_response(code);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(raw)
        def do_GET(self):
            if self.path=='/':
                self.send_response(200);self.send_header('Content-Type','text/html');self.end_headers();self.wfile.write(PAGE.encode());return
            with db() as c:
                self.reply({'reservations':c.execute('select * from reservations').fetchall(),'deliveries':c.execute('select * from deliveries').fetchall()})
        def do_POST(self):
            v=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            try:
                with db() as c:
                    c.execute('BEGIN IMMEDIATE')
                    if self.path=='/reserve':
                        ident=str(uuid.uuid4())
                        if variant!='memory':c.execute('INSERT INTO reservations VALUES(?,?,?,?)',(ident,v['resource'],v['slot'],'confirmed'))
                        c.commit();self.reply({'id':'old' if variant=='old-object' else ident,'status':'confirmed'})
                    elif self.path=='/cancel':
                        target='other' if variant=='wrong-cancel' else v['id']
                        c.execute("UPDATE reservations SET status='cancelled' WHERE id=?",(target,));self.reply({'id':v['id'],'status':'cancelled'})
                    elif self.path=='/send':
                        row=c.execute('SELECT * FROM deliveries WHERE key=?',(v['key'],)).fetchone()
                        if row:
                            if variant=='duplicate':c.execute('UPDATE deliveries SET effects=effects+1 WHERE key=?',(v['key'],))
                            c.commit();self.reply({'receipt':list(row)});return
                        values=(v['key'],v['draft'],v['version']-1 if variant=='old-version' else v['version'],'wrong' if variant=='wrong-target' else v['target'],'queued' if variant=='queue-only' else 'received',1)
                        c.execute('INSERT INTO deliveries VALUES(?,?,?,?,?,?)',values)
                        c.commit();self.reply({'receipt':list(values),'status':'delivered'})
                    else:self.reply({'error':'unknown'},404)
            except sqlite3.IntegrityError:self.reply({'status':'conflict'},409)
    return ThreadingHTTPServer(('127.0.0.1',port),Handler)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--db',required=True);p.add_argument('--port',type=int,default=8065);a=p.parse_args()
    server(a.db,port=a.port).serve_forever()

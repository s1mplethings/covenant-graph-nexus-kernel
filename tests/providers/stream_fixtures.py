"""Synthetic wire fixtures only; no production transport monkeypatches."""
import hashlib,json
from cgkn.providers.gateway_stream import PROTOCOL

def gateway_wire(payload,doc,session='fixture-session'):
    identity='sha256:'+hashlib.sha256(json.dumps(payload,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
    if isinstance(doc,dict):
        doc.setdefault('cgkn_stream',{'completed':True})
        doc.setdefault('cgkn_model_identity',dict(provider_id=payload['model'],requested_model=doc.get('model'),actual_model=doc.get('model'),identity_status='MATCH'))
    rows=[('cgkn.started',{}),('cgkn.completed',dict(response=doc,gateway_http_status=200))]
    return b''.join(('event: '+kind+'\ndata: '+json.dumps(dict(protocol=PROTOCOL,request_identity=identity,session_id=session,sequence=i+1,**body))+'\n\n').encode() for i,(kind,body) in enumerate(rows))

def send_gateway(handler,payload,doc,session='fixture-session'):
    raw=gateway_wire(payload,doc,session)
    handler.send_response(200);handler.send_header('Content-Type','text/event-stream');handler.send_header('Content-Length',str(len(raw)))
    handler.end_headers();handler.wfile.write(raw);handler.wfile.flush()

def upstream_wire(model,text,request_id='fixture-request',usage=None):
    body=dict(id=request_id,model=model,choices=[dict(index=0,delta=dict(content=text),finish_reason='stop')],
              usage=usage if usage is not None else dict(prompt_tokens=3,completion_tokens=2,total_tokens=5))
    return ('data: '+json.dumps(body)+'\n\ndata: [DONE]\n\n').encode()

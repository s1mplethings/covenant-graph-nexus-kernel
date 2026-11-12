"""Generic isolated Chromium CDP tool. No host browser or personal session."""
import base64
import json
import pathlib
import subprocess
import sys
import time
import urllib.request
import websocket

def main():
    request=json.loads(sys.stdin.read())
    profile='/tmp/browser-profile'
    pathlib.Path('/tmp/home').mkdir(exist_ok=True)
    try:
        pages=json.load(urllib.request.urlopen('http://127.0.0.1:9222/json',timeout=2))
    except Exception:
        log=open('/tmp/chromium.log','ab')
        subprocess.Popen(['chromium','--headless','--no-sandbox','--disable-dev-shm-usage','--remote-debugging-port=9222','--remote-allow-origins=http://localhost','--user-data-dir='+profile,'about:blank'],stdout=log,stderr=log,start_new_session=True)
        for _ in range(60):
            time.sleep(.25)
            try:
                pages=json.load(urllib.request.urlopen('http://127.0.0.1:9222/json',timeout=1));break
            except Exception:pass
        else:raise RuntimeError('Chromium did not start')
    page=next(p for p in pages if p['type']=='page')
    ws=websocket.create_connection(page['webSocketDebuggerUrl'],origin='http://localhost',timeout=20)
    seq=0
    def call(method,params):
        nonlocal seq
        seq+=1
        ws.send(json.dumps({'id':seq,'method':method,'params':params}))
        while True:
            message=json.loads(ws.recv())
            if message.get('id')==seq:return message
    if request.get('url'):
        call('Page.enable',{})
        call('Page.navigate',{'url':request['url']})
        time.sleep(min(float(request.get('wait_seconds',1)),5))
    result=call('Runtime.evaluate',{'expression':request.get('javascript','document.body.innerText'),'returnByValue':True,'awaitPromise':True})
    if request.get('screenshot'):
        data=call('Page.captureScreenshot',{'format':'png'})['result']['data']
        target=pathlib.Path(request['screenshot'])
        target.write_bytes(base64.b64decode(data))
        result['screenshot']=str(target)
    ws.close()
    print(json.dumps(result))

if __name__=='__main__':main()

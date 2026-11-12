"""Exercise private reference via actual GUI and independent container evidence."""
import json
import subprocess
import sys
import time
import zipfile
from .capture import ROOT,save,sha
from .acceptance_checks import media_ok,location_ok,persistence_ok

def main():
    packet=ROOT/'dev-packet';private=packet/'private';out=ROOT/'reference-validation-v2'
    snapshot=private/'reference-v2.zip'
    with zipfile.ZipFile(snapshot,'x') as z:z.write(private/'reference.py','reference.py')
    cli=[sys.executable,'experiments/product_eval_076_v8/inspect_candidate.py','--root',str(out)]
    def command(args):
        p=subprocess.run(args,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=150)
        if p.returncode:raise RuntimeError(p.stderr+p.stdout)
        return json.loads(p.stdout.splitlines()[-1])
    def inspect(op,*args):return command(cli+[op,*args])
    def browser(js='document.body.innerText',url=None,screen=None):
        args=[sys.executable,'experiments/product_eval_076_v8/inspection_action.py','--root',str(out),'--javascript',js]
        if url:args+=['--url',url]
        if screen:args+=['--screenshot',screen]
        r=command(args);return json.loads(r['stdout'])['result']['result'].get('value')
    checks=[]
    def check(name,value,details=None):
        checks.append({'check':name,'pass':bool(value),'details':details});save(out/'checks-progress.json',checks);assert value,name
    def submit(action,**fields):
        values={'action':action,**fields}
        browser("(()=>{const v="+json.dumps(values)+";for(const [k,x] of Object.entries(v))document.querySelector('[name='+k+']').value=x;document.querySelector('button').click();return 'clicked';})()")
    def play_script(expression):
        # Trusted GUI gesture via CDP, no autoplay bypass in the candidate.
        code="""import json,urllib.request,websocket
page=next(p for p in json.load(urllib.request.urlopen('http://127.0.0.1:9222/json')) if p['type']=='page')
ws=websocket.create_connection(page['webSocketDebuggerUrl'],origin='http://localhost')
ws.send(json.dumps({'id':1,'method':'Runtime.evaluate','params':{'expression':EXPR,'returnByValue':True,'awaitPromise':True,'userGesture':True}}))
while True:
 r=json.loads(ws.recv())
 if r.get('id')==1:print(json.dumps(r));break
ws.close()
""".replace('EXPR',repr(expression))
        r=inspect('command','--argv',json.dumps(['python','-c',code]))
        doc=json.loads(r['stdout']);assert 'exceptionDetails' not in doc['result'],doc
        return doc['result']['result']['value']
    try:
        inspect('setup','--snapshot',str(snapshot),'--public',str(packet/'public'),'--argv','["python","reference.py"]')
        browser(url='http://127.0.0.1:5000',screen='01-start.png')
        command([sys.executable,'experiments/product_eval_076_v8/inspection_action.py','--root',str(out),'--file','/input/scenario.mp4','--selector','input[name=video]'])
        submit('import')
        video=None
        for _ in range(30):
            time.sleep(1)
            text=browser('document.querySelector("pre").innerText')
            try:
                value=json.loads(text)
                if isinstance(value,dict) and value.get('segments'):video=value;break
            except (ValueError,TypeError):pass
        check('gui_upload_actual_asr',video is not None)
        save(private/'new-media-asr-oracle-v2.json',video)
        browser(screen='02-transcribed.png')
        words=[w.strip('.,!?').lower() for s in video['segments'] for w in s['text'].split() if len(w.strip('.,!?'))>5]
        query=words[len(words)//2]
        submit('search',text=query);time.sleep(1)
        hits=json.loads(browser('document.querySelector("pre").innerText'))
        check('gui_search_real_source_time',bool(hits) and all(location_ok(h,video['id'],video['duration']) for h in hits),hits)
        play=play_script("(async()=>{let v=document.querySelector('video');v.currentTime="+str(hits[0]['from'])+";await v.play();await new Promise(r=>setTimeout(r,500));let x={time:v.currentTime,ready:v.readyState,duration:v.duration};v.pause();return x})()")
        browser(screen='03-search-play.png')
        check('gui_source_playback',play['ready']>=2 and abs(play['time']-hits[0]['from'])<2,play)
        submit('clip',id=video['id'],start='5',end='15');time.sleep(1)
        clip=json.loads(browser('document.querySelector("pre").innerText'))
        submit('export',id=clip['id']);time.sleep(5)
        r=inspect('command','--argv',json.dumps(['python','-c',"import reference,json;print(json.dumps(reference.all_objects()))"]))
        objects=json.loads(r['stdout']);job=next(x for x in objects if x.get('clip_id')==clip['id'])
        check('gui_export_worker_complete',job['status']=='complete',job)
        browser(url='http://127.0.0.1:5000',screen='04-export.png')
        playback=play_script("(async()=>{let v=[...document.querySelectorAll('video')].find(v=>v.src.includes("+json.dumps(job['id'])+"));await v.play();await new Promise(r=>setTimeout(r,400));let x={ready:v.readyState,time:v.currentTime};v.pause();return x})()")
        check('export_browser_playback',playback['ready']>=2 and playback['time']>0,playback)
        decoded=inspect('command','--argv',json.dumps(['ffmpeg','-v','error','-i',job['path'],'-f','null','-']))
        probed=inspect('command','--argv',json.dumps(['ffprobe','-v','error','-show_format','-show_streams','-of','json',job['path']]))
        probe=json.loads(probed['stdout']);check('independent_real_decode_audio_video_duration',media_ok(probe,decoded['exit_code'],10))
        check('oracle_rejects_fake_success',not media_ok({},1,10))
        check('oracle_rejects_wrong_source',not location_ok(dict(hits[0],video_id='other'),video['id'],video['duration']))
        check('oracle_rejects_lost_persistence',not persistence_ok(objects,[]))
        submit('clip',id=video['id'],start='15',end='5');time.sleep(1)
        check('invalid_range_feedback','Invalid clip range' in browser())
        browser(url='http://127.0.0.1:5000')
        command([sys.executable,'experiments/product_eval_076_v8/inspection_action.py','--root',str(out),'--file','/input/bad-video.mp4','--selector','input[name=video]'])
        submit('import');time.sleep(1);check('invalid_media_feedback',bool(browser()))
        inspect('restart')
        browser(url='http://127.0.0.1:5000',screen='05-reopened.png')
        after=json.loads(inspect('command','--argv',json.dumps(['python','-c',"import reference,json;print(json.dumps(reference.all_objects()))"]))['stdout'])
        check('restart_preserves_all_valid_objects',persistence_ok(objects,after))
        save(out/'validation.json',{'kind':'PRIVATE_REFERENCE_NOT_PRODUCT_SCORE','checks':checks,'status':'PASS','paid_calls':0,'domain_review':'UNTESTED/PENDING_HUMAN','snapshot_sha256':sha(snapshot),'operator_source':'public GUI controls; backend read-only evidence'})
    finally:
        if out.exists():inspect('close')
    print(json.dumps({'status':'PASS','checks':len(checks)}))
if __name__=='__main__':main()

"""Read-only candidate snapshot; real GUI + local HTTP integration, no acceptance grant."""
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ast, base64, datetime, hashlib, json, shutil, socket, subprocess, sys, threading, time
import urllib.parse
from playwright.sync_api import sync_playwright

R = Path('F:/CGKN-ITER-132/production-core-convergence-v1/promotion/run-05')
M = Path('F:/CGKN-LeanLoop-V1-20261101/migration/veriarbor')
out = M / sys.argv[1]
assert out.parent == M and not out.exists()
state = json.loads((R/'state/iter132-promotion-studio/promotion-05/run_state.json').read_text(encoding='utf8'))
nodes = json.loads((R/'state/iter132-promotion-studio/promotion-05/capability_tree.json').read_text(encoding='utf8'))['nodes']
writers = {n['id'] for n in nodes if n.get('config',{}).get('leaf_contract',{}).get('task_kind') in {'IMPLEMENTATION','REPAIR','INTEGRATION','DELIVERY'}}
assert not any(v['status'] == 'RUNNING' and key in writers for key,v in state['nodes'].items()), 'Wait for completed snapshot'
out.mkdir(); snapshot = out/'snapshot'; snapshot.mkdir()
for path in (R/'candidate').glob('*.py'): shutil.copy2(path, snapshot/path.name)
shutil.copytree(R/'candidate/milestones', snapshot/'milestones', ignore=shutil.ignore_patterns('__pycache__'))
checker = R/'consumer-revisions/final-gui-integrity-v6.py'
tree = ast.parse(checker.read_text(encoding='utf8'))
exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Platform'], type_ignores=[]), str(checker), 'exec'))
report = {'kind':'ActualFinalProductDiagnostic', 'acceptance_authority':False, 'host_business_patches':0,
          'source_sha256':hashlib.sha256((snapshot/'main.py').read_bytes()).hexdigest(), 'observations':[]}
def record(name, value):
    report['observations'].append({'name':name, 'value':value})
def require(condition, message):
    if not condition: raise AssertionError(message)
png = out/'pixel.png'
png.write_bytes(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a4gAAAABJRU5ErkJggg=='))
video = out/'clip.mp4'
subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-f','lavfi','-i','color=c=blue:s=32x32:d=0.5','-pix_fmt','yuv420p',str(video)], check=True, capture_output=True, timeout=15)
with socket.socket() as sock: sock.bind(('127.0.0.1',0)); port=sock.getsockname()[1]
url='http://127.0.0.1:'+str(port)
log=(out/'server.log').open('wb'); process=None
def start():
    proc=subprocess.Popen(['D:/anaconda/python.exe','-X','utf8',str(snapshot/'main.py'),'--serve','--port',str(port),'--data',str(out/'data')], cwd=snapshot, stdout=log, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
    return proc
def stop(proc):
    proc.terminate()
    try: proc.wait(timeout=5)
    except subprocess.TimeoutExpired: proc.kill(); proc.wait(timeout=5)
try:
    process=start()
    with Platform() as platform, sync_playwright() as pw:
        browser=pw.chromium.launch(channel='msedge',headless=True)
        try:
            page=browser.new_page(); page.set_default_timeout(8000); errors=[]
            page.on('pageerror', lambda e: errors.append(str(e)))
            def ready():
                for _ in range(80):
                    try: page.goto(url,wait_until='networkidle'); return
                    except Exception: time.sleep(.1)
                raise AssertionError('GUI startup failed')
            ready()
            def call(tag,op,**values):
                response=page.request.post(url+'/api/action',data={'milestone':tag,'op':op,**values})
                require(response.ok,(op,response.status,response.text()))
                return response.json()
            def click(selector,op):
                with page.expect_response(lambda r:r.url.endswith('/api/action') and op in (r.request.post_data or '')) as pending:
                    page.locator(selector).click()
                response=pending.value; page.wait_for_timeout(200)
                require(response.ok,(op,response.status,response.text()))
                return response.json()
            page.get_by_label('Project name',exact=True).fill('Final workflow')
            click('#create-project','project.create'); pid=call('M1','project.list')['items'][0]['id']
            page.locator('#nav-media').click(); media=[]
            for fixture,kind in ((png,'image'),(video,'video')):
                page.get_by_label('Media kind',exact=True).select_option(kind)
                page.get_by_label('Media file',exact=True).set_input_files(str(fixture))
                item=click('#import-media','media.import'); media.append(item)
                require(item['sha256']==hashlib.sha256(fixture.read_bytes()).hexdigest(),'Upload hash mismatch')
            page.locator('video:visible').first.wait_for()
            page.wait_for_function('Array.from(document.querySelectorAll("video")).some(v=>v.readyState>=2 && v.videoWidth>0 && v.controls)')
            record('actual_image_video_upload_and_video_decode', [m['id'] for m in media])
            page.locator('#nav-campaigns').click()
            page.get_by_label('Campaign name',exact=True).fill('Final campaign')
            page.get_by_label('Audience',exact=True).fill('Developers')
            page.get_by_label('Channels',exact=True).fill('alpha,beta')
            click('#create-campaign','campaign.create')
            source=out/'evidence'; source.mkdir(); (source/'README.md').write_text('Offline workflows are supported.',encoding='utf8')
            evidence=call('M2','evidence.import',project_id=pid,path=str(source))
            claim=call('M3','claim.create',project_id=pid,text='Offline workflows are supported.',evidence_ids=[evidence['id']])
            page.locator('#nav-content').click()
            page.get_by_label('Content text',exact=True).fill('Offline workflows are supported.')
            page.get_by_label('Channel',exact=True).select_option('alpha')
            page.get_by_label('Claims',exact=True).select_option(label=claim['text'])
            page.get_by_label('Media',exact=True).select_option([m['id'] for m in media])
            click('#save-content','content.')
            content=call('M5','content.list',project_id=pid)['items'][0]; cid=content['id']
            require(set(content['media_ids'])=={m['id'] for m in media},'Attachment identity missing')
            page.wait_for_function('Array.from(document.querySelectorAll("video")).some(v=>v.offsetParent && v.readyState>=2 && v.videoWidth>0 && v.controls)')
            click('#review-action','approval.review'); click('#approve-action','approval.approve')
            page.get_by_label('Platform URL',exact=True).fill(platform.url)
            page.locator('#nav-schedule').click()
            when=(datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(days=1)).isoformat()
            page.locator('#schedule-when').fill(when)
            scheduled=click('#schedule-action','schedule.create')
            later=(datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(days=2)).isoformat()
            page.locator('#schedule-when').fill(later)
            revised=click('#reschedule-action','schedule.reschedule')
            cancelled=click('#cancel-schedule-action','schedule.cancel')
            require(scheduled['id']==revised['id']==cancelled['id'],'Schedule identity changed')
            record('schedule_reschedule_cancel',{'created':scheduled,'rescheduled':revised,'cancelled':cancelled})
            page.locator('#nav-content').click()
            receipt=click('#publish-action','publish.send')
            require(receipt['status']=='PUBLISHED' and receipt['content_id']==cid and receipt['revision']==content['revision'],'Receipt not bound to published content')
            posted=next(iter(platform.records.values()))['payload']
            record('actual_publication',{'receipt':receipt,'platform_payload':posted})
            # Binding may be direct or through immutable content revision; retain both for inspection.
            revisions=call('M5','content.revisions',project_id=pid,content_id=cid)['items']
            bound=next((r for r in revisions if r['revision']==receipt['revision']),None)
            require(bound is not None and set(bound.get('media_ids',[]))=={m['id'] for m in media},'Receipt revision has no durable media binding')
            same=call('M7','publish.send',project_id=pid,content_id=cid,platform_url=platform.url,idempotency_key=receipt['idempotency_key'])
            require(same['id']==receipt['id'] and len(platform.posts)==1,'Duplicate publication')
            page.locator('#nav-receipts-analytics').click(); click('#fetch-analytics','analytics.fetch')
            record('analytics',page.locator('#analytics-list').inner_text())
            stop(process); process=start(); ready()
            receipts=call('M7','publish.list',project_id=pid)['items']
            require(any(r['id']==receipt['id'] and r['revision']==receipt['revision'] for r in receipts),'Receipt lost after restart')
            for item,fixture in zip(media,(png,video)):
                response=page.request.get(url+'/media/'+item['id'],params={'project_id':pid})
                require(response.ok and response.body()==fixture.read_bytes(),'Media lost after restart')
            record('restart_receipts_media',True)
            page.locator('#nav-content').click()
            page.get_by_label('Content text',exact=True).fill('Offline workflows are supported. Edited.')
            click('#save-content','content.')
            updated=call('M5','content.list',project_id=pid)['items']; approval=call('M6','approval.status',project_id=pid,content_id=cid)
            require(len(updated)==1 and updated[0]['id']==cid and updated[0]['revision']>receipt['revision'] and approval['status']=='DRAFT','Edit reused old approval or created duplicate')
            reject=page.request.post(url+'/api/action',data={'milestone':'M7','op':'publish.send','project_id':pid,'content_id':cid,'platform_url':platform.url,'idempotency_key':'after-edit'})
            require(reject.status==400 and len(platform.posts)==1,'Unapproved edited revision published')
            record('edit_invalidates_approval_and_stale_receipt',{'approval':approval,'receipt_revision':receipt['revision'],'current_revision':updated[0]['revision']})
            click('#review-action','approval.review'); click('#approve-action','approval.approve')
            stored=Path(media[0]['path']); original=stored.read_bytes(); stored.write_bytes(original+b'changed')
            reject=page.request.post(url+'/api/action',data={'milestone':'M7','op':'publish.send','project_id':pid,'content_id':cid,'platform_url':platform.url,'idempotency_key':'changed-media'})
            require(reject.status==400 and len(platform.posts)==1,'Changed media published')
            stored.unlink(); page.reload(wait_until='networkidle'); page.locator('#nav-content').click()
            reject=page.request.post(url+'/api/action',data={'milestone':'M7','op':'publish.send','project_id':pid,'content_id':cid,'platform_url':platform.url,'idempotency_key':'missing-media'})
            require(reject.status==400 and len(platform.posts)==1,'Missing/failed-preview media published')
            record('changed_missing_media_block_before_post',True)
            require(not errors,'JavaScript errors: '+repr(errors)); record('javascript_errors',errors)
            page.screenshot(path=str(out/'final-workflow.png'),full_page=True)
            report['status']='PASS'
        finally: browser.close()
except Exception as error:
    report['status']='FAIL'; report['error']=type(error).__name__+': '+str(error)
finally:
    if process is not None: stop(process)
    log.close()
    (out/'receipt.json').write_text(json.dumps(report,indent=2),encoding='utf8')
    print(json.dumps(report))

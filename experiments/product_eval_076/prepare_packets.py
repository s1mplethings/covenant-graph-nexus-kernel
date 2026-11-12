"""Author benchmark inputs, not candidate solutions. No model calls."""
import argparse, hashlib, json, pathlib, shutil, sqlite3, subprocess, zipfile

BASE_APP = '''from flask import Flask,request,redirect,send_from_directory,render_template_string
import sqlite3,pathlib,uuid,json
app=Flask(__name__); root=pathlib.Path(__file__).parent; data=root/'data'; data.mkdir(exist_ok=True)
def db():
 c=sqlite3.connect(data/'catalog.sqlite');c.row_factory=sqlite3.Row;c.execute('create table if not exists assets(id text primary key,name text,path text)');return c
@app.get('/')
def home():
 with db() as c: rows=c.execute('select * from assets order by name').fetchall()
 return render_template_string("""<!doctype html><title>Source Cabinet</title><h1>Source Cabinet</h1><p>Archive and preview source files.</p><form method=post action=/upload enctype=multipart/form-data><input type=file name=file required><button>Import source</button></form>{% for a in rows %}<article><h2>{{a.name}}</h2><a href='/files/{{a.path}}'>Open original</a>{% if a.name.endswith('.mp4') %}<video width=480 controls src='/files/{{a.path}}'></video>{% endif %}</article>{% endfor %}<a href=/history>Saved history</a>""",rows=rows)
@app.post('/upload')
def upload():
 f=request.files.get('file')
 if not f or not f.filename:return 'A file is required',400
 ident=uuid.uuid4().hex; name=pathlib.Path(f.filename).name; path=ident+pathlib.Path(name).suffix;f.save(data/path)
 with db() as c:c.execute('insert into assets values(?,?,?)',(ident,name,path))
 return redirect('/')
@app.get('/files/<path:name>')
def file(name):return send_from_directory(data,name)
@app.get('/history')
def history():
 p=data/'history-v1.json';content=p.read_text() if p.exists() else '[]'
 return render_template_string('<h1>Saved history</h1><pre>{{content}}</pre><a href=/>Back</a>',content=content)
if __name__=='__main__':app.run(host='0.0.0.0',port=5000)
'''

COMMON = [
 ('startup','Provide reproducible user instructions to start the application and operate the required GUI workflow; use existing installed dependencies.','F3'),
 ('gui','Complete the required workflow through a usable GUI; no hidden API/SQL/manual-file replacement for business operations.','E2'),
 ('persist','Saved objects, identities, versions, files, results and states remain accessible after application/process restart.','C2'),
 ('invalid','Reject empty/invalid input without losing existing data. A failed new operation must not destroy successful prior work.','B3'),
 ('isolation','Do not mix results from different objects or versions, falsely mark success, lose data, publish without approval or disclose unrelated data.','C4'),
 ('tests','Deliver your own reproducible tests of real business end states, boundaries and persistence; accurately report pass/fail/skip and known limitations.','D2'),
 ('preserve','Retain the original archive import, preview/download and existing saved data. CREATE must retain data saved during its own session.','F2')]
VIDEO = [
 ('asr','Import real supplied video through GUI and actually transcribe speech with available offline ASR. Do not hard-code transcription or answers.','B1'),
 ('search','Search transcript words and display source identity and time; jump to matching video position and play a preview.','C3'),
 ('export','Select start/end times in GUI and export an actual playable clip with source audio/video; retain source identity and selected boundaries. Reject start<0, end<=start and end beyond duration.','B2'),
 ('retry','After a failed import/export, correct or retry through the GUI; completed media must remain usable.','F1')]
PROMO = [
 ('content','Use raw project evidence to create promotional text and an actual downloadable media image, with source references. Distinguish verified results, scope, limitations and future plans; do not claim general proof or invented impact.','B1'),
 ('approval','GUI preview/edit and approval must bind exact title, text, media, target account and version. Substantive edits invalidate prior approval.','C1'),
 ('publish','Only an approved version may be sent to the designated run-specific controlled test target. Independently readable target receipt must match account/content/media/version; display truthful status. No public platform publishing is authorized.','C3'),
 ('retry','Handle rejected transmission without false success; allow permitted correction and retry. Preserve prior receipts and approved material.','F1'),
 ('real-integration','Real platform authentication/transmission evidence is required for G5, but no live platform target is authorized. Complete other work; record this obligation BLOCKED_DEP, never label the controlled target as real-platform success.','G5')]
EXTRAS = {
 'video':{
  1:[('multi','Manage two real video files; support cross-video search and editable clip labels/tags. One failed media job must not make the other unusable; retry it independently.','B4')],
  2:[('qa','Answer a user question using indexed source evidence with source/time references. For a question unsupported by the supplied footage, say that evidence is absent rather than inventing an answer.','B1'),('subtitle','Preview/edit a selected moment and export with synchronized visible subtitles; preserve versions and start/end boundaries.','B2'),('feedback','Accept/reject a resulting clip in GUI, save feedback and revisit that decision after reopening.','C2')],
  3:[('stale','While an export is in progress the user changes the selected clip; the older export may arrive later. Keep both versions identifiable; never mark the old output as the newest version. Acceptance may delay the encoding process by up to 3 seconds. Only this finite stale-result scenario is required.','F1')],
  4:[('migration','Upgrade saved transcript/clip metadata from the supplied legacy v1 records to a documented new version. Old video, transcript references, clip/export identities and feedback must remain accessible; do not reset/rebuild away the old database.','F2')]},
 'promotion':{
  1:[('schedule','Manage multiple content/media items, schedule publication in UTC, cancel pending work and edit it. Changed content requires new approval before any scheduled send; one failed item must not disable other items.','B4')],
  2:[('campaign','Organize evidence, text and media as campaigns; show version approval, schedules, target readback, saved receipts and feedback together and preserve them across restart.','C4')],
  3:[('uncertain','The controlled target can accept a send but lose its response. Reconcile by correlation identifier/readback, or honestly retain pending-verification. Do not blindly send a duplicate or claim unsupported exactly-once guarantees.','F1')],
  4:[('comparison','Extend the existing one-release campaign history to compare two release snapshots. Preserve old campaigns, factual references, approvals, pending schedules and receipts. Changed comparison content needs new approval.','F2')]} }

def h(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 p=argparse.ArgumentParser();p.add_argument('--output',type=pathlib.Path,required=True);p.add_argument('--inputs',type=pathlib.Path,required=True);a=p.parse_args()
 root=a.output.resolve();root.mkdir(parents=True,exist_ok=False);public=root/'public';public.mkdir();private=root/'private';private.mkdir()
 initial=root/'initial';initial.mkdir(); neutral=root/'neutral';neutral.mkdir()
 (neutral/'README.md').write_text('Neutral CREATE workspace. Python/Flask/SQLite/pytest/Chromium/ffmpeg/whisper-cli are installed. No business implementation is supplied. Save startup and GUI operation instructions in README.md. Public input is /input; /workspace is writable.\n')
 (initial/'app.py').write_text(BASE_APP)
 (initial/'README.md').write_text('# Source Cabinet\nRun `python app.py`, then open http://127.0.0.1:5000. Use Import source to archive a file; Open original/download and video controls provide preview. Saved history shows original records. Existing capability is only archival, preview and persisted source identity. It has no transcription/search/export or campaign/approval/publishing workflow. Your task specifies the new responsibility. Existing application/data may be extended or reorganized while preserving saved content and user behavior.\n')
 data=initial/'data';data.mkdir()
 with sqlite3.connect(data/'catalog.sqlite') as c:
  c.execute('create table assets(id text primary key,name text,path text)')
  c.execute('insert into assets values(?,?,?)',('original-note','original-note.txt','original-note.txt'))
 (data/'original-note.txt').write_text('Original archive record: retain this content and identity through the task.\n')
 # Legacy history is generated later by exercised private reference behavior, not fabricated here.
 matrix=json.loads(pathlib.Path('F:/CGKN-ITER-076/preflight-20261027/matrix.json').read_text())
 mapping={-2:0,-1:1,0:2,1:3,2:4}
 cards=[]
 for domain in ('video','promotion'):
  for level,rank in mapping.items():
   label='B'+('+'+str(level) if level>0 else str(level));task_id='TAKEOVER-'+domain+'-'+label
   obligations=list(COMMON)+(VIDEO if domain=='video' else PROMO)
   for i in range(1,rank+1):obligations+=EXTRAS[domain].get(i,[])
   obs=[{'id':task_id+'-'+key,'must':True,'requirement':text,'primary_score':score} for key,text,score in obligations]
   score_map={}
   for dim in 'ABCDEF':
    for j in range(1,5):
     key=dim+str(j)
     score_map[key]={'obligations':[o['id'] for o in obs if o['primary_score']==key] or [o['id'] for o in obs if o['primary_score'] in {'B1','C2','F3'}], 'observation':{'A':'Inspect raw model understanding, exploration, decomposition and traceability against this task and actual project.','B':'Exercise the specified core/edge workflows and inspect real outputs.','C':'Trace GUI input through backend, saved state, object/version and output; restart and read back.','D':'Inspect candidate-authored tests against obligations; run them and representative valid wrong-output, persistence or stale-approval mutations. Host acceptance is not candidate test quality.','E':'Independent operator uses only README and visible GUI. Record actions, errors, duration and detours.','F':'Exercise only this level recovery/compatibility obligations, restart and verify retained data and handoff.'}[dim]}
   card={'task_id':task_id,'domain':domain,'level':label,'kind':'TAKEOVER','lineage':'source-cabinet-v1-'+domain,'generalization':'Known product/source scenario family; not independent projects and not unseen-media holdout. DEV source content may overlap; no DEV solutions or private feedback supplied.','initial_capabilities':['GUI file archive','download/preview','SQLite persisted identities','legacy history display when supplied'],'increment':'Implement the complete missing domain workflow connecting GUI, real processing, persisted objects/tasks and actual outputs; archival scaffolding is not credited to the model.','public_requirements':obs,'input_scale':{'video':'One 75s real speech file at B-2; two distinct nonoverlapping excerpts from that source at other levels; one corrupt synthetic input for error handling.','promotion':'Complete raw tracked CGKN source archive at fixed HEAD plus two raw version documents; at most 3 campaigns and 3 scheduled sends.'}[domain],'tolerances':{'clip_boundary_seconds':1.0,'subtitle_boundary_seconds':2.0,'schedule_seconds':5.0,'ui_operation_limit':60,'operator_minutes':20,'operator_recheck':1},'dependencies':'Frozen v3-media image; offline only, run-local services permitted. The controlled publication target is evaluator transport, not live-platform integration.','score_mapping':score_map,'reviewers':{'engineering':'independent deterministic checks plus host inspection of frozen artifact and raw trace','domain':'PENDING_HUMAN unless an explicitly recorded proxy review is performed; no automatic human completion'},'formal_frozen':False}
   d=public/task_id;d.mkdir();(d/'task.json').write_text(json.dumps(card,indent=2),encoding='utf-8');cards.append(card)
 for kind in ('CREATE','REPEAT','SELF_EVOLVE'):
  for domain in ('video','promotion'):
   source=next(c for c in cards if c['domain']==domain and c['level']=='B0');card=json.loads(json.dumps(source));card['task_id']=kind+'-'+domain+'-B0';card['kind']=kind
   if kind=='CREATE':card['initial_capabilities']=[];card['increment']='Build the complete specified B0 workflow from the neutral workspace; no business flow is preimplemented.'
   if kind=='SELF_EVOLVE':
    card['initial_capabilities']=['Exactly this route first B0 TAKEOVER frozen candidate and approved public development records; no private evaluation feedback.']
    card['new_requirement']=EXTRAS[domain][3][0][1];card['predecessor_rule']='If minimum public startup check fails, BLOCKED_BY_PREDECESSOR. Never substitute a better repeat or reference.'
   d=public/card['task_id'];d.mkdir();(d/'task.json').write_text(json.dumps(card,indent=2),encoding='utf-8');cards.append(card)
 (root/'matrix.json').write_text(json.dumps(matrix,indent=2))
 contract=json.loads(pathlib.Path('experiments/product_eval_076/scoring_contract.json').read_text());contract.update(version='ITER-076-v5-draft',dev_max=12,budget_cny=50,acceptance_reserved_cny=10)
 (root/'scoring-contract.json').write_text(json.dumps(contract,indent=2))
 manifest={'status':'DRAFT_NOT_FROZEN','cards':len(cards),'planned_formal':32,'initial_hashes':{str(f.relative_to(initial)):h(f) for f in initial.rglob('*') if f.is_file()},'input_hashes':{f.name:h(f) for f in a.inputs.iterdir() if f.is_file() and f.name in {'speech-a.mp4','speech-b.mp4','project-source.zip','release-before.json','release-after.json','bad-video.mp4'}},'private_mount_policy':'Never mount private directory, repository or benchmark source into candidates','pending':['reference behavior and negative-variant validation','initial GUI/persistence validation','legacy actual history snapshots','all formal input validation','model/tool/budget/acceptance freeze']}
 (root/'preparation.json').write_text(json.dumps(manifest,indent=2));print(json.dumps(manifest,indent=2))

if __name__=='__main__':main()

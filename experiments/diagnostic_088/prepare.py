"""Freeze public task inputs; reference sources stay in private evaluator area."""
import json
import shutil
import subprocess
from decimal import Decimal,ROUND_CEILING
from .capture import ROOT,OLD,save,sha

def main():
    packet=ROOT/'dev-packet';packet.mkdir(exist_ok=False)
    public=packet/'public';public.mkdir();private=packet/'private';private.mkdir()
    source=OLD/'benchmark-v5/public/TAKEOVER-video-B-2/task.json'
    task=json.loads(source.read_text(encoding='utf-8').replace('TAKEOVER-video-B-2','DEV088-video-archive'))
    task.update(task_id='DEV088-video-archive',kind='DEV',level='B-2',generalization='New 180..210s source excerpt and task scenario in known source-cabinet video family; not independent project or unseen-source claim.',input_scale='One new 30-second English real speech MP4, plus invalid synthetic media. No recording requirement.',initial_snapshot='initial.zip',initial_capabilities=['Archive upload/list/download/preview','SQLite archive identities; no ASR, transcript index, search/locate or clip export'],milestones=['First effective business change','First GUI completion of new workflow','First effective candidate tests of workflow','Frozen candidate and independent acceptance'])
    task['dependencies']='Immutable v3-media Linux image; Flask/SQLite/Chromium/ffmpeg/ffprobe/whisper-cli and /opt/asr/ggml-tiny.en.bin installed; no network; local services allowed. Tool lifecycle unchanged: timeout kills container; agent arranges background services.'
    task['public_requirements']=[{**r,'requirement':r['requirement'].replace('your own reproducible tests','reproducible candidate tests (new or validly reused)')} for r in task['public_requirements']]
    task['tolerances']={'clip_boundary_seconds':1,'search_position_seconds':2,'ui_operation_limit':60,'operator_minutes':20,'operator_recheck':1,'asr_key_word_accuracy':'Meaningful phrase overlap with audible speech; preserve source and time, no fabricated transcript. Severe wrong source/time prevents delivery.'}
    task['human_review']='Domain Q1-Q4 and final usability require human review; absent output is UNTESTED/NO_CANDIDATE_DOMAIN_OUTPUT, separately PENDING_HUMAN. Automatic track alone is not final delivery.'
    task['future_self_evolve']='Not scheduled. Any future parent must implement a new dependent real workflow with its data/interfaces; runnable scaffold alone is BLOCKED_BY_PREDECESSOR.'
    save(public/'task.json',task)
    scoring=json.loads((OLD/'benchmark-v5/scoring-contract.json').read_text())
    scoring['version']='ITER-088-DEV-v1';scoring['items']['D1']='Effective candidate tests (new or validly reused) cover target obligations; unrelated copied tests do not qualify.'
    save(public/'scoring-contract.json',scoring)
    shutil.copy2(OLD/'benchmark-v5/initial.zip',packet/'initial.zip')
    shutil.copy2(ROOT/'media/jfk-new-scenario.mp4',public/'scenario.mp4')
    (public/'bad-video.mp4').write_bytes(b'Invalid synthetic video for local error handling.\n')
    save(public/'media-provenance.json',{'source_url':'https://upload.wikimedia.org/wikipedia/commons/7/74/John_F._Kennedy_Inauguration_Speech.ogv','source_page':'https://commons.wikimedia.org/wiki/File:John_F._Kennedy_Inauguration_Speech.ogv','license':'Public domain US federal government work; source page checked 2026-10-27','source_interval_seconds':[180,210],'duration_seconds':30,'language':'English','size':(public/'scenario.mp4').stat().st_size,'sha256':sha(public/'scenario.mp4'),'scenario_relation':'Same source speech, nonoverlapping with previous 0..75s excerpts; not new family'})
    shutil.copy2(OLD/'benchmark-v5/private/reference.py',private/'reference.py')
    # Evaluator-only reference supports real GUI file upload; never in initial.zip.
    p=private/'reference.py';s=p.read_text(encoding='utf-8')
    s=s.replace('<form method=post action=/act>','<form method=post action=/act enctype="multipart/form-data"><label>Video upload<input type=file name=video></label>')
    s=s.replace("if a=='import':message=json.dumps(import_video(f['path']))", "if a=='import':\n   uploaded=request.files.get('video')\n   if uploaded and uploaded.filename:\n    target=root/'reference-upload.mp4';uploaded.save(target);message=json.dumps(import_video(target))\n   else:message=json.dumps(import_video(f['path']))")
    p.write_text(s,encoding='utf-8')
    ledger=json.loads((OLD/'global-provider-budget.json').read_text());rows=ledger['calls']
    previous=[c for c in rows if c['run_id']=='dev-video-direct-02']
    reserved=sum(Decimal(c['reserved_input_tokens']*20+c['reserved_output_tokens']*60)/1000000 for c in previous)
    max_next=max(Decimal(c['reserved_input_tokens']*20+c['reserved_output_tokens']*60)/1000000 for c in previous)
    cap=(reserved+4*max_next).quantize(Decimal('.01'),rounding=ROUND_CEILING)
    cumulative=Decimal('47.83242')+2*cap
    plan={'stage':'ITER-088-DEV-PAIR','approved':False,'user_authorization_reference':None,'route_cap_cny':float(cap),'calibration_cny':0,'acceptance_cny':0,'content_cny':0,'pair_hard_cap_cny':float(2*cap),'cumulative_cap_cny':float(cumulative),'existing_unused_cny':2.16758,'increase_over_50_cny':float(cumulative-50),'derivation':{'reference_run':'dev-video-direct-02','historical_requests':len(previous),'historical_sum_request_reservation_cny':str(reserved),'historical_max_request_reservation_cny':str(max_next),'additional_request_allowance':4,'allowance_reason':'Planning estimate for two GUI/restart verification actions, regression result and final handoff beyond the 12-request historical partial workflow. Not a guarantee or model instruction; no candidate solution supplied.'},'budget_rule':'Same 20/60 CNY per million upper tariffs, no cache; actual output adapts 1024..8192 to remaining run/global cap. Raw history unchanged. All planner/worker calls included.','limits':{'requests':80,'tokens':1000000,'seconds':3600,'cgnk_decisions':4},'order':['R_DIRECT','R_CGNK'],'seed':8801,'models':{'agent':'qwen3.8-max','worker':'deepseek-flash'},'comparison':'Complete systems; CGNK still canonical four-decision limit. No causal architecture attribution.'}
    save(packet/'cost-plan.json',plan)
    unknown=[c for c in rows if not isinstance(c.get('input_tokens'),int) or not isinstance(c.get('output_tokens'),int)]
    save(ROOT/'usage-supplement.json',{'unknown_usage_calls':unknown,'rule':'canonical _actual_token falls back to reserved tokens for UNKNOWN strings; no actual invoice queried','cost':47.83242,'new_paid_calls':0})
    save(packet/'manifest-inputs.json',{'public':{p.name:sha(p) for p in public.iterdir()},'initial_snapshot_sha256':sha(packet/'initial.zip'),'private_reference_sha256':sha(private/'reference.py'),'new_product_attempts':0,'old_formal_matrix_unchanged':32})
    print(json.dumps(plan,indent=2))
if __name__=='__main__':main()

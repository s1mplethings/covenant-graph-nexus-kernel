import json
import subprocess
from pathlib import Path
from .capture import ROOT,save
from .real_path_replay import IMAGE
from .acceptance_checks import media_ok

def main():
    out=ROOT/'media-verification';out.mkdir(exist_ok=False)
    validation=json.loads((ROOT/'reference-validation-v2/validation.json').read_text())
    job=next(c['details'] for c in validation['checks'] if c['check']=='gui_export_worker_complete')
    path='/exports/'+Path(job['path']).name
    base=['docker','run','--rm','--network','none','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges','--user','65534:65534','--tmpfs','/tmp:rw,nosuid,nodev,size=134217728','--mount',f'type=bind,source={ROOT / "dev-packet/public"},target=/input,readonly','--mount',f'type=bind,source={ROOT / "reference-validation-v2/workspace/reference-data"},target=/exports,readonly']
    records=[]
    def run(args,stdin=None):
        cmd=base+(['-i'] if stdin else [])+[IMAGE]+args
        p=subprocess.run(cmd,input=stdin,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=120)
        records.append({'argv':cmd,'exit':p.returncode,'stdout':p.stdout,'stderr':p.stderr})
        save(out/'commands.json',records);return p
    code=Path('experiments/diagnostic_088/media_compare.py').read_text()
    good=run(['python','-','/input/scenario.mp4',path,'5','15'],code)
    wrong=run(['python','-','/input/scenario.mp4',path,'17','27'],code)
    bad=run(['ffmpeg','-v','error','-i','/input/bad-video.mp4','-f','null','-'])
    source_probe=run(['ffprobe','-v','error','-show_format','-show_streams','-of','json','/input/scenario.mp4'])
    assert good.returncode==wrong.returncode==0
    correct=json.loads(good.stdout);incorrect=json.loads(wrong.stdout)
    assert correct['pass'] and not incorrect['pass'] and bad.returncode!=0
    assert media_ok(json.loads(source_probe.stdout),0,30)
    save(out/'result.json',{'status':'PASS','correct_export':correct,'wrong_timeline_rejected':incorrect,'invalid_file_decode_exit':bad.returncode,'paid_calls':0,'human_quality':'UNTESTED'})
    print(json.dumps(correct))
if __name__=='__main__':main()

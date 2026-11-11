"""Real media dependency probe through both route bindings, no paid models."""
import argparse
import hashlib
import json
import pathlib
import sys
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[2]))
from experiments.product_eval_076.conformance import Replay
from experiments.product_eval_076.runner import run_route
from experiments.product_eval_076.isolation import verify_audit

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=pathlib.Path,required=True);p.add_argument('--media',type=pathlib.Path,required=True);p.add_argument('--conformance',type=pathlib.Path,required=True);args=p.parse_args()
    seal=json.loads(args.conformance.read_text());out=args.output.resolve();out.mkdir(exist_ok=False)
    data=args.media.read_bytes()
    commands=[
      ['ffmpeg','-v','error','-i','/input/media.mp4','-vn','-ar','16000','-ac','1','audio.wav'],
      ['whisper-cli','-m','/opt/asr/ggml-tiny.en.bin','-f','audio.wav','-t','2','-ng','-oj','-of','transcript'],
      ['python','-c',"import json;d=json.load(open('transcript.json'));assert d['transcription'];print('REAL_ASR_SEGMENTS',len(d['transcription']))"],
      ['ffmpeg','-v','error','-ss','30','-i','/input/media.mp4','-t','3','-c:v','libx264','-c:a','aac','probe-export.mp4'],
      ['ffmpeg','-v','error','-i','probe-export.mp4','-f','null','-'],
    ]
    results=[]
    for short,route in [('direct','R_DIRECT'),('cgnk','R_CGNK')]:
        b,r=run_route(root=out/short,run_id=out.name+'-'+short,route=route,image=seal['image'],client=Replay([{'action':'command','argv':c} for c in commands]),goal='Media dependency conformance, not product development',public_files={'media.mp4':data},mode='HARNESS_CONFORMANCE_ONLY')
        rows=[json.loads(x) for x in b.audit_path.read_text().splitlines()]
        tools=[x for x in rows if x['kind']=='tool']
        passed=len(tools)==len(commands) and all(x['data']['result'].get('exit_code')==0 for x in tools)
        results.append({'route':route,'status':'PASS' if passed else 'FAIL','receipt':r,'audit':verify_audit(b.audit_path),'artifact_hashes':{f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in b.work.iterdir() if f.is_file() and not f.is_symlink()}})
    result={'mode':'HARNESS_CONFORMANCE_ONLY','input_sha256':hashlib.sha256(data).hexdigest(),'image':seal['image'],'results':results,'not_product_acceptance':True}
    (out/'media-check.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result,indent=2))

if __name__=='__main__':main()

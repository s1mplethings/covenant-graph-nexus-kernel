"""Freeze a terminated DEV candidate without following untrusted links on host."""
import argparse
import hashlib
import json
import pathlib
import subprocess

INSPECT=r'''
import os,pathlib,stat,hashlib,json,zipfile
root=pathlib.Path('/candidate');entries=[];skipped=[]
with zipfile.ZipFile('/evidence/candidate.zip','x',compression=zipfile.ZIP_DEFLATED) as z:
 for folder,dirs,names in os.walk(root,followlinks=False):
  keep=[]
  for d in dirs:
   p=pathlib.Path(folder)/d
   if p.is_symlink() or d in {'.git','__pycache__','.pytest_cache','node_modules','.venv'}:skipped.append(str(p.relative_to(root)))
   else:keep.append(d)
  dirs[:]=keep
  for name in names:
   p=pathlib.Path(folder)/name;mode=p.lstat().st_mode
   if not stat.S_ISREG(mode):skipped.append(str(p.relative_to(root)));continue
   rel=str(p.relative_to(root));raw=p.read_bytes()
   if len(raw)>100_000_000:raise RuntimeError('Oversized snapshot file')
   entries.append({'path':rel,'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)})
   z.writestr(rel,raw)
pathlib.Path('/evidence/manifest.json').write_text(json.dumps({'files':entries,'excluded':skipped},indent=2))
print(json.dumps({'files':len(entries),'excluded':len(skipped)}))
'''

def main():
    p=argparse.ArgumentParser();p.add_argument('--dev-root',required=True,type=pathlib.Path);p.add_argument('--output',required=True,type=pathlib.Path);p.add_argument('--image',required=True);p.add_argument('--receipt-name',default='dev-result.json',choices=['dev-result.json','formal-result.json']);args=p.parse_args()
    root=args.dev_root.resolve();result=json.loads((root/args.receipt_name).read_text(encoding='utf-8'))
    run_id=result['receipt']['run_id'];name='eval076-'+run_id
    check=subprocess.run(['docker','inspect',name],capture_output=True,text=True)
    if check.returncode==0:raise RuntimeError('Development container still exists; freeze denied')
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    cmd=['docker','run','--rm','--network','none','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges','--user','65534:65534','--mount',f'type=bind,source={root / "run/workspace"},target=/candidate,readonly','--mount',f'type=bind,source={out},target=/evidence',args.image,'python','-c',INSPECT]
    r=subprocess.run(cmd,capture_output=True,text=True,timeout=120)
    receipt={'run_id':run_id,'development_container_absent':True,'command':cmd,'exit_code':r.returncode,'stdout':r.stdout,'stderr':r.stderr,'source_receipt_sha256':hashlib.sha256((root/args.receipt_name).read_bytes()).hexdigest()}
    if r.returncode==0:
        receipt['candidate_zip_sha256']=hashlib.sha256((out/'candidate.zip').read_bytes()).hexdigest()
        receipt['manifest_sha256']=hashlib.sha256((out/'manifest.json').read_bytes()).hexdigest()
    (out/'freeze.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8');print(json.dumps(receipt))
    raise SystemExit(r.returncode)

if __name__=='__main__':main()

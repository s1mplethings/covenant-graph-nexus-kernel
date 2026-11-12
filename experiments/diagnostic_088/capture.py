"""Capture actual local sources and original evidence without modifying either."""
import hashlib
import json
import subprocess
import zipfile
from pathlib import Path

ROOT=Path('F:/CGKN-ITER-088')
OLD=Path('F:/CGKN-ITER-076')
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p, value): p.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')

def main():
    ROOT.mkdir(exist_ok=False)
    tracked=subprocess.check_output(['git','ls-files'],text=True).splitlines()
    files=[Path(x) for x in tracked if Path(x).is_file()]
    files += list(Path('experiments/product_eval_076').glob('*.py'))+list(Path('experiments/product_eval_076_v8').glob('*.py'))
    files += list(Path('project_management/summaries').glob('ITER-076*.md'))
    with zipfile.ZipFile(ROOT/'source-before.zip','w',zipfile.ZIP_DEFLATED) as z:
        for p in files:z.write(p,p.as_posix())
    original={str(p.relative_to(OLD)):sha(p) for p in [OLD/'global-provider-budget.json',OLD/'budget-authorization-v8.json',OLD/'benchmark-v8/freeze-v8.json',OLD/'benchmark-v5/freeze-v7.json',OLD/'evidence-seal-v7/seal.json',OLD/'evidence-seal-v8/seal.json',OLD/'inspection-events-v8.json',OLD/'final-verification-v8.json']}
    save(ROOT/'baseline.json',{'id':'ITER-088','head':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'branch':subprocess.check_output(['git','branch','--show-current'],text=True).strip(),'status':subprocess.check_output(['git','status','--short'],text=True),'source_zip_sha256':sha(ROOT/'source-before.zip'),'source_files':{p.as_posix():sha(p) for p in files},'original_records':original,'paid_authorization':0,'id_check':'git grep and project_management/governance/experiments rg: ITER-088 unused; ITER-077..087 history occupied'})
    print(ROOT)
if __name__=='__main__':main()

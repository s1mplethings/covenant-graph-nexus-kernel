from pathlib import Path
import json
ROOT=Path('F:/CGKN-ITER-113')
IMAGE='sha256:1059097764b634a5b1e2ed4bf035700d6ce47dfd206044c1b9bf63300523ee20'
def save(p,v):
 p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')

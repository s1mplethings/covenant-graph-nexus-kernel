import hashlib,json,shutil,zipfile,subprocess
from pathlib import Path
from decimal import Decimal
from .budget_policy import ledger_cost
from .routes import TOOL_POLICY
ROOT=Path('F:/CGKN-ITER-090')
IMAGE='sha256:1059097764b634a5b1e2ed4bf035700d6ce47dfd206044c1b9bf63300523ee20'
def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')
def main():
 old=Path('F:/CGKN-ITER-089/dev-packet');out=ROOT/'packet-v1';out.mkdir(exist_ok=False)
 shutil.copyfile(old/'initial.zip',out/'initial.zip');shutil.copytree(old/'public',out/'public')
 task=json.loads((out/'public/task.json').read_text(encoding='utf-8'))
 task.update(continuation_version='ITER090-engineering-DEV-v1',kind='ENGINEERING_DEV',formal_frozen=False)
 task['FAQ']['What if a requirement is unclear?']='State a reasonable business assumption. Public tests and exposed independent raw failures may be used for self-repair in this engineering DEV.'
 task['additional_public_responsibilities']=[
 'Ordinary non-video file upload, list, download and reaccess must continue, not merely preserve one existing file.',
 'Actual ASR text, time, processing state and real failure reason bind to each uploaded source. No fixed input or fabricated transcript.',
 'Reject negative, reversed, equal and beyond-duration clip boundaries. Clip must contain the selected source picture and audio.',
 'After bad input or failed export, valid operations still work and previous records survive. Repeated clicks/retries must not mix objects or cause uncontrolled duplicate processing.',
 'After restarting app and browser, GUI access and database/media/transcript/export relationships remain usable.',
 'Deliver own reproducible tests of real workflow end states, boundaries, reopen and archive compatibility, plus dependencies, start/user/test instructions and honest known limits.',
 'Complete the entire task, not only worker dispatch or ASR. No recording, cloud publishing, accounts or extra higher-tier requirements.']
 task['public_blackbox_checks']='Read /input/public_checks.py --help; immutable generic download equality and media decode/duration checks may be run. They are host checks, not your own tests; independent GUI/source alignment/restart checks still apply.'
 save(out/'public/task.json',task)
 auth={'stage':'ITER-090-CGNK-DEV','approved':True,'user_authorization_reference':'attachment 38ea2bf8-6c66-4bfa-88f1-ef47bd3ee8a2 complete CGNK project engineering DEV','baseline_cny':str(ledger_cost(Path('F:/CGKN-ITER-076/global-provider-budget.json'))),'cumulative_cap_cny':89.43242,'route_cap_cny':float(min(Decimal('19.98122'),Decimal('89.43242')-ledger_cost(Path('F:/CGKN-ITER-076/global-provider-budget.json')))),'max_calls':80,'max_tokens':1000000,'max_development_seconds':3600,'max_new_transport_retries':1,'acceptance_reserve':0,'formal_runs':0,'scope':'CGNK only, all workers/stages share one client and ledger'}
 save(ROOT/'authorization.json',auth)
 save(out/'public/execution-policy.json',{'version':'ITER090-engineering-DEV-v1','tool_policy':TOOL_POLICY,'limits':auth,'feedback':'Public tests and exposed final failures are permitted. No private reference answers. Tools return raw data; self-repair is the model responsibility. No independent four-decision limit.'})
 shutil.copyfile('experiments/product_dev_090/public_checks.py',out/'public/public_checks.py')
 paths=[]
 for base in ['cgkn/agent','cgkn/executors','cgkn/runtime','cgkn/state','experiments/product_dev_090','experiments/product_dev_089','experiments/product_eval_076_v8']:
  paths.extend(Path(base).glob('*.py'))
 with zipfile.ZipFile(ROOT/'source-v1.zip','w',zipfile.ZIP_DEFLATED) as z:
  for p in paths:z.write(p,p.as_posix())
 save(out/'freeze.json',{'version':'ITER090-engineering-DEV-v1','image':IMAGE,'files':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [*paths,*[p for p in out.rglob('*') if p.is_file()],ROOT/'authorization.json']},'source_snapshot_sha256':hashlib.sha256((ROOT/'source-v1.zip').read_bytes()).hexdigest(),'scope':'engineering DEV; not blind comparison; initial snapshot original only','conformance':'conformance-v1/result.json','transport':'API Lab urllib one request, no retry loop; adapter permits one new inference transport retry, separate billed reservation'})
 print(auth)
if __name__=='__main__':main()

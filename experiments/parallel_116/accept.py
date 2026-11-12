"""Independent black-box checks on a frozen copy; oracle stays on the host.

The development Agent and its sessions must already be terminated. No candidate
business edits. Every app invocation is a separate process in the isolated copy.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

from experiments.parallel_116.run_task import safe_files
from experiments.product_eval_076.isolation import ContainerBoundary, Policy, verify_audit


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--candidate',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--image',required=True)
    a = p.parse_args()
    a.output.mkdir(parents=True,exist_ok=False)
    source = a.candidate.resolve()
    manifest = {f.relative_to(source).as_posix():hashlib.sha256(f.read_bytes()).hexdigest() for f in safe_files(source)}
    (a.output/'candidate-manifest.json').write_text(json.dumps(manifest,indent=2))
    boundary = ContainerBoundary(a.output/'environment',a.output.name,'R_CGNK',Policy(a.image))
    for relative in manifest:
        target = boundary.work/relative;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source/relative,target)
    checks=[]
    try:
        boundary.start()
        def execute(rows):
            boundary.execute({'action':'write_file','path':'accept-input.jsonl',
                              'content':'\n'.join(json.dumps(row) for row in rows)+'\n'})
            return boundary.execute({'action':'command','argv':['python','app.py','accept-input.jsonl',
                '--out','accept-result.json','--db','accept-state.sqlite']},timeout=30)
        def output():
            raw=boundary.execute({'action':'read_file','path':'accept-result.json'})
            if raw['exit_code']!=0:raise ValueError('result not readable')
            return json.loads(json.loads(raw['stdout'])['content'])
        def database():
            # Read only. Candidate SQL is never executed by the host evaluator.
            program="""import sqlite3,json
c=sqlite3.connect('file:accept-state.sqlite?mode=ro',uri=True)
names=[r[0] for r in c.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%' order by name")]
result={n:sorted([repr(r) for r in c.execute('select * from "'+n.replace('"','""')+'"')]) for n in names}
assert any(result.values()), 'no persisted records'
print(json.dumps(result,sort_keys=True))
"""
            raw=boundary.execute({'action':'command','argv':['python','-c',program]})
            if raw['exit_code']!=0:raise ValueError('SQLite state not independently readable/nonempty')
            return json.loads(raw['stdout'])
        first=[dict(order_id=' A ',sku=' alpha ',qty=2,unit_price='1.25'),
               dict(order_id='B',sku='alpha',qty=1,unit_price='0.10')]
        expected=dict(order_count=2,total_cents=260,by_sku={'alpha':dict(qty=3,total_cents=260)})
        r=execute(first);actual=output();db1=database()
        checks.append({'id':'normal_exact_money','pass':r['exit_code']==0 and actual==expected,'actual':actual})
        r=execute(first);db2=database()
        checks.append({'id':'process_reopen_idempotence','pass':r['exit_code']==0 and output()==expected and db1==db2})
        second=[dict(order_id='C',sku='beta',qty=3,unit_price='2.30')]
        expected2=dict(order_count=3,total_cents=950,by_sku={'alpha':dict(qty=3,total_cents=260),'beta':dict(qty=3,total_cents=690)})
        r=execute(second);db3=database()
        checks.append({'id':'cumulative_reopen','pass':r['exit_code']==0 and output()==expected2 and db3!=db2})
        bad=[dict(order_id='D',sku='delta',qty=1,unit_price='3.00'),dict(order_id='A',sku='alpha',qty=3,unit_price='1.25')]
        r=execute(bad)
        checks.append({'id':'conflict_atomicity','pass':r['exit_code']!=0 and database()==db3 and output()==expected2})
        r=execute([dict(order_id='E',sku='epsilon',qty=True,unit_price='1.00')])
        checks.append({'id':'invalid_quantity_no_mutation','pass':r['exit_code']!=0 and database()==db3 and output()==expected2})
    except Exception as exc:
        checks.append({'id':'acceptance_execution','pass':False,'error_type':type(exc).__name__,'error':str(exc)})
    finally:
        boundary.close()
    unchanged={f.relative_to(source).as_posix():hashlib.sha256(f.read_bytes()).hexdigest() for f in safe_files(source)}==manifest
    result={'checks':checks,'original_candidate_unchanged':unchanged,'audit':verify_audit(boundary.audit_path),
            'status':'PASS_CHECKED_OBLIGATIONS' if checks and all(r['pass'] for r in checks) and unchanged else 'NOT_DELIVERABLE',
            'model_calls':0,'scope':'five public business obligations; model/parallel witnesses and own-test effectiveness separately required'}
    (a.output/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))
    if result['status']=='NOT_DELIVERABLE':raise SystemExit(1)


if __name__=='__main__':main()

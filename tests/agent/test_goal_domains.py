"""Actual HTTP+SQLite fixture measurements through AgentProjectLoop/DAG/store."""
import importlib.util,json,threading,sqlite3
from urllib.request import urlopen,Request
from urllib.error import HTTPError
from concurrent.futures import ThreadPoolExecutor
import pytest
from cgkn.execution import BlockExecutionResult,BlockStatus
from test_goal_acceptance_integration import PLAN,action,setup,Check
spec=importlib.util.spec_from_file_location('domains','tests/fixtures/goal_domains.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)

@pytest.mark.parametrize('domain,variant,passes', [('reservation','',True),('reservation','memory',False),('reservation','old-object',False),('reservation','overbook',False),('reservation','wrong-cancel',False),('delivery','',True),('delivery','old-version',False),('delivery','wrong-target',False),('delivery','duplicate',False),('delivery','queue-only',False)])
def test_domain_measurement_via_actual_goal_entry(tmp_path,domain,variant,passes):
    db=tmp_path/'data.sqlite';srv=mod.server(db,variant);thread=threading.Thread(target=srv.serve_forever,daemon=True);thread.start()
    url='http://127.0.0.1:'+str(srv.server_port)
    def post(path,payload):
        try:
            with urlopen(Request(url+path,json.dumps(payload).encode(),method='POST'),timeout=5) as r:return r.status,json.load(r)
        except HTTPError as e:return e.code,json.load(e)
    observed={}
    try:
        def measure_business():
            if domain=='reservation':
                # Keep an old unrelated identity present throughout.
                post('/reserve',{'resource':'B','slot':'old'})
                with ThreadPoolExecutor(2) as pool:rows=list(pool.map(lambda _:post('/reserve',{'resource':'A','slot':'1'}),range(2)))
                winners=[r[1]['id'] for r in rows if r[0]==200]
                with sqlite3.connect(db) as c:before=c.execute("select id from reservations where resource='A' and status='confirmed'").fetchall()
                if winners:post('/cancel',{'id':winners[0]})
                with sqlite3.connect(db) as c:
                    after=c.execute("select id from reservations where resource='A' and status='confirmed'").fetchall()
                    old=c.execute("select id from reservations where resource='B' and status='confirmed'").fetchall()
                valid=len(winners)==1 and before==[(winners[0],)] and not after and len(old)==1
                observed={'responses':rows,'before':before,'after':after,'old':old}
            else:
                post('/send',{'key':'old','draft':'draft','version':1,'target':'local'})
                payload={'key':'new','draft':'draft','version':2,'target':'local'}
                first=post('/send',payload);post('/send',payload)
                with sqlite3.connect(db) as c:row=c.execute("select * from deliveries where key='new'").fetchone()
                valid=row==('new','draft',2,'local','received',1) and first[1]['receipt']==list(row)
                observed={'receipt':first,'persisted':row}
            return valid,observed
        loop,a,client=setup(tmp_path/'store',[action('plan',PLAN),action('execute',{},'check@1'),action('finish')],wrong=False)
        original=loop.runner.registry.resolve('check@1','check@1').execute
        def measure(request):
            from dataclasses import replace
            valid,observation=measure_business()
            observed.update(observation)
            result=original(request);out=result.as_dict()['outputs'];out['goal_check']['observed']=observed;out['goal_check']['verdict']='VERIFIED' if valid else 'FAILED'
            return replace(result,outputs=out)
        loop.runner.registry.resolve('check@1','check@1').execute=measure
        result=loop.run(project_id='p',run_id='r',goal=domain+' fixture measured relationship')
        assert a.view()['complete'] is passes
        assert (result.status=='GOALS_VERIFIED') is passes
        assert bool(observed)
    finally:srv.shutdown();srv.server_close();thread.join()

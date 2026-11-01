"""Local real process/SQLite integration through the production DAG runner."""
import hashlib
import json
import sys
import sqlite3

from cgkn.executors import CommandExecutor, ExecutorRegistry
from cgkn.orchestration.capability_tree import CapabilityNode, CapabilityTree
from cgkn.orchestration.execution_dag import compile_tree
from cgkn.runtime import DAGRunner
from cgkn.state import FileRunStore
from cgkn.orchestration.leaf_contract import build_leaf_contract
from cgkn.execution.deliverables import FileDeliverableChecker


PROGRAM = r'''
import sys,pathlib,time,json,sqlite3,hashlib
n=sys.argv[1];root=pathlib.Path('.');start=time.time()
def wait(name):
 end=time.monotonic()+8
 while not (root/name).exists():
  if time.monotonic()>end:raise RuntimeError('dependency witness timeout: '+name)
  time.sleep(.01)
if n in ('a','b'):
 p=root/n;p.mkdir();db=sqlite3.connect(p/'data.sqlite')
 db.execute('create table result (identity text, digest text)')
 db.execute('insert into result values (?,?)',(n,hashlib.sha256((n*10000).encode()).hexdigest()))
 db.commit();db.close();(root/(n+'.started')).write_text(str(start))
 wait('b.started' if n=='a' else 'c.finished')
elif n=='c':
 wait('a.finished');db=sqlite3.connect('a/data.sqlite')
 assert db.execute('select identity from result').fetchone()[0]=='a';db.close()
else:
 for key in ('a','b'):
  db=sqlite3.connect(key+'/data.sqlite');rows=db.execute('select * from result').fetchall();db.close()
  assert rows==[(key,hashlib.sha256((key*10000).encode()).hexdigest())]
(root/(n+'.finished')).write_text(json.dumps({'start':start,'end':time.time()}))
print(n+' verified')
'''


def test_process_overlap_join_and_durable_resume(tmp_path):
    work = tmp_path / 'work'
    work.mkdir()
    registry = ExecutorRegistry()
    registry.register(CommandExecutor(work))
    def node(n,deps):
        writing=n in {'a','b'}
        c=build_leaf_contract(goal='Persist independent SQLite result '+n if writing else 'Inspect dependency databases '+n,
            kind='IMPLEMENTATION' if writing else 'TEST',scope=[n+'.finished']+([n+'/data.sqlite',n+'.started'] if writing else []),
            acceptance=['process-objects'],checker='process',output_identity=n,effect_domains=[n],executor='local.command@1',
            dependencies=deps,probe_id=n,**({'expected_delta':'new independent SQLite object and timing'} if writing else
            {'subject':'dependency database','expected_observation':'exact stored identity and digest','pass_fail_rule':'read-only SQL equality'}))
        return CapabilityNode(n, capability_ref='process@1', depends_on=deps,
        config={'executor_ref': 'local.command@1', 'parallel_safe': True,
                'resources': {n: 'write'}, 'timeout_seconds': 15,
                'command': [sys.executable, '-c', PROGRAM, n],'leaf_contract':c})
    nodes=tuple(node(n,deps) for n,deps in [('a',()),('b',()),('c',('a',)),('join',('b','c'))])
    tree = CapabilityTree('process integration', nodes)
    store = FileRunStore(tmp_path / 'state')
    def inspect(root,c):
        n=c['probe_id'];objects={}
        for key in ([n] if n in {'a','b'} else ['a'] if n=='c' else ['a','b']):
            with sqlite3.connect(f'file:{(root/key/"data.sqlite").as_posix()}?mode=ro',uri=True) as db:
                objects[key]=db.execute('select * from result').fetchall()
        valid=all(rows==[(key,hashlib.sha256((key*10000).encode()).hexdigest())] for key,rows in objects.items())
        timing=json.loads((root/(n+'.finished')).read_text())
        return {'passed':valid and timing['end']>=timing['start'],'observed':{'objects':objects,'timing':timing}}
    registry.register(FileDeliverableChecker(work,{'process-objects':inspect}))
    runner = DAGRunner(registry, store, max_parallel=2,deliverable_checkers={'process':'deliverable.files@1'})
    result = runner.run(project_id='p', run_id='r', tree=tree, dag=compile_tree(tree))
    assert result.status == 'SUCCEEDED'
    times = {n: json.loads((work / (n+'.finished')).read_text()) for n in ('a', 'b', 'c')}
    assert times['a']['start'] < times['b']['end'] and times['b']['start'] < times['a']['end']
    assert times['c']['start'] < times['b']['end']
    before = {p.relative_to(work).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in work.rglob('*') if p.is_file()}
    assert not runner.run(project_id='p', run_id='r', tree=tree, dag=compile_tree(tree), resume=True).actual_executions
    after = {p.relative_to(work).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in work.rglob('*') if p.is_file()}
    assert before == after

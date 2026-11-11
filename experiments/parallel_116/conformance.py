"""No-model production DAG/container conformance. No business candidate code."""
import argparse
import dataclasses
import hashlib
import json
from pathlib import Path

from cgkn.executors import ExecutorRegistry
from cgkn.orchestration.capability_tree import CapabilityNode, CapabilityTree
from cgkn.orchestration.execution_dag import compile_tree
from cgkn.runtime import DAGRunner
from cgkn.state import FileRunStore
from experiments.product_eval_076.isolation import ContainerBoundary, Policy, verify_audit
from experiments.product_dev_113.routes import IsolatedExecutor


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--image', required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    boundaries = []
    registry = ExecutorRegistry()
    try:
        for name in ('a', 'b'):
            boundary = ContainerBoundary(args.output / name, args.output.name + '-' + name,
                                         'R_CGNK', Policy(args.image))
            boundaries.append(boundary)
            (boundary.public / 'public.txt').write_text('PUBLIC-FIXTURE', encoding='utf-8')
            boundary.start()
            executor = IsolatedExecutor(boundary, 'local.command@1')
            executor.descriptor = dataclasses.replace(executor.descriptor, executor_ref='isolated.'+name+'@1')
            executor.resource_claims = {'container:'+boundary.name: 'write'}
            registry.register(executor)
        private = args.output / "host-private-canary.txt"
        private.write_text("PRIVATE-SYNTHETIC-116", encoding="utf-8")
        command = """import pathlib,sqlite3,hashlib,subprocess
assert pathlib.Path('/input/public.txt').read_text()=='PUBLIC-FIXTURE'
try:pathlib.Path('/input/public.txt').write_text('bad')
except OSError as exc:assert exc.errno in (1,13,30), str(exc)
else:raise AssertionError('read-only input writable')
assert not pathlib.Path('/private/host-canary.txt').exists()
assert not pathlib.Path('/var/run/docker.sock').exists()
c=sqlite3.connect('fixture.sqlite');c.execute('create table evidence (value text)')
h=hashlib.sha256(b'PUBLIC-FIXTURE').hexdigest();c.execute('insert into evidence values (?)',(h,));c.commit();c.close()
print(subprocess.check_output(['python','--version'],text=True).strip());print(h)
"""
        command += "\nassert not pathlib.Path(" + repr(str(private.resolve())) + ").exists()\n"
        reopen = """import sqlite3,hashlib
c=sqlite3.connect('fixture.sqlite')
assert c.execute('select value from evidence').fetchall()==[(hashlib.sha256(b'PUBLIC-FIXTURE').hexdigest(),)]
print('REOPEN_VERIFIED')
"""
        nodes = [CapabilityNode(name, capability_ref='probe@1', config={
            'executor_ref':'isolated.'+name+'@1', 'parallel_safe':True,
            'command':['python','-c',command]}) for name in ('a','b')]
        nodes += [CapabilityNode('reopen-'+name, capability_ref='probe@1', depends_on=(name,),
            config={'executor_ref':'isolated.'+name+'@1', 'parallel_safe':True,
                    'command':['python','-c',reopen]}) for name in ('a','b')]
        tree = CapabilityTree('Container conformance only', tuple(nodes))
        store = FileRunStore(args.output / 'state')
        runner = DAGRunner(registry, store, max_parallel=2)
        first = runner.run(project_id='conformance', run_id='r', tree=tree, dag=compile_tree(tree))
        assert first.status == 'SUCCEEDED', first
        second = runner.run(project_id='conformance', run_id='r', tree=tree, dag=compile_tree(tree), resume=True)
        assert not second.actual_executions
        result = {'mode':'HARNESS_CONFORMANCE_ONLY', 'model_calls':0, 'formal_product_runs':0,
                  'source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 'image':args.image, 'first':first.as_dict(), 'resume':second.as_dict(),
                  'gui':'NOT_TESTED; not required for this local mechanism fixture'}
    finally:
        for boundary in boundaries:
            boundary.close()
    result['audits'] = {b.run_id:verify_audit(b.audit_path) for b in boundaries}
    (args.output / 'result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()

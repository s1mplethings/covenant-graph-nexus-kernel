import hashlib
import pytest
from cgkn.execution.python_exports import python_export_declarations
from cgkn.execution.deliverables import FileDeliverableChecker
from cgkn.executors import ExecutorRegistry
from cgkn.executors.llm import LLMExecutor
from cgkn.providers import ModelRoleConfig
from cgkn.runtime import DAGRunner
from cgkn.state import FileRunStore
from tests.runtime.test_execution_continuity import Client,node,write,run

pytestmark=[pytest.mark.boundary,pytest.mark.negative]


def test_declared_python_exports_bind_source_without_executing_it(tmp_path):
    p=tmp_path/'a.py';p.write_text("class Service: pass\nclass Error(Exception): pass\ndef operation(): pass\nVALUE=7\nraise RuntimeError('must not execute')\n")
    exports=[{'name':n,'kind':k} for n,k in [('Service','class'),('Error','exception'),('operation','function'),('VALUE','constant')]]
    row=python_export_declarations(p,exports)
    assert row['passed'] and row['observed']['sha256']==hashlib.sha256(p.read_bytes()).hexdigest()


@pytest.mark.parametrize('source',[
    '{"name":"Service","description":"documentation is not implementation"}',
    'def Service(): pass', 'class Service: pass\nService=7',
    'class Service: pass\ndel Service', 'if False:\n class Service: pass',
    'from another import Service',
])
def test_document_or_unresolved_export_never_verifies_declared_class(tmp_path,source):
    p=tmp_path/'a.py';p.write_text(source)
    assert not python_export_declarations(p,[{'name':'Service','kind':'class'}])['passed']


@pytest.mark.parametrize('source,passed', [('class Service: pass',True),('{"class":"Service"}',False)])
def test_real_dag_rejects_parseable_document_and_does_not_retain_it_as_verified(tmp_path,source,passed):
    root=tmp_path/'project';root.mkdir();store=FileRunStore(tmp_path/'state');reg=ExecutorRegistry()
    reg.register(LLMExecutor(root,Client([write(content=source)]),ModelRoleConfig('worker','fake')))
    # The old parse-only callback claims success. Mandatory public declarations
    # must still reject a syntactically valid documentation object.
    reg.register(FileDeliverableChecker(root,{'works':lambda r,c:{'passed':True,'observed':{'parse':True},'artifacts':['f.py']}},
        public_exports={'f.py':[{'name':'Service','kind':'class'}]}))
    runner=DAGRunner(reg,store,deliverable_checkers={'check':'deliverable.files@1'})
    summary=run(runner,[node()]);result=store.load_result('p','r','n')
    assert (summary.status=='SUCCEEDED')==passed
    assert (result.metadata['deliverable_verdict']=='VERIFIED')==passed
    proof=result.as_dict()['metadata']['deliverable_check']
    assert ('f.py' in proof['verified_artifacts'])==passed


def test_export_policy_change_cannot_reuse_old_deliverable_proof(tmp_path):
    from dataclasses import replace
    from tests.execution.test_migration_contracts import request
    from cgkn.execution.deliverables import verified_proof
    from cgkn.orchestration.capability_tree import _thaw
    (tmp_path/'f.py').write_text('class Service: pass')
    contract=_thaw(node().config['leaf_contract'])
    checker=FileDeliverableChecker(tmp_path,{'works':lambda r,c:{'passed':True,'observed':{'ok':True}}},
        public_exports={'f.py':[{'name':'Service','kind':'class'}]})
    req=replace(request(contract,{}),executor_ref=checker.descriptor.executor_ref)
    checked=checker.execute(req)
    assert verified_proof(checked,req,checker,contract)[0]
    checker.public_exports['f.py'].append({'name':'Missing','kind':'function'})
    assert not verified_proof(checked,req,checker,contract)[0]

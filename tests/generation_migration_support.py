"""Shared fixtures for migrated generation assertions; no alternate runtime."""
import json
from pathlib import Path
from cgkn.execution import BlockStatus
from cgkn.executors import ExecutorRegistry,LLMExecutor
from cgkn.providers import ModelRoleConfig,ProviderCompletion
from cgkn.orchestration import CapabilityTree,CapabilityNode,compile_tree
from cgkn.orchestration.leaf_contract import build_leaf_contract
from cgkn.execution.deliverables import FileDeliverableChecker
from cgkn.runtime import DAGRunner
from cgkn.state import FileRunStore
from tests.governed_measurement_support import admit_fixture_tree


def proposal(node, actions, *, escalate=False):
    return {'schema_version':'1.0','node_id':node,'summary':'Explicit migration fixture',
        'actions':actions,'expected_outputs':[],'confidence':1,
        'needs_escalation':escalate,'escalation_reason':'retained local failure' if escalate else ''}


def candidate_run(root, *, workspace=None, files=None, check=None, responder=None, nodes=None):
    work=Path(workspace) if workspace is not None else Path(root)/'work'
    work.mkdir(parents=True,exist_ok=True);store=FileRunStore(Path(root)/'state');calls=[]
    class Client:
        def complete(self,**kw):
            context=json.loads(kw['user']);calls.append(context)
            if responder is not None:value=responder(context)
            elif any(o.get('action') in {'write_file','patch_file'} for o in context.get('observations',())):
                value=proposal(context['node_id'],[])
            else:
                selected=(files or {'result.py':'value = 1\n'})
                scope=context['config']['leaf_contract']['target_scope']
                value=proposal(context['node_id'],[{'action':'write_file','path':n,'content':selected[n]} for n in scope])
            return ProviderCompletion(value if isinstance(value,str) else json.dumps(value),'fixture','migration',{'input_tokens':1,'output_tokens':1})
    if nodes is None:
        contract=build_leaf_contract(goal='Preserve original observable behavior',kind='IMPLEMENTATION',scope=list(files or {'result.py':''}),
            acceptance=['current-contract'],checker='source',output_identity='component',
            effect_domains=['filesystem','external_network'],executor='llm.cheap@1',expected_delta='Candidate changes within authorized ownership')
        nodes=(CapabilityNode('writer',capability_ref='code',config={'executor_ref':'llm.cheap@1','leaf_contract':contract}),)
    def independent(root,contract):
        outcomes={}
        for name in contract['target_scope']:
            path=root/name
            try:
                if not path.is_file() or not path.stat().st_size:raise ValueError('missing artifact')
                if path.suffix=='.py':compile(path.read_text(),name,'exec')
                outcomes[name]=True
            except (ValueError,SyntaxError):outcomes[name]=False
        passed=all(outcomes.values())
        extra=check(root,contract) if check else {'passed':True,'observed':{'contract':'bounded fixture'}}
        return {'passed':passed and extra['passed'],'observed':{'artifacts':outcomes,**extra['observed']},
                'artifacts':[n for n,v in outcomes.items() if v and extra['passed']]}
    registry=ExecutorRegistry();registry.register(LLMExecutor(work,Client(),ModelRoleConfig('worker','fixture'),max_rounds=8))
    registry.register(FileDeliverableChecker(work,{'current-contract':independent}))
    runner=DAGRunner(registry,store,deliverable_checkers={'source':'deliverable.files@1'})
    tree=admit_fixture_tree(store,CapabilityTree('Original frozen goal',tuple(nodes)))
    summary=runner.run(project_id='p',run_id='r',tree=tree,dag=compile_tree(tree))
    return summary,store,runner,tree,calls,work


def assert_current_generation_behavior(root, case):
    """Migrated assertions target the live authority rather than deleted retry APIs."""
    import pytest
    from cgkn.runtime.dag_runner import GraphEditRejected
    root=Path(root)
    if case=='ownership':
        def response(c):return proposal(c['node_id'],[{'action':'write_file','path':'unowned.py','content':'bad'}])
        summary,store,_,_,calls,work=candidate_run(root,responder=response)
        assert summary.status!='SUCCEEDED' and not (work/'unowned.py').exists()
        assert len(calls)==1
        assert 'outside leaf target_scope' in store.load_result('p','r','writer').error.message
    elif case=='invalid_json':
        summary,store,_,_,calls,work=candidate_run(root,responder=lambda c:'raw prose is not a proposal')
        assert summary.status!='SUCCEEDED' and not (work/'result.py').exists() and len(calls)==1
        assert store.load_result('p','r','writer').error is not None
        assert not list(store.run_dir('p','r').glob('publication_intents/*/*.json'))
    elif case=='budget':
        summary,store,_,_,calls,work=candidate_run(root,responder=lambda c:proposal(c['node_id'],[{'action':'read_file','path':'missing'}]))
        assert summary.status!='SUCCEEDED' and len(calls)==3
        assert 'NO_LOCAL_PROGRESS' in store.load_result('p','r','writer').error.message
        assert not (work/'result.py').exists()
    elif case=='self_repair':
        leaf=build_leaf_contract(goal='Repair based on actual local test observation',kind='IMPLEMENTATION',scope=['calc.py','test_calc.py'],
            acceptance=['current-contract'],checker='source',output_identity='calc',effect_domains=['filesystem','external_network','local_process'],
            executor='llm.cheap@1',expected_delta='Implement sum with local tests')
        node=CapabilityNode('writer',capability_ref='code',config={'executor_ref':'llm.cheap@1','leaf_contract':leaf})
        def response(c):
            obs=c.get('observations',[]);tests=[o for o in obs if o['action']=='run_tests']
            if not obs:return proposal(c['node_id'],[
                {'action':'write_file','path':'calc.py','content':'def add(a,b): return a-b\n'},
                {'action':'write_file','path':'test_calc.py','content':'from calc import add\ndef test_sum(): assert add(2,3)==5\n'}])
            if not tests:return proposal(c['node_id'],[{'action':'run_tests','path':'test_calc.py'}])
            if tests[-1]['status']=='FAILED' and obs[-1]['action']=='run_tests':
                assert tests[-1]['outputs']['test_observation']['status']!='PASS'
                return proposal(c['node_id'],[{'action':'patch_file','path':'calc.py','find':'a-b','replace':'a+b'}])
            if tests[-1]['status']=='FAILED':return proposal(c['node_id'],[{'action':'run_tests','path':'test_calc.py'}])
            assert tests[-1]['status']=='SUCCEEDED'
            return proposal(c['node_id'],[])
        summary,store,_,_,calls,work=candidate_run(root,nodes=(node,),responder=response)
        assert summary.status=='SUCCEEDED' and len(calls)==6
        result=store.load_result('p','r','writer')
        assert [o['status'] for o in result.outputs['action_results'] if o['action']=='run_tests']==['FAILED','SUCCEEDED']
        assert result.metadata['goal_acceptance']=='NOT_EVALUATED'
        assert (work/'calc.py').read_text()=='def add(a,b): return a+b\n'
    elif case in {'feedback','multi_feedback'}:
        def response(c):
            obs=c.get('observations',[])
            if not obs:return proposal(c['node_id'],[{'action':'read_file','path':'missing-spec.txt'}])
            assert obs[0]['status']=='FAILED' and obs[0]['error_type']=='FileNotFoundError'
            if len(obs)==1 and case=='multi_feedback':return proposal(c['node_id'],[{'action':'read_file','path':'second-missing.txt'}])
            if not any(o['action']=='write_file' for o in obs):return proposal(c['node_id'],[{'action':'write_file','path':'result.py','content':'value = 7\n'}])
            return proposal(c['node_id'],[])
        summary,store,_,_,calls,work=candidate_run(root,responder=response)
        assert summary.status=='SUCCEEDED' and len(calls)==(4 if case=='multi_feedback' else 3)
        assert store.load_result('p','r','writer').outputs['action_results'][0]['error_type']=='FileNotFoundError'
        assert (work/'result.py').read_text()=='value = 7\n'
    elif case in {'unchanged','invalid_candidate','independent_rejection'}:
        work=root/'work';work.mkdir(parents=True);(work/'result.py').write_text('value = 1\n');before=(work/'result.py').read_bytes()
        content='def broken(:\n' if case=='invalid_candidate' else 'value = 1\n' if case=='unchanged' else 'value = 2\n'
        check=(lambda r,c:{'passed':False,'observed':{'business':'original requirement still fails'}}) if case=='independent_rejection' else None
        summary,store,_,_,calls,work=candidate_run(root,files={'result.py':content},check=check)
        assert summary.status!='SUCCEEDED' and (work/'result.py').read_bytes()==before
        assert store.load_result('p','r','writer').metadata['deliverable_verdict']=='FAILED'
        assert not list(store.run_dir('p','r').glob('publication_intents/*/*.json'))
    elif case in {'reuse','stale','missing','history'}:
        summary,store,runner,tree,calls,work=candidate_run(root)
        assert summary.status=='SUCCEEDED' and len(calls)==2
        original=store.load_result('p','r','writer').as_dict();assert original['metadata']['node_commit_receipt_id']
        if case=='stale':(work/'result.py').write_text('value = 9\n')
        if case=='missing':(work/'result.py').unlink()
        if case in {'stale','missing'}:
            with pytest.raises(GraphEditRejected):runner.run(project_id='p',run_id='r',tree=tree,dag=compile_tree(tree),resume=True)
        else:
            resumed=runner.run(project_id='p',run_id='r',tree=tree,dag=compile_tree(tree),resume=True)
            assert resumed.reused_nodes==('writer',) and len(calls)==2
            assert store.load_result('p','r','writer').as_dict()==original
    elif case in {'partial','invalidation','parallel'}:
        nodes=[]
        for name,deps in [('first',()),('second',('first',)),('peer',())]:
            leaf=build_leaf_contract(goal='Independently owned '+name,kind='IMPLEMENTATION',scope=[name+'.py'],
                acceptance=['current-contract'],checker='source',output_identity=name,effect_domains=['filesystem','external_network'],
                executor='llm.cheap@1',dependencies=deps,expected_delta='Produce only the declared artifact')
            nodes.append(CapabilityNode(name,capability_ref='code',depends_on=deps,config={'executor_ref':'llm.cheap@1','leaf_contract':leaf}))
        def response(c):
            if case=='partial' and c['node_id']=='second':return proposal(c['node_id'],[],escalate=True)
            return proposal(c['node_id'],[] if c.get('observations') else [{'action':'write_file','path':c['node_id']+'.py','content':'value = 1\n'}])
        summary,store,runner,tree,calls,work=candidate_run(root,nodes=nodes,responder=response)
        assert (work/'first.py').read_text()=='value = 1\n' and (work/'peer.py').read_text()=='value = 1\n'
        first=store.load_result('p','r','first').as_dict()
        if case=='partial':
            assert not (work/'second.py').exists()
            assert store.load_result('p','r','second').status is BlockStatus.BLOCKED
            assert first['metadata']['node_commit_receipt_id']
        elif case=='invalidation':
            from cgkn.orchestration.invalidation import downstream_closure
            assert downstream_closure(compile_tree(tree),{'first'})==('first','second')
            assert downstream_closure(compile_tree(tree),{'second'})==('second',)
        else:
            # Independently owned exact outputs retain concurrent scheduling and distinct receipts.
            assert summary.status=='SUCCEEDED'
            assert len({store.load_result('p','r',n.id).metadata['node_commit_receipt_id'] for n in nodes})==3
            assert len(calls)==6
            from cgkn.adapters.veriarbor.dag_adapter import select_batch
            configs={n.id:{**runner._effective_config(n),'parallel_safe':True} for n in nodes if not n.depends_on}
            assert len(select_batch(configs,slots=4))==2
    else:raise AssertionError('unmapped migration behavior: '+case)


def semantic_submission(kwargs):
    """Explicit second fake response for historical one-write Worker fixtures."""
    packet=json.loads(kwargs['user'])
    if not isinstance(packet,dict) or 'paths' not in packet.get('tables',{}):return None
    aliases=packet.get('context_values',{})
    def expand(value, depth=0):
        if depth>16:raise AssertionError('invalid fixture context aliases')
        if isinstance(value,dict) and set(value)=={'$context_ref'}:return expand(aliases[value['$context_ref']],depth+1)
        if isinstance(value,list):return [expand(v,depth+1) for v in value]
        if isinstance(value,dict):return {k:expand(v,depth+1) for k,v in value.items()}
        return value
    context=expand(packet.get('context',{}))
    if any(o.get('action') in {'write_file','patch_file'} for o in context.get('observations',())):
        return ProviderCompletion(json.dumps({'op':5}),kwargs['config'].model_id or kwargs['config'].model,
            'explicit-candidate-submission',{'input_tokens':1,'output_tokens':1},raw_finish_reason='stop')
    return None


def candidate_submission(kwargs):
    from cgkn.protocol.adaptive_context import ContextPacker
    raw=ContextPacker.restore(json.loads(kwargs['user']))
    if 'node_id' not in raw:return None
    if any(o.get('action') in {'write_file','patch_file'} for o in raw.get('observations',())):
        return ProviderCompletion(json.dumps(proposal(raw['node_id'],[])),kwargs['config'].model_id or kwargs['config'].model,
            'explicit-candidate-submission',{'input_tokens':1,'output_tokens':1},raw_finish_reason='stop')
    return None

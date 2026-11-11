"""Tiny local records project. Public governance APIs only; zero network transport."""
from dataclasses import asdict
from pathlib import Path
import json

from cgkn.state import FileRunStore
from cgkn.agent.project_agent import AdmissionPolicy, ProjectProposal
from cgkn.orchestration.capability_tree import CapabilityTree, CapabilityNode
from cgkn.orchestration.leaf_contract import build_leaf_contract
from cgkn.runtime.node_authority import ExecutionAuthority,file_hash
from cgkn.runtime.governed import governed_node
from cgkn.adapters.veriarbor.capability_adapter import record_acceptance
from veriarbor.capability import CapabilityContract,AcceptanceMetric
from veriarbor.execution_authority import CriticalCheckRegistry,CriticalCheckSpec,DecisionRecord
from veriarbor.governance import InputBinding,EvaluationScope


def records_checker(decisions,context):
    permit=context['permit'];relations=[];derivations=[]
    for decision in decisions:
        rows=[]
        for ref in decision.input_refs:
            rows.extend(json.loads(Path(ref).read_text(encoding='utf-8'))['records'])
        values={r.get('state') for r in rows}
        relation='CONTRADICTS' if 'not-ready' in values else 'SUPPORTS' if values=={'ready'} else 'INSUFFICIENT'
        relations.append(dict(relation_id='relation-'+decision.decision_id,claim_ref=decision.claim_ref,
            evidence_refs=list(decision.input_refs),relation=relation,reason_code='LOCAL_RECORD_STATE',
            scope={k:permit[k] for k in ('project_id','run_id','node_id')}))
        derivations.extend(dict(record_id=r['id'],independence_key=r['event'],derivation_type='DIRECT') for r in rows)
    return dict(status='PASS',claim_relations=relations,derivations=derivations)


def report_outcome(decisions,context):
    receipt=context['receipt']
    outputs=[json.loads(Path(p).read_text(encoding='utf-8')) for p in receipt['output_hashes']]
    valid=bool(outputs) and all(o.get('claim')=='all records ready' and o.get('independent_count',0)>=2 for o in outputs)
    return {'observations':{'quality':{'actual':valid,'conclusion_scope':'POPULATION'},
                            'transfer':{'actual':valid,'conclusion_scope':'POPULATION'}}}


def contract():
    return CapabilityContract('records@1','Report supported local readiness',
        critical_checks=(CriticalCheckSpec('support','records→supported claim','local.records'),),
        requires_claim_support=True,independence_policy={'minimum_count':2},
        evidence_requirements={'allow_imported_unmanaged':True},
        acceptance_metrics=(AcceptanceMetric('quality','==',True),AcceptanceMetric('transfer','==',True,'GENERALIZATION_VERIFIED')),
        generalization_requirement={'generalization_target':'local-records-v1'})


def setup(root,run_id='run',records=None):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    source=root/(run_id+'-source.json')
    source.write_text(json.dumps({'records':records if records is not None else [
        {'id':'a','event':'e1','state':'ready'},{'id':'b','event':'e2','state':'ready'}]}),encoding='utf-8')
    registry=CriticalCheckRegistry();registry.register('local.records',records_checker,version='1',policy={'states':['ready','not-ready']})
    registry.register('local.outcome',report_outcome,version='1',role='OUTCOME')
    authority=ExecutionAuthority(FileRunStore(root/'runs'),'veriarbor-core-governance-e2e-v1',run_id,registry=registry)
    return authority,contract(),source


def session(authority,c,node_id,source,*,tree=None,version=1,producer=None,domains=('filesystem',),**options):
    tree=tree or CapabilityTree('ROOT',(CapabilityNode('ROOT'),))
    leaf=build_leaf_contract(goal='Validate local records',kind='INSPECTION',scope=['records/'+node_id],
        acceptance=['probe_observation'],checker='local.records',output_identity='records/'+node_id,
        effect_domains=list(domains),executor='local.worker@1',dependencies=[],subject='records/'+node_id,
        expected_observation='supported readiness',pass_fail_rule='registered record checker')
    catalog={c.capability_id:{'executor_ref':'local.worker@1','config':{'leaf_contract':leaf}}}
    proposal=ProjectProposal('proposal-'+node_id+'-'+str(version),authority.project_id,version,'ROOT',(),
        ({'operation':'add_node','node_id':node_id,'parent_id':'ROOT','capability_ref':c.capability_id},),
        reason_summary='One frontier local records',target_capability_id=c.capability_id,strategy_capabilities=(c.capability_id,),
        exploration_reason='offline deterministic verification',exploration_budget=1,exploration_measure='supported claim')
    policy=AdmissionPolicy(project_id=authority.project_id,capability_contracts={c.capability_id:asdict(c)},
        allow_remote_effects=True,execution_budget={'calls':2,'cost':1.0})
    binding=InputBinding(str(source),str(source),file_hash(source),node_id,context={'dataset':'local-v1'},
        producer_receipt_id=producer,execution_mode='GOVERNED' if producer else 'IMPORTED_UNMANAGED',
        requirements={'context':{'dataset':'local-v1'}})
    return governed_node(authority,tree=tree,tree_version=version,proposal=proposal,node_id=node_id,contract=c,
        known_capabilities={c.capability_id},catalog=catalog,policy=policy,input_manifest=(binding,),**options)


def execute(node,source,*,operation='PRODUCT_EXPORT',fake_provider=False,consumed_inputs=None):
    from veriarbor.governance import count_independent
    rows=json.loads(Path(source).read_text(encoding='utf-8'))['records']
    with node:
        node.record_decision(DecisionRecord('decision-'+node.node_id,'records→supported claim','local-record-rule',
            input_refs=(str(source),),output_claim='all records ready',claim_ref='claim:ready',check_id='support'))
        count=count_independent([dict(record_id=r['id'],independence_key=r['event']) for r in rows])
        report={'records':rows,'claim':'all records ready','independent_count':count}
        if fake_provider:output=node.provider_result(lambda:report,resource_usage={'calls':1,'cost':0.01})
        else:output=node.write_json('report.json',report,operation=operation)
        node.submit_result((output,),evidence_refs=(str(source),),claim_refs=('claim:ready',),consumed_inputs=consumed_inputs)
    return output,node.receipt


def accept(authority,c,receipt,sample,*,strategy='FULL_POPULATION',conclusion='POPULATION'):
    scope=EvaluationScope('evaluation-'+receipt.node_id,str(sample),str(sample),file_hash(sample),strategy,
        'all local rows' if strategy=='FULL_POPULATION' else 'selected rows','NONE' if strategy=='FULL_POPULATION' else 'KNOWN',
        'local population',(conclusion,),{},population_hash=file_hash(sample),generalization_target='local-records-v1')
    oid=authority.evaluate_outcome(receipt.receipt_id,'local.outcome',evaluation_scope=scope.as_dict())
    return record_acceptance(authority.store,authority.project_id,authority.run_id,receipt.node_id,c,{},
        object_versions={},checker_versions={},strategy_capabilities=(c.capability_id,),commit_receipt_id=receipt.receipt_id,
        outcome_receipt_ids=(oid,))


def admit_repair(authority,c,node):
    from cgkn.orchestration.capability_tree import CapabilityTree
    current=authority.committed_tree();tree=CapabilityTree.from_dict(current['tree'])
    proposal=ProjectProposal('repair-'+node.permit_id,authority.project_id,current['tree_version'],'ROOT',(),
        ({'operation':'retry_node','node_id':node.node_id},),reason_summary='repair blocked local attempt',
        target_capability_id=c.capability_id,strategy_capabilities=(c.capability_id,),
        exploration_reason='offline repair',exploration_budget=1,exploration_measure='supported result')
    policy=AdmissionPolicy(project_id=authority.project_id,capability_contracts={c.capability_id:asdict(c)},
        allow_remote_effects=True,execution_budget={'calls':2,'cost':1.0})
    aid,result=authority.admit(tree,current['tree_version'],proposal,known_capabilities={c.capability_id},catalog={},policy=policy)
    if not result.valid:raise ValueError(result.code)
    return authority.commit_tree(aid)


def run(root):
    a,c,source=setup(root);tree=None;version=1;producer=None;receipts=[]
    for name in ('extract_claim','aggregate_support','publish_report'):
        first=name=='extract_claim'
        node=session(a,c,name,source,tree=tree,version=version,producer=producer,
                     domains=('external_network',) if first else ('filesystem',))
        source,receipt=execute(node,source,fake_provider=first)
        gates=accept(a,c,receipt,source)
        if gates.generalization_status!='PASS':raise AssertionError(gates)
        tree=node.tree;version=node.tree_version;producer=receipt.receipt_id;receipts.append(receipt.as_dict())
    views={name:a.node_runtime_record(name).as_dict() for name in ('extract_claim','aggregate_support','publish_report')}
    result={'status':'PASS','real_provider_calls':0,'fake_provider_calls':1,'tree_version':version,
            'receipts':receipts,'nodes':views,'event_count':len(a.events()),'final_report':str(source)}
    Path(root,'E2E_RESULT.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True)
    args=parser.parse_args();print(json.dumps({'status':run(args.output)['status'],'real_provider_calls':0}))

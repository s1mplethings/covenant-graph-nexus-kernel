"""Explicit fixture builders for scheduler *observations*, not business delivery.

Only scheduler tests opt in. Production validation and the canonical runner are
unchanged. A probe delivers a checked measurement; business effects remain checked
by each test's original assertions or a separately registered application checker.
"""
from cgkn.orchestration.capability_tree import CapabilityNode
from cgkn.orchestration.leaf_contract import build_leaf_contract
from cgkn.execution.deliverables import SubjectDeliverableChecker
from cgkn.runtime import DAGRunner
from cgkn.state.task_feedback import digest


def probe_node(id, parent_id='', capability_ref='', depends_on=(), config=None):
    cfg=dict(config or {})
    if capability_ref:
        ref=cfg.setdefault('executor_ref','unregistered.fixture@1')
        cfg['leaf_contract']=build_leaf_contract(goal='Observe bounded scheduler probe '+id,
            kind='INSPECTION',scope=['probe/'+id],acceptance=['probe_observation'],
            checker='fixture.probe',output_identity='probe/'+id,effect_domains=['probe/'+id],
            executor=ref,dependencies=depends_on,subject='probe/'+id,
            expected_observation='node identity, configuration echo, or monotonic executor interval',
            pass_fail_rule='independent fixture checker verifies the declared observation')
    return CapabilityNode(id,parent_id,capability_ref,tuple(depends_on),cfg)


def check_probe(request, contract):
    receipt=request.as_dict()['input_values']['execution_receipt']
    outputs=receipt['outputs']
    # These are concrete observation schemas emitted by scheduler test executors.
    # Empty output or a claimed success alone cannot satisfy this checker.
    passed=(outputs.get('node')==request.node_id or
        outputs.get('original')==request.task_context.as_dict()['node_config'] or
        (isinstance(outputs.get('start'),(float,int)) and
         isinstance(outputs.get('end'),(float,int)) and outputs['end']>=outputs['start']))
    return {'passed':bool(passed),'observed':dict(outputs) or {'missing':'probe observation'},
            'evidence_refs':[dict(request.input_values['execution_receipt_ref'])]}


def probe_runner(registry, store, **kwargs):
    import json
    def observed(request, contract):
        value=check_probe(request,contract)
        outputs=request.as_dict()['input_values']['execution_receipt']['outputs']
        evaluation=outputs.get('evaluation')
        if isinstance(evaluation,dict):
            target=request.input_values['execution_receipt'].get('metadata',{}).get('source_identity')
            identity=evaluation.get('identity','')
            revision=evaluation.get('revision')
            store._validate_segment(identity)
            if isinstance(revision,int) and revision>0:
                path=store.run_dir(request.project_id,request.run_id)/'evaluations'/identity/f'{revision:06d}.json'
                value['passed']=path.is_file() and json.loads(path.read_text(encoding='utf-8'))==evaluation
                value['observed']={'evaluation_identity':identity,'revision':revision,'stored':value['passed']}
        return value
    try:registry.resolve('deliverable.subjects@1','deliverable.check@1')
    except LookupError:
        registry.register(SubjectDeliverableChecker(
            lambda c:{name:digest({'subject':name,'condition':list(c['acceptance'])}) for name in c['target_scope']},
            {'probe_observation':observed}))
    return DAGRunner(registry,store,deliverable_checkers={'fixture.probe':'deliverable.subjects@1'},**kwargs)


def measurement_runner(registry, store, checks, **kwargs):
    """Fixture-specific validators for actual observations, no status-only rule."""
    def measure(request, contract):
        outputs=request.as_dict()['input_values']['execution_receipt']['outputs']
        return {'passed':checks[request.node_id](outputs), 'observed':outputs or {'missing':'observation'},
                'evidence_refs':[dict(request.input_values['execution_receipt_ref'])]}
    registry.register(SubjectDeliverableChecker(
        lambda c:{name:digest({'subject':name,'condition':list(c['acceptance'])}) for name in c['target_scope']},
        {'probe_observation':measure}))
    return DAGRunner(registry,store,deliverable_checkers={'fixture.probe':'deliverable.subjects@1'},**kwargs)

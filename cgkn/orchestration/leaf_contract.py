"""Versioned, deterministic admission for executable leaves.

This validates proposals; it never decomposes a business goal for the Agent.
Historical graphs can still be deserialized without executing them.
"""
from collections.abc import Mapping
from pathlib import PurePosixPath

KINDS = frozenset({'RESEARCH', 'READ_ONLY_ANALYSIS', 'IMPLEMENTATION', 'REPAIR',
                   'TEST', 'INSPECTION', 'INTEGRATION', 'DELIVERY'})
WRITING = frozenset({'IMPLEMENTATION', 'REPAIR', 'INTEGRATION', 'DELIVERY'})
CONTRACT_SCHEMA = {
    'type':'object',
    'required':['schema_version','leaf_goal','task_kind','target_scope','acceptance','checker_ref',
                'output_identity','effect_domains','executor_ref','dependencies'],
    'properties':{
        'schema_version':{'const':'1.0'},'leaf_goal':{'type':'string','minLength':1},
        'task_kind':{'enum':sorted(KINDS),'description':'IMPLEMENTATION/REPAIR create or change artifacts, including test source. TEST/INSPECTION measure existing subjects; RESEARCH/READ_ONLY_ANALYSIS cite sources.'},
        **{key:{'type':'array','items':{'type':'string','minLength':1},'minItems':1}
           for key in ('target_scope','acceptance','effect_domains')},
        'dependencies':{'type':'array','items':{'type':'string'},'description':'Exact ordered node IDs from the enclosing node depends_on; never filenames or output identities.'},
        **{key:{'type':'string','minLength':1} for key in ('checker_ref','output_identity','executor_ref')},
        'component_roots':{'type':'array','maxItems':4,'items':{'type':'string','minLength':1}},
        'max_candidate_files':{'type':'integer','minimum':1,'maximum':128},
        'expected_delta':{'type':'string','minLength':1},
        'source_refs':{'type':'array','items':{'type':'string'},'minItems':1},
        'completion_criterion':{'type':'string','minLength':1},
        'subject':{'type':'string','minLength':1},'expected_observation':{'type':'string','minLength':1},
        'pass_fail_rule':{'type':'string','minLength':1}
    },
    'allOf':[
        {'if':{'properties':{'task_kind':{'enum':sorted(WRITING)}}},
         'then':{'required':['expected_delta']}},
        {'if':{'properties':{'task_kind':{'enum':['RESEARCH','READ_ONLY_ANALYSIS']}}},
         'then':{'required':['source_refs','completion_criterion']}},
        {'if':{'properties':{'task_kind':{'enum':['TEST','INSPECTION']}}},
         'then':{'required':['subject','expected_observation','pass_fail_rule']}}
    ]
}


def build_leaf_contract(*, goal, kind, scope, acceptance, checker, output_identity,
                        effect_domains, executor, dependencies=(), **details):
    """Explicit constructor for new proposals, never a historical-data upgrade.

    Callers supply business semantics. Validation is identical to model proposals;
    this helper does not infer a checker, goal, decomposition or acceptance rule.
    """
    from .capability_tree import CapabilityNode
    contract = dict(details, schema_version='1.0', leaf_goal=goal, task_kind=kind,
                    target_scope=list(scope), acceptance=list(acceptance),
                    checker_ref=checker, output_identity=output_identity,
                    effect_domains=list(effect_domains), executor_ref=executor,
                    dependencies=list(dependencies))
    validate_leaf(CapabilityNode('contract-preview', capability_ref='contract.preview@1',
        depends_on=tuple(dependencies), config={'executor_ref':executor, 'leaf_contract':contract}))
    return contract


class LeafContractError(ValueError):
    def __init__(self, node_id, verdict, reasons):
        self.details = {'node_id': node_id, 'verdict': verdict, 'reasons': reasons,
                        'suggested_actions': ['inspect', 'split', 'revise_contract']}
        super().__init__(f'{verdict}:{node_id}:' + ';'.join(reasons))


def validate_leaf(node, *, has_children=False, max_artifacts=8):
    if not node.executable:
        return 'COMPOSITE'
    if has_children:
        raise LeafContractError(node.id, 'NEEDS_DECOMPOSITION', ['composite nodes cannot execute'])
    c = node.config.get('leaf_contract')
    errors = []
    if not isinstance(c, Mapping):
        raise LeafContractError(node.id, 'INVALID_CONTRACT', ['ExecutionLeafContract required'])
    from .capability_tree import _thaw
    from jsonschema import Draft202012Validator
    schema_errors = sorted(Draft202012Validator(CONTRACT_SCHEMA).iter_errors(_thaw(c)),key=lambda e:str(e.path))
    if schema_errors:
        raise LeafContractError(node.id,'INVALID_CONTRACT',[e.message for e in schema_errors])
    for key in ('leaf_goal', 'task_kind', 'target_scope', 'acceptance', 'checker_ref',
                'output_identity', 'effect_domains', 'executor_ref'):
        if not c.get(key): errors.append('missing ' + key)
    if c.get('schema_version') != '1.0': errors.append('unsupported contract version')
    if c.get('task_kind') not in KINDS: errors.append('unknown task kind')
    if c.get('executor_ref') != node.config.get('executor_ref'): errors.append('executor identity mismatch')
    if tuple(c.get('dependencies', ())) != node.depends_on: errors.append('dependency identity mismatch')
    scope = c.get('target_scope', ())
    roots = c.get('component_roots', ())
    if not isinstance(roots, (list, tuple)) or len(roots)>4:
        errors.append('bounded component roots required')
        roots=()
    for name in roots:
        p=PurePosixPath(str(name))
        if not isinstance(name,str) or not p.parts or p.is_absolute() or '..' in p.parts or any(x in name for x in '*?\\:') or any(x.startswith('.') or x=='inputs' for x in p.parts):
            errors.append('unsafe component root')
    from cgkn.execution.file_actions import writable_path
    if any(writable_path(c, name) for name in c.get('read_scope',())):
        errors.append('read-only input overlaps write authorization')
    if not isinstance(scope, (list, tuple)) or not scope: errors.append('scope must name artifacts')
    else:
        for path in scope:
            p = PurePosixPath(str(path))
            if not isinstance(path, str) or not path or path in {'.','/'} or p.is_absolute() or '..' in p.parts or any(x in path for x in '*?\\:'):
                errors.append('unbounded or unsafe scope')
        if len(set(scope)) != len(scope): errors.append('duplicate scope')
    if not isinstance(c.get('acceptance'), (list, tuple)) or not all(isinstance(x,str) and x.strip() for x in c.get('acceptance',())):
        errors.append('acceptance must name independent observable checks')
    if c.get('task_kind') in WRITING and not c.get('expected_delta'): errors.append('expected delta required')
    if c.get('task_kind') in {'RESEARCH','READ_ONLY_ANALYSIS'}:
        if not c.get('source_refs') or not c.get('completion_criterion'): errors.append('research sources and criterion required')
    if c.get('task_kind') in {'TEST','INSPECTION'}:
        if not c.get('subject') or not c.get('expected_observation') or not c.get('pass_fail_rule'): errors.append('test subject and observation rule required')
    if errors: raise LeafContractError(node.id, 'INVALID_CONTRACT', errors)
    domains = c['effect_domains']
    if not isinstance(domains,(tuple,list)) or not all(isinstance(d,str) and d.strip() for d in domains):
        raise LeafContractError(node.id,'INVALID_CONTRACT',['invalid effect domains'])
    # A bounded file Worker needs both its model transport and file effect
    # grants. They are still enforced individually by Permit at dispatch.
    # Transport is not a second independently deliverable business frontier.
    supporting_model_transport=(str(c.get('executor_ref','')).startswith('llm.')
        and set(domains) in ({'filesystem','external_network'}, {'filesystem','external_network','local_process'}))
    if len(scope) > max_artifacts or (len(set(domains)) > 1 and not supporting_model_transport and not (c.get('executor_ref')=='local.component@1' and c.get('atomic_component') is True and set(domains)=={'filesystem','local_process'}) and not c.get('atomic_repair_justification')):
        raise LeafContractError(node.id,'NEEDS_DECOMPOSITION',['artifact bound exceeded or independent effect domains'])
    if c.get('atomic_repair_justification') and c['task_kind'] != 'REPAIR':
        raise LeafContractError(node.id,'NEEDS_DECOMPOSITION',['cross-domain exception requires justified atomic repair'])
    return 'BOUNDED'


def validate_tree_leaves(tree):
    parents = {n.parent_id for n in tree.nodes if n.parent_id}
    return {n.id: validate_leaf(n, has_children=n.id in parents) for n in tree.nodes}

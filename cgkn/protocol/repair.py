"""Repair contracts and intent at the existing semantic compiler boundary.

These are immutable views/projections of FileRunStore evidence, not another
planner, scheduler, state store, or acceptance authority.
"""
from collections.abc import Mapping
import json,hashlib
from .normalization import ContractError, digest

ACTIONS_V2 = {0:'KEEP', 1:'ADD_TASK', 2:'SPLIT_TASK', 3:'RETRY_EXECUTION',
    4:'REPAIR_IMPLEMENTATION', 5:'CHANGE_STRATEGY', 6:'INSPECT',
    7:'ADD_DEPENDENCY', 8:'REPLAN', 9:'FINISH', 10:'ESCALATE'}
ACTION_RULES = {
    0:'Execute existing ready work without changing its contract.',
    1:'Add one bounded task using an available target row.',
    2:'Split a target into explicit bounded children; preserve requirements. Select goal_ref from the goals table to bind the composite to a registered independent acceptance goal covering every child scope. A child success is not parent acceptance.',
    3:'Same goal, expected, acceptance, interface and dependencies. Only action,target needed. Not implementation repair.',
    4:'Fix implementation of an existing target after observed business failure. Keep original public contract; supply repair goal, expected, accept, scope, deps and task_kind=3.',
    5:'Change implementation strategy of an existing target while preserving public requirements.',
    6:'Add a read-only test/inspection task on an available target.',
    7:'Add explicit dependencies to an existing target.',
    8:'Bounded replan of a target and dependencies; carry original goal and all goal-state obligations forward.',
    9:'Request finish; independent GoalAcceptance remains authoritative.',
    10:'Escalate with a goal explaining the unresolved prerequisite.'}


def planner_schema_v2():
    from .admission import PLANNER_SCHEMA
    schema=plain(PLANNER_SCHEMA)
    schema['properties']['failed_acceptance_ids']={'type':'array','items':{'type':'string'}}
    schema['properties']['children']={'type':'array','minItems':2,'maxItems':4,'items':plain(PLANNER_SCHEMA)}
    schema['properties']['goal_ref']={'type':'integer'}
    return schema


def plain(value):
    if isinstance(value,Mapping):return {str(k):plain(v) for k,v in value.items()}
    if isinstance(value,(tuple,list)):return [plain(v) for v in value]
    return value


class PublicContractRegistry:
    """One content-addressed declaration in the existing run store."""
    REQUIRED = {'contract_id','feature','source_decision','version','status','evidence_refs',
        'change_policy','definition','artifact_paths'}
    def __init__(self, document):
        self._json=json.dumps(plain(document),ensure_ascii=False,sort_keys=True,allow_nan=False)
        if set(self.document)!={'kind','entries'} or self.document['kind']!='PublicContractRegistry':
            raise ContractError('INVALID_PUBLIC_CONTRACT_REGISTRY')
        ids=[]
        for entry in self.document['entries']:
            if not self.REQUIRED <= set(entry) or not isinstance(entry['definition'],dict) or not entry['definition']:
                raise ContractError('INCOMPLETE_PUBLIC_CONTRACT')
            if not entry['artifact_paths'] or not entry['evidence_refs'] or not entry['source_decision']:
                raise ContractError('UNBOUND_PUBLIC_CONTRACT')
            required=entry.get('required_sections',[])
            if not isinstance(required,list) or not all(isinstance(k,str) for k in required):raise ContractError('INVALID_REQUIRED_CONTRACT_SECTIONS')
            if any(not entry['definition'].get(k) for k in required):
                raise ContractError('INCOMPLETE_PUBLIC_CONTRACT',details={'missing_sections':[k for k in required if not entry['definition'].get(k)]})
            ids.append(entry['contract_id'])
        if not ids or len(ids)!=len(set(ids)):raise ContractError('DUPLICATE_OR_EMPTY_CONTRACT_IDS')
        self.hash=digest(self.document)

    @property
    def document(self):return json.loads(self._json)

    def persist(self,store,project_id,run_id):
        path=store.run_dir(project_id,run_id)/'contracts'/(self.hash+'.json')
        store.immutable_json(path,self.document)
        return {'ref':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'registry_hash':self.hash}

    def select(self,paths):
        wanted=set(paths)
        return {'registry_hash':self.hash,'entries':[e for e in self.document['entries']
            if wanted.intersection(e['artifact_paths'])]}


def contract_diff(before,after):
    """Structural diff, conservative on semantic weakening: never guess equivalence."""
    before=plain(before);after=plain(after);changes=[]
    def walk(a,b,path):
        if a==b:return
        if isinstance(a,dict) and isinstance(b,dict):
            for key in sorted(set(a)|set(b)):
                if key not in a:changes.append({'path':path+[key],'kind':'added','new':b[key]})
                elif key not in b:changes.append({'path':path+[key],'kind':'removed','old':a[key]})
                else:walk(a[key],b[key],path+[key])
        else:changes.append({'path':path,'kind':'changed','old':a,'new':b})
    walk(before,after,[])
    return {'changes':changes,'drift_count':len(changes),'semantic_equivalence':'UNCHANGED' if not changes else 'UNPROVEN',
        'removed_requirements':[x for x in changes if x['kind']=='removed'],
        'added_requirements':[x for x in changes if x['kind']=='added'],
        'possible_weakening':[x for x in changes if x['kind']!='added']}


class RepairIntentClassifier:
    @staticmethod
    def classify(selected_action,failures,semantic_diff=None,target_state=None):
        domains={x.get('failure_domain','UNKNOWN') for x in failures}
        if 'outcome_unknown' in domains:return {'intent':'UNKNOWN','next_operation':'RECONCILE','automatic_retry':False}
        if domains and domains<= {'transport'}:return {'intent':'SAME_EXECUTION_RETRY','next_operation':'RETRY_EXECUTION'}
        if domains and domains<= {'schema'}:return {'intent':'UNKNOWN','next_operation':'SCHEMA_CORRECTION'}
        if selected_action==8 or 'decomposition' in domains:return {'intent':'TREE_REPLAN','next_operation':'REPLAN'}
        if selected_action==5:return {'intent':'STRATEGY_CHANGE','next_operation':'CHANGE_STRATEGY'}
        if domains.intersection({'business','field_mismatch','exception','idempotency','persistence'}):
            return {'intent':'IMPLEMENTATION_REPAIR','next_operation':'REPAIR_IMPLEMENTATION'}
        if selected_action==3 and not semantic_diff:return {'intent':'SAME_EXECUTION_RETRY','next_operation':'RETRY_EXECUTION'}
        return {'intent':'UNKNOWN','next_operation':'INSPECT','automatic_retry':False}


def failure_for_target(document,node_id,paths):
    from .context_pack import expand_failures
    return [f for f in expand_failures(document.get('repair_context',{}))
        if node_id in f.get('target_leaf_refs',[]) or set(paths).intersection(f.get('artifact_paths',[]))]


def repair_contract(packet,old_node,tree,snapshot,paths,dependencies,contracts):
    failures=failure_for_target(snapshot.document,old_node.id,paths)
    ids=[f['acceptance_id'] for f in failures if f.get('failure_domain')=='business']
    selected=packet.get('failed_acceptance_ids',ids)
    if not selected or not isinstance(selected,list) or not set(selected)<=set(ids):
        raise ContractError('REPAIR_REQUIRES_OBSERVED_FAILURE',fields=('failed_acceptance_ids',),repair_class='R5',
            details={'allowed_values':ids,'allowed_action_ids':[6,8,10]})
    if not contracts['entries']:raise ContractError('REPAIR_PUBLIC_CONTRACT_MISSING')
    old_contracts=plain(old_node.config.get('public_contracts',contracts))
    difference=contract_diff(old_contracts,contracts)
    if difference['drift_count']:raise ContractError('REPAIR_PUBLIC_CONTRACT_DRIFT',details={'contract_diff':difference})
    relevant=[f for f in failures if f['acceptance_id'] in selected]
    strategy=digest({k:packet.get(k) for k in ('target','goal','expected','scope','deps')})
    history=snapshot.document.get('repair_context',{}).get('previous_repair_attempts',[])
    if len(history)>=2 and all(x.get('strategy_fingerprint')==strategy and x.get('status') in {'REPAIR_NO_PROGRESS','REPAIR_REGRESSION'} for x in history[-2:]):
        raise ContractError('REPEATED_REPAIR_NO_PROGRESS',fields=('action',),repair_class='R6',
            details={'allowed_action_ids':[5,6,8],'correction_path_terminated':True,'previous_repair_attempts':history[-2:]})
    if not all(f.get('evidence_refs') and f.get('object_identity') for f in relevant):
        raise ContractError('REPAIR_FAILURE_EVIDENCE_UNBOUND')
    return {'kind':'RepairContractV1','strategy_fingerprint':strategy,'parent_goal_ref':digest(tree.goal),'immutable_goal':tree.goal,
        'target_leaf_ref':old_node.id,'failed_acceptance_ids':selected,
        'observed_actual':[{k:f.get(k) for k in ('acceptance_id','actual','object_identity','failure_code')} for f in relevant],
        'expected_behavior':[{k:f.get(k) for k in ('acceptance_id','expected')} for f in relevant],
        'relevant_artifact_refs':paths,'allowed_write_scope':paths,
        'immutable_contract_refs':{'registry_hash':contracts['registry_hash'],'contract_ids':[e['contract_id'] for e in contracts['entries']]},
        'immutable_acceptance':plain(old_node.config.get('semantic_acceptance',[])),
        'repair_goal':packet['goal'],'repair_expected_delta':packet['expected'],
        'repair_acceptance':packet['accept'],'dependency_refs':dependencies,
        'evidence_refs':sorted({r for f in relevant for r in f['evidence_refs']}),
        'contract_diff':difference,'state':'REPAIR_ADMITTED'}


def repair_progress(previous,current,strategy_fingerprint,previous_attempts=()):
    before=set(previous);after=set(current);verified=before-after;regressed=after-before
    status='REPAIR_REGRESSION' if regressed else 'REPAIR_PROGRESS' if verified else 'REPAIR_NO_PROGRESS'
    repeated=bool(previous_attempts and status!='REPAIR_PROGRESS' and
        previous_attempts[-1].get('status')!='REPAIR_PROGRESS' and
        previous_attempts[-1].get('strategy_fingerprint')==strategy_fingerprint)
    return {'failed_before':sorted(before),'failed_after':sorted(after),'newly_verified_ids':sorted(verified),
        'regressions':sorted(regressed),'status':status,'strategy_fingerprint':strategy_fingerprint,
        'next_operation':'CHANGE_STRATEGY_OR_INSPECT_OR_REPLAN' if repeated else 'CONTINUE',
        'code':'REPEATED_REPAIR_NO_PROGRESS' if repeated else status}

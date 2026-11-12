"""Pure admission at the existing compiler boundary; no state or dispatch authority."""
from .normalization import ContractError, digest

PLANNER_FIELDS=frozenset(('action','task_kind','target','goal','scope','expected','accept','deps','capability','confidence','needs_user','sources'))
WORKER_FIELDS=frozenset(('op','path','payload','expected_local_effect','escalation'))
MECHANICAL_FIELDS=frozenset(('capability_ref','executor_ref','checker_ref','schema_version','provenance','internal_effects','run_id','output_identity'))
PLANNER_SCHEMA={'type':'object','additionalProperties':False,
    'properties':{key:({'type':'integer'} if key in {'action','task_kind','target','capability'} else
        {'type':'array','items':{'type':'integer'}} if key in {'scope','deps','sources'} else
        {'type':'array','items':{'type':'string'}} if key in {'expected','accept'} else
        {'type':'boolean'} if key=='needs_user' else {'type':'number'} if key=='confidence' else {'type':'string'}) for key in sorted(PLANNER_FIELDS)},
    'required':['action']}


class CapabilityScopeCompatibility:
    """One derived graph over the immutable, request-local registry snapshot."""
    def __init__(self,document):
        self.capabilities=document.get('capabilities',[])
        self.scopes=document.get('scopes',[])
        self.pairs={i:[j for j,s in enumerate(self.scopes)
            if s.get('allowed_capabilities') is None or c['capability_ref'] in s['allowed_capabilities']]
            for i,c in enumerate(self.capabilities)}

    def public(self):
        return [{'capability_id':i,'allowed_scope_ids':v} for i,v in self.pairs.items()]

    def resolve(self,packet,snapshot):
        kind=packet.get('task_kind');scopes=packet.get('scope',[])
        candidates=[i for i,c in enumerate(self.capabilities) if kind in c['task_kinds']]
        if not candidates:
            raise rejection('TASK_KIND_UNAVAILABLE',packet,snapshot,'task_kind',
                sorted({k for c in self.capabilities for k in c['task_kinds']}),status='REPLAN_REQUIRED',
                instruction='Select a task kind supported by the current capabilities. IMPLEMENTATION=2 writes source, test files or documentation. TEST=4 executes an admitted measurement; it does not author test files. Preserve the public goal; no semantics are changed automatically.')
        compatible=[i for i in candidates if all(s in self.pairs[i] for s in scopes)]
        explicit=packet.get('capability')
        if 'capability' in packet:
            snapshot.field_row('capabilities',explicit,'capability')
            if explicit not in candidates:
                raise rejection('CAPABILITY_KIND_CONTRADICTION',packet,snapshot,'capability',candidates,status='REPLAN_REQUIRED')
            chosen=explicit
        elif len(compatible)==1:chosen=compatible[0]
        elif len(candidates)==1:chosen=candidates[0]
        else:
            raise rejection('CAPABILITY_SELECTION_REQUIRED',packet,snapshot,'capability',compatible,
                status='REPAIRABLE_SEMANTIC' if compatible else 'REPLAN_REQUIRED')
        invalid=[s for s in scopes if s not in self.pairs[chosen]]
        if invalid:
            raise rejection('SCOPE_CAPABILITY_DENIED',packet,snapshot,'scope',self.pairs[chosen],
                status='REPAIRABLE_SEMANTIC' if self.pairs[chosen] else 'REPLAN_REQUIRED',
                capability_id=chosen,requested_scope_ids=scopes,invalid_scope_ids=invalid,
                allowed_scope_ids=self.pairs[chosen],can_preserve_intent=bool(self.pairs[chosen]))
        return chosen


def rejection(code,packet,snapshot,field,allowed,*,status='REPAIRABLE_SEMANTIC',**extra):
    return ContractError(code,fields=(field,),repair_class='R5' if status=='REPAIRABLE_SEMANTIC' else 'R6',
        vector_key='invalid_registry_ids',details={'admission_status':status,'field':field,
        'current_value':packet.get(field),'allowed_values':allowed,'compatibility_snapshot':snapshot.hash,
        'can_preserve_intent':False,'auto_generate_semantics':False,**extra})


def planner_fields(snapshot):
    return PLANNER_FIELDS | ({'children','goal_ref','failed_acceptance_ids','strategy','hypothesis'} if snapshot.document.get('action_version')==2 else set())


def strip_proven_mechanical(packet,snapshot):
    """Strip only a redundant binding with a concrete equality proof, never intent."""
    allowed=planner_fields(snapshot)
    extras=set(packet)-allowed
    if not extras:return dict(packet),[]
    clean={k:v for k,v in packet.items() if k in allowed}
    proof={};resolved=None
    if clean.get('action') in (1,4,5):
        try:resolved=snapshot.compatibility.resolve(clean,snapshot)
        except ContractError:
            candidates=[i for i,c in enumerate(snapshot.document.get('capabilities',[])) if clean.get('task_kind') in c['task_kinds']]
            if len(candidates)==1 and clean.get('capability',candidates[0])==candidates[0]:resolved=candidates[0]
    if resolved is not None:
        cap=snapshot.document['capabilities'][resolved]
        proof={k:cap[k] for k in ('capability_ref','executor_ref','checker_ref')}
    proof['schema_version']='1.0'
    safe={k for k in extras if k in proof and packet[k]==proof[k]}
    # A numeric capability_ref is an unambiguous duplicate of a local selection.
    if resolved is not None and type(packet.get('capability_ref')) is int and packet['capability_ref']==resolved:
        safe.add('capability_ref')
    unsafe=extras-safe
    if unsafe:
        raise ContractError('UNEXPECTED_PLANNER_FIELDS',fields=sorted(unsafe),repair_class='R6' if unsafe<=MECHANICAL_FIELDS else 'R7',
            details={'admission_status':'REPLAN_REQUIRED' if unsafe<=MECHANICAL_FIELDS else 'POLICY_DENIED',
                'current_value':{k:packet[k] for k in sorted(unsafe)},'allowed_values':sorted(allowed),
                'allowed_model_fields':sorted(allowed),'safe_strip_allowed':False,'compatibility_snapshot':snapshot.hash})
    receipt={'rule':'STRIPPED_FORBIDDEN_MECHANICAL_FIELD','fields':sorted(safe),
        'before_hash':digest(packet),'after_hash':digest(clean),'semantics_changed':False,
        'proof':'exact equality with deterministic bindings','snapshot_hash':snapshot.hash}
    return clean,[receipt]


class SemanticAdmissionPreflight:
    @staticmethod
    def evaluate(packet,snapshot,*,bound_hash,tree,context_identity):
        """Full canonical dry validation, with no persistence, execution or graph commit."""
        from .compiler import compile_planner
        try:
            result=compile_planner(packet,snapshot,bound_hash=bound_hash,tree=tree,context_identity=context_identity)
            return {'status':'ADMISSIBLE','table_hash':snapshot.hash,'mechanical_receipts':result['mechanical_receipts']}
        except ContractError as error:
            return {'status':error.details.get('admission_status',
                'REPAIRABLE_SEMANTIC' if error.repair_class=='R5' else 'REPLAN_REQUIRED' if error.repair_class=='R6' else 'POLICY_DENIED'),
                'error':error.as_dict(),'table_hash':snapshot.hash}

    @staticmethod
    def prepare(packet,snapshot,bound_hash):
        snapshot.bind(bound_hash)
        packet,receipts=strip_proven_mechanical(packet,snapshot)
        action=packet.get('action')
        if action in (1,4,5):
            snapshot.field_row('nodes',packet.get('target'),'target')
            for field,table in [('scope','scopes'),('deps','nodes')]:
                values=packet.get(field)
                if not isinstance(values,list) or (field=='scope' and not values):
                    raise rejection('ID_LIST_REQUIRED',packet,snapshot,field,list(range(len(snapshot.document.get(table,[])))))
                for value in values:snapshot.field_row(table,value,field)
            if type(packet.get('task_kind')) is int and packet['task_kind'] in range(8):
                try:snapshot.compatibility.resolve(packet,snapshot)
                except ContractError as error:
                    error.details['mechanical_receipts']=receipts
                    raise
        return packet,receipts


class WorkerAdmissionPreflight:
    @staticmethod
    def prepare(packet,snapshot,bound_hash):
        snapshot.bind(bound_hash)
        extras=set(packet)-WORKER_FIELDS
        if extras:
            raise ContractError('UNEXPECTED_WORKER_FIELDS',fields=sorted(extras),details={
                'admission_status':'POLICY_DENIED','allowed_values':sorted(WORKER_FIELDS),'safe_strip_allowed':False})
        if 'escalation' in packet and type(packet['escalation']) is not bool:
            raise rejection('BOOLEAN_REQUIRED',packet,snapshot,'escalation',[False,True])
        if 'expected_local_effect' in packet and (not isinstance(packet['expected_local_effect'],str) or not packet['expected_local_effect'].strip()):
            raise rejection('SEMANTIC_FIELD_REQUIRED',packet,snapshot,'expected_local_effect',['nonempty description'])
        if packet.get('escalation'):
            if set(packet)-{'escalation','expected_local_effect'}:
                raise rejection('ESCALATION_CONTRADICTION',packet,snapshot,'escalation',[False],status='REPLAN_REQUIRED')
            if not packet.get('expected_local_effect'):
                raise rejection('SEMANTIC_FIELD_REQUIRED',packet,snapshot,'expected_local_effect',['public reason for escalation'])
            return packet,[]
        op=packet.get('op')
        if type(op) is not int or op not in range(6):
            raise rejection('ACTION_ID_INVALID',packet,snapshot,'op',list(range(6)))
        if op==5:
            if set(packet)-{'op','expected_local_effect'}:raise ContractError('SUBMIT_WITH_UNRELATED_FIELDS')
            return packet,[]
        if op==4 and not snapshot.document.get('allow_local_tests'):
            raise ContractError('LOCAL_TEST_EFFECT_NOT_ADMITTED')
        row=snapshot.field_row('paths',packet.get('path'),'path')
        permission='writable' if op in (2,3,4) else 'readable'
        if row.get(permission) is not True:
            allowed=[i for i,p in enumerate(snapshot.document.get('paths',[])) if p.get(permission) is True]
            raise rejection('UNAUTHORIZED_WRITE' if permission=='writable' else 'UNAUTHORIZED_READ',packet,snapshot,'path',allowed,
                allowed_op_ids=[i for i in range(4) if row.get('writable' if i in (2,3) else 'readable') is True])
        return packet,[]


def invalid_decision_fingerprint(packet,error):
    semantic={k:packet.get(k) for k in ('action','target','task_kind','op','path')}
    for key in ('scope','deps'):semantic[key]=sorted(packet.get(key,[]),key=repr) if isinstance(packet.get(key,[]),list) else packet.get(key)
    semantic.update(code=error.code,invalid={k:packet.get(k) for k in error.fields})
    return digest(semantic)


class InvalidDecisionTracker:
    """Per-exchange projection; receipts remain the durable evidence authority."""
    def __init__(self):self.counts={}
    def observe(self,packet,error):
        fingerprint=invalid_decision_fingerprint(packet,error)
        count=self.counts.get(fingerprint,0)+1;self.counts[fingerprint]=count
        error.details.update(fingerprint=fingerprint,repeat_count=count,
            repetition_status='STRATEGY_EXHAUSTED' if count>=3 else 'REPEATED_INVALID_DECISION' if count==2 else 'FIRST_REJECTION',
            identical_retry_allowed=count<2,correction_path_terminated=bool(error.details.get('correction_path_terminated')) or count>=3)
        return count

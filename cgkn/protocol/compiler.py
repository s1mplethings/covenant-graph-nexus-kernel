"""Deterministic compiler; canonical validators remain authoritative."""
from __future__ import annotations
import json
from .normalization import ContractError,digest

ACTIONS={0:'KEEP',1:'ADD_TASK',3:'RETRY_TASK',4:'CHANGE_STRATEGY',5:'INSPECT',6:'ADD_DEPENDENCY',7:'FINISH',8:'ESCALATE'}
KINDS={0:'RESEARCH',1:'READ_ONLY_ANALYSIS',2:'IMPLEMENTATION',3:'REPAIR',4:'TEST',5:'INSPECTION',6:'INTEGRATION',7:'DELIVERY'}

class TableSnapshot:
    def __init__(self,document):
        self._json=json.dumps(document,sort_keys=True,ensure_ascii=False,allow_nan=False)
        self.hash=digest(document)
    @property
    def document(self):return json.loads(self._json)
    @property
    def public_document(self):
        """Model-facing row IDs; compiler-only identities remain server-owned."""
        result={}
        for name,rows in self.document.items():
            if name in {'repair_context','context_raw_ref','public_contract_registry_ref'}:continue
            if name=='public_contract_registry' and self.document.get('action_version')==2:
                result[name]={'kind':rows['kind'],'registry_hash':digest(rows),'entries':[
                    {k:v for k,v in e.items() if k in {'contract_id','version','definition','artifact_paths','change_policy'}} for e in rows['entries']]}
                continue
            if name not in {'nodes','scopes','capabilities','paths','sources','goals'}:
                result[name]=rows
                continue
            visible={
                'nodes':{'state','goal','target_version'},
                'scopes':{'path','purpose','interfaces'},
                'capabilities':{'task_kinds','description'},
                'paths':{'path','readable','writable'},
                'sources':{'ref','description'},
                'goals':{'acceptance','subject_refs','covered_artifact_paths'},
            }[name]
            result[name]=[{'id':index,**{k:v for k,v in row.items() if k in visible}} for index,row in enumerate(rows)]
            if self.document.get('action_version')==2:
                # The registry is the public contract authority. Scope signatures
                # were a legacy duplicate and must not compete with it.
                if name=='scopes':
                    for row in result[name]:row.pop('interfaces',None)
                if name=='nodes':
                    for row in result[name]:
                        if len(row.get('goal',''))>160:row['goal']=row['goal'][:160]+' [full target contract in referenced context]'
        if 'capabilities' in self.document:
            result['compatibility']=self.compatibility.public()
            for index,cap in enumerate(self.document['capabilities']):
                if cap.get('external_effect'):
                    result['capabilities'][index].update(requires_approval=True,approved=cap.get('authorized') is True)
        for name in ('nodes','scopes','capabilities','paths'):
            for row in result.get(name,[]):
                if self.document.get('action_version')!=2:
                    row['label']=str(row.get('purpose') or row.get('description') or row.get('path') or row.get('goal') or {'nodes':'node','scopes':'scope','capabilities':'capability','paths':'path'}[name])[:96]
        return result
    @property
    def compatibility(self):
        from .admission import CapabilityScopeCompatibility
        return CapabilityScopeCompatibility(self.document)
    def row(self,table,key):
        if type(key) is not int:raise ContractError('INTEGER_ID_REQUIRED',fields=(table,),repair_class='R5',vector_key='invalid_registry_ids')
        rows=self.document.get(table,[])
        if key<0 or key>=len(rows):raise ContractError('REGISTRY_ID_INVALID',fields=(table,),repair_class='R5',vector_key='invalid_registry_ids')
        return rows[key]
    def bind(self,expected_hash):
        if expected_hash!=self.hash or digest(self.document)!=self.hash:raise ContractError('STALE_TABLE',fields=('table_hash',),vector_key='invalid_registry_ids',details={'admission_status':'STALE_CONTEXT','expected_hash':expected_hash,'actual_hash':digest(self.document),'allowed_values':[self.hash]})

    def field_row(self,table,key,field):
        try:return self.row(table,key)
        except ContractError as exc:
            raise ContractError(exc.code,fields=(field,),repair_class=exc.repair_class,
                vector_key=next(k for k,v in exc.vector.items() if v),details={'field':field,'current_value':key,'allowed_values':list(range(len(self.document.get(table,[])))),'compatibility_snapshot':self.hash}) from exc


def _compile_worker(packet,snapshot,*,bound_hash,node_id):
    from cgkn.executors.llm import validate_worker_proposal
    from .admission import WorkerAdmissionPreflight
    packet,_=WorkerAdmissionPreflight.prepare(packet,snapshot,bound_hash)
    if packet.get('escalation'):
        return validate_worker_proposal({'schema_version':'1.0','node_id':node_id,'summary':packet['expected_local_effect'],
            'actions':[],'expected_outputs':[],'confidence':0.0,'needs_escalation':True,'escalation_reason':packet['expected_local_effect']},node_id)
    snapshot.bind(bound_hash)
    allowed={'op','path','payload','expected_local_effect','escalation'}
    if set(packet)-allowed:raise ContractError('UNEXPECTED_WORKER_FIELDS',fields=tuple(set(packet)-allowed))
    if 'op' not in packet or 'path' not in packet:raise ContractError('MISSING_ACTION',fields=tuple({'op','path'}-set(packet)),repair_class='R5',vector_key='missing_semantic_fields')
    op=packet['op']
    if type(op) is not int or op not in range(4):raise ContractError('ACTION_ID_INVALID',fields=('op',),repair_class='R5',vector_key='invalid_registry_ids')
    row=snapshot.field_row('paths',packet['path'],'path');path=row['path']
    from pathlib import PurePosixPath
    if not isinstance(path,str) or not path or path in {'.','/'} or PurePosixPath(path).is_absolute() or '..' in PurePosixPath(path).parts or any(c in path for c in '*?\\:') or any(p.lower() in {'.git','.hg','.svn'} for p in PurePosixPath(path).parts):raise ContractError('UNSAFE_REGISTERED_PATH')
    if op in (2,3) and row.get('writable') is not True:raise ContractError('UNAUTHORIZED_WRITE',fields=('path',))
    if op in (0,1) and row.get('readable') is not True:raise ContractError('UNAUTHORIZED_READ',fields=('path',))
    action={'action':('read_file','list_files','write_file','patch_file')[op],'path':path}
    if op==2:
        if not isinstance(packet.get('payload'),str):raise ContractError('WRITE_PAYLOAD_REQUIRED',fields=('payload',),repair_class='R5',vector_key='missing_semantic_fields')
        action['content']=packet['payload']
    elif op==3:
        payload=packet.get('payload')
        if not isinstance(payload,dict) or set(payload)!={'find','replace'} or not all(isinstance(x,str) for x in payload.values()):raise ContractError('PATCH_PAYLOAD_REQUIRED',fields=('payload',),repair_class='R5',vector_key='missing_semantic_fields')
        action.update(payload)
    elif 'payload' in packet:raise ContractError('READ_WITH_UNRELATED_PAYLOAD',fields=('payload',))
    result={'schema_version':'1.0','node_id':node_id,'summary':packet.get('expected_local_effect','Compiled bounded action'),
        'actions':[action],'expected_outputs':[path] if op in (2,3) else [],'confidence':0.0,
        'needs_escalation':False,'escalation_reason':''}
    return validate_worker_proposal(result,node_id)


def _compile_planner(packet,snapshot,*,bound_hash,tree,context_identity):
    from cgkn.orchestration.tree_edits import TreeEdit,apply_tree_edits
    from cgkn.orchestration.leaf_contract import build_leaf_contract
    from .admission import SemanticAdmissionPreflight
    packet,mechanical_receipts=SemanticAdmissionPreflight.prepare(packet,snapshot,bound_hash)
    snapshot.bind(bound_hash)
    allowed={'action','task_kind','target','goal','scope','expected','accept','deps','capability','confidence','needs_user','sources'}
    if set(packet)-allowed:raise ContractError('UNEXPECTED_PLANNER_FIELDS',fields=sorted(set(packet)-allowed))
    action=packet.get('action')
    if type(action) is not int or action not in ACTIONS:raise ContractError('ACTION_ID_INVALID',fields=('action',),repair_class='R5',vector_key='invalid_registry_ids')
    if 'needs_user' in packet and type(packet['needs_user']) is not bool:raise ContractError('BOOLEAN_REQUIRED',fields=('needs_user',),repair_class='R5')
    if packet.get('needs_user') and action!=8:raise ContractError('ESCALATION_CONTRADICTION',fields=('action','needs_user'),repair_class='R6',vector_key='semantic_contradictions')
    if 'confidence' in packet and (type(packet['confidence']) not in (int,float) or not 0<=packet['confidence']<=1):raise ContractError('CONFIDENCE_INVALID',fields=('confidence',),repair_class='R5')
    edits=[];identity=digest({'packet':packet,'table':bound_hash,'context':context_identity})[:24]
    provenance={'source':'semantic-compiler-v1','table_hash':bound_hash,'packet_hash':digest(packet),'context_identity':context_identity}
    def edit(operation,node_id,payload):
        edits.append(TreeEdit(identity+'-'+str(len(edits)),operation,node_id,payload,provenance))
    def text(key):
        value=packet.get(key)
        if not isinstance(value,str) or not value.strip():raise ContractError('SEMANTIC_FIELD_REQUIRED',fields=(key,),repair_class='R5',vector_key='missing_semantic_fields')
        return value
    def strings(key):
        value=packet.get(key)
        if not isinstance(value,list) or not value or not all(isinstance(x,str) and x.strip() for x in value):raise ContractError('SEMANTIC_LIST_REQUIRED',fields=(key,),repair_class='R5',vector_key='missing_semantic_fields')
        return value
    def ids(key,table,required=False):
        value=packet.get(key)
        if not isinstance(value,list) or (required and not value):raise ContractError('ID_LIST_REQUIRED',fields=(key,),repair_class='R5',vector_key='invalid_registry_ids')
        try:
            return [snapshot.row(table,x) for x in value]
        except ContractError as exc:
            # One registry can serve multiple semantic fields (target/deps).
            # Correction authority belongs to the exact field, not the table.
            raise ContractError(exc.code,fields=(key,),repair_class=exc.repair_class,
                vector_key=next(k for k,v in exc.vector.items() if v)) from exc
    if action in (0,7,8):
        if set(packet)-{'action','goal','confidence','needs_user'}:raise ContractError('CONTROL_WITH_UNRELATED_FIELDS')
        if action==8:text('goal')
        if action==0 and not any(n.executable for n in tree.nodes):raise ContractError('KEEP_WITHOUT_WORK',repair_class='R6',vector_key='semantic_contradictions')
    else:
        target=snapshot.field_row('nodes',packet.get('target'),'target');node_id=target['node_id']
        exists=node_id in tree.by_id
        if exists and target.get('target_version') and target['target_version']!=digest(tree.by_id[node_id].as_dict()):
            raise ContractError('STALE_TARGET',fields=('target',),details={'admission_status':'STALE_CONTEXT',
                'expected_hash':target['target_version'],'actual_hash':digest(tree.by_id[node_id].as_dict()),
                'allowed_values':['refresh target snapshot; do not reuse old local IDs'],'compatibility_snapshot':snapshot.hash})
        if action==3:
            if set(packet)-{'action','target','confidence','needs_user'}:raise ContractError('RETRY_CHANGES_SEMANTICS',repair_class='R6',vector_key='semantic_contradictions')
            if not exists:raise ContractError('RETRY_UNKNOWN_NODE',fields=('target',),repair_class='R5',vector_key='invalid_registry_ids')
            edit('retry_node',node_id,{})
        elif action==6:
            if set(packet)-{'action','target','deps','confidence','needs_user'}:raise ContractError('DEPENDENCY_WITH_UNRELATED_FIELDS')
            if not exists:raise ContractError('UNKNOWN_TARGET',fields=('target',),repair_class='R5',vector_key='invalid_registry_ids')
            for dep in ids('deps','nodes',True):edit('add_dependency',node_id,{'dependency':dep['node_id']})
        else:
            kind=packet.get('task_kind')
            if type(kind) is not int or kind not in KINDS:raise ContractError('TASK_KIND_INVALID',fields=('task_kind',),repair_class='R5',vector_key='invalid_registry_ids')
            if action==5 and kind not in (4,5):raise ContractError('INSPECT_WRITE_CONTRADICTION',fields=('task_kind',),repair_class='R6',vector_key='semantic_contradictions')
            if action==4 and not exists:raise ContractError('STRATEGY_TARGET_MISSING',fields=('target',),repair_class='R5',vector_key='invalid_registry_ids')
            if action in (1,5) and exists:raise ContractError('TARGET_ALREADY_EXISTS',fields=('target',),repair_class='R5',vector_key='invalid_registry_ids')
            scopes=ids('scope','scopes',True);deps=ids('deps','nodes')
            for dep in deps:
                if dep.get('target_version') and dep['node_id'] in tree.by_id and dep['target_version']!=digest(tree.by_id[dep['node_id']].as_dict()):
                    raise ContractError('STALE_DEPENDENCY',fields=('deps',),details={'admission_status':'STALE_CONTEXT',
                        'expected_hash':dep['target_version'],'actual_hash':digest(tree.by_id[dep['node_id']].as_dict()),
                        'allowed_values':['refresh dependency snapshot; do not reuse old local IDs'],'compatibility_snapshot':snapshot.hash})
            goal=text('goal');expected=strings('expected');accept=strings('accept')
            capabilities=snapshot.document['capabilities']
            cap=capabilities[snapshot.compatibility.resolve(packet,snapshot)]
            if kind not in cap['task_kinds']:raise ContractError('CAPABILITY_KIND_CONTRADICTION',fields=('capability','task_kind'),repair_class='R6',vector_key='semantic_contradictions')
            if cap.get('external_effect',False) and cap.get('authorized') is not True:raise ContractError('UNAUTHORIZED_EXTERNAL_EFFECT',fields=('capability',),details={
                'admission_status':'POLICY_DENIED','field':'capability','current_value':capabilities.index(cap),
                'allowed_values':[i for i,c in enumerate(capabilities) if not c.get('external_effect') or c.get('authorized') is True],
                'requires_approval':True,'approved':False,'compatibility_snapshot':snapshot.hash,'can_preserve_intent':False})
            paths=[s['path'] for s in scopes]
            dependencies=[d['node_id'] for d in deps]
            details={}
            if kind in (2,3,6,7):details['expected_delta']='\n'.join(expected)
            elif kind in (4,5):details.update(subject='\n'.join(paths),expected_observation='\n'.join(expected),pass_fail_rule='\n'.join(accept))
            else:details.update(source_refs=[r['ref'] for r in ids('sources','sources',True)],completion_criterion='\n'.join(accept))
            contract=build_leaf_contract(goal=goal,kind=KINDS[kind],scope=paths,acceptance=cap['acceptance_refs'],checker=cap['checker_ref'],
                output_identity=digest({'node':node_id,'scope':paths}),effect_domains=cap['effect_domains'],executor=cap['executor_ref'],dependencies=dependencies,**details)
            config={**cap.get('config',{}),'executor_ref':cap['executor_ref'],'leaf_contract':contract,
                'semantic_acceptance':accept,'semantic_expected':expected,'semantic_table_hash':bound_hash}
            config['interfaces']={s['path']:s.get('interfaces',{}) for s in scopes}
            read_scope=[]
            for dep in dependencies:
                if dep in tree.by_id:
                    read_scope.extend(tree.by_id[dep].config.get('leaf_contract',{}).get('target_scope',()))
            if read_scope:contract['read_scope']=sorted(set(read_scope))
            if action==4:
                if tree.by_id[node_id].capability_ref!=cap['capability_ref']:raise ContractError('STRATEGY_REQUIRES_REPLAN',repair_class='R6',vector_key='semantic_contradictions')
                if snapshot.document.get('action_version')==2:
                    for dep in sorted(set(tree.by_id[node_id].depends_on)-set(dependencies)):edit('remove_dependency',node_id,{'dependency':dep})
                    for dep in sorted(set(dependencies)-set(tree.by_id[node_id].depends_on)):edit('add_dependency',node_id,{'dependency':dep})
                edit('update_config',node_id,{'config':config});edit('retry_node',node_id,{})
            else:edit('add_node',node_id,{'capability_ref':cap['capability_ref'],'parent_id':target.get('parent_id',''),'depends_on':dependencies,'config':config})
    try:apply_tree_edits(tree,tuple(edits),known_capabilities={c['capability_ref'] for c in snapshot.document['capabilities']})
    except (ValueError,KeyError,TypeError) as exc:raise ContractError('CANONICAL_REJECTED:'+str(exc),repair_class='R6',vector_key='semantic_contradictions') from exc
    return {'edits':tuple(edits),'request_run':action not in (7,8),'finish':action==7,'needs_escalation':action==8,
            'reason':packet.get('goal',ACTIONS[action]),'decision_id':identity,'table_hash':bound_hash,'admission_status':'ADMISSIBLE','mechanical_receipts':mechanical_receipts}


def _feedback(error,packet,snapshot,worker=False):
    """Attach current public values without guessing a business diagnosis."""
    from .admission import PLANNER_FIELDS,WORKER_FIELDS
    if not error.fields:
        controls={'CONTROL_WITH_UNRELATED_FIELDS':{'action','goal','confidence','needs_user'},
            'RETRY_CHANGES_SEMANTICS':{'action','target','confidence','needs_user'},
            'DEPENDENCY_WITH_UNRELATED_FIELDS':{'action','target','deps','confidence','needs_user'}}
        if error.code in controls:error.fields=tuple(sorted(set(packet)-controls[error.code]))
        else:error.fields=({'UNSAFE_REGISTERED_PATH':('path',),'KEEP_WITHOUT_WORK':('action',),
            'STRATEGY_REQUIRES_REPLAN':('capability',)}.get(error.code,('$',)))
    values={key:(packet if key=='$' else packet.get(key)) for key in error.fields}
    error.details.setdefault('current_value',next(iter(values.values())) if len(values)==1 else values)
    error.details.setdefault('compatibility_snapshot',snapshot.hash)
    error.details.setdefault('auto_generate_semantics',False)
    error.details.setdefault('can_preserve_intent',False)
    allowed={}
    for field in error.fields:
        registry={'target':'nodes','deps':'nodes','scope':'scopes','capability':'capabilities','path':'paths','sources':'sources'}.get(field)
        if registry:allowed[field]=list(range(len(snapshot.document.get(registry,[]))))
        elif field=='action':allowed[field]=list(ACTIONS)
        elif field=='task_kind':allowed[field]=list(KINDS)
        elif field=='op':allowed[field]=list(range(4))
        elif field in ('goal','expected_local_effect'):allowed[field]=['non-empty public semantic text; must be supplied explicitly']
        elif field in ('expected','accept'):allowed[field]=['non-empty list of explicit public observable predicates']
        elif field=='payload':allowed[field]=['literal text' if packet.get('op')==2 else '{find: string, replace: string}' if packet.get('op')==3 else 'omit payload for reads']
        elif field=='confidence':allowed[field]=['number in [0,1]']
        elif field in ('needs_user','escalation'):allowed[field]=[False,True]
        else:allowed[field]={'allowed_fields':sorted(WORKER_FIELDS if worker else PLANNER_FIELDS),
            'constraint':str(error),'root_cause':'UNRESOLVED' if field=='$' else 'field not allowed for this action'}
    error.details.setdefault('allowed_values',next(iter(allowed.values())) if len(allowed)==1 else allowed)
    return error


def compile_worker(packet,snapshot,*,bound_hash,node_id):
    try:return _compile_worker(packet,snapshot,bound_hash=bound_hash,node_id=node_id)
    except ContractError as error:
        raise _feedback(error,packet,snapshot,True)


def compile_planner(packet,snapshot,*,bound_hash,tree,context_identity):
    try:
        if snapshot.document.get('action_version')==2:
            from .repair_compiler import compile_v2
            return compile_v2(packet,snapshot,bound_hash=bound_hash,tree=tree,context_identity=context_identity)
        return _compile_planner(packet,snapshot,bound_hash=bound_hash,tree=tree,context_identity=context_identity)
    except ContractError as error:
        raise _feedback(error,packet,snapshot)

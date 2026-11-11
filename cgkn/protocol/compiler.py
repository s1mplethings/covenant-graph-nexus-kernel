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
                'nodes':{'state','goal','target_version','execution_state','declared_target_scope','task_kind','dependency_ids'},
                'scopes':{'path','purpose','interfaces'},
                'capabilities':{'task_kinds','description'},
                'paths':{'path','readable','writable','observed_content_sha256'},
                'sources':{'ref','description'},
                'goals':{'acceptance','subject_refs','covered_artifact_paths'},
            }[name]
            result[name]=[{'id':index,**{k:v for k,v in row.items() if k in visible}} for index,row in enumerate(rows)]
            if name=='scopes' and any('task_kind' in n for n in self.document.get('nodes',[])):
                for row in result[name]:
                    row['writer_target_ids']=[i for i,n in enumerate(self.document.get('nodes',[]))
                        if n.get('task_kind') in {'IMPLEMENTATION','REPAIR','INTEGRATION','DELIVERY'}
                        and row['path'] in n.get('declared_target_scope',())]
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
    write_operations=snapshot.document.get('allowed_write_operations',[2,3])
    if op in (2,3) and op not in write_operations:
        raise ContractError('WRITE_OPERATION_POLICY_VIOLATION',fields=('op','payload'),repair_class='R6',
            vector_key='semantic_contradictions',details={
                'allowed_values':{'op':[0,1,*write_operations],'payload':'Complete file content string for op2; omit for reads'},
                'instruction':'The admitted strategy explicitly restricts write operations. For full_file_write=true use op2 with the complete current file and every required change. Changing only the opcode of a patch is invalid. Read/list and explicit missing-prerequisite escalation remain available. No implementation is supplied or transformed by this gate.'})
    if op in (0,1) and row.get('readable') is not True:raise ContractError('UNAUTHORIZED_READ',fields=('path',))
    if op==0 and row.get('observed_content_sha256'):
        raise ContractError('READ_ALREADY_IN_CONTEXT',fields=('op','path','payload','escalation','expected_local_effect'),repair_class='R5',
            vector_key='semantic_contradictions',details={'observed_path':path,
                'observed_content_sha256':row['observed_content_sha256'],
                'instruction':'The complete file content is already present in context observations (resolve context_values aliases). Repeating this read supplies no new evidence. Use the existing content and choose a new bounded action, read a different missing path, or explicitly escalate with the missing prerequisite. No automatic write or business patch is supplied.'})
    action={'action':('read_file','list_files','write_file','patch_file')[op],'path':path}
    if op==2:
        if not isinstance(packet.get('payload'),str):raise ContractError('WRITE_PAYLOAD_REQUIRED',fields=('payload',),repair_class='R5',vector_key='missing_semantic_fields')
        if row.get('observed_content_sha256')==digest(packet['payload'].encode('utf8')):
            raise ContractError('WRITE_UNCHANGED_CONTEXT',fields=('op','path','payload','escalation','expected_local_effect'),repair_class='R5',
                vector_key='semantic_contradictions',details={'observed_path':path,
                    'observed_content_sha256':row['observed_content_sha256'],
                    'instruction':'The proposed content is exactly the complete existing source in context. This performs no implementation change. Reconsider the bounded task and choose an actual change (prefer an exact local patch for a local repair), obtain missing evidence, or explicitly escalate. No business implementation is supplied; changing bytes alone never proves acceptance.'})
        action['content']=packet['payload']
    elif op==3:
        payload=packet.get('payload')
        patches=payload if isinstance(payload,list) else [payload]
        limit=snapshot.document.get('patch_batch_limit',1)
        if (type(limit) is not int or not 1<=limit<=8 or not 1<=len(patches)<=limit
                or any(not isinstance(p,dict) or set(p)!={'find','replace'}
                       or not all(isinstance(x,str) for x in p.values()) for p in patches)):
            raise ContractError('PATCH_PAYLOAD_REQUIRED',fields=('payload',),repair_class='R5',vector_key='missing_semantic_fields')
        if isinstance(payload,list) and (limit==1 or snapshot.document.get('allowed_write_operations')!=[3]):
            raise ContractError('PATCH_BATCH_POLICY_REQUIRED',fields=('payload',),repair_class='R5',vector_key='semantic_contradictions')
        action.update(patches[0])
    elif 'payload' in packet:raise ContractError('READ_WITH_UNRELATED_PAYLOAD',fields=('payload',),repair_class='R5',vector_key='semantic_contradictions',details={'instruction':'Remove the payload field entirely for read/list, including null. Keep the valid op and path unchanged; no automatic payload stripping or write is allowed.'})
    result={'schema_version':'1.0','node_id':node_id,'summary':packet.get('expected_local_effect','Compiled bounded action'),
        'actions':([{'action':'patch_file','path':path,**p} for p in patches] if op==3 else [action]),'expected_outputs':[path] if op in (2,3) else [],'confidence':0.0,
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
        def dependency_rows(required=False):
            rows=ids('deps','nodes',required)
            forbidden={node_id}
            if exists and rows:
                from cgkn.orchestration import compile_tree
                from cgkn.orchestration.invalidation import downstream_closure
                forbidden.update(downstream_closure(compile_tree(tree),{node_id}))
            if any(row['node_id'] in forbidden for row in rows):
                allowed=[i for i,row in enumerate(snapshot.document['nodes'])
                         if row['node_id'] in tree.by_id and tree.by_id[row['node_id']].executable
                         and row['node_id'] not in forbidden]
                code='SELF_DEPENDENCY' if any(row['node_id']==node_id for row in rows) else 'DEPENDENCY_CYCLE'
                existing_dependencies=[i for i,row in enumerate(snapshot.document['nodes'])
                    if exists and row['node_id'] in tree.by_id[node_id].depends_on]
                raise ContractError(code,fields=('deps',),repair_class='R6',vector_key='semantic_contradictions',details={
                    'field':'deps','current_value':packet['deps'],'allowed_values':allowed,
                    'existing_dependency_targets':existing_dependencies,
                    'instruction':'A task cannot depend on itself or its downstream closure. existing_dependency_targets lists the target task prerequisites in the current canonical graph; [] means no prerequisites. If preserving that graph is intended, explicitly resubmit those dependencies. For a deliberate dependency change, select intended prerequisites from allowed_values. No dependency is removed automatically; this graph rejection is not business failure evidence.',
                    'auto_generate_semantics':False,'can_preserve_intent':False})
            return rows
        if exists and target.get('target_version') and target['target_version']!=digest(tree.by_id[node_id].as_dict()):
            raise ContractError('STALE_TARGET',fields=('target',),details={'admission_status':'STALE_CONTEXT',
                'expected_hash':target['target_version'],'actual_hash':digest(tree.by_id[node_id].as_dict()),
                'allowed_values':['refresh target snapshot; do not reuse old local IDs'],'compatibility_snapshot':snapshot.hash})
        if action==3:
            if set(packet)-{'action','target','confidence','needs_user'}:raise ContractError('RETRY_CHANGES_SEMANTICS',repair_class='R6',vector_key='semantic_contradictions')
            if not exists:raise ContractError('RETRY_UNKNOWN_NODE',fields=('target',),repair_class='R5',vector_key='invalid_registry_ids')
            from cgkn.adapters.veriarbor.verification_adapter import reject_duplicate_measurement
            reject_duplicate_measurement(snapshot.document, node_id=node_id)
            edit('retry_node',node_id,{})
        elif action==6:
            if set(packet)-{'action','target','deps','confidence','needs_user'}:raise ContractError('DEPENDENCY_WITH_UNRELATED_FIELDS')
            if not exists:raise ContractError('UNKNOWN_TARGET',fields=('target',),repair_class='R5',vector_key='invalid_registry_ids')
            for dep in dependency_rows(True):edit('add_dependency',node_id,{'dependency':dep['node_id']})
        else:
            kind=packet.get('task_kind')
            if type(kind) is not int or kind not in KINDS:raise ContractError('TASK_KIND_INVALID',fields=('task_kind',),repair_class='R5',vector_key='invalid_registry_ids')
            if action==5 and kind not in (4,5):raise ContractError('INSPECT_WRITE_CONTRADICTION',fields=('task_kind',),repair_class='R6',vector_key='semantic_contradictions')
            if action==4 and not exists:raise ContractError('STRATEGY_TARGET_MISSING',fields=('target',),repair_class='R5',vector_key='invalid_registry_ids')
            if action in (1,5) and exists:raise ContractError('TARGET_ALREADY_EXISTS',fields=('target',),repair_class='R5',vector_key='invalid_registry_ids')
            scopes=ids('scope','scopes',True);deps=dependency_rows()
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
            if kind in (4,5):
                from cgkn.adapters.veriarbor.verification_adapter import reject_duplicate_measurement
                reject_duplicate_measurement(snapshot.document, goal_id=cap.get('config',{}).get('goal_id'))
            paths=[s['path'] for s in scopes]
            # A materialized milestone is measured before it is changed. New
            # ADD_TASK writers must not bypass explicit repair/strategy history.
            materialized={r['path'] for r in snapshot.document.get('artifact_readiness',[])
                          if r.get('materialized')}
            occupied=sorted(materialized.intersection(paths))
            imported_repair=[]
            if action==1 and kind in (2,3,6,7) and occupied:
                writers=[i for i,n in enumerate(snapshot.document.get('nodes',[]))
                         if n['node_id'] in tree.by_id
                         and tree.by_id[n['node_id']].config.get('leaf_contract',{}).get('task_kind') in {'IMPLEMENTATION','REPAIR','INTEGRATION','DELIVERY'}
                         and set(tree.by_id[n['node_id']].config.get('leaf_contract',{}).get('target_scope',())).intersection(occupied)]
                # Imported Provider artifacts have no writer in the new graph.
                # A first explicit REPAIR can be admitted only after independent
                # business failure evidence covers every existing target path.
                failures=snapshot.document.get('repair_context',{}).get('failures',[])
                eligible=[f for f in failures if f.get('failure_domain')=='business'
                          and f.get('acceptance_id') and f.get('evidence_refs')]
                covered={p for f in eligible for p in f.get('artifact_paths',[])}
                if kind==3 and not writers and set(occupied)<=covered:
                    imported_repair=[f for f in eligible if set(f.get('artifact_paths',[])).intersection(occupied)]
                if not imported_repair: raise ContractError('MATERIALIZED_SCOPE_REQUIRES_EXPLICIT_CHANGE',fields=('action',),repair_class='R6',details={
                    'materialized_paths':occupied,'writer_target_ids':writers,
                    'instruction':'These admitted milestone artifacts already exist. Run independent acceptance on the current objects first; missing evidence is not an implementation failure. Do not add another writer. If observed failure requires a change, explicitly repair an existing writer with evidence, or use an explicit strategy/replan decision preserving its public contract. Do not place downstream work into the current milestone scope. For imported artifacts with no existing writer, a first ADD_TASK with task_kind=3 is allowed only after independent business failure evidence covers all existing target paths.',
                    'auto_generate_semantics':False,'can_preserve_intent':False})
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
            if imported_repair:config['imported_artifact_repair_evidence']=imported_repair
            read_scope=[]
            for dep in dependencies:
                if dep in tree.by_id:
                    read_scope.extend(tree.by_id[dep].config.get('leaf_contract',{}).get('target_scope',()))
            read_subjects={}
            for path in paths:
                inputs=snapshot.document.get('milestone_dependency_inputs',{}).get(path,{})
                if inputs.get('unresolved_goal_ids') or inputs.get('unavailable_paths'):
                    raise ContractError('MILESTONE_DEPENDENCY_NOT_READY',fields=('scope',),repair_class='R6',details={
                        'unresolved_goal_ids':inputs.get('unresolved_goal_ids',[]),'unavailable_paths':inputs.get('unavailable_paths',[]),
                        'instruction':'Restore independent verification of declared upstream milestone inputs before using them. No automatic business repair or acceptance is inferred.'})
                for name,subject in inputs.get('subjects',{}).items():
                    if name in paths:raise ContractError('MILESTONE_DEPENDENCY_WRITE_CONFLICT',fields=('scope',))
                    if name in read_subjects and read_subjects[name]!=subject:raise ContractError('MILESTONE_DEPENDENCY_IDENTITY_CONFLICT')
                    read_subjects[name]=subject;read_scope.append(name)
            if read_subjects:contract['read_subjects']=read_subjects
            if read_scope:contract['read_scope']=sorted(set(read_scope))
            if action==4:
                if tree.by_id[node_id].capability_ref!=cap['capability_ref']:
                    candidates=[i for i,row in enumerate(snapshot.document['nodes'])
                        if row['node_id'] in tree.by_id
                        and tree.by_id[row['node_id']].capability_ref==cap['capability_ref']
                        and set(paths)<=set(tree.by_id[row['node_id']].config.get('leaf_contract',{}).get('target_scope',()))]
                    raise ContractError('STRATEGY_REQUIRES_REPLAN',fields=('target',),repair_class='R6',vector_key='semantic_contradictions',details={
                        'field':'target','current_value':packet['target'],'allowed_values':candidates,
                        'instruction':'The selected target has a different capability. To repair implementation, select an existing implementation target numeric ID from allowed_values, not the measurement/checker node or a file path. Preserve its dependency_ids unless explicitly replanning. These IDs are scope-compatible choices, not proof of business failure or authorization; all repair evidence checks still apply. If no target is listed, replan bounded implementation work; do not convert the checker.'})
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
    from .admission import PLANNER_FIELDS,WORKER_FIELDS,planner_fields
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
        elif field=='payload':allowed[field]=['literal text' if packet.get('op')==2 else '{find: string, replace: string}, or a bounded array when table.patch_batch_limit allows' if packet.get('op')==3 else 'omit payload for reads']
        elif field=='confidence':allowed[field]=['number in [0,1]']
        elif field in ('needs_user','escalation'):allowed[field]=[False,True]
        else:allowed[field]={'allowed_fields':sorted(WORKER_FIELDS if worker else planner_fields(snapshot)),
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
        adding=packet.get('action') in ((1,6) if snapshot.document.get('action_version')==2 else (1,5))
        if adding and error.fields==('target',) and error.code in {'TARGET_ALREADY_EXISTS','INTEGER_ID_REQUIRED','REGISTRY_ID_INVALID'}:
            available=[i for i,n in enumerate(snapshot.document.get('nodes',[])) if n['node_id'] not in tree.by_id]
            error.details.update(field='target',allowed_values=available,
                instruction='ADD_TASK/INSPECT requires an unused numeric node row ID from allowed_values. Existing nodes and file paths are not valid new targets. Keep verified dependency work; scope selects the new milestone artifact.')
            if not available:error.repair_class='R6';error.details['admission_status']='REPLAN_REQUIRED'
        raise _feedback(error,packet,snapshot)

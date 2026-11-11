"""Action v2 translation into the existing canonical TreeEdit compiler."""
from .normalization import ContractError,digest
from .repair import ACTIONS_V2,PublicContractRegistry,RepairIntentClassifier,repair_contract,failure_for_target,plain


def compile_v2(packet,snapshot,*,bound_hash,tree,context_identity):
    from .compiler import _compile_planner
    from .admission import PLANNER_FIELDS
    from cgkn.orchestration.tree_edits import TreeEdit,apply_tree_edits
    snapshot.bind(bound_hash)
    action=packet.get('action')
    if type(action) is not int or action not in ACTIONS_V2:
        raise ContractError('ACTION_ID_INVALID',fields=('action',),repair_class='R5',details={'allowed_values':list(ACTIONS_V2)})
    if packet.get('needs_user') and action!=10:raise ContractError('ESCALATION_CONTRADICTION',fields=('action','needs_user'))
    if action==2:
        if set(packet)-{'action','target','children','goal_ref'}:raise ContractError('SPLIT_WITH_UNRELATED_FIELDS')
        children=packet.get('children')
        if not isinstance(children,list) or not 2<=len(children)<=4:raise ContractError('SPLIT_REQUIRES_BOUNDED_CHILDREN',fields=('children',),repair_class='R5')
        parent=snapshot.field_row('nodes',packet.get('target'),'target')['node_id']
        provenance={'source':'semantic-compiler-v2','table_hash':bound_hash,'context_identity':context_identity}
        if parent in tree.by_id and tree.by_id[parent].executable:
            raise ContractError('SPLIT_EXECUTED_IDENTITY_REQUIRES_ADDITIVE_REPLAN',fields=('target',),repair_class='R5',
                details={'allowed_action_ids':[2,8],'allowed_values':[i for i,n in enumerate(snapshot.document['nodes']) if n['node_id'] not in tree.by_id],
                    'instruction':'Use an available target for a new composite. Retain executed leaf identities; do not demote/remove historical work.'})
        binding={}
        if 'goals' in snapshot.document or 'goal_ref' in packet:
            if 'goal_ref' not in packet:
                raise ContractError('COMPOSITE_GOAL_REQUIRED',fields=('goal_ref',),repair_class='R5',
                    details={'allowed_values':list(range(len(snapshot.document.get('goals',[])))),
                             'instruction':'Select goal_ref from the registered goals table. Its frozen contract must cover all child scopes; no parent acceptance is inferred.'})
            goal=snapshot.field_row('goals',packet['goal_ref'],'goal_ref')
            existing=tree.by_id.get(parent)
            previous=existing.config.get('acceptance_goal_id') if existing else None
            if previous is not None and previous!=goal['goal_id']:
                raise ContractError('COMPOSITE_GOAL_BINDING_CHANGED',fields=('goal_ref',),repair_class='R6')
            paths=[]
            for child in children:
                scopes=child.get('scope') if isinstance(child,dict) else None
                if not isinstance(scopes,list) or not scopes:
                    raise ContractError('ID_LIST_REQUIRED',fields=('scope',),repair_class='R5')
                paths.extend(snapshot.field_row('scopes',key,'scope')['path'] for key in scopes)
            missing=sorted(set(paths)-set(goal.get('covered_artifact_paths',[])))
            if missing:
                raise ContractError('COMPOSITE_GOAL_SCOPE_MISMATCH',fields=('goal_ref','children'),repair_class='R5',
                    details={'uncovered_paths':missing,'instruction':'Choose a registered independent goal whose frozen contract covers all child scopes; do not weaken or invent acceptance.'})
            binding={'acceptance_goal_id':goal['goal_id']}
        edits=[];preview=tree;new_ids=[]
        if parent not in tree.by_id:
            group=TreeEdit(context_identity+':split-group','add_node',parent,{'parent_id':'','capability_ref':'','depends_on':[],'config':{'original_goal':tree.goal,**binding}},provenance)
            edits.append(group);preview=apply_tree_edits(preview,(group,),known_capabilities={c['capability_ref'] for c in snapshot.document['capabilities']})
        elif binding and not tree.by_id[parent].config.get('acceptance_goal_id'):
            update=TreeEdit(context_identity+':split-goal','update_config',parent,
                {'config':{**plain(tree.by_id[parent].config),**binding}},provenance)
            edits.append(update);preview=apply_tree_edits(preview,(update,),known_capabilities={c['capability_ref'] for c in snapshot.document['capabilities']})
        for index,child in enumerate(children):
            if child.get('action')!=1:raise ContractError('SPLIT_CHILD_MUST_ADD_TASK')
            result=compile_v2(child,snapshot,bound_hash=bound_hash,tree=preview,context_identity=context_identity+f':child:{index}')
            additions=[e for e in result['edits'] if e.operation=='add_node']
            if len(additions)!=1:raise ContractError('SPLIT_CHILD_NOT_LEAF')
            e=additions[0];e=TreeEdit(e.edit_id,e.operation,e.node_id,{**dict(e.payload),'parent_id':parent},e.provenance)
            edits.append(e);new_ids.append(e.node_id)
            preview=apply_tree_edits(preview,(e,),known_capabilities={c['capability_ref'] for c in snapshot.document['capabilities']})
        apply_tree_edits(tree,tuple(edits),known_capabilities={c['capability_ref'] for c in snapshot.document['capabilities']})
        return {'edits':tuple(edits),'request_run':True,'finish':False,'needs_escalation':False,'reason':'Execute explicit bounded split',
            'decision_id':digest(packet),'table_hash':bound_hash,'admission_status':'ADMISSIBLE','mechanical_receipts':[]}
    extras=set(packet)-PLANNER_FIELDS-{'failed_acceptance_ids','strategy','hypothesis'}
    # Existing safe normalization still proves redundant mechanical bindings.
    if extras and not extras<= {'capability_ref','executor_ref','checker_ref','schema_version'}:
        raise ContractError('UNEXPECTED_PLANNER_FIELDS',fields=sorted(extras))
    target=None;old=None
    if action not in (0,9,10):
        target=snapshot.field_row('nodes',packet.get('target'),'target')
        old=tree.by_id.get(target['node_id'])
    if old and target.get('target_version') and target['target_version']!=digest(old.as_dict()):
        raise ContractError('STALE_TARGET',fields=('target',),details={'expected_hash':target['target_version'],'actual_hash':digest(old.as_dict())})
    if action==4 and old is not None:
        paths=[snapshot.field_row('scopes',key,'scope')['path'] for key in packet.get('scope',[])] if isinstance(packet.get('scope'),list) else []
        prior_scope=set(old.config.get('leaf_contract',{}).get('target_scope',()))
        if paths and not set(paths)<=prior_scope:
            candidates=[i for i,row in enumerate(snapshot.document['nodes']) if row['node_id'] in tree.by_id
                and tree.by_id[row['node_id']].config.get('leaf_contract',{}).get('task_kind') in {'IMPLEMENTATION','REPAIR','INTEGRATION','DELIVERY'}
                and set(paths)<=set(tree.by_id[row['node_id']].config.get('leaf_contract',{}).get('target_scope',()))]
            if not candidates:
                available=[i for i,row in enumerate(snapshot.document['nodes']) if row['node_id'] not in tree.by_id]
                raise ContractError('REPAIR_TARGET_SCOPE_MISMATCH',fields=('action','target'),repair_class='R6',details={
                    'field':'target','current_value':packet['target'],'allowed_values':available,
                    'allowed_action_ids':[1],'required_task_kind':3,
                    'instruction':'No existing writer owns the selected scope. Do not repair a measurement or an unrelated node. For imported materialized artifacts, explicitly propose ADD_TASK action=1, task_kind=3, with an available numeric target and the current scope IDs. This is only a proposal: admission still requires independent business failure evidence covering every materialized path and the immutable public contract. Without that evidence, measure first. Never substitute a path string for target or add a plain implementation to overwrite existing work.'})
            raise ContractError('REPAIR_TARGET_SCOPE_MISMATCH',fields=('target',),repair_class='R6',details={
                'field':'target','current_value':packet['target'],'allowed_values':candidates,
                'instruction':'The selected target owns different artifact paths. Repair an existing writer for the selected scope using one of these numeric target IDs; scopes also expose writer_target_ids. Do not rewrite a verified unrelated milestone. Keep original public requirements and existing dependency_ids. These candidates do not replace required observed business failure evidence.'})
    if action==3:
        if old is None:raise ContractError('RETRY_UNKNOWN_NODE',fields=('target',),repair_class='R5')
        old_config=plain(old.config);leaf=old_config.get('leaf_contract',{})
        failures=failure_for_target(snapshot.document,old.id,leaf.get('target_scope',[]))
        changes={k:v for k,v in packet.items() if k not in {'action','target','confidence','needs_user'}}
        classification_failures=failures
        if leaf.get('task_kind') in {'TEST','INSPECTION'}:
            # A checker reporting bad business behavior is not the business
            # implementation. Remeasure its original predicate; never coerce
            # that node into a Worker. UNKNOWN still requires reconciliation.
            classification_failures=[f for f in failures if f.get('failure_domain') not in
                {'business','field_mismatch','exception','idempotency','persistence'}]
        intent=RepairIntentClassifier.classify(action,classification_failures,changes)
        if intent.get('next_operation')=='RECONCILE':raise ContractError('OUTCOME_UNKNOWN_REQUIRES_RECONCILE',details=intent)
        if intent['intent']=='IMPLEMENTATION_REPAIR':
            from .context_pack import share_failures
            from cgkn.orchestration import compile_tree
            from cgkn.orchestration.invalidation import downstream_closure
            forbidden=downstream_closure(compile_tree(tree),{old.id})
            allowed_deps=[i for i,n in enumerate(snapshot.document['nodes']) if n['node_id'] in tree.by_id and n['node_id'] not in forbidden]
            invalid_deps=[i for i in packet.get('deps',[]) if i not in allowed_deps]
            original={'goal':leaf.get('leaf_goal'),'expected':old_config.get('semantic_expected',[]),
                'accept':old_config.get('semantic_acceptance',[]),'deps':list(old.depends_on)}
            raise ContractError('ACTION_MISMATCH_REPAIR_REQUIRED',fields=('action','deps') if invalid_deps else ('action',),repair_class='R5',vector_key='semantic_contradictions',details={
                'admission_status':'REPAIR_ACTION_CORRECTION','selected_action':3,'inferred_intent':intent['intent'],
                'allowed_action_ids':[4,5,8],'allowed_values':[4,5,8],'immutable_goal':tree.goal,
                'immutable_acceptance':original['accept'],'old_values':original,'new_values':changes,'changed_fields':sorted(changes),
                'failed_acceptance_ids':[x['acceptance_id'] for x in failures],
                'actual_observations':share_failures(failures),'repair_fields_required':not bool(changes),
                'allowed_dependency_ids':allowed_deps,'invalid_dependency_ids':invalid_deps,
                'can_preserve_intent':True,'instruction':'This is business implementation repair, not execution retry. Preserve repair intent; select action 4. Original contract remains immutable.'})
        if changes and leaf.get('task_kind') in {'TEST','INSPECTION'}:
            raise ContractError('RETRY_CHANGES_SEMANTICS',fields=sorted(changes),repair_class='R6',details={
                'old_values':{'goal':leaf.get('leaf_goal'),'expected':old_config.get('semantic_expected'),
                    'accept':old_config.get('semantic_acceptance'),'deps':list(old.depends_on)},
                'new_values':changes,'changed_fields':sorted(changes),'allowed_action_ids':[3],
                'allowed_fields':['action','target','confidence','needs_user'],
                'instruction':'To remeasure this existing TEST/INSPECTION target, submit action=3 and its numeric target only (optional confidence/needs_user). Omit task_kind, goal, scope, expected, accept and deps entirely. Existing measurement semantics and dependencies remain unchanged. This rejection is not business failure evidence and does not authorize repairing the checker.',
                'auto_generate_semantics':False,'can_preserve_intent':False})
        if changes:raise ContractError('RETRY_CHANGES_SEMANTICS',fields=sorted(changes),repair_class='R6',details={
            'old_values':{'goal':leaf.get('leaf_goal'),'expected':old_config.get('semantic_expected'),
                'accept':old_config.get('semantic_acceptance'),'deps':list(old.depends_on)},
            'new_values':changes,'changed_fields':sorted(changes),'allowed_action_ids':[4,5,8]})
    if action==4 and packet.get('task_kind')!=3:
        raise ContractError('REPAIR_KIND_REQUIRED',fields=('task_kind',),repair_class='R5',details={'allowed_values':[3]})
    if action in (4,5,8) and old is None:raise ContractError('REPAIR_OR_STRATEGY_TARGET_MISSING',fields=('target',),repair_class='R5')
    if action in (1,4,5,6,8) and snapshot.document.get('progress_policy')=='SEMANTIC_STRATEGY_V1':
        invalid=[]
        if not isinstance(packet.get('goal'),str) or not packet['goal'].strip():invalid.append('goal')
        for name in ('expected','accept'):
            value=packet.get(name)
            if not isinstance(value,list) or not value or any(not isinstance(x,str) or not x.strip() for x in value):invalid.append(name)
        if type(packet.get('task_kind')) is not int:invalid.append('task_kind')
        if invalid:
            raise ContractError('LEAF_SEMANTIC_FIELDS_REQUIRED',fields=invalid,repair_class='R5',details={
                'admission_status':'REPAIRABLE_SEMANTIC','missing_or_invalid_fields':invalid,
                'instruction':'Correct ALL listed fields together. goal is a non-empty string. expected and accept are non-empty arrays of observable predicate strings, not objects, booleans, evidence paths or decision IDs. Preserve every other existing field exactly. This is schema feedback, not a business strategy change.'})
    mapping={0:0,1:1,3:3,4:4,5:4,6:5,7:6,8:4,9:7,10:8}
    translated={k:v for k,v in packet.items() if k not in {'failed_acceptance_ids','strategy','hypothesis'}}
    translated['action']=mapping[action]
    result=_compile_planner(translated,snapshot,bound_hash=bound_hash,tree=tree,context_identity=context_identity)
    if action not in (1,4,5,6,8):return result
    registry_doc=snapshot.document.get('public_contract_registry')
    if registry_doc is None:raise ContractError('PUBLIC_CONTRACT_REGISTRY_REQUIRED')
    registry=PublicContractRegistry(registry_doc)
    edits=[]
    for e in result['edits']:
        if e.operation not in {'add_node','update_config'}:edits.append(e);continue
        config=plain(e.payload['config']);leaf=config['leaf_contract'];paths=leaf['target_scope']
        contracts=registry.select(paths)
        if not contracts['entries']:raise ContractError('WORKER_REQUIRED_CONTRACT_MISSING',fields=('scope',))
        config.update(public_contracts=contracts,action_version=2,public_contract_registry_ref=snapshot.document.get('public_contract_registry_ref'))
        if config.get('imported_artifact_repair_evidence'):
            config['verified_artifact_change_reason']='Explicit evidence-bound initial repair of imported artifact '+digest(config['imported_artifact_repair_evidence'])
        if old and action in (4,5,8):
            previous=plain(old.config.get('public_contracts',contracts))
            from .repair import contract_diff
            diff=contract_diff(previous,contracts)
            if diff['drift_count']:raise ContractError('PUBLIC_CONTRACT_CHANGE_REQUIRES_EXPLICIT_VERSION_REVIEW',details={'contract_diff':diff,'downstream_tests_required':True})
            # Supplemental repair predicates cannot replace original obligations.
            config['semantic_acceptance']=list(dict.fromkeys([*plain(old.config.get('semantic_acceptance',[])),*config['semantic_acceptance']]))
            if action==4 or (action in (5,8) and snapshot.document.get('progress_policy')=='SEMANTIC_STRATEGY_V1'
                            and failure_for_target(snapshot.document,old.id,paths)):
                config['repair_contract']=repair_contract(packet,old,tree,snapshot,paths,leaf['dependencies'],contracts)
                config['previous_repair_attempts']=[plain(x) for x in snapshot.document.get('repair_context',{}).get('previous_repair_attempts',[]) if x.get('node_id')==old.id]
                config['verified_artifact_change_reason']='Evidence-bound implementation repair '+digest(config['repair_contract'])
            if action in (5,8):
                config['verified_artifact_change_reason']='Explicit Agent strategy revision '+digest({'decision':context_identity,'packet':packet,'previous_target':old.as_dict()})
            if action==8:config['replan_carry_forward']={'original_goal':tree.goal,**plain(snapshot.document.get('repair_context',{}).get('goal_state',{}))}
        edits.append(TreeEdit(e.edit_id,e.operation,e.node_id,{**plain(e.payload),'config':config},e.provenance))
    try:apply_tree_edits(tree,tuple(edits),known_capabilities={c['capability_ref'] for c in snapshot.document['capabilities']})
    except (ValueError,KeyError,TypeError) as exc:raise ContractError('CANONICAL_REJECTED:'+str(exc),repair_class='R6') from exc
    return {**result,'edits':tuple(edits),'action_version':2,'selected_action':action}

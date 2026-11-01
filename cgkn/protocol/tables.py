"""Bounded request-local views over existing catalog/tree; no second registry."""
from pathlib import PurePosixPath
from .compiler import TableSnapshot
from .normalization import ContractError,digest


def planner_snapshot(context,artifact_declarations,*,new_slots=8,action_version=1,
                     public_contract_registry=None,public_contract_registry_ref=None,
                     repair_context=None,context_raw_ref=None):
    if type(new_slots) is not int or not 1<=new_slots<=16:raise ValueError('bounded new slot count required')
    if not isinstance(artifact_declarations,list) or not 1<=len(artifact_declarations)<=64:raise ValueError('bounded model-authored artifact declarations required')
    scopes=[];seen=set()
    for row in artifact_declarations:
        if not isinstance(row,dict) or set(row)-{'path','purpose','interfaces'} or not all(isinstance(row.get(k),str) and row[k].strip() for k in ['path','purpose']):raise ContractError('INVALID_ARTIFACT_DECLARATION')
        path=row['path'];p=PurePosixPath(path)
        if p.is_absolute() or path in {'.','/'} or '..' in p.parts or any(c in path for c in '*?\\:') or path in seen:raise ContractError('UNSAFE_OR_DUPLICATE_DECLARED_PATH')
        seen.add(path);scopes.append(dict(row))
    nodes=[{'node_id':n.id,'state':'existing','goal':n.config.get('leaf_contract',{}).get('leaf_goal',''),'parent_id':n.parent_id,
        'target_version':digest(n.as_dict())} for n in context.tree.nodes]
    used={n['node_id'] for n in nodes};index=0
    while sum(n['state']=='available' for n in nodes)<new_slots:
        node_id=f'sem-node-{index:04d}';index+=1
        if node_id not in used:nodes.append({'node_id':node_id,'state':'available','parent_id':''})
    capabilities=[]
    for ref,row in sorted(context.capability_catalog.items()):
        if 'semantic_task_kinds' not in row:continue
        capabilities.append({'capability_ref':ref,'executor_ref':row['executor_ref'],'checker_ref':row['checker_ref'],
            'acceptance_refs':row['acceptance'],'effect_domains':row['effect_domains'],'task_kinds':row['semantic_task_kinds'],
            'external_effect':row.get('external_effect',False),'authorized':row.get('authorized',False),
            'description':row.get('description',''),'config':row.get('config',{})})
    if not capabilities:raise ContractError('NO_ADMITTED_SEMANTIC_CAPABILITY')
    document={'nodes':nodes,'scopes':scopes,'capabilities':capabilities,'sources':[]}
    if action_version not in (1,2):raise ContractError('UNSUPPORTED_ACTION_VERSION')
    if action_version==2:
        from .repair import PublicContractRegistry,ACTIONS_V2
        registry=PublicContractRegistry(public_contract_registry)
        document.update(action_version=2,action_table={str(k):v for k,v in ACTIONS_V2.items()},public_contract_registry=registry.document,
            public_contract_registry_ref=public_contract_registry_ref,repair_context=repair_context or {},context_raw_ref=context_raw_ref)
        # Goal rows are views of the existing acceptance authority, not new
        # goals inferred from a successful child or model self-report.
        goals=[]
        view=context.goal_acceptance
        for goal in view.get('goals',[]):
            checker=view.get('checker_bindings',{}).get(goal.get('checker'))
            covered=set()
            for entry in registry.document['entries']:
                bindings=entry['definition'].get('acceptance_bindings',[])
                if any(b.get('acceptance_id')==goal['id'] and b.get('checker_ref')==checker
                       and b.get('object_ref') in goal.get('subject_refs',[]) for b in bindings):
                    covered.update(entry['artifact_paths'])
            goals.append({'goal_id':goal['id'],'acceptance':goal.get('acceptance',''),
                          'subject_refs':list(goal.get('subject_refs',[])),
                          'covered_artifact_paths':sorted(covered)})
        document['goals']=goals
    return TableSnapshot(document)

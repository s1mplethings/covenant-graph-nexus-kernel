"""Goal-only application wiring over ProjectSession, not a business scheduler."""
from dataclasses import asdict,replace
from copy import deepcopy
from pathlib import Path
import hashlib,importlib.util,json,os,re,subprocess,sys
from cgkn.agent import ProjectSession
from cgkn.agent.composer import AgentComposer,AGENT_SCHEMA
from cgkn.agent.planning_scope import HostPlanningScope
from cgkn.agent.project_agent import AdmissionPolicy
from cgkn.executors import ExecutorRegistry,FileExecutor,LLMExecutor,PythonTestExecutor
from cgkn.executors.protocol import ExecutorDescriptor
from cgkn.execution import BlockExecutionResult,BlockStatus
from cgkn.execution.deliverables import FileDeliverableChecker,SubjectDeliverableChecker
from cgkn.orchestration import CapabilityTree
from cgkn.orchestration.leaf_contract import build_leaf_contract
from cgkn.providers import ModelRoleConfig
from cgkn.providers.recording import RecordedCompletionClient
from cgkn.runtime import DAGRunner
from cgkn.state import FileRunStore
from cgkn.runtime.acceptance import open_goal_acceptance as GoalAcceptance
from cgkn.state.acceptance import identity
from veriarbor.capability import CapabilityContract,GoalGap

# One definition feeds the public interface and the compiler's allowed fields.
REPAIR_CONFIG_FIELDS = ('goal','read_paths','verified_artifact_change_reason')
UNSUPPORTED_EDIT_OPERATIONS = {'replace_executor','replace_node'}

EXECUTOR_INTERFACES = {
    'llm.cheap@1': {'config_fields':['target_paths','component_roots','read_paths','expected_delta'],
        'target_paths':'Exact public output files; component_roots authorize internal implementation and test files'},
    'local.file@1': {'config_fields':['action','path','offset_chars','limit_chars'],
        'actions':['read_file','list_files'],
        'read_file':'UTF-8 page: default 6000, maximum 12000 characters; follow next_offset_chars'},
    'local.python-test@1': {'config_fields':['pytest_args']},
    'goal.acceptance@1': {'config_fields':['acceptance_goal_id']},
}


def digest_file(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def workspace_identity(root):
    if any(p.is_symlink() for p in root.rglob('*')):raise ValueError('workspace symlinks are outside this bounded file adapter')
    return identity({p.relative_to(root).as_posix():digest_file(p) for p in sorted(root.rglob('*'))
                     if p.is_file() and p.relative_to(root).parts[:2]!=('inputs','runtime-results')
                     and not any(x in p.parts for x in ['__pycache__','.pytest_cache'])})
from cgkn.execution.node_effects import child_environment

def relative_files(values):
    if not isinstance(values,list) or len(values)>16:raise ValueError('bounded explicit file paths required')
    for name in values:
        p=Path(name)
        if not isinstance(name,str) or not name or p.is_absolute() or '..' in p.parts or ':' in name or name.startswith(('.','inputs/')):
            raise ValueError('path outside candidate write scope')
    return values

def deduplicate_gap_view(gaps,acceptance,results,feedback):
    """Lossless references into existing one-copy context objects, not state."""
    return [{'requirement_ref':g['requirement_ref'],
             'requirement_ref_path':'goal_acceptance.requirements.'+g['requirement_ref'],
             'acceptance_goal_ids':[x['id'] for x in g['acceptance']],
             'user_feedback_ref':'task_feedback.user_feedback',
             'observation_node_ids':[x['node_id'] for x in g['observations']],
             **{k:v for k,v in g.items() if k not in {'requirement_ref','requirement','acceptance','user_feedback','observations'}}} for g in gaps]

class GoalComposer(AgentComposer):
    """Mechanical contract compiler; Agent retains decomposition and selection."""
    def requirement_gap_bindings(self):
        # Objective missing verification evidence, NOT an invented failed test or
        # a numeric judgement of subjective product quality. Existing acceptance
        # and immutable requirements are the only source of this derived view.
        view=self.session.acceptance.view();registered=dict(self.session.admission_policy.goal_gaps);bindings={}
        for ref,description in self.goal_config['requirements'].items():
            goals=[g for g in view.get('goals',[]) if ref in g.get('requirement_refs',[])]
            if len(goals)!=1:continue  # no arbitrary choice between goal scopes
            goal=goals[0];gid='requirement-evidence-'+identity([self.goal_config['project_id'],ref,description,goal['id']])[:24]
            verified=goal.get('verdict')=='VERIFIED'
            old=registered.get(gid,{})
            registered[gid]=asdict(GoalGap(gap_id=gid,goal_id=goal['id'],metric_id='verified_acceptance_evidence',
                target=1,current=1 if verified else 0,status='CLOSED' if verified else 'OPEN',
                capability_ids=tuple(old.get('capability_ids',()))))
            bindings[ref]={'gap_id':gid,'goal_id':goal['id'],'requirement_ref':ref,
                'basis':'current GoalAcceptance verification evidence; not an executed failure or humor score',
                'acceptance_verdict':goal.get('verdict'),'status':registered[gid]['status']}
        self.session.admission_policy=replace(self.session.admission_policy,goal_gaps=registered)
        return bindings
    def prepare_context(self,context):
        if hasattr(self,'component_packages'):
            context=replace(context,retrieved_knowledge={**context.retrieved_knowledge,
                'component_candidates':self.component_packages.catalog(self.goal_config.get('reuse_context',{}))})
        self.decision_schema=deepcopy(AGENT_SCHEMA)
        self.decision_schema['required'].remove('decision_id')
        edit_schema=self.decision_schema['properties']['edits']['items']
        edit_schema['required']=[k for k in edit_schema['required'] if k not in {'edit_id','provenance'}]
        edit_schema['properties']['operation']['enum']=[op for op in edit_schema['properties']['operation']['enum'] if op not in UNSUPPORTED_EDIT_OPERATIONS]
        edit_schema['allOf'].append({'if':{'properties':{'operation':{'const':'update_config'}}},
            'then':{'properties':{'payload':{'properties':{'config':{'type':'object',
                'properties':{key:({'type':'array','items':{'type':'string'}} if key=='read_paths' else {'type':'string','minLength':1}) for key in REPAIR_CONFIG_FIELDS},
                'additionalProperties':False}}}}}})
        interfaces=self.executor_interfaces()
        config_schema={'type':'object','required':['executor_ref','goal'],
            'properties':{'executor_ref':{'enum':sorted(interfaces)},'goal':{'type':'string','minLength':1}},
            'allOf':[{'if':{'properties':{'executor_ref':{'const':ref}}},
                'then':{'properties':{k:{} for k in ['executor_ref','goal','optional_strategy',*row['config_fields']]},
                        'additionalProperties':False}} for ref,row in interfaces.items()]}
        edit_schema['allOf'].append({'if':{'properties':{'operation':{'const':'add_node'}}},
            'then':{'properties':{'payload':{'properties':{'config':config_schema}}}}})
        bindings=self.requirement_gap_bindings()
        path=Path(self.goal_config.get('budget_ledger',self.run_root/'provider-budget.json'));limits=self.goal_config['resource_and_effect_limits']
        ledger=json.loads(path.read_text(encoding='utf-8')) if path.exists() else None
        totals=ledger.get('totals',{}) if ledger else {}
        remaining={}
        for cap,key in [('max_api_calls','api_calls'),('max_input_tokens','input_tokens'),('max_output_tokens','output_tokens'),('max_estimated_cost','estimated_cost')]:
            remaining[key]=max(0,limits[cap]-totals.get(key,0)) if limits.get(cap) is not None else None
        public_artifacts={}
        for item in self.goal_config.get('inputs_and_workspace',{}).get('inputs',[]):
            source=(self.workspace/'inputs'/item['name']).resolve()
            if not source.is_relative_to(self.workspace/'inputs') or source.is_symlink():raise ValueError('authorized input scope changed')
            if digest_file(source)!=item['sha256']:raise ValueError('authorized input identity changed')
            try:content=source.read_text(encoding='utf-8')
            except UnicodeError:continue  # binary inputs remain explicit file references, not guessed text
            public_artifacts[item['name']]={'path':'inputs/'+item['name'],'sha256':item['sha256'],'content':content}
        compact={}
        for node,result in context.execution_results.items():
            outputs=result.get('outputs',{});metadata=result.get('metadata',{})
            compact[node]={**{k:result.get(k) for k in ['attempt_id','status','error']},
                'outputs':{k:outputs[k] for k in ['summary','modified_files','expected_outputs','manifest','clips','actual_media_review','goal_check','evidence_summary','artifact_path','strategy_sha256'] if k in outputs},
                'metadata':{k:metadata[k] for k in ['node_commit_receipt_id','raw_execution_receipt_ref','deliverable_check'] if k in metadata},
                'full_result_ref':str(self.session.store.run_dir(context.project_id,context.run_id)/'node_results'/(node+'.json'))}
            if isinstance(outputs.get('content'),str):
                compact[node]['outputs'].update({k:outputs[k] for k in ['path','content','offset_chars','next_offset_chars','total_chars'] if k in outputs})
            if isinstance(outputs.get('files'),(list,tuple)):compact[node]['outputs']['files']=list(outputs['files'])[:80]
        archive_view=[]
        state_path=self.session.store.run_dir(context.project_id,context.run_id)/'run_state.json'
        if state_path.exists():
            state=self.session.store.load_run(context.project_id,context.run_id)
            for node,versions in state.archived_nodes.items():
                raw=json.dumps(versions,ensure_ascii=False,sort_keys=True,indent=2).encode('utf-8')
                name='inputs/runtime-results/archive-'+hashlib.sha256(raw).hexdigest()+'.json'
                target=self.workspace/name;target.parent.mkdir(parents=True,exist_ok=True)
                if target.exists() and target.read_bytes()!=raw:raise ValueError('archive projection identity mismatch')
                if not target.exists():target.write_bytes(raw)
                archive_view.append({'node_id':node,'versions':len(versions),
                    'historical_status':versions[-1]['execution']['status'],
                    'evidence_applicability':'HISTORICAL_ONLY',
                    'readable_ref':{'path':name,'sha256':hashlib.sha256(raw).hexdigest(),'tool':'local.file@1 read_file'}})
        # Immutable readable projections; authority remains in FileRunStore.
        recent=set(list(compact)[-2:])
        for node,row in compact.items():
            raw=json.dumps(context.execution_results[node],ensure_ascii=False,sort_keys=True,indent=2).encode('utf-8')
            name='inputs/runtime-results/'+hashlib.sha256(raw).hexdigest()+'.json'
            target=self.workspace/name;target.parent.mkdir(parents=True,exist_ok=True)
            if target.exists() and target.read_bytes()!=raw:raise ValueError('result projection identity mismatch')
            if not target.exists():target.write_bytes(raw)
            row['readable_result_ref']={'path':name,'sha256':hashlib.sha256(raw).hexdigest(),'tool':'local.file@1 read_file with pagination'}
            if node not in recent or len(json.dumps(row['outputs'],ensure_ascii=False))>14000:
                row['outputs']={'status':'full output available by readable_result_ref; no facts inferred or discarded from authority'}
        gaps=[{'requirement_ref':k,'requirement':v,'acceptance':[g for g in context.goal_acceptance.get('goals',[]) if k in g.get('requirement_refs',[])],
               'user_feedback':self.goal_config.get('feedback',[])[-8:],
               'observations':[{ 'node_id':n,**r} for n,r in compact.items()][-6:],
               'cause_status':'unverified unless supported by referenced observation'} for k,v in self.goal_config['requirements'].items()]
        feedback=self.goal_config.get('feedback',[])
        gaps=deduplicate_gap_view(gaps,context.goal_acceptance,compact,feedback)
        return replace(context,execution_results=compact,retrieved_knowledge={**context.retrieved_knowledge,'public_artifacts':public_artifacts},task_feedback={**context.task_feedback,
            'user_feedback':feedback,
            'archived_strategies':archive_view,
            'archive_instruction':'remove_node archives only completed explicitly optional strategies with no consumers or goal task references; restore using add_node after reading archived contract. Restoration requires current admission and new execution, never historical PASS.',
            'requirement_gap_bindings':bindings,
            'repair_interface':{'config_fields':list(REPAIR_CONFIG_FIELDS),'operation':'update_config followed by retry_node; omit Host-generated leaf_contract and input_paths'},
            'proposal_compile_limits':{'max_new_nodes':self.session.admission_policy.max_new_nodes,
                'inputs':'All referenced input files must already exist at admission; a future producer cannot be bundled with its consumer.'},
            'executor_interfaces':{k:{**v,'config_fields':['executor_ref','goal','optional_strategy',*v['config_fields']]} for k,v in self.executor_interfaces().items()},
            'capability_governance':{**context.task_feedback.get('capability_governance',{}),'goal_gaps':list(self.session.admission_policy.goal_gaps.values()),
                'proposal_instruction':'Choose requirement_refs from original requirements OR an exact registered target_gap_id. Host compiles identity; requirement IDs are not Gap IDs. No need to invent a Gap ID.'},
            'goal_gap_view':gaps,'evidence_catalog':self.goal_config.get('evidence_catalog',[]),
            'available_application_executors':{k:{'executor_ref':k,'config_fields':['executor_ref','goal','optional_strategy',*v['config_fields']],
                'description':v.get('description',''),'capability_ref_rule':'Agent chooses project.<name>@1, distinct from executor_ref'} for k,v in getattr(self,'application_executors',{}).items()},'resource_scope':{
            'remaining_including_reservations':remaining,'totals':totals,'ledger_ref':str(path) if ledger else None,
            'amount_basis':'configured estimate, not bill','models':limits['models'],
            'historical_model_quality':'UNKNOWN; no fabricated rankings'}})
    def executor_interfaces(self):
        return {**deepcopy(EXECUTOR_INTERFACES), **{k:{f:deepcopy(v[f]) for f in ('config_fields','description') if f in v} for k,v in getattr(self,'application_executors',{}).items()}}

    def _normalize_decision(self,value,context):
        # Compilation may discover local declarations, but a rejected batch must
        # not leave partial declarations for the next proposal to reuse.
        policy=self.session.admission_policy
        known=self.session.known_capabilities
        catalog=deepcopy(self.session.capability_catalog)
        try:
            return self._compile_decision(deepcopy(value),context)
        except Exception:
            self.session.admission_policy=policy
            self.session.known_capabilities=known
            self.session.capability_catalog=catalog
            raise

    def _compile_decision(self,value,context):
        if value.get('goal_plan'):raise ValueError('original requirements cannot be rewritten')
        value['decision_id']='host-decision-'+identity([context.project_id,context.run_id,context.decision_number])[:24]
        audit=dict(value.get('decision_audit',{}))
        claim=dict(audit.get('capability_claim',{}))
        bindings=self.requirement_gap_bindings()
        gap_id=claim.get('target_gap_id')
        refs=audit.get('requirement_refs',[])
        if not isinstance(refs,list) or any(not isinstance(r,str) for r in refs) or not set(refs)<=set(self.goal_config['requirements']):
            raise ValueError('unknown requirement_refs')
        if gap_id is not None and not isinstance(gap_id,str):raise ValueError('target_gap_id must be a registered string identifier')
        requested_gap=gap_id
        selected_requirement=None
        if gap_id in self.goal_config['requirements']:
            selected_requirement=gap_id
            if refs and gap_id not in refs:raise ValueError('conflicting requirement and gap references')
        elif not gap_id and len(refs)==1:selected_requirement=refs[0]
        if selected_requirement:
            if selected_requirement not in bindings:raise ValueError('requirement has no unambiguous acceptance goal; cannot compile gap')
            gap_id=bindings[selected_requirement]['gap_id'];claim['target_gap_id']=gap_id
            if not refs:refs=[selected_requirement];audit['requirement_refs']=refs
        if gap_id and gap_id not in self.session.admission_policy.goal_gaps:
            raise ValueError('unknown or cross-project target_gap_id; use requirement_refs from '+str(list(bindings))+' or exact registered gap IDs')
        bound_ref=next((r for r,b in bindings.items() if b['gap_id']==gap_id),None)
        if bound_ref and refs and bound_ref not in refs:raise ValueError('conflicting requirement and gap references')
        if gap_id and self.session.admission_policy.goal_gaps[gap_id].get('status','OPEN')!='OPEN':raise ValueError('target gap is not open')
        edits=[]
        for raw in value.get('edits',[]):
            edit=dict(raw);payload=dict(edit.get('payload',{}));node=edit['node_id']
            edit['edit_id']='host-edit-'+identity([value['decision_id'],len(edits),node,edit['operation'],payload])[:24]
            edit['provenance']={'host_context':identity(context.as_dict()),'project_id':context.project_id,
                                'run_id':context.run_id,'model_proposal_id':value.get('decision_id','unspecified'),
                                'goal_binding':{'requested':requested_gap,'requirement_refs':refs,'compiled_gap_id':gap_id,'basis':bindings.get(bound_ref)}}
            if node==HostPlanningScope.root_id:raise ValueError('Host planning scope is protected')
            if edit['operation']=='add_node':
                cap=payload['capability_ref'];cfg=dict(payload.get('config',{}));executor=cfg.get('executor_ref')
                if executor=='llm.cheap@1' and 'input_paths' in cfg:
                    declared=[str((self.workspace/n).resolve()) for n in cfg.get('read_paths',[])]
                    if cfg['input_paths']!=declared:raise ValueError('input_paths must exactly repeat Host-resolved read_paths')
                    cfg.pop('input_paths')
                extensions=getattr(self,'application_executors',{})
                interfaces=self.executor_interfaces()
                if executor not in interfaces:
                    raise ValueError('executor is not in frozen allowlist; allowed='+str(sorted(interfaces)))
                allowed={'executor_ref','goal','optional_strategy',*interfaces[executor]['config_fields']}
                if 'optional_strategy' in cfg and type(cfg['optional_strategy']) is not bool:raise ValueError('optional_strategy must be an explicit boolean')
                if set(cfg)-allowed:raise ValueError('unapproved executor configuration fields for '+str(executor)+': '+str(sorted(set(cfg)-allowed))+'; allowed='+str(sorted(allowed))+'. Application executor declarations are in task_feedback.available_application_executors.')
                if executor=='local.python-test@1':
                    for arg in cfg.get('pytest_args',['-q']):
                        if arg not in {'-q','-v','-x'}:
                            relative_files([arg])
                            if not arg.endswith('.py'):raise ValueError('only bounded pytest file targets or basic flags')
                if not re.fullmatch(r'project\.[a-zA-Z0-9_.-]+@1',cap):raise ValueError('new capabilities must be project-local')
                goal=cfg.get('goal','')
                if not isinstance(goal,str) or not goal.strip():raise ValueError('bounded semantic goal required')
                deps=list(payload.get('depends_on',[]))
                if executor in extensions:
                    cfg,leaf=extensions[executor]['compile'](cfg,node,deps,self.workspace)
                elif executor=='llm.cheap@1':
                    targets=relative_files(cfg.get('target_paths',[]))
                    roots=relative_files(cfg.get('component_roots',[]))
                    if not 1<=len(targets)<=8 or len(roots)>4:raise ValueError('bounded public outputs and component roots required')
                    reads=cfg.get('read_paths',[])
                    if not isinstance(reads,list) or len(reads)>16:raise ValueError('bounded read scope required')
                    for name in reads:
                        if not isinstance(name,str) or Path(name).is_absolute() or '..' in Path(name).parts or ':' in name:raise ValueError('read scope escape')
                    if set(reads)&set(targets):raise ValueError('read-only and write scopes must be disjoint')
                    read_subjects={}
                    for name in reads:
                        p=(self.workspace/name).resolve()
                        if not p.is_relative_to(self.workspace) or not p.is_file() or p.is_symlink():raise ValueError('input missing or outside workspace')
                        read_subjects[name]=digest_file(p)
                    cfg['input_paths']=[str(self.workspace/name) for name in reads]
                    leaf=build_leaf_contract(goal=goal,kind='IMPLEMENTATION',scope=targets,acceptance=['local-artifacts'],
                        checker='files',output_identity=node,effect_domains=['filesystem','external_network','local_process'],executor=executor,
                        dependencies=deps,expected_delta=cfg.get('expected_delta',goal),read_scope=reads,read_subjects=read_subjects,component_roots=roots,max_candidate_files=128)
                else:
                    if executor=='local.file@1' and cfg.get('action') not in {'read_file','list_files'}:
                        raise ValueError('local file executor is read-only in this application')
                    if executor=='local.file@1':
                        if type(cfg.get('offset_chars',0)) is not int or cfg.get('offset_chars',0)<0 or type(cfg.get('limit_chars',6000)) is not int or not 1<=cfg.get('limit_chars',6000)<=12000:raise ValueError('bounded file page required')
                        cfg.setdefault('limit_chars',6000)
                        source=(self.workspace/str(cfg.get('path','.'))).resolve()
                        if source!=self.workspace and not source.is_relative_to(self.workspace):raise ValueError('read scope escape')
                        if cfg['action']=='read_file':
                            if not source.is_file():raise ValueError('read input missing')
                            cfg['input_paths']=[str(source)]
                    leaf=build_leaf_contract(goal=goal,kind='TEST' if executor!='local.file@1' else 'INSPECTION',scope=['workspace'],
                        acceptance=['observation'],checker='observations',output_identity=node,effect_domains=['filesystem' if executor=='local.file@1' else 'local_process'],
                        executor=executor,dependencies=deps,subject='workspace',expected_observation=goal,
                        pass_fail_rule='bound local observation; final independent product oracle decides Root')
                cfg['leaf_contract']=leaf
                payload.update(config=cfg,parent_id=payload.get('parent_id',''),depends_on=deps)
                contract=CapabilityContract(cap,goal,critical=False,positive_controls=('bound-local-check',),
                    evidence_requirements={'allow_imported_unmanaged':True})
                contracts=dict(self.session.admission_policy.capability_contracts)
                if cap in contracts and contracts[cap]!=asdict(contract):raise ValueError('existing local capability contract changed')
                contracts[cap]=asdict(contract)
                self.session.admission_policy=replace(self.session.admission_policy,capability_contracts=contracts)
                self.session.known_capabilities=frozenset({*self.session.known_capabilities,cap})
                self.session.capability_catalog[cap]={'executor_ref':executor,'config':cfg,'description':goal,'project_local':True}
            elif edit['operation'] in UNSUPPORTED_EDIT_OPERATIONS:
                raise ValueError('use a newly admitted bounded local capability; do not mutate executor permissions')
            elif edit['operation']=='update_config':
                changed=dict(payload.get('config',{}))
                for key in set(changed).intersection(REPAIR_CONFIG_FIELDS)-{'read_paths'}:
                    if not isinstance(changed[key],str) or not changed[key].strip():raise ValueError('repair '+key+' must be a nonempty string')
                current=context.tree.by_id[node].as_dict()['config']
                for k in list(changed):
                    if k not in {'goal','verified_artifact_change_reason'} and k in current and changed[k]==current[k]:changed.pop(k)
                # A newly supplied local observation is a bound read input, not
                # a new write permission or executor. Recompile its hashes and
                # let ordinary Admission invalidate dependent evidence.
                if 'read_paths' in changed and current.get('executor_ref')=='llm.cheap@1':
                    reads=changed.pop('read_paths')
                    if not isinstance(reads,list) or len(reads)>16:raise ValueError('bounded read scope required')
                    if not set(current.get('read_paths',[])).issubset(reads):raise ValueError('retain existing bound inputs')
                    subjects={}
                    for name in reads:
                        p=(self.workspace/name).resolve()
                        if not isinstance(name,str) or not p.is_relative_to(self.workspace/'inputs') or not p.is_file() or p.is_symlink():
                            raise ValueError('repair observation must be an existing workspace inputs file')
                        subjects[name]=digest_file(p)
                    if not changed.get('verified_artifact_change_reason'):raise ValueError('read binding change needs observed failure reason')
                    leaf={**current['leaf_contract'],'read_scope':reads,'read_subjects':subjects}
                    compiled_inputs={'read_paths':reads,'input_paths':[str((self.workspace/n).resolve()) for n in reads],'leaf_contract':leaf}
                    if 'input_paths' in changed:
                        if changed['input_paths']!=compiled_inputs['input_paths']:raise ValueError('input_paths mismatch declared repair observations')
                        changed.pop('input_paths')
                else:compiled_inputs={}
                payload['config']=changed
                if set(changed)-{'goal','verified_artifact_change_reason'}:
                    raise ValueError('permission/interface change requires new bounded capability')
                if 'verified_artifact_change_reason' in changed:
                    if not isinstance(changed['verified_artifact_change_reason'],str) or not changed['verified_artifact_change_reason'].strip():
                        raise ValueError('explicit change reason required')
                    revisions=self.session.acceptance.data.get('requirement_revisions',[])
                    authorized_extension=bool(revisions and bound_ref in revisions[-1]['additions']
                        and revisions[-1].get('authority_reference'))
                    if not authorized_extension and not context.failure_details and not any(g.get('verdict')=='FAILED' for g in context.goal_acceptance.get('goals',[])):
                        raise ValueError('accepted artifact change requires observed failure evidence or an explicit unmet requirement revision')
                changed.update(compiled_inputs)
            edit['payload']=payload;edits.append(edit)
        result={**value,'edits':edits}
        if edits:
            first=edits[0];cap=first['payload'].get('capability_ref') or context.tree.by_id[first['node_id']].capability_ref
            if claim.get('target_capability_id',cap)!=cap:raise ValueError('capability claim does not match edited frontier')
            if gap_id and bound_ref:
                registered=dict(self.session.admission_policy.goal_gaps);g=dict(registered[gap_id])
                g['capability_ids']=sorted(set(g['capability_ids'])|{cap});registered[gap_id]=g
                self.session.admission_policy=replace(self.session.admission_policy,goal_gaps=registered)
            if gap_id and cap not in self.session.admission_policy.goal_gaps[gap_id]['capability_ids']:
                raise ValueError('target gap is unrelated to selected capability')
            claim.setdefault('target_capability_id',cap)
            if not claim.get('strategy_capabilities'):claim['strategy_capabilities']=[cap]
            if not gap_id and any(e['operation']=='add_node' for e in edits):
                if (not isinstance(claim.get('exploration_reason'),str) or not claim['exploration_reason'].strip()
                    or type(claim.get('exploration_budget')) not in {int,float} or claim['exploration_budget']<=0
                    or not isinstance(claim.get('exploration_measure'),str) or not claim['exploration_measure'].strip()):
                    raise ValueError('missing business binding: supply one requirement_refs entry or a registered target_gap_id; exploration requires explicit reason, positive budget and observable measure')
            result['decision_audit']={**audit,'capability_claim':claim}
        return result

def build_session(config,run_root,client):
    workspace=Path(config['inputs_and_workspace']['workspace']).resolve()
    store=FileRunStore(Path(run_root)/'store');project=config['project_id'];run=config['run_id']
    requirements=config['requirements'];condition=json.dumps(requirements,ensure_ascii=False,sort_keys=True)
    checker=Path(config['completion']['checker_path']).resolve()
    if digest_file(checker)!=config['completion']['checker_sha256']:raise ValueError('CHECKER_IDENTITY_MISMATCH')
    acceptance=GoalAcceptance(store,project,run,{k:{'must':True,'description':v} for k,v in requirements.items()}, {'root':'goal.acceptance@1'})
    acceptance.bind_subjects({'workspace':workspace_identity(workspace)})
    if not acceptance.data['plans']:
        acceptance.commit(acceptance.propose({'phases':[{'id':'delivery','depends_on':[]}],'goals':[{'id':'root',
            'phase_id':'delivery','requirement_refs':list(requirements),'acceptance':condition,'subject_refs':['workspace'],
            'checker':'root','task_refs':[]}]},CapabilityTree(config['root_goal'],())))
    covered={r for g in acceptance.data['plans'][-1]['goals'] for r in g['requirement_refs']}
    uncovered=set(requirements)-covered
    if uncovered:
        if not acceptance.data.get('requirement_revisions'):raise ValueError('unversioned requirement extension')
        plan=deepcopy(acceptance.data['plans'][-1]);plan.pop('revision',None)
        extra={k:requirements[k] for k in sorted(uncovered)}
        plan['goals'].append({'id':'extension-'+identity(extra)[:16],'phase_id':'delivery',
            'requirement_refs':sorted(uncovered),'acceptance':json.dumps(extra,ensure_ascii=False,sort_keys=True),
            'subject_refs':['workspace'],'checker':'root','task_refs':[]})
        acceptance.commit(acceptance.propose(plan,CapabilityTree(config['root_goal'],())))
    class RootCheck:
        descriptor=ExecutorDescriptor('goal.acceptance@1','deterministic_checker',('*',))
        def execute(self,request):
            if digest_file(checker)!=config['completion']['checker_sha256']:raise ValueError('CHECKER_IDENTITY_MISMATCH')
            goal_id=request.task_context.node_config.get('acceptance_goal_id','root')
            goal=next((g for g in acceptance.data['plans'][-1]['goals'] if g['id']==goal_id),None)
            if goal is None:raise ValueError('unknown acceptance_goal_id')
            checked_requirements={k:requirements[k] for k in goal['requirement_refs']}
            before=workspace_identity(workspace)
            from cgkn.execution.node_effects import perform_scoped_effect
            completed=perform_scoped_effect('EXTERNAL_SUBPROCESS',lambda:subprocess.run([sys.executable,str(checker),*config['completion'].get('checker_args',[]),'--workspace',str(workspace)],
                capture_output=True,text=True,encoding='utf-8',timeout=60,env=child_environment(),creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)))
            try:observed=json.loads(completed.stdout)
            except ValueError:observed={'error':'invalid checker response','stdout':completed.stdout[-4000:]}
            subjects={'workspace':workspace_identity(workspace)}
            checks=observed.get('requirements',{})
            passed=(completed.returncode==0 and before==subjects['workspace'] and set(checked_requirements)<=set(checks) and set(checks)<=set(requirements)
                    and all(checks[k] is True for k in checked_requirements))
            acceptance.bind_subjects(subjects)
            return BlockExecutionResult(project_id=request.project_id,run_id=request.run_id,node_id=request.node_id,
                attempt_id=request.attempt_id,executor_ref=request.executor_ref,status=BlockStatus.SUCCEEDED,
                outputs={'goal_check':{'goal_id':goal_id,'condition_hash':identity(goal['acceptance']),'subjects':subjects,'execution':'VALID',
                    'verdict':'VERIFIED' if passed else 'FAILED','observed':{'oracle':observed,'exit_code':completed.returncode,
                    'stderr':completed.stderr[-4000:],'checker_sha256':digest_file(checker)},'evidence_refs':[str(checker)]}})
    def local_artifacts(root,c):
        outcomes={}
        from cgkn.execution.file_actions import candidate_files
        for name in candidate_files(root,c):
            p=root/name
            try:
                if not p.is_file() or not p.stat().st_size:raise ValueError('absent or empty')
                if p.suffix=='.py':compile(p.read_text(encoding='utf-8'),name,'exec')
                if name in c.get('portable_output_contracts',{}):
                    from jsonschema import Draft202012Validator
                    schema=json.loads(c['portable_output_contracts'][name]['contract']['schema_json'])
                    if list(Draft202012Validator(schema).iter_errors(json.loads(p.read_text(encoding='utf-8')))):
                        raise ValueError('component output violates declared Port contract')
                outcomes[name]=True
            except (ValueError,SyntaxError,UnicodeError):outcomes[name]=False
        return {'passed':all(outcomes.values()),'observed':{'nonempty_and_compilable':outcomes,'utility':'NOT_EVALUATED'},
                'artifacts':[n for n,v in outcomes.items() if v]}
    def observation(request,c):
        raw=request.input_values['execution_receipt']
        return {'passed':raw['status']=='SUCCEEDED','observed':raw['outputs'] or {'empty_observation':True},
                'evidence_refs':[dict(request.input_values['execution_receipt_ref'])]}
    roles=config['resource_and_effect_limits']['models']
    recorded=RecordedCompletionClient(client,store,project,run)
    planner=ModelRoleConfig('agent',**roles['planner']);worker=ModelRoleConfig('worker',**roles['worker'])
    registry=ExecutorRegistry();registry.register(FileExecutor(workspace))
    tests=PythonTestExecutor(workspace);tests.environment_base=child_environment();registry.register(tests)
    registry.register(LLMExecutor(workspace,recorded,worker,max_rounds=config['resource_and_effect_limits']['max_calls_per_leaf']));registry.register(RootCheck())
    registry.register(FileDeliverableChecker(workspace,{'local-artifacts':local_artifacts}))
    registry.register(SubjectDeliverableChecker(lambda c:{name:workspace_identity(workspace) for name in c['target_scope']}, {'observation':observation}))
    planning_contract=CapabilityContract('host.planning@1','Produce a bounded public proposal for the authorized root goal',
        critical=False,positive_controls=('public-proposal-captured',),evidence_requirements={'allow_imported_unmanaged':True})
    limits=config['resource_and_effect_limits']
    node_limit=limits.get('max_new_nodes_per_decision',limits['max_calls_per_leaf'])
    if type(node_limit) is not int or node_limit<1:raise ValueError('max_new_nodes_per_decision must be a positive integer')
    policy=AdmissionPolicy(project_id=project,capability_contracts={'host.planning@1':asdict(planning_contract)},
        allowed_effect_domains=frozenset({'filesystem','measurement','local_process','external_network'}),
        allow_remote_effects=True,execution_budget={'calls':limits['max_calls_per_leaf']},
        max_new_nodes=node_limit)
    composer=GoalComposer(recorded,planner,require_decision_audit=True,allow_goal_plan=False)
    composer.workspace=workspace;composer.run_root=Path(run_root);composer.goal_config=config
    composer.additional_instructions='''The user supplies the outcome, not a route. Retain every original requirement.
Choose only the next useful bounded frontier; no prefilled node names or complete future workflow.
Use available_context fetch_artifact for authorized input investigation without creating a capability node.
In summary/reason name the unmet requirement IDs, cite relevant current result references, explain
the selected executor and the next observable confirmation. Do not invent historical success rates.
New capability_ref values must be project.<meaningful-name>@1. For a coding leaf choose executor_ref=llm.cheap@1,
goal, target_paths (public outputs), component_roots (bounded internal directories), read_paths and expected_delta.
Worker chooses internal source/tests and repairs in the same delegation; local self-tests do not establish goal acceptance.
In this Host-compiled application do NOT supply config.leaf_contract; Host constructs it.
Each edits item supplies operation, node_id and payload. Host generates decision_id, edit_id and provenance; do not invent lineage. For add_node,
capability_ref, parent_id, depends_on and config MUST be INSIDE payload, never beside payload.
The JSON shape is {"operation":"add_node","node_id":"your-node",
"payload":{"capability_ref":"project.your-capability@1","parent_id":"","depends_on":[],
"config":{"executor_ref":"your-selected-executor","goal":"your-bounded-goal"}}}.
This is syntax only; choose your own next work and executor-specific config fields. Parent may be empty.
Host compiles local contract boilerplate and admits it; new project capability is not a new trusted Host tool.
Available deterministic executors: local.file@1 (read_file/list_files action and relative path),
local.python-test@1 (pytest_args), goal.acceptance@1 (final independent user-path checker).
Do not modify __host_planning_root__. Avoid attaching business nodes to that Host-only scope.
For a bounded repair use update_config for the goal then retry_node, preserving permissions and prior failure.
One decision may retry ONLY ONE earliest affected node; its dependent subtree is invalidated automatically.
Never add a second retry_node for its downstream consumer in the same decision.
Previously locally checked files require verified_artifact_change_reason in update_config, citing current failed
independent product observation or recorded failure. A local compile PASS does not prove product Utility.
If an interface/scope must change, create a new explicit project capability and bind real dependencies.
Local nonempty/compile checks are not product success. Run final acceptance only when the whole product is plausibly usable.
Public decision_audit must contain expected_outcome; cite requirement_refs and facts. Alternatives are optional; no private chain of thought.
No goal_plan edits. Finish only when independent root acceptance is complete. Do not inspect secrets or network.
'''
    runner=DAGRunner(registry,store,max_parallel=1,deliverable_checkers={'files':'deliverable.files@1','observations':'deliverable.subjects@1'})
    session=ProjectSession(composer,runner,store,known_capabilities=set(),worker_model=worker.model,
        capability_catalog={},admission_policy=policy,acceptance=acceptance,max_decisions=limits['max_planning_decisions'],continuous=False)
    composer.session=session
    from cgkn.adapters.veriarbor.skill_authority import lifecycle_for_run
    from veriarbor.skills import SkillMatcher
    skill_lifecycle=lifecycle_for_run(config,store,runner._authority(project,run))
    session.skill_lifecycle=skill_lifecycle
    session.skill_trial=config.get('skill_trial')
    session.skill_matcher=SkillMatcher(skill_lifecycle.registry)
    session.skill_task=config.get('skill_task')
    from cgkn.adapters.veriarbor.component_package import ComponentPackages
    composer.component_packages=ComponentPackages(store,project,run)
    composer.component_packages.materialize_inputs(workspace,config.get('reuse_context',{}))
    from cgkn.adapters.veriarbor.component_package import PortableComponentExecutor
    portable=PortableComponentExecutor(workspace,composer.component_packages,config.get('reuse_context',{}))
    registry.register(portable)
    composer.application_executors={**getattr(composer,'application_executors',{}),
        'local.component@1':{'config_fields':['package_identity','inputs','bindings','output_paths'],
            'description':'Invoke an imported component with exact Block/Port semantics, literal inputs or dependency port bindings, and bounded output destinations. Source-only packages are not executable.',
            'compile':portable.compile}}

    # Resume restores admissible local contract metadata from the authoritative
    # committed admission, not from a second catalog database or chat history.
    authority=runner._authority(project,run);committed=authority.committed_tree()
    if committed:
        tree=CapabilityTree.from_dict(committed['tree'])
        admitted=authority._find('PROPOSAL_ADMITTED','admission_id',committed['admission_id'])
        session.admission_policy=replace(policy,capability_contracts=admitted['contracts'])
        session.known_capabilities=frozenset(n.capability_ref for n in tree.nodes if n.executable)
        session.capability_catalog={n.capability_ref:{'executor_ref':n.config['executor_ref'],'config':n.as_dict()['config']} for n in tree.nodes if n.executable}
    # A decision may fetch the declared bounded context before answering.
    # This allocation is planning-only; Worker permits retain max_calls_per_leaf.
    from cgkn.protocol.exchange import MAX_CONTEXT_EXPANSIONS
    planning_calls=MAX_CONTEXT_EXPANSIONS+1
    if 'max_api_calls' in limits:planning_calls=min(planning_calls,limits['max_api_calls'])
    composer.max_context_expansions=planning_calls-1
    planning_policy=replace(policy,execution_budget={'calls':planning_calls})
    scope=HostPlanningScope(planning_policy,max_decisions=limits['max_planning_decisions'],calls_per_decision=planning_calls)
    return session,scope

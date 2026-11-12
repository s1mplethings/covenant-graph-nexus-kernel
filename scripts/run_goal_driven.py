"""Finite goal-driven ProjectSession entry. No implicit budgets or model fallback."""
from pathlib import Path
import argparse,hashlib,json,math,os,signal,sys,time
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))

def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def hash_file(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def execution_deadline(store, rd, max_seconds, *, resume, now=None, inherited_window=None):
    """One frozen wall-clock allowance per run, including restarts and downtime."""
    now=time.time() if now is None else now
    path=rd/'execution-window.json'
    if resume:
        if not path.is_file():
            raise ValueError('EXECUTION_WINDOW_MISSING: reconcile original time allowance before resume')
        value=read(path)
    else:
        if inherited_window is not None:
            source=Path(inherited_window['path'])
            if source.is_symlink() or hash_file(source)!=inherited_window['sha256']:
                raise ValueError('INHERITED_EXECUTION_WINDOW_IDENTITY_MISMATCH')
            value=read(source)
        else:
            value={'started_at':now,'max_seconds':max_seconds,'deadline':now+max_seconds}
    if (value.get('max_seconds')!=max_seconds or
        any(type(value.get(k)) not in {int,float} or not math.isfinite(value[k]) for k in ('started_at','deadline')) or
        value['deadline']!=value['started_at']+max_seconds):
        raise ValueError('EXECUTION_WINDOW_INVALID: inspect original immutable run evidence')
    if now < value['started_at']:
        raise ValueError('EXECUTION_CLOCK_REGRESSION: reconcile clock before resume')
    if not resume:store.immutable_json(path,value)
    return value['deadline']


def bind_goal_config(store, rd, frozen, command, source_revision=None):
    """Version user additions in the existing run; retain limits and source identity."""
    from cgkn.state import EventRecord
    from cgkn.runtime.acceptance import open_goal_acceptance as GoalAcceptance
    from cgkn.state.acceptance import identity
    if command=='start':
        store.immutable_json(rd/'goal-config.json',frozen)
        return
    current=read(rd/'goal-config.json')
    project=frozen['config']['project_id'];run=frozen['config']['run_id']
    events=store.load_events(project,run) if (rd/'events.jsonl').exists() else ()
    for event in events:
        if event.event_type not in {'GOAL_CONFIG_EXTENDED','GOAL_FRAMEWORK_REVISED'}:continue
        if event.data['parent_identity']!=identity(current):raise ValueError('broken requirement revision lineage')
        successor=read(rd/'goal-config-revisions'/(event.data['identity']+'.json'))
        if identity(successor)!=event.data['identity']:raise ValueError('requirement revision identity mismatch')
        current=successor
    if command=='revise-sources':
        if frozen==current:return
        proof=source_revision or {}
        if proof.get('parent_config_identity')!=identity(current) or not proof.get('authority_reference') or not proof.get('reason'):
            raise ValueError('source revision requires exact parent identity, authority and observed reason')
        if frozen['config']!=current['config'] or frozen['checker']!=current['checker'] or frozen.get('core_sources')!=current.get('core_sources'):
            raise ValueError('source revision cannot change requirements, budget, inputs, checker or Core')
        old=current['sources'];new=frozen['sources']
        changes={p:{'before':old.get(p),'after':new.get(p)} for p in set(old)|set(new) if old.get(p)!=new.get(p)}
        if not changes or proof.get('changes')!=changes:
            raise ValueError('source revision must bind every changed Host source hash')
        state=store.load_run(project,run) if (rd/'run_state.json').exists() else None
        if state is not None and state.nodes:
            if any(getattr(row,'status',None) not in {'FAILED','BLOCKED','PENDING'} for row in state.nodes.values()):
                raise ValueError('source revision requires pre-materialization state; successful or unresolved business work needs a qualified successor')
            for attempt in (rd/'attempts').glob('*/*.json'):
                saved=read(attempt)
                if saved.get('status')=='SUCCEEDED' or (saved.get('error') or {}).get('details',{}).get('outcome_unknown'):
                    raise ValueError('source revision cannot inherit successful or UNKNOWN historical execution')
            area=frozen['config'].get('inputs_and_workspace',{})
            workspace=Path(area.get('workspace','')).resolve()
            if not area.get('workspace') or not workspace.is_dir():raise ValueError('source revision requires explicit unmaterialized workspace')
            expected={str(Path('inputs')/item['name']):item['sha256'] for item in area.get('inputs',[])}
            actual={str(p.relative_to(workspace)):hash_file(p) for p in workspace.rglob('*') if p.is_file()}
            # Host's read-only feedback projections are not business products.
            actual={p:h for p,h in actual.items() if not Path(p).is_relative_to(Path('inputs')/'runtime-results')}
            if actual!=expected:raise ValueError('source revision cannot reuse existing product bytes')
        ledger_path=Path(frozen['config'].get('budget_ledger',rd.parents[2]/'provider-budget.json'))
        if not ledger_path.is_file() or hash_file(ledger_path)!=proof.get('ledger_sha256'):
            raise ValueError('source revision requires exact preserved budget ledger')
        ledger=read(ledger_path)
        if any(row.get('status') not in {'SUCCEEDED','FAILED','CANCELLED_BEFORE_SEND'} for row in ledger.get('calls',[])):
            raise ValueError('source revision requires all Provider attempts to be settled; preserve UNKNOWN')
        revision=identity(frozen)
        store.immutable_json(rd/'goal-config-revisions'/(revision+'.json'),frozen)
        store.append_event(EventRecord('source-revision-'+revision,project,run,'GOAL_FRAMEWORK_REVISED',
            data={'identity':revision,'parent_identity':identity(current),'authority_reference':proof['authority_reference'],
                  'reason':proof['reason'],'changes':changes,'ledger_sha256':proof['ledger_sha256'],
                  'evidence_applicability':'No successful business execution or product bytes reused; failed attempts, planning and costs retained, no new PASS granted'}))
        return
    if command!='extend':
        if frozen!=current:raise ValueError('frozen config/source changed; use an authorized requirement extension')
        return
    old=current['config'];new=frozen['config']
    amendment=new.get('requirement_extension',{})
    if frozen==current:return  # idempotent resume of an already committed extension
    if amendment.get('parent_config_identity')!=identity(current) or not amendment.get('authority_reference'):
        raise ValueError('extension requires current parent_config_identity and user authority_reference')
    for key in set(current)|set(frozen):
        if key not in {'config','checker'} and current.get(key)!=frozen.get(key):
            raise ValueError('source identity changed; requirement extension cannot authorize framework replacement')
    for key in set(old)|set(new):
        if key not in {'requirements','completion','requirement_extension'} and old.get(key)!=new.get(key):
            raise ValueError('extension cannot alter original goal, limits, models, inputs or run lineage: '+key)
    if any(new['requirements'].get(k)!=v for k,v in old['requirements'].items()):
        raise ValueError('extension cannot remove or change original requirements')
    additions={k:{'must':True,'description':v} for k,v in new['requirements'].items() if k not in old['requirements']}
    if not additions:raise ValueError('extension has no new requirements')
    # Preserve UNKNOWN before changing the user's active acceptance version.
    if (rd/'run_state.json').exists():
        state=store.load_run(project,run)
        for node,record in state.nodes.items():
            if record.status=='RUNNING':raise ValueError('extension requires reconciliation of running work')
            if record.latest_result_ref:
                result=store.load_result(project,run,node)
                if result.error and result.error.details.get('outcome_unknown'):
                    raise ValueError('extension requires reconciliation of UNKNOWN before new dispatch')
    revision=identity(frozen)
    store.immutable_json(rd/'goal-config-revisions'/(revision+'.json'),frozen)
    required={k:{'must':True,'description':v} for k,v in old['requirements'].items()}
    saved=read(rd/'goal_acceptance.json')
    if saved['requirements']==required:
        acceptance=GoalAcceptance(store,project,run,required,{'root':'goal.acceptance@1'})
        acceptance.extend_requirements(additions,authority_reference=amendment['authority_reference'])
    elif saved['requirements']!={**required,**additions} or not any(
            r.get('additions')==additions and r.get('authority_reference')==amendment['authority_reference']
            for r in saved.get('requirement_revisions',[])):
        raise ValueError('interrupted extension does not match preserved acceptance revision')
    store.append_event(EventRecord('extension-'+revision,project,run,'GOAL_CONFIG_EXTENDED',
        data={'identity':revision,'parent_identity':identity(current),'authority_reference':amendment['authority_reference']}))


def preflight(config):
    from cgkn.application.goal_driven import relative_files
    limits=config['resource_and_effect_limits'];reasons=[]
    required=['authorization_reference','billing_mode','currency','pricing_reference','max_api_calls',
              'max_input_tokens','max_output_tokens','max_estimated_cost','input_cost_per_million','output_cost_per_million',
              'max_seconds','max_planning_decisions','max_calls_per_leaf','models','allowed_egress']
    reasons += ['missing '+k for k in required if limits.get(k) is None or limits.get(k)=='']
    if limits.get('billing_mode') not in {None,'api_estimated_with_frozen_upper_rates'}:reasons.append('billing channel not supported by this adapter')
    for name in ['max_api_calls','max_input_tokens','max_output_tokens','max_seconds','max_planning_decisions','max_calls_per_leaf']:
        if limits.get(name) is not None and (type(limits[name]) is not int or limits[name]<=0):reasons.append('invalid '+name)
    for name in ['max_estimated_cost','input_cost_per_million','output_cost_per_million']:
        if limits.get(name) is not None and (type(limits[name]) not in {float,int} or not math.isfinite(limits[name]) or limits[name]<0):reasons.append('invalid '+name)
    if limits.get('allowed_egress') is not None and (not isinstance(limits['allowed_egress'],list) or not limits['allowed_egress'] or any(not isinstance(x,str) or not x.strip() for x in limits['allowed_egress'])):
        reasons.append('explicit allowed egress data scope required')
    if not isinstance(config.get('requirements'),dict) or not config['requirements']:reasons.append('observable requirements missing')
    checker_args=config['completion'].get('checker_args',[])
    if not isinstance(checker_args,list) or any(not isinstance(x,str) for x in checker_args):reasons.append('checker_args must be an explicit string list')
    checker=Path(config['completion']['checker_path'])
    if not checker.is_file() or hash_file(checker)!=config['completion']['checker_sha256']:reasons.append('checker identity mismatch')
    area=config['inputs_and_workspace'];workspace=Path(area['workspace']).resolve();runroot=Path(config['run_root']).resolve()
    if workspace==runroot or workspace.is_relative_to(runroot) or runroot.is_relative_to(workspace):reasons.append('separate product workspace and Host store required')
    for item in area['inputs']:
        p=Path(item['path']).resolve()
        if not p.is_file() or p.is_symlink() or hash_file(p)!=item['sha256']:reasons.append('input identity mismatch: '+str(p))
        if p==workspace or p.is_relative_to(workspace) or p.is_relative_to(runroot):reasons.append('source input must be outside writable areas')
        if Path(item['name']).name!=item['name'] or ':' in item['name']:reasons.append('input copy name must be a plain filename')
    for role in ('planner','worker'):
        model=limits.get('models',{}).get(role,{})
        if model.get('model') not in {'qwen','deepseek','grok'} or not model.get('model_id'):reasons.append('concrete authorized '+role+' route missing')
    return {'status':'BLOCKED_AUTHORIZATION_OR_CONFIG' if reasons else 'CONFIGURED_NOT_QUALIFIED',
            'reasons':reasons,'provider_contacted':False,'cost_basis':'estimate with configured upper rates, not supplier invoice',
            'scope':'one finite product goal; no A/B, no long-run campaign'}

def main(argv=None):
    ap=argparse.ArgumentParser();ap.add_argument('command',choices=['preflight','start','resume','extend','revise-sources','status','stop','report','export-component','import-component','register-skill','export-skill','import-skill','requalify-skill'])
    ap.add_argument('--config',required=True,type=Path);ap.add_argument('--output',type=Path);ap.add_argument('--revision',type=Path);ap.add_argument('--feedback',type=Path);ap.add_argument('--package',type=Path);ap.add_argument('--skill',type=Path)
    args=ap.parse_args(argv)
    if args.feedback and args.command!='resume':raise ValueError('--feedback requires explicit resume')
    feedback=read(args.feedback) if args.feedback else None
    if feedback is not None and (not isinstance(feedback,dict) or set(feedback)!={'redecision'}):raise ValueError('resume feedback requires explicit redecision evidence')
    config=read(args.config);runroot=Path(config['run_root']).resolve();workspace=Path(config['inputs_and_workspace']['workspace']).resolve()
    if args.command in {'register-skill','export-skill','import-skill','requalify-skill'}:
        if not args.skill:raise ValueError('--skill JSON manifest or envelope required')
        from cgkn.state import FileRunStore
        from cgkn.runtime.node_authority import ExecutionAuthority
        from cgkn.adapters.veriarbor.skill_authority import lifecycle_for_run
        from veriarbor.skills import SkillManifest
        store=FileRunStore(runroot/'store');authority=ExecutionAuthority(store,config['project_id'],config['run_id'])
        lifecycle=lifecycle_for_run(config,store,authority);row=read(args.skill)
        with store.exclusive_file(store.run_dir(config['project_id'],config['run_id'])/'session.lock'):
            if args.command=='export-skill':
                if not args.output:raise ValueError('--output required for portable Skill export')
                value=lifecycle.export(row['skill_id'],row['version'])
                with args.output.open('x',encoding='utf-8') as handle:json.dump(value,handle,ensure_ascii=False,indent=2)
            elif args.command=='import-skill':
                value=lifecycle.import_candidate(row,project_id=config['project_id']).as_dict()
            elif args.command=='register-skill':
                manifest,validations=lifecycle.candidate(SkillManifest(**row['manifest']),row['receipt_ids'])
                if manifest.scope!='PROJECT' or manifest.project_id!=config['project_id']:
                    raise ValueError('initial registration requires current project candidate')
                lifecycle.registry.register(manifest,validations);value=manifest.as_dict()
            else:
                value=lifecycle.requalify(row['skill_id'],row['version'],row['receipt_ids'],project_id=config['project_id']).as_dict()
        print(json.dumps(value,ensure_ascii=False));return 0
    if args.command in {'export-component','import-component'}:
        if not args.package:raise ValueError('--package JSON manifest required')
        from cgkn.state import FileRunStore
        from cgkn.runtime.node_authority import ExecutionAuthority
        from cgkn.adapters.veriarbor.component_package import ComponentPackages
        from veriarbor.block import Block
        store=FileRunStore(runroot/'store');packages=ComponentPackages(store,config['project_id'],config['run_id'])
        row=read(args.package)
        with store.exclusive_file(store.run_dir(config['project_id'],config['run_id'])/'session.lock'):
            if args.command=='export-component':
                authority=ExecutionAuthority(store,config['project_id'],config['run_id'])
                value=packages.export(block=Block.from_dict(row['block']),artifact_paths=row['artifact_paths'],
                    receipt_id=row['receipt_id'],authority=authority,entrypoint=row['entrypoint'],
                    dependencies=row['dependencies'],applicability=row['applicability'],invocation=row.get('invocation'))
                if not args.output:raise ValueError('--output required for portable export')
                with args.output.open('x',encoding='utf-8') as handle:json.dump(value,handle,ensure_ascii=False,indent=2)
            else:
                value=packages.import_candidate(row,context=config.get('reuse_context',{}),dependencies=row['dependencies'])
        print(json.dumps(value,ensure_ascii=False));return 0
    if args.command=='preflight':
        value=preflight(config);print(json.dumps(value,ensure_ascii=False));return 0 if not value['reasons'] else 2
    if args.command in {'status','report','stop'}:
        if not runroot.is_dir():raise ValueError('run has not started')
        if args.command=='stop':
            with (runroot/'stop.request').open('a',encoding='utf-8') as f:f.write('operator stop\n')
            print(json.dumps({'status':'STOP_REQUESTED','remote_stop_confirmed':False}));return 0
        from cgkn.state import FileRunStore,StateStoreError
        store=FileRunStore(runroot/'store');rd=store.run_dir(config['project_id'],config['run_id']);active=False
        try:
            with store.exclusive_file(rd/'session.lock'):pass
        except StateStoreError:active=True
        value={'active':active,'run_root':str(runroot),'results':[read(p) for p in sorted(rd.glob('invocation-*.json'))],
               'run_state':read(rd/'run_state.json') if (rd/'run_state.json').exists() else None}
        from cgkn.state.acceptance import identity
        revisions=[e.data['identity'] for e in store.load_events(config['project_id'],config['run_id']) if e.event_type in {'GOAL_CONFIG_EXTENDED','GOAL_FRAMEWORK_REVISED'}] if (rd/'events.jsonl').exists() else []
        value['config_identity']=revisions[-1] if revisions else identity(read(rd/'goal-config.json'))
        if args.command=='report':
            if args.output is None:raise ValueError('--output required')
            with args.output.open('x',encoding='utf-8') as f:json.dump(value,f,ensure_ascii=False,indent=2)
        else:print(json.dumps(value,ensure_ascii=False))
        return 0
    check=preflight(config)
    if check['reasons']:print(json.dumps(check,ensure_ascii=False));return 2
    # Live setup is reachable only after the operator supplies this project's
    # explicit scope. An account login or old global budget is never imported.
    from cgkn.state import FileRunStore
    if args.command=='start':
        if workspace.exists() or runroot.exists():raise ValueError('new workspace and run root required')
        runroot.mkdir(parents=True);workspace.mkdir(parents=True)
    store=FileRunStore(runroot/'store');rd=store.run_dir(config['project_id'],config['run_id'])
    with store.exclusive_file(rd/'application.lock'):
        frozen={'config':config,'sources':{str(p):hash_file(p) for base in [ROOT/'cgkn',ROOT/'scripts'/Path(__file__).name] for p in (base.rglob('*.py') if base.is_dir() else [base])},
                'checker':hash_file(config['completion']['checker_path'])}
        import veriarbor
        frozen['core_sources']={str(p):hash_file(p) for p in Path(veriarbor.__file__).parent.rglob('*.py')}
        bind_goal_config(store,rd,frozen,args.command,read(args.revision) if args.revision else None)
        if args.command=='revise-sources':
            print(json.dumps({'status':'SOURCE_REVISION_RECORDED','provider_dispatched':False,'run_id':config['run_id']}));return 0
        if args.command=='start':
            import shutil
            (workspace/'inputs').mkdir()
            for item in config['inputs_and_workspace']['inputs']:shutil.copyfile(item['path'],workspace/'inputs'/item['name'])
        else:
            for item in config['inputs_and_workspace']['inputs']:
                if hash_file(workspace/'inputs'/item['name'])!=item['sha256']:raise ValueError('READ_ONLY_INPUT_CHANGED')
            if (runroot/'stop.request').exists():(runroot/'stop.request').rename(runroot/('stop-consumed-'+str(time.time_ns())))
        limits=config['resource_and_effect_limits']
        deadline=execution_deadline(store,rd,limits['max_seconds'],resume=args.command!='start',
            inherited_window=config.get('inherited_execution_window'))
        if time.time()>=deadline:
            raise ValueError('PROVIDER_BUDGET_EXHAUSTED: original execution deadline reached; inspect status, no new dispatch permitted')
        envmap={'max_api_calls':'MAX_API_CALLS','max_input_tokens':'MAX_INPUT_TOKENS','max_output_tokens':'MAX_OUTPUT_TOKENS',
                'max_estimated_cost':'MAX_ESTIMATED_COST','input_cost_per_million':'INPUT_COST_PER_MILLION','output_cost_per_million':'OUTPUT_COST_PER_MILLION'}
        for key,suffix in envmap.items():os.environ['CGKN_PROVIDER_'+suffix]=str(limits[key])
        ledger=Path(config.get('budget_ledger',runroot/'provider-budget.json')).resolve()
        if ledger.is_relative_to(workspace):raise ValueError('budget ledger must be outside product workspace')
        os.environ['CGKN_PROVIDER_BUDGET_LEDGER']=str(ledger)
        from cgkn.providers import completion_client_from_environment,GatewayCompletionClient
        from dataclasses import replace
        raw=completion_client_from_environment()
        if not isinstance(raw,GatewayCompletionClient):raise ValueError('existing governed Gateway required; no legacy fallback')
        raw=replace(raw,run_id=config['run_id'],case_id=config['project_id'],enforce_budget=True,
                    authorization_reference=limits['authorization_reference'],input_token_ceiling=limits['max_input_tokens'])
        started=time.monotonic();started_wall=time.time();stop=[False]
        signal.signal(signal.SIGINT,lambda *_:stop.__setitem__(0,True));signal.signal(signal.SIGTERM,lambda *_:stop.__setitem__(0,True))
        class Cancel:
            def is_set(self):return stop[0] or (runroot/'stop.request').exists() or time.time()>=deadline or time.monotonic()-started>=max(0,deadline-started_wall)
        cancel=Cancel()
        class BoundClient(GatewayCompletionClient):
            def complete(self,**kw):
                if cancel.is_set():raise RuntimeError('PROVIDER_BUDGET_EXHAUSTED: finite run stopped')
                return super().complete(**kw,cancel=cancel)
        from dataclasses import fields
        bound=BoundClient(**{f.name:getattr(raw,f.name) for f in fields(raw)})
        from cgkn.application.goal_driven import build_session
        session,planning=build_session(config,runroot,bound)
        intent={'overall_goal':config['root_goal'],'user_visible_outcomes':list(config['requirements'].values()),
            'constraints':['retain original requirements','write only bounded product candidates','explicit sanitized inputs only','no publication'],
            'forbidden_operations':['change budgets, checker or Host control code','read credentials','network outside configured Provider scope'],
            'delivery_expectations':[config['completion']['description'],
                json.dumps(config['completion'].get('public_acceptance_interface',{}),ensure_ascii=False),
                'Read-only supplied copies: '+json.dumps(['inputs/'+x['name'] for x in config['inputs_and_workspace']['inputs']])],
            'major_acceptance_categories':list(config['requirements'])}
        try:
            result=session.run(project_id=config['project_id'],run_id=config['run_id'],goal=config['root_goal'],
                resume=args.command!='start',planning=planning,project_intent=intent,cancel=cancel,finish_when_verified=True,continuation_feedback=feedback).as_dict()
        except Exception as exc:
            result={'status':'BLOCKED','error':type(exc).__name__+': '+str(exc),'instruction':'preserve attempts and inspect recorded outcomes; no automatic replay'}
        result.update(elapsed_seconds=time.monotonic()-started,scope='configured goal-driven path; real transport must be established from raw receipts',cost_source=str(ledger))
        store.immutable_json(rd/('invocation-'+str(time.time_ns())+'.json'),result)
        print(json.dumps(result,ensure_ascii=False));return 0 if result['status']=='GOALS_VERIFIED' else 3
if __name__=='__main__':
    try:sys.exit(main())
    except (ValueError,KeyError,OSError,RuntimeError) as exc:print(json.dumps({'status':'BLOCKED','error':str(exc)},ensure_ascii=False));sys.exit(2)

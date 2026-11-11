"""Finite goal-driven ProjectSession entry. No implicit budgets or model fallback."""
from pathlib import Path
import argparse,hashlib,json,math,os,signal,sys,time
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))

def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def hash_file(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
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
    ap=argparse.ArgumentParser();ap.add_argument('command',choices=['preflight','start','resume','status','stop','report'])
    ap.add_argument('--config',required=True,type=Path);ap.add_argument('--output',type=Path)
    args=ap.parse_args(argv);config=read(args.config);runroot=Path(config['run_root']).resolve();workspace=Path(config['inputs_and_workspace']['workspace']).resolve()
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
        store.immutable_json(rd/'goal-config.json',frozen)
        if args.command=='start':
            import shutil
            (workspace/'inputs').mkdir()
            for item in config['inputs_and_workspace']['inputs']:shutil.copyfile(item['path'],workspace/'inputs'/item['name'])
        else:
            for item in config['inputs_and_workspace']['inputs']:
                if hash_file(workspace/'inputs'/item['name'])!=item['sha256']:raise ValueError('READ_ONLY_INPUT_CHANGED')
            if (runroot/'stop.request').exists():(runroot/'stop.request').rename(runroot/('stop-consumed-'+str(time.time_ns())))
        limits=config['resource_and_effect_limits']
        envmap={'max_api_calls':'MAX_API_CALLS','max_input_tokens':'MAX_INPUT_TOKENS','max_output_tokens':'MAX_OUTPUT_TOKENS',
                'max_estimated_cost':'MAX_ESTIMATED_COST','input_cost_per_million':'INPUT_COST_PER_MILLION','output_cost_per_million':'OUTPUT_COST_PER_MILLION'}
        for key,suffix in envmap.items():os.environ['CGKN_PROVIDER_'+suffix]=str(limits[key])
        os.environ['CGKN_PROVIDER_BUDGET_LEDGER']=str(runroot/'provider-budget.json')
        from cgkn.providers import completion_client_from_environment,GatewayCompletionClient
        from dataclasses import replace
        raw=completion_client_from_environment()
        if not isinstance(raw,GatewayCompletionClient):raise ValueError('existing governed Gateway required; no legacy fallback')
        raw=replace(raw,run_id=config['run_id'],case_id=config['project_id'],enforce_budget=True,
                    authorization_reference=limits['authorization_reference'],input_token_ceiling=limits['max_input_tokens'])
        started=time.monotonic();stop=[False]
        signal.signal(signal.SIGINT,lambda *_:stop.__setitem__(0,True));signal.signal(signal.SIGTERM,lambda *_:stop.__setitem__(0,True))
        class Cancel:
            def is_set(self):return stop[0] or (runroot/'stop.request').exists() or time.monotonic()-started>=limits['max_seconds']
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
                resume=args.command=='resume',planning=planning,project_intent=intent,cancel=cancel,finish_when_verified=True).as_dict()
        except Exception as exc:
            result={'status':'BLOCKED','error':type(exc).__name__+': '+str(exc),'instruction':'preserve attempts and inspect recorded outcomes; no automatic replay'}
        result.update(elapsed_seconds=time.monotonic()-started,scope='configured goal-driven path; real transport must be established from raw receipts',cost_source=str(runroot/'provider-budget.json'))
        store.immutable_json(rd/('invocation-'+str(time.time_ns())+'.json'),result)
        print(json.dumps(result,ensure_ascii=False));return 0 if result['status']=='GOALS_VERIFIED' else 3
if __name__=='__main__':
    try:sys.exit(main())
    except (ValueError,KeyError,OSError,RuntimeError) as exc:print(json.dumps({'status':'BLOCKED','error':str(exc)},ensure_ascii=False));sys.exit(2)

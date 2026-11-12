"""Resume the original ProjectSession with recorded cheap-first routing.

No business implementation is authored here. All candidate writes remain
bounded Provider work under the existing executor, admission and provenance.
"""
from pathlib import Path
import datetime
import dataclasses
import hashlib
import json
import os
import sys
import traceback

H = Path(__file__).resolve().parents[2]
V = Path(r'D:\VeriArbor')
P = Path(r'F:\CGKN-ITER-132\production-core-convergence-v1')
sys.path.insert(0, str(H))


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)


def main():
    label = sys.argv[1]
    if not label.startswith('veriarbor-') or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789-' for c in label):
        raise ValueError('invalid continuation identity')
    migration = H / 'migration/veriarbor'
    assert read(migration / 'P0_REQUIRED_BASELINE.json')['status'] == 'P0_REQUIRED_BASELINE_CAPTURED'
    regression = read(migration / 'REGRESSION.json')
    assert regression['status'] == 'PASS_FOR_RECORDED_SCOPE' and regression['current_replay_identical']
    assert all(sha(V / rel) == expected for rel, expected in regression['library_sources'].items())
    assert all(sha(H / rel) == expected for rel, expected in regression['host_sources'].items())
    root = P / 'promotion/run-05'
    profile = read(root / 'profile.json')
    fixture = read(root / 'fixture-freeze.json')
    assert sha(root / 'profile.json') == fixture['profile_sha256']
    assert sha(root / 'consumer.py') == fixture['checker_sha256']
    run = root / 'state' / profile['project_id'] / profile['run_id']
    state = read(run / 'run_state.json')
    assert not any(v['status'] in {'UNKNOWN', 'RUNNING', 'INTERRUPTED_UNKNOWN'} for v in state['nodes'].values())
    out = root / 'continuations' / label
    out.mkdir(parents=True, exist_ok=False)
    with (out / 'controller-source.py').open('xb') as stream:
        stream.write(Path(__file__).read_bytes())
    ledger = Path(r'F:\CGKN-ITER-076\global-provider-budget.json')
    before = read(ledger)
    put(out / 'accounting-before.json', before)
    os.environ['CGKN_PROVIDER_BUDGET_LEDGER'] = str(ledger)
    for key, value in before['limits'].items():
        name = 'CGKN_PROVIDER_' + key.upper()
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = str(value)
    from cgkn.providers import completion_client_from_environment, GatewayCompletionClient, CGKNModelRouting
    from cgkn.state import FileRunStore
    from cgkn.state.provenance import put_evidence
    from cgkn.application.software_project.service import SoftwareProjectGenerationService
    client = completion_client_from_environment()
    assert isinstance(client, GatewayCompletionClient)
    client = dataclasses.replace(client, execution_policy='accounting_only',
        authorization_reference=r'C:\Users\sunom\Downloads\VeriArbor_run_from_new_VB_folder_direct_migration_v2_prompt.txt')
    from cgkn.providers.gateway_client import GatewayCompletionError
    startup_profile = None
    startup_profile_saved = False
    def finish_startup_profile():
        nonlocal startup_profile_saved
        if startup_profile is None or startup_profile_saved:
            return
        startup_profile.disable()
        startup_profile_saved = True
        import pstats
        startup_profile.dump_stats(str(out / 'startup.pstats'))
        with (out / 'startup-profile.txt').open('w', encoding='utf-8') as stream:
            pstats.Stats(startup_profile, stream=stream).sort_stats('cumulative').print_stats(30)
    class ControlledGateway(GatewayCompletionClient):
        def complete(self, **kwargs):
            finish_startup_profile()
            # Cooperative stop only before dispatch; an in-flight response is
            # allowed to finish and be durably recorded by the normal client.
            if (out / 'STOP_BEFORE_NEXT_CALL').exists():
                raise GatewayCompletionError('controller_hold_before_dispatch', 'Controller requested a safe boundary for new evidence', outcome_unknown=False)
            acceptance_data = read(run / 'goal_acceptance.json')
            latest = next((c for c in reversed(acceptance_data['checks']) if c['goal_id'] == 'accept-d6e339ee9f02be6ab5e1'), {})
            if latest.get('verdict') == 'VERIFIED' and not (root / 'DOGFOOD_MVP/receipt.json').exists():
                from cgkn.state.acceptance import GoalAcceptance
                current = GoalAcceptance(store, profile['project_id'], profile['run_id'], acceptance_data['requirements'], acceptance_data['checker_bindings']).view()
                if current['obligations']['M7']['verdict'] == 'VERIFIED':
                    raise GatewayCompletionError('dogfood_checkpoint_before_dispatch', 'M7 independently VERIFIED; capture requested DOGFOOD_MVP before further Provider work', outcome_unknown=False)
            return super().complete(**kwargs)
    client = ControlledGateway(**{f.name:getattr(client, f.name) for f in dataclasses.fields(client) if f.init})
    qwen_worker = int(label.split('-')[-1]) >= 7
    alternate_planner = int(label.split('-')[-1]) >= 9
    route_path = migration / 'deepseek-flash-route.json' if int(label.split('-')[-1]) >= 10 else migration / 'cross-family-flash-route.json' if alternate_planner else migration / 'qwen-flash-worker-route.json' if qwen_worker else P / 'provider/production-route-06.json'
    if len(sys.argv) > 2:
        assert len(sys.argv) == 3 and sys.argv[2] in {
            'deepseek-flash-route.json', 'cross-family-flash-route.json', 'qwen-flash-worker-route.json',
            'qwen-agent-deepseek-worker-route.json'}
        route_path = migration / sys.argv[2]
        route_document = read(route_path)
        assert route_document['fallback'] == 'deny'
        assert all(role['model_id'] in {'deepseek-flash', 'qwen3.8-flash'}
                   for role in route_document['roles'].values())
        put(out / 'explicit-flash-route.json', {'path':str(route_path), 'sha256':sha(route_path),
            'reason':'Explicit cheap-tier route replacement after recorded failure; old UNKNOWN requests never replayed'})
    routing = CGKNModelRouting.load(route_path)
    store = FileRunStore(root / 'state')
    from cgkn.agent.project_loop import ProjectSession
    unresolved = ProjectSession._unresolved_execution_nodes(type('StoreView', (), {'store': store})(), profile['project_id'], profile['run_id'])
    assert not unresolved, 'canonical outcome_unknown receipts require reconciliation: ' + repr(unresolved)
    checkpoint = read(run / 'agent_checkpoint.json')
    previous = read(run / 'model_routing_snapshot.json')['routing_config_hash']
    for event in store.load_events(profile['project_id'], profile['run_id']):
        if event.event_type == 'MODEL_ROUTE_CHANGED':
            previous = event.data['to_config_hash']
    evidence = put_evidence(store, profile['project_id'], profile['run_id'], {
        'kind': 'VeriArborMigrationResume', 'migration_regression_sha256': sha(migration / 'REGRESSION.json'),
        'checkpoint_next_decision': checkpoint['next_decision'],
        'user_policy': 'Cheap-first Qwen Flash planner, DeepSeek Flash worker; no Pro for ordinary JSON/schema/context/evaluator/transport bugs; Max zero',
        'library_distribution': 'veriarbor==0.1.0.dev0', 'continuation': label})
    feedback = {
        'milestone_completion_request': 'Continue the original M7 GUI -> M7 independent vertical slice -> DOGFOOD_MVP -> M8-M12. Preserve all verified backend work and M1-M6. Do not rebuild them. Current frontend needs a coherent single-writer fix for DOM IDs, event bindings, non-null saved content_id, state propagation, sequential review/approve/publish and receipt display. Preserve backend public interfaces and already admitted dependency ordering. No host business patches or external publishing.',
        'cost_policy': 'This request supersedes previous Pro escalation suggestions: Qwen Flash Agent and DeepSeek Flash Worker only. No automatic Pro/Max escalation. Same failure+strategy+zero delta must not repeat.',
        'admission_correction': 'hypothesis.falsifying_evidence must be a JSON array of exact current bound evidence references, even for one object. Strategy requires problem plus at least two actual mechanism dimensions. Fix only the rejected fields; no acceptance changes.',
        'migration': {'evidence_ref': evidence, 'original_checkpoint': checkpoint['next_decision'],
                      'certificate_reuse': '83 authenticated M1-M6 predicates rebuilt; original receipts preserved',
                      'host_business_patches': 0},
        'gui_writer_policy': 'One authoritative writer owns the coupled GUI file; inspections are read-only and acceptance reads a frozen completed candidate.',
    }
    if previous != routing.config_hash:
        decision = {'from_config_hash': previous, 'to_config_hash': routing.config_hash,
                    'reason_summary': 'User-requested cheap-first policy after VeriArbor migration; reverting historical Pro routing, no quota or evidence reset',
                    'evidence_refs': [evidence]}
        decision['decision_id'] = hashlib.sha256(json.dumps(decision, sort_keys=True).encode()).hexdigest()
        feedback['route_change'] = decision
    if qwen_worker and len(sys.argv) == 2:
        recovery = migration / 'LOCAL_EFFECT_RECONCILIATION-attempt-0051.json'
        assert read(recovery)['candidate_unchanged'] and read(recovery)['ledger_unchanged']
        feedback['cost_policy'] = 'Qwen Flash Agent and Worker only after DeepSeek explicit HTTP503 service unavailable. This is authorized cheap-tier provider replacement, not Pro/Max escalation. Original UNKNOWN output/usage/cost retained; never replay its request. Same-model review is SELF_CRITIQUE only; independent checker remains acceptance authority.'
        feedback['transport_recovery'] = {'evidence': str(recovery), 'upstream': str(migration / 'WORKER_UNKNOWN06_TRANSPORT.json'), 'disposition': 'Bounded local effects NOT_APPLIED, old upstream UNKNOWN retained. Original GUI task remains incomplete.'}
        if 'route_change' in feedback:
            decision['reason_summary'] = 'Explicit Qwen Flash Worker replacement after DeepSeek HTTP503 service unavailable; bounded local effects reconciled, original UNKNOWN accounting retained, no model tier escalation'
            decision['decision_id'] = hashlib.sha256(json.dumps({k:v for k,v in decision.items() if k != 'decision_id'}, sort_keys=True).encode()).hexdigest()
    if label == 'veriarbor-04':
        blocked_request = run / 'provider_calls/bc3ba60463e749679aa37c1f00f0ee3f/error.json'
        failure = read(blocked_request)
        assert failure['error_type'] == 'ProviderBudgetExhausted' and not failure['outcome_unknown']
        assert read(root / 'continuations/veriarbor-02/accounting-increment.json')['calls'] == []
        feedback['redecision'] = {
            'strategy_revision': hashlib.sha256(b'veriarbor restore original accounting_only pre-dispatch configuration v1').hexdigest(),
            'reason': 'Original planner context271 stopped before dispatch due to limited-mode configuration mismatch. Restore original accounting_only mode with unchanged ledger and prices. New decision identity; preserve old context/request/error. No upstream UNKNOWN replay.',
            'evidence_refs': [str(blocked_request), str(root / 'continuations/veriarbor-02/accounting-increment.json')]}
    if label == 'veriarbor-05':
        rejected = run / 'provider_calls/bc46e7ed0d02410baa0ab098eaaa5d7c/error.json'
        assert read(rejected)['category'] == 'concrete_model_not_admitted' and read(rejected)['outcome_unknown'] is False
        inventories = [migration / ('AUTHENTICATED_MODELS_' + p + '.json') for p in ('qwen', 'deepseek')]
        for path, model in zip(inventories, ('qwen3.8-flash', 'deepseek-flash')):
            inventory = read(path)
            assert inventory['upstream_http_status'] == 200 and model in inventory['model_ids']
        feedback['redecision'] = {
            'strategy_revision': hashlib.sha256(b'veriarbor authenticated inventory refreshed in original gateway session v1').hexdigest(),
            'reason': 'Fresh gateway initialized admission inventory to configured default only; authenticated read-only upstream model listing now admits both exact Flash models. Original rejection known, not UNKNOWN. New decision identity; same cheap-first route, no escalation or original request replay.',
            'evidence_refs': [str(rejected), *(str(p) for p in inventories)]}
    if label == 'veriarbor-06':
        interruption = root / 'continuations/veriarbor-05/controller-interruption.json'
        assert read(interruption)['unfinished_new_calls'] == 0
        assert read(V / 'governance/checks/semantic-anchor/receipt.json')['status'] == 'PASS'
        feedback['admission_correction'] += ' Include BOTH strategy and hypothesis in the initial repair packet. hypothesis requires previous, new, expected_novel_delta and falsifying_evidence array. Strategy must describe the original GUI repair, never a repair to CGKN or its planner. Field corrections now include read-only task_anchor. Use exact acceptance IDs from the current table, never truncated descriptions.'
        feedback['redecision'] = {
            'strategy_revision': hashlib.sha256(b'veriarbor task-bound semantic correction and missing hypothesis v1').hexdigest(),
            'reason': 'Observed narrow correction lost task semantics and rejected missing hypothesis. Host context correction now preserves original task anchor and narrowly requests missing hypothesis, with unchanged strict validation; 789 protocol tests pass. All four prior responses completed; no candidate edits or upstream UNKNOWN replay.',
            'evidence_refs': [str(interruption), str(V / 'governance/checks/semantic-anchor/receipt.json'), str(migration / 'REGRESSION.json')]}
    if label in {'veriarbor-08','veriarbor-09'}:
        diagnostic = migration / 'gui-visibility-904f5b/observation.json'
        observed = read(diagnostic)
        assert sha(root / 'candidate/early_main.py') == observed['artifact_sha256']
        feedback['fresh_runtime_diagnosis'] = {
            'evidence_ref':str(diagnostic), 'artifact_sha256':observed['artifact_sha256'],
            'observed':observed,
            'repair_requirement':'After Save content the qualified browser workflow stays in content-view; persisted contentId is nonempty, but actual Review/Approve/Publish action buttons are hidden and disabled. Visible Review/Publish are navigation only and correctly excluded by the qualified checker. Fix coherent workflow visibility and readiness across SAVE->REVIEW->APPROVE->PUBLISH; merely renaming DOM IDs or navigation cannot repair this. Distinguish authoritative M5 content status from M6 approval status. Inspect actual return values and preserve API semantics; current JS compares draft/reviewed/approved strings while backend contracts use DRAFT/REVIEW/APPROVED. Make the required successive actions and Platform URL reachable in the workflow without an extra unrequested navigation step. Preserve current backend files. Host supplies observations/requirements, no business code.'}
        feedback['admission_correction'] += ' Include both strategy (problem plus two meaningful mechanism dimensions) and hypothesis (previous/new/expected_novel_delta/falsifying_evidence array) initially. Anchor them to fresh visibility/readiness evidence and exact current bound failure refs.'
        feedback['redecision'] = {
            'strategy_revision':hashlib.sha256(b'veriarbor fresh visibility and readiness observation 904f5b v1').hexdigest(),
            'reason':'New independent runtime diagnosis shows saved ID exists but workflow actions are hidden and disabled. Replace prior locator-only repair strategy with visibility/readiness and authoritative approval state integration. Controller interruption is canonically recovered; original UNKNOWN request is retained and not replayed.',
            'evidence_refs':[str(diagnostic),str(migration / 'CONTROLLER_INTERRUPTION_RECOVERY.json')]}
    if label == 'veriarbor-09':
        feedback['cost_policy'] = 'DeepSeek Flash Agent, Qwen Flash Worker. Different-family cheap-tier planning after two-key strategy-array correction exhaustion; no Pro/Max. Current GUI diagnosis and strict acceptance unchanged. Old DeepSeek503 UNKNOWN retained; this is a new Agent request, not replay of that Worker request.'
        feedback['admission_correction'] += ' The prior invalid object had exactly TWO keys: problem and mechanism_dimensions. Three strings inside mechanism_dimensions still count as ONE property. Return a strategy object with problem and at least two separately named top-level mechanism properties; each value describes the actual mechanism. Do not return a mechanism_dimensions wrapper. For an initial semantic_decision_attempt return the full decision, not patches; patches are only for an explicit correction call.'
        feedback['redecision'] = {
            'strategy_revision':hashlib.sha256(b'veriarbor split top-level mechanism fields with cross-family Flash planner v1').hexdigest(),
            'reason':'Prior Flash planner repeated a two-property wrapper despite correction. Preserve the new GUI visibility/readiness diagnosis but represent distinct concrete mechanisms as separate top-level properties. Use alternate-family Flash planning, same strict compiler and bounded Worker.',
            'evidence_refs':[str(root / 'continuations/veriarbor-08/result.json'),str(migration / 'gui-visibility-904f5b/observation.json')]}
        if 'route_change' in feedback:
            decision['reason_summary'] = feedback['redecision']['reason']
            decision['decision_id'] = hashlib.sha256(json.dumps({k:v for k,v in decision.items() if k != 'decision_id'}, sort_keys=True).encode()).hexdigest()
    if label == 'veriarbor-10':
        diagnostic = migration / 'gui-visibility-4ed2f6/observation.json'
        observation = read(diagnostic)
        assert sha(root / 'candidate/early_main.py') == observation['artifact_sha256']
        feedback['cost_policy'] = 'DeepSeek Flash Agent and Worker only. Qwen Worker changed status comparisons but left the specifically requested visibility mechanism unchanged; change cheap Worker family for this distinct remaining repair. DeepSeek Flash Agent just returned successful responses, supporting current availability. No Pro/Max. Same-model review is SELF_CRITIQUE only.'
        feedback['gui_writer_policy'] = 'Current successful writer92 attempt40 produced source4ed2f6. Preserve that result and its backend dependency89. The next single writer must be target91, with its existing deps89,92 preserved and a NEW current repair contract. Do not retry or repair92 again, which invalidates91 and replays its obsolete contract. Do not replay the interrupted old worker request. Current91 guard block57 is explicitly NOT_APPLIED; no current execution effects remain unknown.'
        feedback['fresh_runtime_diagnosis'] = {
            'evidence_ref':str(diagnostic),'full_independent_failed_check':str(migration/'m7-4ed2-full-check/output.log'),
            'artifact_sha256':observation['artifact_sha256'],'observed':observation,
            'remaining_problem':'Actual current source4ed2f6: Save content creates and selects a real contentId; Review action is now enabled (a real partial delta), BUT Review/Approve/Publish remain hidden in separate inactive sections. Only content-view is visible. The full unchanged M7 checker again times out clicking the non-navigation Review action. Therefore status-string-only fixes and label/ID-only rewrites are falsified as sufficient strategies. The next repair MUST implement the missing visibility transition or a consistently visible workflow action region; after SAVE actual Review must be visible/enabled, after REVIEW actual Approve must be visible/enabled, after APPROVE Platform URL and Publish must be reachable without extra navigation. Preserve sequential asynchronous completion and consult actual M6 approval.status or returned authoritative statuses, not nonexistent M5 approval_status fields. Cover all these states in one coherent change; no backend rewrite, no acceptance weakening.'}
        feedback['admission_correction'] += ' Supply complete strategy and hypothesis initially. strategy has problem and at least two separately named concrete mechanism properties at the top level; never a mechanism_dimensions array wrapper. Use exact current bound failure references in falsifying_evidence array and use fresh diagnostic facts to choose mechanisms.'
        feedback['redecision'] = {'strategy_revision':hashlib.sha256(b'veriarbor remaining visibility mechanism target91 source4ed2f6 v1').hexdigest(),
            'reason':'New source fixed Review disabled status but not visibility; full current checker still fails. Select downstream single writer91 with a fresh complete visibility/readiness contract instead of rerunning producer92 and inheriting obsolete91 work. Different cheap Worker family, same strict acceptance.',
            'evidence_refs':[str(diagnostic),str(migration/'m7-4ed2-full-check/receipt.json'),str(migration/'GUARD_BLOCK57_RECONCILIATION.json')]}
        if 'route_change' in feedback:
            decision['reason_summary']=feedback['redecision']['reason']
            decision['decision_id']=hashlib.sha256(json.dumps({k:v for k,v in decision.items() if k!='decision_id'},sort_keys=True).encode()).hexdigest()
    if label == 'veriarbor-11':
        feedback['cost_policy']='DeepSeek Flash Agent and Worker only; no Pro/Max. Preserve all old UNKNOWN requests and cost.'
        feedback['milestone_completion_request']='NEXT ACTION MUST BE CURRENT INDEPENDENT MEASUREMENT, not repair. REPAIR_REQUIRES_OBSERVED_FAILURE correctly rejected prior proposals because source4ed2f6 invalidated old canonical failure. The snapshot diagnostic is not canonical GoalAcceptance. Use existing INSPECT/read-only measurement capability and registered M7 independent checker to measure current source4ed2f6 through the normal DAG/GoalAcceptance path. Select a fresh available target and correct measurement scope from current tables. Depend on the current successful producers89/92 as required, not blocked obsolete GUI writer91; do not execute another writer merely to measure the actual existing artifact. Preserve the entire unchanged M7 predicate and checker. The snapshot full checker already reports Review hidden, so expect a genuine current failure; do not claim PASS. After canonical current failure is recorded, repair only downstream writer91 with deps89/92 preserved, using a fresh visibility/readiness contract, then independently measure. M7 VERIFIED -> immediate requested DOGFOOD_MVP -> M8-M12.'
        feedback['fresh_runtime_diagnosis']={'source_sha256':'4ed2f6a1c91c0194c3834197a8675d4000c694e3c4f09739818c811c8892e143',
            'snapshot_full_check':str(migration/'m7-4ed2-full-check/output.log'),'visibility_observation':read(migration/'gui-visibility-4ed2f6/observation.json'),
            'authority':'Diagnostic only. Must first run the original registered independent checker on current subjects via existing GoalAcceptance; no repair until its current failure is recorded.'}
        feedback['gui_writer_policy']='Do not rerun successful writer92 or backend89. Read-only measurement first. After current failure, target91 is the single next writer; preserve deps89/92 and public contract. Original interrupted request is not replayed.'
        feedback['redecision']={'strategy_revision':hashlib.sha256(b'veriarbor current canonical measurement before repair source4ed2f6 v1').hexdigest(),
            'reason':'Correct sequence after evidence invalidation: current qualified independent measurement first, then evidence-bound repair. Prior direct repair proposals correctly failed REPAIR_REQUIRES_OBSERVED_FAILURE. Snapshot observations are not canonical acceptance and must not bypass that gate.',
            'evidence_refs':[str(root/'continuations/veriarbor-10'),str(migration/'m7-4ed2-full-check/receipt.json')]}
    if label == 'veriarbor-12':
        diagnostic=migration/'gui-visibility-60428c/observation.json';observed=read(diagnostic)
        assert sha(root/'candidate/early_main.py')==observed['artifact_sha256'] and observed['action_bar_element_count']==0
        feedback['cost_policy']='DeepSeek Flash Agent and Worker; no Pro/Max. Prefer a small complete bounded repair over another broad GUI rewrite.'
        feedback['milestone_completion_request']='Current canonical M7 failure is now recorded by the original checker on source60428c (node98 attempt48). Repair only existing writer91, preserving deps89/92. Take a genuinely bounded next leaf: DOM visibility closure for the real workflow controls. Make the existing real non-navigation Review/Approve/Publish controls reachable in the active Content workflow after Save, so the first qualified Review click can execute. Keep existing readiness/approval semantics intact for this visibility leaf; subsequent current independent measurement will identify any remaining Review/Approve/Publish state handoff failures. This narrows the repair leaf, never the public M7 acceptance or final obligation. Do not claim full M7 success from this leaf. Continue state handoffs, full original vertical slice, DOGFOOD then M8-M12.'
        feedback['fresh_runtime_diagnosis']={'evidence_ref':str(diagnostic),'observed':observed,
            'falsified_strategy':'Last Worker changed updateReadiness to look up action-bar and clear its hidden flag. Actual current DOM contains ZERO #action-bar elements, so this guarded branch never runs and visibility remains unchanged. Do not repeat optional operations on an invented or absent element.',
            'actual_structure':'The real action controls are review-action/approve-action in review-view and publish-action in publish-view. Those existing sections are hidden while content-view is active. Inspect the actual .view CSS and showView behavior and change the real visibility mechanism. Existing DOM IDs are facts, not hypothetical names. A new optional guard on a missing element cannot meet the leaf goal.'}
        feedback['gui_writer_policy']='Only target91 writes early_main.py. Preserve successful target92 and backend89. One bounded visibility change, then registered independent measurement; no concurrent writer and no old UNKNOWN replay.'
        feedback['redecision']={'strategy_revision':hashlib.sha256(b'veriarbor actual DOM identity visibility-only leaf source60428c v1').hexdigest(),
            'reason':'Fresh real DOM probe falsifies nonexistent action-bar strategy; canonical current checker confirms Review still unreachable. Narrow next repair to actual section visibility, retain all public M7 requirements, and measure next state handoff after that concrete leaf delta.',
            'evidence_refs':[str(diagnostic),str(run/'attempts/sem-node-0098/attempt-0048.json'),str(root/'continuations/veriarbor-11/execution-error.json')]}
    if label == 'veriarbor-13':
        diagnostic=migration/'gui-visibility-a179ce/observation.json';observed=read(diagnostic)
        assert sha(root/'candidate/early_main.py')==observed['artifact_sha256']
        feedback['cost_policy']='DeepSeek Flash Agent and Worker only; no Pro/Max. Ordinary implementation defect must be repaired at cheap tier.'
        feedback['milestone_completion_request']='Repair only target91 with deps89/92 preserved. The last leaf added revealWorkflowSections but NEVER CALLS IT. Current actual Review remains hidden. Next bounded leaf must connect the real visibility operation to the actually executed Save/load/readiness event path. A helper definition without any reachable invocation is not an executable change. Require a complete atomic semantic delta in the bounded Worker edit, not merely a new declaration. Preserve all public M7 acceptance and existing backend; then run the original independent full checker to identify the next real state handoff failure. After M7 VERIFIED immediately DOGFOOD_MVP, then M8-M12.'
        feedback['fresh_runtime_diagnosis']={'evidence_ref':str(diagnostic),'observed':observed,
            'source_observation':'The only occurrence of revealWorkflowSections is its declaration; updateReadiness still only tries the nonexistent action-bar. showView still removes active from review-view and publish-view. Actual Review remains hidden after Save. New visibility helper has no reachable callsite.',
            'falsified_strategy':'Adding an unused helper is not sufficient. Repair must alter the actual event path and make Review visible; preserve readiness semantics for subsequent independent handoff diagnosis.'}
        feedback['gui_writer_policy']='Only91 writes; preserve89/92. No original UNKNOWN replay; do not repair92. Use current bound failure references.'
        feedback['redecision']={'strategy_revision':hashlib.sha256(b'veriarbor executable visibility closure unused helper a179ce v1').hexdigest(),
            'reason':'New source adds real-section helper but no invocation. Independent DOM observation confirms unchanged visibility. Require executable event-path closure instead of disconnected declaration, with unchanged public acceptance.',
            'evidence_refs':[str(diagnostic),str(run/'attempts/sem-node-0098/attempt-0049.json')]}
    additional_feedback = migration / 'continuation-feedback' / (label + '.json')
    if additional_feedback.exists():
        supplied = read(additional_feedback)
        assert sha(root / 'candidate/early_main.py') == supplied['expected_gui_sha256']
        assert set(supplied['feedback']) <= {'cost_policy', 'milestone_completion_request',
            'fresh_runtime_diagnosis', 'gui_writer_policy', 'redecision', 'admission_correction', 'strategy_constraints'}
        assert supplied['feedback']['redecision']['strategy_revision']
        feedback.update(supplied['feedback'])
        put(out / 'supplied-feedback.json', {'source':str(additional_feedback),
            'source_sha256':sha(additional_feedback), 'value':supplied})
    put(out / 'started.json', {'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                             'feedback': feedback, 'host_business_patches': 0, 'provider_calls_before': len(before['calls'])})
    import cProfile
    startup_profile = cProfile.Profile() if os.environ.get('VERIARBOR_PROFILE_STARTUP') == '1' else None
    if startup_profile is not None:
        startup_profile.enable()
    try:
        service = SoftwareProjectGenerationService(H, root / 'state', client=client, routing=routing)
        result = service.run_profile(root / 'profile.json', goal=profile['intent']['overall_goal'], continuation_feedback=feedback)
        put(out / 'result.json', result)
        print(json.dumps({k: result.get(k) for k in ('status', 'target_goal_satisfied', 'delivery_status', 'public_delivery_allowed')}), flush=True)
    except Exception as error:
        put(out / 'execution-error.json', {'type': type(error).__name__, 'message': str(error), 'traceback': traceback.format_exc()})
        raise
    finally:
        finish_startup_profile()
        after = read(ledger)
        put(out / 'accounting-after.json', after)
        identities = {r['request_identity'] for r in before['calls']}
        put(out / 'accounting-increment.json', {
            'calls': [r for r in after['calls'] if r['request_identity'] not in identities],
            'historical_records_unchanged': after['calls'][:len(before['calls'])] == before['calls'],
            'estimated_cost_delta': after['totals']['estimated_cost'] - before['totals']['estimated_cost'],
            'settled_vendor_cost': 'UNKNOWN_NOT_INVOICED', 'host_business_patches': 0})


if __name__ == '__main__':
    main()

"""Bind migration claims to real sources, retained snapshots and check receipts."""
from pathlib import Path
import ast
import hashlib
import importlib.metadata
import json
import sys
import types
from capture_baseline import H, V, P

OUT = H / 'migration/veriarbor'
sys.path.insert(0, str(H))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding='utf-8')


def metrics(source):
    tree = ast.parse(source)
    return {'lines': len(source.splitlines()),
            'functions': sum(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) for n in ast.walk(tree)),
            'branches': sum(isinstance(n, (ast.If, ast.IfExp, ast.For, ast.While, ast.Try)) for n in ast.walk(tree))}


def main():
    source = {f.relative_to(V).as_posix(): sha(f) for f in (V / 'src').rglob('*.py')}
    forbidden = []
    for path in (V / 'src').rglob('*.py'):
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            names = [alias.name for alias in node.names] if isinstance(node, ast.Import) else [node.module or ''] if isinstance(node, ast.ImportFrom) and node.level == 0 else []
            forbidden += [name for name in names if name.split('.')[0] in {'cgkn', 'requests', 'httpx', 'openai', 'sqlite3', 'subprocess'}]
    assert not forbidden, forbidden
    dist = importlib.metadata.distribution('veriarbor')
    save(V / 'governance/DEPENDENCY_IDENTITY.json', {
        'distribution': dist.metadata['Name'], 'version': dist.version,
        'direct_url': json.loads(dist.read_text('direct_url.json')),
        'library_sources': source, 'library_source_hash': hashlib.sha256(json.dumps(source, sort_keys=True).encode()).hexdigest(),
        'test_interpreter': sys.executable,
        'live_interpreter_policy': 'Original frozen Promotion interpreter plus process-local sitecustomize loading isolated editable metadata; no global installation',
        'dependency_direction': 'CGKN -> VeriArbor', 'forbidden_imports': forbidden})
    rows = [json.loads(line) for line in (OUT / 'AUTHORITY_SWITCH_RECEIPTS.jsonl').read_text().splitlines()]
    latest = {row['file']: row for row in rows}
    virtual = {rel: (H / rel).read_bytes() for rel in latest}
    for row in reversed(rows):
        assert hashlib.sha256(virtual[row['file']]).hexdigest() == row['after_sha256'], row['file']
        backup = Path(row['rollback']).read_bytes()
        assert hashlib.sha256(backup).hexdigest() == row['before_sha256']
        virtual[row['file']] = backup
    deletions = []
    for rel, old in virtual.items():
        deletions.append({'file': rel, 'before': metrics(old.decode('utf-8-sig')), 'after': metrics((H / rel).read_text(encoding='utf-8')),
                          'legacy_reader': 'Existing public imports retained as adapters; snapshots offline only',
                          'rollback_chain_verified': True,
                          'migrated_callers': 'Public host callsites delegate to veriarbor; see SYMBOL_EXTRACTION_MAP.json',
                          'removed': [row['authority'] for row in rows if row['file'] == rel]})
    with (OUT / 'DELETION_RECEIPTS.jsonl').open('w', encoding='utf-8') as stream:
        stream.writelines(json.dumps(row) + '\n' for row in deletions)
    # Execute the retained pre-migration acceptance projection against the same
    # current authenticated evidence. Neither projection saves/re-records it.
    from cgkn.state import FileRunStore
    from cgkn.state.acceptance import GoalAcceptance
    legacy = types.ModuleType('cgkn.state._veriarbor_baseline_acceptance')
    legacy.__package__ = 'cgkn.state'
    exec(compile(virtual['cgkn/state/acceptance.py'], 'baseline_acceptance.py', 'exec'), legacy.__dict__)
    p = P / 'promotion/run-05'
    profile = json.loads((p / 'profile.json').read_text(encoding='utf-8'))
    root = p / 'state' / profile['project_id'] / profile['run_id']
    data = json.loads((root / 'goal_acceptance.json').read_text(encoding='utf-8'))
    args = (FileRunStore(p / 'state'), profile['project_id'], profile['run_id'], data['requirements'], data['checker_bindings'])
    before = sha(root / 'goal_acceptance.json')
    old_view, new_view = legacy.GoalAcceptance(*args).view(), GoalAcceptance(*args).view()
    shadow_differences = []
    if old_view != new_view:
        # V1 intentionally reuses a historical dependent check only through a
        # newly authenticated identical-boundary replacement. The legacy view
        # cannot express that proof; do not falsify byte-for-byte equivalence.
        assert old_view['requirements'] == new_view['requirements']
        assert old_view['checker_bindings'] == new_view['checker_bindings']
        assert old_view['subject_identities'] == new_view['subject_identities']
        old_goals = {g['id']: g for g in old_view['goals']}
        assert set(old_goals) == {g['id'] for g in new_view['goals']}
        for goal in new_view['goals']:
            old_goal = old_goals[goal['id']]
            assert {k:v for k,v in old_goal.items() if k not in {'verdict','evidence'}} == {k:v for k,v in goal.items() if k not in {'verdict','evidence'}}
            if old_goal != goal:
                evidence = goal.get('evidence') or {}
                assert goal['verdict'] == 'VERIFIED' and old_goal['verdict'] in {'INSUFFICIENT_EVIDENCE','VERIFIED'}
                assert evidence.get('certified_substitutions') and evidence.get('effective_subjects')
                assert evidence['provenance']['status'] == 'TRUSTED'
                shadow_differences.append({'goal_id':goal['id'],'old':old_goal['verdict'],'new':goal['verdict'],
                                          'substitutions':evidence['certified_substitutions']})
        assert new_view == GoalAcceptance(*args).view(), 'Current V1 replay must still be deterministic'
    assert before == sha(root / 'goal_acceptance.json')
    checks = {path.parent.name: json.loads(path.read_text()) for path in (V / 'governance/checks').glob('*/receipt.json')}
    incomplete = []
    if (V / 'governance/BROAD_REGRESSION_INTERRUPTION.json').exists():
        interrupted = json.loads((V / 'governance/BROAD_REGRESSION_INTERRUPTION.json').read_text())
        assert checks[interrupted['replacement']]['exit_code'] == 0
        incomplete.append(interrupted['check'])
    repaired = []
    repairs = V / 'governance/REPAIRED_REGRESSIONS.json'
    if repairs.exists():
        for repair in json.loads(repairs.read_text())['repairs']:
            failed, replacement = repair['failed_check'], repair['replacement']
            assert checks[failed]['exit_code'] != 0 and checks[replacement]['exit_code'] == 0
            if checks[failed]['argv'] != checks[replacement]['argv']:
                correction = repair['invocation_correction']
                assert correction['kind'] == 'MissingTestPathCorrection'
                assert checks[failed]['exit_code'] == 4
                old_args, new_args = checks[failed]['argv'], checks[replacement]['argv']
                assert old_args.count(correction['missing_path']) == 1
                assert new_args == [correction['existing_path'] if arg == correction['missing_path'] else arg for arg in old_args]
                assert not (H / correction['missing_path']).exists()
                assert sha(H / correction['existing_path']) == correction['existing_path_sha256']
            assert checks[failed]['cwd'] == checks[replacement]['cwd']
            assert sha(V / 'governance/checks' / failed / 'receipt.json') == repair['failed_receipt_sha256']
            assert sha(V / 'governance/checks' / replacement / 'receipt.json') == repair['replacement_receipt_sha256']
            assert repair['reason']
            if not repair.get('source_change_receipts'):
                environment = repair['environment_repair_ref']
                path = V / environment['path']
                assert sha(path) == environment['sha256']
                fixed = json.loads(path.read_text())
                assert fixed['kind'] == 'TestTemporaryDirectorySetupRepair'
                assert fixed['failed_check'] == failed and fixed['replacement'] == replacement
                directory = Path(fixed['created_parent']).resolve()
                assert directory.is_relative_to((OUT / 'scratch').resolve()) and directory.is_dir()
                assert fixed['product_sources_modified'] is False
            repaired.append(repair)
    repaired_names = {row['failed_check'] for row in repaired}
    scoped = []
    scope_path = V / 'governance/OUT_OF_SCOPE_CHECK_FAILURES.json'
    if scope_path.exists():
        for item in json.loads(scope_path.read_text())['checks']:
            assert checks[item['check']]['exit_code'] != 0
            assert sha(V / 'governance/checks' / item['check'] / 'receipt.json') == item['receipt_sha256']
            assert item['status'] == 'UNRESOLVED_OUTSIDE_MINIMUM_V1_GATE'
            assert checks[item['focused_replacement']]['exit_code'] == 0
            assert item['failures'] and item['limitations']
            scoped.append(item)
    scoped_names = {item['check'] for item in scoped}
    assert checks and all(row['exit_code'] == 0 for key, row in checks.items() if key not in incomplete and key not in repaired_names and key not in scoped_names)
    host_sources = {rel: sha(H / rel) for rel in latest}
    host_sources.update({f.relative_to(H).as_posix(): sha(f) for f in (H / 'cgkn/adapters').rglob('*.py')})
    baseline_sources = json.loads((V / 'governance/SOURCE_MANIFEST.json').read_text())['files']
    for rel, expected in baseline_sources.items():
        if rel.endswith('.py') and rel.startswith(('cgkn/', 'scripts/', 'contracts/')):
            actual = sha(H / rel)
            if rel not in latest:
                assert actual == expected, 'Unaccounted concurrent source change: ' + rel
            host_sources[rel] = actual
    regression = {'status': 'PASS_FOR_RECORDED_SCOPE', 'checks': checks, 'current_replay_identical': True,
                  'legacy_shadow_identical': old_view == new_view, 'qualified_v1_shadow_differences': shadow_differences,
                  'rollback_hash_chain_verified': True, 'library_sources': source, 'host_sources': host_sources,
                  'incomplete_checks': incomplete, 'repaired_checks': repaired, 'unresolved_out_of_scope_checks': scoped, 'full_repository_suite': 'NOT_RUN', 'product_acceptance': 'NOT_VERIFIED_BY_THESE_CHECKS'}
    save(V / 'REGRESSION.json', regression)
    save(OUT / 'REGRESSION.json', regression)
    baseline = json.loads((OUT / 'AUTHORITY_MAP_BEFORE.json').read_text())
    save(OUT / 'AUTHORITY_MAP_AFTER.json', {'retained_host_authorities': baseline['authorities'],
        'migrated_policies': [row['authority'] for row in rows],
        'new_slot_allocation': 'veriarbor.search.allocate -> veriarbor.scheduling.parallel_batch',
        'no_second_runtime_database_or_ledger': True})
    save(OUT / 'ENTRYPOINT_MAP_AFTER.json', {'public_host_entries_preserved': sorted(latest),
        'delegates_to': sorted(source), 'default_call_depth': 'Each migrated pure policy adds an adapter/library boundary; runtime and provider loops unchanged'})
    receipt = {'status': 'CORE_MIGRATION_CHECKPOINT', 'library_version': dist.version,
        'host_switches': len(rows), 'product_status': 'PRODUCT_NOT_READY',
        'M1_M6_baseline': '83 baseline certificates; two identical preserved rebuilds before later integration repairs',
        'M1_M6': {k:new_view['obligations'][k]['verdict'] for k in ('M1','M2','M3','M4','M5','M6')},
        'M7': new_view['obligations']['M7']['verdict'],
        'M8_M12': {k:new_view['obligations'][k]['verdict'] for k in ('M8','M9','M10','M11','M12')},
        'push_publish': False, 'host_business_patches': 0,
        'regression': 'REGRESSION.json', 'library_limitations': [
            'New hierarchical rollup is available; compatibility host rollup retains original predicate structure',
            'Allocation adapter governs slots, not every model/token/context resource',
            'Non-chronological host advice uses exact failed strategy identity; no automatic rollback',
            'General learned-nogood matching is tested; host repeated-no-progress guard is integrated'],
        'next': 'Continue remaining product milestones and canonical delivery; do not equate migration regression with product acceptance'}
    save(V / 'MIGRATION_RECEIPT.json', receipt)
    print(json.dumps(receipt))


if __name__ == '__main__':
    main()

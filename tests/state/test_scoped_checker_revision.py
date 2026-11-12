import json
from dataclasses import replace
import pytest
from tests.state.test_checker_revision import fixture,measure
from cgkn.state.provenance import put_evidence, ProvenanceGate, ProvenanceError
from cgkn.state.checker_revision import bind_checker_revision
from cgkn.application.software_project.acceptance import ExternalAcceptanceExecutor


@pytest.mark.parametrize('scope,version', [(['R'], 'qualified-revision-1'), (['S'], '1')])
def test_scoped_revision_preserves_unrelated_checker_identity(tmp_path, scope, version, monkeypatch):
    from tests.application.software_project import test_milestone_consumer as fixtures
    acceptance_type = fixtures.GoalAcceptance
    def initial_registry(store, project, run, requirements, checkers):
        return acceptance_type(store, project, run, {**requirements, 'S': {'must': True}}, checkers)
    monkeypatch.setattr(fixtures, 'GoalAcceptance', initial_registry)
    old, request, a, workspace, original, decision, proof = fixture(tmp_path)
    proof['requirement_scope'] = scope
    decision['qualification_ref'] = put_evidence(a.store, 'p', 'r', proof)
    revision = bind_checker_revision(a.store, 'p', 'r', 'independent', original, decision)
    executor = ExternalAcceptanceExecutor(workspace, tmp_path, session_acceptance=a,
                                         consumer=original, qualified_revision=revision)
    result = measure(executor,replace(request, attempt_id='scoped'))
    assert result.succeeded
    assert result.outputs['goal_check']['checker_version'] == version
    assert result.metadata['independent_checker_hash'] == (
        revision['checker_hash'] if scope == ['R'] else original['sha256'])
    a.store.save_result(result)
    a.record('g', result, executor_ref='project.acceptance@1')
    goal = a.view()['goals'][0]
    assert ProvenanceGate(a.store, 'p', 'r').verify_check(
        result, goal, a.view()['subject_identities'])['status'] == 'TRUSTED'


@pytest.mark.parametrize('scope', [[], 'R', [None], ['R', 'R']])
def test_malformed_scope_cannot_activate(tmp_path, scope):
    old, request, a, workspace, original, decision, proof = fixture(tmp_path)
    proof['requirement_scope'] = scope
    decision['qualification_ref'] = put_evidence(a.store, 'p', 'r', proof)
    with pytest.raises(ProvenanceError):
        bind_checker_revision(a.store, 'p', 'r', 'independent', original, decision)
    assert not list((a.store.run_dir('p', 'r') / 'checker_revisions').glob('*.json'))


def test_scope_tamper_cannot_select_old_checker(tmp_path):
    old, request, a, workspace, original, decision, proof = fixture(tmp_path)
    proof['requirement_scope'] = ['R']
    decision['qualification_ref'] = put_evidence(a.store, 'p', 'r', proof)
    revision = bind_checker_revision(a.store, 'p', 'r', 'independent', original, decision)
    path = a.store.root / decision['qualification_ref']['path']
    proof['requirement_scope'] = ['S']
    path.write_text(json.dumps(proof))
    with pytest.raises(ProvenanceError):
        ExternalAcceptanceExecutor(workspace, tmp_path, session_acceptance=a,
                                   consumer=original, qualified_revision=revision)

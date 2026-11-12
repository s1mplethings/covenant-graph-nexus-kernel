"""A failed core test must not silently mutate its frozen tool environment."""
import pytest
from scripts import codex_conversation as bridge


class ReachedCandidateSeal(Exception):
    pass


@pytest.mark.parametrize('core', [True, False])
def test_post_build_failure_preserves_core_environment(monkeypatch, tmp_path, core):
    installs = []
    events = []
    monkeypatch.setattr(bridge.production_candidate_provenance, 'inspect',
        lambda *a, **k: {'status': 'PASS', 'document': {'generation_route': 'project_session'}})
    monkeypatch.setattr(bridge, 'append_agent_session_event', lambda *a: events.append(a[-1]))
    monkeypatch.setattr(bridge, 'collect_provider_image_evidence', lambda *a: {})
    monkeypatch.setattr(bridge, 'infer_public_delivery_requirements', lambda *a: {})
    monkeypatch.setattr(bridge, 'required_image_backend_missing_config', lambda *a: [])
    monkeypatch.setattr(bridge, 'run_provider_project_tests',
        lambda *a, **k: {'ok': False, 'failure_type': 'test_failure', 'failed': 1})
    def installer(*a, **k):
        installs.append(True)
        return {'ok': False, 'error': 'fixture_no_install'}
    monkeypatch.setattr(bridge, 'ensure_provider_test_environment', installer)
    def stop_at_seal(*a, **k):
        raise ReachedCandidateSeal
    monkeypatch.setattr(bridge.canonical_evidence_hash, 'candidate_source_manifest', stop_at_seal)
    with pytest.raises(ReachedCandidateSeal):
        bridge.post_build_finalize_provider_project(
            tmp_path, {}, {}, {}, session_dir=tmp_path, conversation_id='fixture',
            production_identity={'run_id': 'r', 'candidate_id': 'c', 'commit_sha': 'frozen'},
            production_run_dir=tmp_path, stage_receipts={},
            provider_result_path=tmp_path/'provider.json', provider_causal_capture={},
            core_provenance_ref=tmp_path/'core.json' if core else None)
    assert installs == ([] if core else [True])
    repair = next(e for e in events if e['kind'] == 'post_build_provider_repair_required')
    assert repair['repair']['changed'] is False
    assert repair['repair']['failure_type'] == 'test_failure'
    if core:
        assert repair['dependency_setup']['status'] == 'NOT_ATTEMPTED'

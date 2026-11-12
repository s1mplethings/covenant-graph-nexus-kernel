from pathlib import Path
from types import SimpleNamespace
import pytest
from experiments.semantic_artifact_design.common import runner


def test_missing_client_uses_governed_factory_and_preserves_injected_client(tmp_path,monkeypatch):
    root=Path(__file__).resolve().parents[3]
    calls=[]
    client=SimpleNamespace()
    monkeypatch.setattr(runner,'completion_client_from_environment',lambda:calls.append(True) or client)
    assert runner.SemanticExperimentRunner(root,tmp_path).client is client
    assert runner.SemanticExperimentRunner(root,tmp_path,client=client).client is client
    assert calls==[True]
    def deny():raise ValueError('GOVERNED_GATEWAY_REQUIRED')
    monkeypatch.setattr(runner,'completion_client_from_environment',deny)
    with pytest.raises(ValueError,match='GOVERNED_GATEWAY_REQUIRED'):
        runner.SemanticExperimentRunner(root,tmp_path)

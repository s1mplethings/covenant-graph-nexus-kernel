from __future__ import annotations

import json

import pytest

from cgkn.application.provider_evaluation import ProviderEvaluationService, ProviderPrice, benchmark_cases, suite_hash
from cgkn.application.provider_evaluation.suite import evaluate
from cgkn.providers import ProviderCompletion


RESPONSES = {
    "structured-identifiers": {"result": ["alpha-project", "beta-item", "alpha-project"]},
    "structured-dependencies": {"result": ["certifi", "requests", "urllib3"]},
    "composition-feature": {"nodes": [
        {"id": "inspect", "capability": "workspace.inspect", "depends_on": []},
        {"id": "implement", "capability": "project.file.patch", "depends_on": ["inspect"]},
        {"id": "test", "capability": "local.python-test", "depends_on": ["implement"]},
    ]},
    "composition-repair": {"nodes": [
        {"id": "inspect", "capability": "workspace.inspect", "depends_on": []},
        {"id": "repair", "capability": "project.file.patch", "depends_on": ["inspect"]},
        {"id": "verify", "capability": "local.python-test", "depends_on": ["repair"]},
    ]},
    "codegen-normalize": {"path": "solution.py", "content": "def normalize_identifier(text):\n    out = []\n    pending = False\n    for char in text.strip().lower():\n        if char.isalnum():\n            if pending and out:\n                out.append('-')\n            out.append(char)\n            pending = False\n        else:\n            pending = True\n    return ''.join(out)\n"},
    "codegen-clamp": {"path": "solution.py", "content": "def clamp_int(value, lower, upper):\n    if lower > upper:\n        raise ValueError('invalid bounds')\n    return min(max(value, lower), upper)\n"},
    "repair-average": {"path": "solution.py", "content": "def average(values):\n    if not values:\n        raise ValueError('empty values')\n    return sum(values) / len(values)\n"},
    "repair-unique": {"path": "solution.py", "content": "def unique_ordered(values):\n    result = []\n    for value in values:\n        if value not in result:\n            result.append(value)\n    return result\n"},
}


class FakeClient:
    def __init__(self, responses=None):
        self.responses = dict(RESPONSES if responses is None else responses)
        self.calls = []

    def complete(self, *, system, user, schema_name, schema, config):
        request = json.loads(user)
        self.calls.append({"system": system, "user": user, "schema": schema, "config": config})
        value = self.responses[request["case_id"]]
        return ProviderCompletion(
            json.dumps(value),
            f"{config.model}-actual-v1",
            f"req-{config.model}-{request['case_id']}",
            {"prompt_tokens": 100, "completion_tokens": 50},
        )


@pytest.mark.happy_path
@pytest.mark.boundary
def test_fixed_suite_has_two_cases_per_core_task_class_and_stable_hash() -> None:
    cases = benchmark_cases()
    counts = {}
    for case in cases:
        counts[case.task_class] = counts.get(case.task_class, 0) + 1
    assert counts == {
        "structured.output": 2,
        "agent.composition": 2,
        "worker.codegen": 2,
        "worker.repair": 2,
    }
    assert suite_hash(cases) == suite_hash(cases)


@pytest.mark.happy_path
@pytest.mark.local_functional
def test_all_fixed_cases_cross_real_local_evaluators() -> None:
    for case in benchmark_cases():
        result = evaluate(case.case_id, RESPONSES[case.case_id])
        assert result.functional_valid is True, case.case_id
        assert result.interface_valid is True, case.case_id
        assert result.scope_valid is True, case.case_id


@pytest.mark.happy_path
@pytest.mark.provider
def test_service_emits_complete_credential_free_receipts_and_real_cost_when_supplied() -> None:
    client = FakeClient()
    service = ProviderEvaluationService(
        client,
        gateway_config_hash="sha256:" + "g" * 64,
        source_commit="a" * 40,
        prices={"qwen": ProviderPrice(1.0, 2.0)},
    )
    receipts = service.run_provider("qwen", run_id="benchmark-run")
    assert len(receipts) == 8 and all(row.success for row in receipts)
    assert all(row.cost_estimate == 0.0002 for row in receipts)
    rendered = json.dumps([row.as_dict() for row in receipts])
    assert "credential" not in rendered.lower()
    assert "secret_safe\": false" not in rendered.lower()
    assert "token_usage_unavailable" not in rendered.lower()


@pytest.mark.happy_path
@pytest.mark.determinism
def test_provider_fairness_uses_identical_prompt_contract_and_limits() -> None:
    case = benchmark_cases()[0]
    clients = [FakeClient(), FakeClient()]
    for provider, client in zip(("qwen", "deepseek"), clients):
        ProviderEvaluationService(
            client,
            gateway_config_hash="sha256:" + "g" * 64,
            source_commit="a" * 40,
        ).run_case(provider, case, run_id="same-run")
    left, right = clients[0].calls[0], clients[1].calls[0]
    assert left["system"] == right["system"]
    assert left["user"] == right["user"]
    assert left["schema"] == right["schema"]
    assert left["config"].timeout_seconds == right["config"].timeout_seconds
    assert left["config"].max_output_tokens == right["config"].max_output_tokens
    assert left["config"].temperature == right["config"].temperature == 0.0


@pytest.mark.negative
@pytest.mark.security
def test_schema_failure_and_unsafe_code_fail_closed() -> None:
    cases = {case.case_id: case for case in benchmark_cases()}
    malformed = FakeClient({"structured-identifiers": {"unknown": []}})
    receipt = ProviderEvaluationService(
        malformed,
        gateway_config_hash="sha256:" + "g" * 64,
        source_commit="a" * 40,
    ).run_case("qwen", cases["structured-identifiers"], run_id="run")
    assert receipt.success is False and receipt.schema_valid is False and receipt.error_class == "SCHEMA_FAILURE"
    unsafe = evaluate("codegen-normalize", {"path": "solution.py", "content": "import os\ndef normalize_identifier(text):\n return text\n"})
    assert unsafe.functional_valid is False and unsafe.scope_valid is False


@pytest.mark.happy_path
@pytest.mark.local_functional
def test_repair_evaluator_accepts_safe_builtin_set_implementation() -> None:
    result = evaluate(
        "repair-unique",
        {
            "path": "solution.py",
            "content": (
                "def unique_ordered(values):\n"
                "    seen = set()\n"
                "    result = []\n"
                "    for value in values:\n"
                "        if value not in seen:\n"
                "            seen.add(value)\n"
                "            result.append(value)\n"
                "    return result\n"
            ),
        },
    )
    assert result.functional_valid is True
    assert result.interface_valid is True
    assert result.scope_valid is True


@pytest.mark.roundtrip
@pytest.mark.security
def test_receipt_is_write_once(tmp_path) -> None:
    case = benchmark_cases()[0]
    receipt = ProviderEvaluationService(
        FakeClient(), gateway_config_hash="sha256:" + "g" * 64, source_commit="a" * 40
    ).run_case("qwen", case, run_id="run")
    path = ProviderEvaluationService.write_receipt_once(receipt, tmp_path / "receipt.json")
    assert json.loads(path.read_text(encoding="utf-8"))["contains_credentials"] is False
    with pytest.raises(FileExistsError):
        ProviderEvaluationService.write_receipt_once(receipt, path)

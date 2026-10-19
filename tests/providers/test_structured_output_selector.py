from __future__ import annotations

import json

import pytest

from cgkn.application.project_loop import BLUEPRINT_EDIT_SCHEMA
from cgkn.providers.structured_output import StructuredAnswerSelector, StructuredSelectionError


VALID = {"edits": [{"operation": "finish_design", "payload": {}}]}
OTHER_VALID = {"edits": [{"operation": "set_goal", "payload": {"goal": "csv"}}]}


def select(text: str):
    return StructuredAnswerSelector().select(
        text, BLUEPRINT_EDIT_SCHEMA, schema_name="cgkn_blueprint_edits",
        provider_id="deepseek", model="deepseek", task_class="project.compose",
        operation="COMPOSITION", prompt_hash="sha256:prompt", transport_attempts=1,
        usage_status="REPORTED",
    )


@pytest.mark.parametrize(
    ("name", "text", "expected_candidates", "envelope"),
    [
        ("single", json.dumps(VALID), 1, None),
        ("fenced", "```json\n" + json.dumps(VALID) + "\n```", 1, None),
        ("schema_echo", "Schema: " + json.dumps(BLUEPRINT_EDIT_SCHEMA) + "\nAnswer: " + json.dumps(VALID), 2, None),
        ("reasoning", '{"reasoning":"plan first"}\n' + json.dumps(VALID), 2, None),
        ("envelope", json.dumps({"answer": VALID}), 1, "answer"),
        ("natural_language", "Here is the only answer:\n" + json.dumps(VALID) + "\nDone.", 1, None),
        ("unicode", json.dumps({"edits": [{"operation": "set_goal", "payload": {"goal": "清理数据"}}]}, ensure_ascii=False), 1, None),
        ("nested_brace_string", json.dumps({"edits": [{"operation": "set_goal", "payload": {"goal": "literal } { braces"}}]}), 1, None),
    ],
    ids=("single", "fenced", "schema-echo", "reasoning", "envelope", "natural-language", "unicode", "nested-braces"),
)
def test_unique_schema_valid_candidate_is_selected(name: str, text: str, expected_candidates: int, envelope: str | None) -> None:
    value, receipt = select(text)
    assert value["edits"] and receipt.final_status == "ACCEPTED"
    assert receipt.json_candidate_count == expected_candidates
    assert receipt.schema_valid_candidate_count == 1
    assert receipt.envelope_detected == envelope
    assert receipt.schema_hash.startswith("sha256:") and receipt.raw_response_hash.startswith("sha256:")
    assert receipt.as_dict()["contains_credentials"] is False


@pytest.mark.parametrize(
    ("name", "text"),
    [
        ("unknown_nested_envelope", json.dumps({"wrapper": {"answer": VALID}})),
        ("zero_valid", '{"reasoning":"only"}'),
        ("truncated", '{"edits":[{"operation":"finish_design"'),
        ("array", json.dumps([VALID])),
        ("json_inside_string", json.dumps(json.dumps(VALID))),
        ("extra_field", json.dumps({**VALID, "extra": True})),
        ("missing_required", json.dumps({"not_edits": []})),
        ("invalid_operation", json.dumps({"edits": [{"operation": "write_source", "payload": {}}]})),
        ("provider_schema_echo", json.dumps(BLUEPRINT_EDIT_SCHEMA)),
        ("huge_invalid", json.dumps({"reasoning": "x" * 200_000})),
    ],
    ids=("unknown-envelope", "zero-valid", "truncated", "array", "json-string", "extra", "missing", "invalid-operation", "schema-only", "huge-invalid"),
)
def test_zero_valid_candidates_fail_closed(name: str, text: str) -> None:
    with pytest.raises(StructuredSelectionError) as caught:
        select(text)
    assert caught.value.status == "PROVIDER_SCHEMA_FAILURE"
    assert caught.value.receipt.schema_valid_candidate_count == 0
    assert caught.value.receipt.selected_candidate_hash is None


def test_two_valid_candidates_are_ambiguous() -> None:
    with pytest.raises(StructuredSelectionError) as caught:
        select(json.dumps(VALID) + "\n" + json.dumps(OTHER_VALID))
    assert caught.value.status == "PROVIDER_AMBIGUOUS_STRUCTURED_OUTPUT"
    assert caught.value.receipt.schema_valid_candidate_count == 2
    assert caught.value.receipt.selected_candidate_index is None


def test_schema_echo_is_never_selected() -> None:
    value, receipt = select(json.dumps(BLUEPRINT_EDIT_SCHEMA) + "\n" + json.dumps(VALID))
    assert value == VALID and receipt.selected_candidate_index == 1
    assert receipt.candidate_rejections[0].startswith("0:")


def test_receipt_does_not_persist_secret_text() -> None:
    secret = "sk-live-secret-value-123456789"
    with pytest.raises(StructuredSelectionError) as caught:
        select(json.dumps({"reasoning": secret}))
    serialized = json.dumps(caught.value.receipt.as_dict(), sort_keys=True)
    assert secret not in serialized and "authorization" not in serialized.lower()


def test_selector_uses_the_production_blueprint_edit_schema() -> None:
    value, _ = select(json.dumps(VALID))
    assert value == VALID
    with pytest.raises(StructuredSelectionError):
        select(json.dumps({"edits": [{"operation": "finish_design", "payload": {}, "unknown": 1}]}))

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping


DOMAINS: tuple[tuple[str, str, str, str], ...] = (
    ("structured_data_transformation", "three clean rows", "rename customer_id to account_id", "emit only the projected rows"),
    ("logs", "ERROR request r7", "HTTP 503 occurred twice", "filter only trace r7"),
    ("configuration", "port 9000", "environment overrides the file", "reject keys outside the allowlist"),
    ("document_processing", "heading Release Notes", "two citation markers", "preserve heading order"),
    ("local_file_operations", "reports/output.json", "sha256 manifest entry", "write only inside reports"),
    ("small_data_analysis", "median 4", "two missing values", "report the missing-value denominator"),
    ("media_metadata", "1920 by 1080", "H.264 with AAC", "inspect metadata without decoding frames"),
    ("api_like_workflows", "retry HTTP 429", "idempotency key required", "redact the authorization header"),
    ("code_repair", "return a plus b", "preserve add(a, b)", "change only arithmetic.py"),
    ("research_evidence_synthesis", "claim supported by E7", "E8 contradicts the older note", "cite only supplied evidence IDs"),
    ("stateful_multi_turn", "revision 4", "the prior choice remains blue", "apply the update once"),
    ("unknown_format_parsing", "pipe-delimited records", "the first row is a header", "refuse opaque binary bytes"),
)


@dataclass(frozen=True)
class HoldoutCase:
    case_id: str
    domain: str
    difficulty: str
    question: str
    evidence: tuple[tuple[str, str], ...]
    expected_terms: tuple[str, ...]
    forbidden_terms: tuple[str, ...] = ()
    expect_abstention: bool = False

    def public_packet(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "domain": self.domain,
            "difficulty": self.difficulty,
            "question": self.question,
            "evidence": [{"evidence_id": key, "text": text} for key, text in self.evidence],
        }

    def evaluator_record(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "expected_terms": list(self.expected_terms),
            "forbidden_terms": list(self.forbidden_terms),
            "expect_abstention": self.expect_abstention,
        }


def _slug_terms(value: str) -> tuple[str, ...]:
    return tuple(word.casefold() for word in value.replace("(", " ").replace(")", " ").replace(",", " ").split() if len(word) > 1)


def frozen_cross_domain_holdout() -> tuple[HoldoutCase, ...]:
    rows: list[HoldoutCase] = []
    for domain_index, (domain, primary, secondary, safe_rule) in enumerate(DOMAINS, start=1):
        prefix = f"XD-{domain_index:02d}"
        rows.extend((
            HoldoutCase(
                f"{prefix}-01", domain, "easy",
                f"For this {domain.replace('_', ' ')} task, return the authoritative observation from evidence.",
                ((f"{prefix}.OBS", f"Authoritative observation: {primary}."),), _slug_terms(primary),
            ),
            HoldoutCase(
                f"{prefix}-02", domain, "medium",
                f"Combine both authoritative facts for this {domain.replace('_', ' ')} task.",
                ((f"{prefix}.A", f"First fact: {primary}."), (f"{prefix}.B", f"Second fact: {secondary}.")),
                _slug_terms(primary) + _slug_terms(secondary),
            ),
            HoldoutCase(
                f"{prefix}-03", domain, "medium",
                f"Use the current record, not the superseded record, for this {domain.replace('_', ' ')} task.",
                ((f"{prefix}.OLD", "SUPERSEDED record: obsolete-value."), (f"{prefix}.CURRENT", f"CURRENT record: {primary}.")),
                _slug_terms(primary), ("obsolete-value",),
            ),
            HoldoutCase(
                f"{prefix}-04", domain, "hard",
                "Two equally authoritative records conflict. Abstain and state insufficient evidence.",
                ((f"{prefix}.C1", f"Authoritative record one: {primary}."), (f"{prefix}.C2", "Authoritative record two: incompatible-value.")),
                ("insufficient",), expect_abstention=True,
            ),
            HoldoutCase(
                f"{prefix}-05", domain, "hard",
                f"The requested {domain.replace('_', ' ')} fact is absent. Abstain and state insufficient evidence.",
                (), ("insufficient",), expect_abstention=True,
            ),
            HoldoutCase(
                f"{prefix}-06", domain, "medium",
                f"State the safe bounded action for this {domain.replace('_', ' ')} task.",
                ((f"{prefix}.SAFE", f"Safe bounded action: {safe_rule}."),), _slug_terms(safe_rule),
                ("unrestricted", "any path", "invent"),
            ),
        ))
    if len(rows) != 72 or len({row.case_id for row in rows}) != 72:
        raise AssertionError("cross-domain holdout must freeze exactly 72 unique tasks")
    return tuple(rows)


def canonical_hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def holdout_manifest() -> dict[str, Any]:
    cases = frozen_cross_domain_holdout()
    public = [case.public_packet() for case in cases]
    evaluator = [case.evaluator_record() for case in cases]
    return {
        "schema_version": "1.0",
        "kind": "CGKNFrozenCrossDomainHoldout",
        "task_count": len(cases),
        "domain_count": len(DOMAINS),
        "tasks_per_domain": 6,
        "public_task_hash": canonical_hash(public),
        "evaluator_hash": canonical_hash(evaluator),
        "difficulty_distribution": {level: sum(case.difficulty == level for case in cases) for level in ("easy", "medium", "hard")},
        "domains": [domain for domain, *_ in DOMAINS],
        "execution_visibility": "PUBLIC_PACKET_ONLY",
    }


def evaluate_holdout_answer(case: HoldoutCase, answer: Mapping[str, Any]) -> dict[str, Any]:
    text = str(answer.get("answer") or "").casefold()
    abstained = bool(answer.get("abstained"))
    cited = tuple(str(value) for value in answer.get("evidence_ids") or ())
    available = {key for key, _ in case.evidence}
    terms_ok = all(term in text for term in case.expected_terms)
    forbidden_ok = not any(term in text for term in case.forbidden_terms)
    citation_scope_ok = set(cited) <= available and len(cited) == len(set(cited))
    citation_required_ok = bool(cited) if case.evidence and not case.expect_abstention else True
    abstention_ok = abstained == case.expect_abstention
    success = terms_ok and forbidden_ok and citation_scope_ok and citation_required_ok and abstention_ok
    return {
        "success": success,
        "terms_ok": terms_ok,
        "forbidden_ok": forbidden_ok,
        "citation_scope_ok": citation_scope_ok,
        "citation_required_ok": citation_required_ok,
        "abstention_ok": abstention_ok,
    }


from __future__ import annotations

from cgkn_provider_lab.redaction import redact_text


def test_redacts_exact_secret_and_common_fields() -> None:
    secret = "fixture-super-secret-value"
    raw = (
        f"Authorization: Bearer {secret}; api_key={secret}; "
        f'{{"access_token":"{secret}"}}'
    )
    output = redact_text(raw, [secret])
    assert secret not in output
    assert output.count("[REDACTED]") >= 1

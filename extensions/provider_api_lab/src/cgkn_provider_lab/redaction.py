from __future__ import annotations

import re
from collections.abc import Iterable


_REDACTION_PATTERNS = (
    re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,;\"']+"),
    re.compile(r"(?i)((?:api[-_ ]?key|access[-_ ]?token|bearer[-_ ]?token|password|secret)\s*[:=]\s*)[^\s,;\"']+"),
    re.compile(r"(?i)(\"(?:api_key|apikey|access_token|token|password|secret)\"\s*:\s*\")[^\"]+(\")"),
)


def redact_text(value: object, secrets: Iterable[str] = ()) -> str:
    """Redact known credentials and common credential-shaped fields from text."""
    text = str(value)
    for secret in sorted({item for item in secrets if item}, key=len, reverse=True):
        text = text.replace(secret, "[REDACTED]")
    for pattern in _REDACTION_PATTERNS:
        if pattern.groups == 2:
            text = pattern.sub(r"\1[REDACTED]\2", text)
        else:
            text = pattern.sub(r"\1[REDACTED]", text)
    return text

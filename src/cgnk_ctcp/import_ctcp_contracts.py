from __future__ import annotations

import pathlib


def discover_legacy_docs(ctcp_root: pathlib.Path) -> list[pathlib.Path]:
    """Return readable legacy docs/config/examples only; never imports CTCP runtime."""
    allowed = []
    for pattern in ("*.md", "docs/**/*.md", "config/**/*.json", "examples/**/*.json"):
        allowed.extend(path for path in ctcp_root.glob(pattern) if path.is_file())
    return sorted(set(allowed))

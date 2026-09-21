from __future__ import annotations

import pathlib
import warnings


SPEC_CATEGORIES = ("artifacts", "modules", "flows", "policies", "migrations", "context_packs")


def spec_directory(root: pathlib.Path, category: str) -> pathlib.Path:
    """Return the formal specs directory, with a deprecated examples fallback."""
    if category not in SPEC_CATEGORIES:
        raise ValueError(f"unknown spec category: {category}")
    root = pathlib.Path(root).resolve()
    formal = root / "specs" / category
    if formal.is_dir():
        return formal
    legacy = root / "examples" / category
    if legacy.is_dir():
        warnings.warn(
            f"{legacy.relative_to(root).as_posix()} is deprecated; move formal definitions to specs/{category}",
            DeprecationWarning,
            stacklevel=2,
        )
        return legacy
    return formal

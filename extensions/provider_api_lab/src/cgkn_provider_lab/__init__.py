"""CGKN Provider API Lab.

This package is an isolated local experiment surface. It does not replace the
canonical CGKN ProviderJob or delivery route.
"""

from .models import ComparisonOptions, ProviderConfig, ProviderResult
from .service import ProviderComparisonService
from .storage import ProviderConfigStore

__all__ = [
    "ComparisonOptions",
    "ProviderComparisonService",
    "ProviderConfig",
    "ProviderConfigStore",
    "ProviderResult",
]

__version__ = "0.1.0"

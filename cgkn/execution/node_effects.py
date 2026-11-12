"""Compatibility imports for the shared Core effect scope (one ContextVar owner)."""
from veriarbor.execution_effects import (
    execution_scope, guard_effect, require_provider_context,
    guard_provider_transport, perform_scoped_effect, governed_provider_open,
)


def child_environment():
    """Minimal default child environment, never inherited Provider credentials.

    This controls inheritance only; it does not claim OS isolation from files.
    """
    import os
    allowed={'SYSTEMROOT','WINDIR','PATH','TEMP','TMP','COMSPEC'}
    return {k:v for k,v in os.environ.items() if k.upper() in allowed}

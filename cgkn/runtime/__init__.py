"""Runtime entry exports loaded on demand, without pulling a scheduler into contracts."""
from importlib import import_module

_EXPORTS = {
    'build_context_pack': '.context',
    'execution_fingerprint': '.fingerprint',
    'ArtifactInvalidator': '.invalidation',
    'ArtifactModuleRunner': '.runner',
    'ModuleExecutionError': '.runner',
    'DAGRunner': '.dag_runner',
    'RunSummary': '.dag_runner',
}
__all__ = list(_EXPORTS)


def __getattr__(name):
    if name not in _EXPORTS:
        raise AttributeError(name)
    value = getattr(import_module(_EXPORTS[name], __name__), name)
    globals()[name] = value
    return value

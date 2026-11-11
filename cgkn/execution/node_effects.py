"""Standard effect boundary for trusted Host transports; no OS interception."""
from contextvars import ContextVar
from contextlib import contextmanager
from veriarbor.execution_authority import ExecutionMode

_scope=ContextVar('node_effect_authority',default=None)
_provider_reserved=ContextVar('node_provider_reserved',default=False)
_provider_metered=ContextVar('node_provider_metered',default=False)


@contextmanager
def execution_scope(authority,permit_id):
    token=_scope.set((authority,permit_id))
    reservation=_provider_reserved.set(False)
    try:yield
    finally:
        _provider_reserved.reset(reservation)
        _scope.reset(token)


def guard_effect(request,operation,*,resource_usage=None):
    mode=ExecutionMode(request.metadata.get('execution_mode','GOVERNED'))
    if mode=='LEGACY':
        from veriarbor.governance import require_legacy
        require_legacy(project_id=request.project_id,run_id=request.run_id)
        import warnings
        warnings.warn('LEGACY effect transport: unmanaged lineage',RuntimeWarning)
        return
    if mode!='GOVERNED':raise ValueError('IMPORTED_UNMANAGED_CANNOT_EXECUTE')
    scope=_scope.get()
    if scope is None:raise ValueError('NODE_EXECUTION_AUTHORITY_REQUIRED')
    authority,permit_id=scope
    if request.metadata.get('node_execution_permit',{}).get('permit_id')!=permit_id:
        raise ValueError('PERMIT_BINDING_REJECT')
    authority.validate_permit(permit_id,project_id=request.project_id,run_id=request.run_id,
                              node_id=request.node_id,executor_identity=request.executor_ref,
                              capability_id=request.metadata['node_execution_permit']['capability_id'],
                              tree_version=request.metadata['node_execution_permit']['tree_version'],
                              execution_epoch=request.metadata['node_execution_permit']['execution_epoch'])
    authority.use_effect(permit_id,operation,resource_usage=resource_usage)
    if operation=='PROVIDER_CALL':_provider_reserved.set(True)


def require_provider_context(execution_mode='GOVERNED'):
    if execution_mode=='LEGACY':
        from veriarbor.governance import require_legacy
        require_legacy();return None
    if execution_mode!='GOVERNED' or _scope.get() is None:raise ValueError('PERMIT_REQUIRED')
    authority,pid=_scope.get();authority.validate_permit(pid)
    return authority,pid


def guard_provider_transport(execution_mode='GOVERNED'):
    scope=require_provider_context(execution_mode)
    if scope is None:return
    if _provider_reserved.get():_provider_reserved.set(False)
    else:scope[0].use_effect(scope[1],'PROVIDER_CALL',resource_usage={'calls':1})


def perform_scoped_effect(operation,callback,*,resource_usage=None):
    authority,permit_id=require_provider_context()
    token=_provider_reserved.set(operation=='PROVIDER_CALL')
    meter=_provider_metered.set(operation=='PROVIDER_CALL')
    try:return authority.perform_effect(permit_id,operation,callback,resource_usage=resource_usage)
    finally:
        _provider_metered.reset(meter)
        _provider_reserved.reset(token)


@contextmanager
def governed_provider_open(opener,request,*,timeout,execution_mode='GOVERNED'):
    import time
    scope=require_provider_context(execution_mode)
    started=time.monotonic();outcome='FAILED'
    try:
        with opener(request,timeout=timeout) as response:
            yield response
        outcome='SUCCEEDED'
    finally:
        if scope and not _provider_metered.get():scope[0].finish_effect(scope[1],'PROVIDER_CALL',duration_seconds=time.monotonic()-started,
                                       cost=None,outcome=outcome)

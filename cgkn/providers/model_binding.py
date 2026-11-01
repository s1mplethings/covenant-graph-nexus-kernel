"""Concrete model identity policy, separate from Provider service aliases."""

def bind_model(provider,requested,default,visible,allowed):
    bound=requested or default
    if not provider or not bound or bound==provider:
        raise ValueError('concrete model identity required')
    if bound not in visible:raise ValueError('model invisible')
    if bound not in allowed:raise ValueError('model not allowlisted')
    return {'provider_id':provider,'requested_model':requested or bound,'bound_model':bound,
            'request_policy':'pinned' if requested else 'explicit_provider_default'}


def confirm_model(binding,actual,*,aliases=()):
    """Only an explicit trusted alias list may admit a vendor version suffix."""
    if not actual or actual==binding['provider_id'] or actual not in {binding['bound_model'],*aliases}:
        raise ValueError('unexpected actual model')
    return {**binding,'actual_model':actual,'identity_status':'MATCH',
            'binding_policy':{'kind':'exact' if not aliases else 'explicit_aliases','aliases':list(aliases)}}

import pytest
from cgkn.providers.model_binding import bind_model,confirm_model
from cgkn.providers.gateway_client import _validate_terminal,GatewayCompletionError
from cgkn.providers import ModelRoleConfig

def test_default_pinned_and_explicit_alias_policy():
    default=bind_model('P',None,'M1',{'M1','M2'},{'M1','M2'})
    other=bind_model('P','M2','M1',{'M1','M2'},{'M1','M2'})
    assert default['bound_model']=='M1' and other['bound_model']=='M2'
    assert confirm_model(other,'M2')['identity_status']=='MATCH'
    with pytest.raises(ValueError):confirm_model(other,'M2-version')
    assert confirm_model(other,'M2-version',aliases=('M2-version',))['actual_model']=='M2-version'
    with pytest.raises(ValueError):confirm_model(other,'P',aliases=('P',))
    with pytest.raises(ValueError,match='invisible'):bind_model('P','M3','M1',{'M1','M2'},{'M1','M2','M3'})
    with pytest.raises(ValueError,match='allowlisted'):bind_model('P','M2','M1',{'M1','M2'},{'M1'})

def test_gateway_does_not_silently_accept_alias_or_changed_binding():
    doc={'cgkn_stream':{'completed':True},'status':'completed','id':'i','model':'M1',
        'usage':{'input_tokens':1,'output_tokens':2},'cgkn_model_identity':{'provider_id':'P','requested_model':'M1','actual_model':'M1','identity_status':'MATCH'}}
    config=ModelRoleConfig('worker','P',model_id='M1')
    _validate_terminal(doc,'responses',config)
    assert doc['cgkn_model_identity']['bound_model']=='M1'
    doc['cgkn_model_identity']['bound_model']='M2'
    with pytest.raises(GatewayCompletionError):_validate_terminal(doc,'responses',config)

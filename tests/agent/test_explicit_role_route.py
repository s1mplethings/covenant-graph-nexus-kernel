from experiments.product_dev_113.network_client import NetworkClient
from cgkn.providers import ModelRoleConfig,ProviderCompletion
from types import SimpleNamespace

def test_agent_fallback_uses_authorized_role_and_preserves_context():
    c=NetworkClient.__new__(NetworkClient);c.authorization={'agent_models':['qwen','grok']}
    c.network=SimpleNamespace(disabled_providers=set())
    attempts=[];events=[];c._trace=events.append
    def transport(**kw):
        attempts.append(kw)
        if kw['config'].model=='qwen':
            error=RuntimeError('PROVIDER_TRANSPORT_FAILED: controlled unavailable')
            error.network_outcome={'submitted':False}
            raise error
        return ProviderCompletion('{}','actual-grok','r',{},1)
    c._complete_transport=transport
    result=c.complete(config=ModelRoleConfig('agent','qwen'),user='same goal and receipt',system='planner',schema={},schema_name='decision')
    assert result.model=='actual-grok'
    assert [r['config'].model for r in attempts]==['qwen','grok']
    assert attempts[0]['user']==attempts[1]['user']
    assert events[-1]['effective_alias']=='grok' and events[-1]['role']=='agent'

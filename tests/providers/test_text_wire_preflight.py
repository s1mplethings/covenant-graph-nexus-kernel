import json
import pytest
from cgkn.providers import ModelRoleConfig
from cgkn.providers.text_wire import text_payload,serialize_text_payload,input_size,completion_preflight
from cgkn.providers.streaming_bound_adapter import BoundProviderRoute,invoke_stream_via_bound_opener

@pytest.mark.parametrize('provider,model',[('qwen','qwen3.8-flash'),('deepseek','deepseek-flash')])
@pytest.mark.boundary
@pytest.mark.happy_path
def test_preflight_matches_actual_stream_request_and_rejects_before_open(provider,model):
    config=ModelRoleConfig('agent',model=provider,model_id=model,max_output_tokens=5000)
    schema={'type':'object','properties':{'items':{'type':'array','uniqueItems':True,'items':{'type':'string'}}}}
    args=dict(system='中文系统',user='原目标与证据',schema_name='check',schema=schema,config=config,ceiling=64000)
    check=completion_preflight(**args)
    payload,_,_=text_payload(provider,model,args['system'].strip(),('user: '+args['user']).strip(),{'type':'json_schema','json_schema':{'name':'check','strict':True,'schema':schema}},config.temperature,config.max_output_tokens)
    captured=[]
    def bound(req,parser):
        captured.append(req.data)
        assert input_size(req.data,64000)==check
        assert not input_size(req.data,check['conservative_input_upper']-1)['within_ceiling']
        raise RuntimeError('fixture stop before network')
    with pytest.raises(RuntimeError,match='fixture stop'):
        invoke_stream_via_bound_opener(route=BoundProviderRoute(provider,'https://example.test/v1',model),token='fixture',upstream_chat_payload=payload,bound_consume=bound)
    assert captured[0]==serialize_text_payload(payload)

@pytest.mark.boundary
@pytest.mark.negative
def test_invalid_ceiling_and_large_multibyte_content():
    assert not input_size(b'x',None)['within_ceiling']
    assert not input_size(b'x',64000.0)['within_ceiling']
    assert not input_size(('你'*22000).encode(),64000)['within_ceiling']


def test_lab_ingress_matches_preflight(tmp_path):
    import sys
    sys.path.insert(0,'D:/cgkn-provider-api-lab/src')
    from cgkn_provider_lab.gateway import _messages_from_request,_options
    config=ModelRoleConfig('agent',model='qwen',model_id='qwen3.8-flash',max_output_tokens=5000)
    schema={'type':'object'}
    system=' system\n';user=' evidence\n'
    fmt={'type':'json_schema','json_schema':{'name':'check','strict':True,'schema':schema}}
    request={'messages':[{'role':'system','content':system},{'role':'user','content':user}],'temperature':config.temperature,'max_tokens':config.max_output_tokens,'response_format':fmt}
    lab_system,prompt=_messages_from_request(request,'chat');options=_options(request,lab_system)
    payload,_,_=text_payload(config.model,config.model_id,options.system_prompt,prompt,options.response_format,options.temperature,options.max_tokens)
    assert completion_preflight(system=system,user=user,schema_name='check',schema=schema,config=config,ceiling=64000)==input_size(serialize_text_payload(payload),64000)

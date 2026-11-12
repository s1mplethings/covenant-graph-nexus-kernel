"""One pure final text request serializer for Gateway and local preflight."""
import json
from .streaming_sse import configure_streamed_chat_request

def unsupported_qwen_keywords(schema):
    unsupported={'uniqueItems','contains','minContains','maxContains','additionalItems','multipleOf','patternProperties','propertyNames'}
    found=set()
    def visit(node):
        if not isinstance(node,dict):return
        found.update(unsupported.intersection(node))
        for key in ('properties','$defs','definitions','dependentSchemas','patternProperties'):
            children=node.get(key)
            if isinstance(children,dict):
                for child in children.values():visit(child)
        for key in ('items','additionalProperties','if','then','else','not','contains','propertyNames'):visit(node.get(key))
        for key in ('allOf','anyOf','oneOf','prefixItems'):
            children=node.get(key)
            if isinstance(children,list):
                for child in children:visit(child)
    visit(schema);return sorted(found)

def text_payload(provider_id,model,system,user,response_format,temperature,max_tokens):
    response_format=dict(response_format);schema=(response_format.get('json_schema') or {}).get('schema')
    unsupported=unsupported_qwen_keywords(schema) if provider_id=='qwen' else []
    adapted=response_format.get('type')=='json_schema' and (provider_id=='deepseek' or bool(unsupported))
    if adapted:
        system+='\nReturn one JSON object matching this JSON Schema exactly: '+json.dumps(schema,ensure_ascii=False)
        response_format={'type':'json_object'}
    payload=dict(model=model,messages=[dict(role='system',content=system),dict(role='user',content=user)],temperature=temperature,max_tokens=max_tokens,reasoning_effort='none')
    if provider_id=='qwen' and model.startswith('qwen3.8-max'):payload['max_completion_tokens']=payload.pop('max_tokens')
    if provider_id=='qwen' and model=='qwen3.8-flash':
        payload.pop('reasoning_effort',None);payload['enable_thinking']=False;payload['max_completion_tokens']=payload.pop('max_tokens')
    if response_format:payload['response_format']=response_format
    return payload,unsupported,adapted

def serialize_text_payload(payload):
    return json.dumps(configure_streamed_chat_request(payload),ensure_ascii=False,separators=(',',':')).encode('utf-8')

def input_size(body,ceiling):
    upper=len(body)+1024
    valid=type(ceiling) is int and 0<ceiling<=1_000_000 and upper<=ceiling
    return {'request_bytes':len(body),'framing_allowance_bytes':1024,'conservative_input_upper':upper,
            'input_token_ceiling':ceiling,'within_ceiling':valid,'excess':max(0,upper-ceiling) if type(ceiling) is int else None,
            'basis':'final serialized UTF-8 bytes plus framing; not tokenizer count or supplier usage'}

def completion_preflight(*,system,user,schema_name,schema,config,ceiling):
    return input_size(completion_wire(system=system,user=user,schema_name=schema_name,schema=schema,config=config),ceiling)


def completion_wire(*,system,user,schema_name,schema,config):
    if not config.model_id:raise ValueError('exact model identity required for final wire preflight')
    fmt={'type':'json_schema','json_schema':{'name':schema_name,'strict':True,'schema':dict(schema)}} if schema is not None else {}
    if schema is None and schema_name=='cgkn_semantic_v1':fmt={'type':'json_schema','json_schema':{'name':schema_name,'strict':False,'schema':{'type':'object'}}}
    # Lab text ingress: ComparisonOptions strips system; chat/responses add the
    # role prefix before service strips the conversation. Test against Lab ingress.
    system=system.strip()
    user=('user: '+user).strip()
    payload,_,_=text_payload(config.model,config.model_id,system,user,fmt,float(config.temperature),min(131072,max(1,int(config.max_output_tokens))))
    body=serialize_text_payload(payload)
    return body

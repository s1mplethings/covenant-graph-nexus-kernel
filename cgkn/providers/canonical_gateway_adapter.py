"""Connect the existing canonical Provider boundary to the budget-owning client.

Raw text remains subject to the original caller's parsing/admission contracts.
No task, planning, publishing or retry authority is added here.
"""
import json,os
from .client import ModelRoleConfig
from .gateway_client import completion_client_from_environment,GatewayCompletionClient
from scripts import provider_api_budget as budget


def provider_text(messages,model,timeout,*,max_tokens,stage='provider_text',response_format=None,temperature=0.2,transport_scope=None,endpoint=None,on_progress=None,client=None):
    if not isinstance(messages,list) or any(not isinstance(m,dict) or m.get('role') not in ('system','developer','user','assistant') or not isinstance(m.get('content'),str) for m in messages):
        raise ValueError('CANONICAL_GATEWAY_TEXT_MESSAGES_REQUIRED')
    # Fail before constructing a transport if no run-level admission exists.
    limits=budget.configured_limits()
    if budget.configured_ledger_path() is None or not budget.budget_configured() or any(limits[k] is None for k in ('input_cost_per_million','output_cost_per_million')):
        raise budget.ProviderBudgetExhausted('PROVIDER_BUDGET_EXHAUSTED: canonical domestic generation requires an authorized run ledger and price limits')
    if model not in ('qwen','deepseek'):
        raise ValueError('APPLICATION_MODEL_NOT_ADMITTED:'+str(model))
    ledger=budget.configured_ledger_path()
    if ledger.exists():
        doc=json.loads(ledger.read_text(encoding='utf-8'))
        if any((row.get('submission_outcome_unknown') or row.get('status')=='INTERRUPTED_UNKNOWN')
               and not str(row.get('request_identity','')).startswith('sha256:') for row in doc.get('calls',[])):
            raise budget.ProviderBudgetExhausted('LEGACY_UNKNOWN_SUBMISSION_REQUIRES_RECONCILIATION')
    client=client or completion_client_from_environment()
    if not isinstance(client,GatewayCompletionClient) or not client.enforce_budget:
        raise RuntimeError('CANONICAL_DOMESTIC_REQUIRES_BUDGETED_GATEWAY')
    if endpoint is not None and endpoint not in (client.base_url+'/v1/responses',client.base_url+'/v1/chat/completions'):
        raise RuntimeError('DOMESTIC_OLD_ENDPOINT_REFUSED_NO_FALLBACK')
    system='\n'.join(str(m.get('content','')) for m in messages if m.get('role') in ('system','developer'))
    user='\n'.join(str(m.get('role','user'))+': '+str(m.get('content','')) for m in messages if m.get('role') not in ('system','developer'))
    schema=None;name='canonical_raw_text'
    if response_format:
        if response_format.get('type')!='json_schema':raise ValueError('UNSUPPORTED_CANONICAL_RESPONSE_FORMAT')
        contract=response_format['json_schema'];schema=contract['schema'];name=contract['name']
    purpose=budget.call_purpose(stage)
    role='agent' if purpose=='PLANNING' else 'worker'
    config=ModelRoleConfig(role,model,max(1,min(600,int(timeout))),int(max_tokens),float(temperature),'none')
    from .application_network import settings
    application = settings()
    if application:
        from .routing import CGKNModelRouting
        from dataclasses import replace
        selected = getattr(CGKNModelRouting.load(application['model_routing']), role)
        if selected.model == model:
            config = replace(config, model_id=selected.model_id, reasoning_effort=selected.reasoning_effort)
    result=client.complete(system=system,user=user,schema_name=name,schema=schema,config=config,purpose=purpose,transport_scope=transport_scope,on_progress=on_progress)
    return result


def post_payload(payload,timeout,*,endpoint=None):
    """Compatibility callers receive their usual OpenAI response envelope."""
    allowed={'model','messages','input','max_tokens','max_output_tokens','temperature','response_format','text','cgkn_stage'}
    if set(payload)-allowed:raise ValueError('CANONICAL_GATEWAY_UNSUPPORTED_FIELDS:'+','.join(sorted(set(payload)-allowed)))
    messages=payload.get('messages',payload.get('input',[]))
    if isinstance(messages,str):messages=[{'role':'user','content':messages}]
    if not isinstance(messages,list):raise ValueError('CANONICAL_INPUT_MESSAGES_REQUIRED')
    response_format=payload.get('response_format')
    raw_format=(payload.get('text') or {}).get('format')
    if raw_format and raw_format.get('type')!='json_schema':
        raise ValueError('UNSUPPORTED_CANONICAL_RESPONSE_FORMAT')
    if raw_format and raw_format.get('type')=='json_schema':
        response_format={'type':'json_schema','json_schema':raw_format}
    result=provider_text(messages,payload['model'],timeout,
        max_tokens=payload.get('max_tokens',payload.get('max_output_tokens',4096)),
        stage=str(payload.get('cgkn_stage','requirements_planning')),response_format=response_format,
        temperature=payload.get('temperature',0.2),endpoint=endpoint)
    return dict(id=result.request_id,model=result.model,status='completed',output_text=result.text,usage=dict(result.usage),
        choices=[{'message':{'role':'assistant','content':result.text},'finish_reason':'stop'}],
        cgkn_transport='BUDGETED_GATEWAY',attempts=result.attempts)

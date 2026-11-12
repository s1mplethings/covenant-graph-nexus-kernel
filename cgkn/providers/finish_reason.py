"""Public completion dispositions; never imply business acceptance or retry safety."""
REASONS = frozenset({'MODEL_STOP','OUTPUT_TOKEN_LIMIT','TOOL_FINISHED','TOOL_INTERRUPTED',
                    'STREAM_TRUNCATED','TRANSPORT_INTERRUPTED','SCHEMA_INCOMPLETE','TIMEOUT','PROVIDER_ERROR','UNKNOWN'})

def classify_finish(reason):
    if reason in REASONS:
        return reason
    return {'stop':'MODEL_STOP','completed':'MODEL_STOP','length':'OUTPUT_TOKEN_LIMIT','max_tokens':'OUTPUT_TOKEN_LIMIT','max_output_tokens':'OUTPUT_TOKEN_LIMIT',
            'tool_calls':'TOOL_FINISHED','function_call':'TOOL_FINISHED',
            'stream_eof_without_done':'STREAM_TRUNCATED','stream_tool_interrupted':'TOOL_INTERRUPTED',
            'stream_output_token_limit':'OUTPUT_TOKEN_LIMIT','stream_tool_finished':'TOOL_FINISHED',
            'timeout':'TIMEOUT','schema_incomplete':'SCHEMA_INCOMPLETE',
            'transport_interrupted':'TRANSPORT_INTERRUPTED','provider_error':'PROVIDER_ERROR'}.get(reason,'UNKNOWN')


def finish_disposition(reason, *, outcome_unknown=False, partial_verified=False, retry_safe=False):
    """Public recovery advice, not permission to replay an operation."""
    classified = classify_finish(reason)
    if outcome_unknown:
        action = 'reconcile'
    elif classified == 'OUTPUT_TOKEN_LIMIT':
        action = 'continue' if partial_verified else 'split'
    elif classified in {'MODEL_STOP','TOOL_FINISHED'}:
        action = 'inspect'
    elif classified in {'TIMEOUT','TRANSPORT_INTERRUPTED','PROVIDER_ERROR'} and retry_safe:
        action = 'retry'
    elif classified == 'UNKNOWN':
        action = 'escalate'
    else:
        action = 'inspect'
    return {'finish_reason':classified, 'raw_finish_reason':reason, 'disposition':action,
            'acceptance':'NOT_INFERRED'}

"""Isolated, zero-provider qualification of optional higher-level libraries."""
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ['INSPECT_DISABLE_MODEL_API'] = '1'


def pydantic_trial():
    from pydantic_ai import Agent, models
    from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
    from pydantic_ai.models.function import FunctionModel
    from pydantic_ai.usage import UsageLimits
    from cgkn.executors.llm import BoundedFileActions

    models.ALLOW_MODEL_REQUESTS = False
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / 'fixture.txt').write_text('offline', encoding='utf-8')
        actions = BoundedFileActions(root)
        calls = []
        def respond(messages, info):
            calls.append(len(messages))
            if len(calls) == 1:
                return ModelResponse(parts=[ToolCallPart('read_file', {'path': 'fixture.txt'})])
            return ModelResponse(parts=[TextPart('done')])
        agent = Agent(FunctionModel(respond), retries=0)
        @agent.tool_plain
        def read_file(path: str) -> str:
            return actions.apply({'action': 'read_file', 'path': path})['content']
        result = agent.run_sync('read fixture', usage_limits=UsageLimits(request_limit=2))
        assert result.output == 'done' and len(calls) == 2
        for bad in ('../outside', '.git/config'):
            try:
                actions.apply({'action': 'read_file', 'path': bad})
            except PermissionError:
                pass
            else:
                raise AssertionError('path boundary accepted')
    return {'status': 'PASS', 'model_calls': 2, 'paid_calls': 0,
            'scope': 'bounded read adapter only; complete Worker qualification not performed'}


def inspect_trial():
    from inspect_ai import Task, eval
    from inspect_ai.dataset import Sample
    from inspect_ai.model import ModelOutput, get_model
    from inspect_ai.scorer import match
    from inspect_ai.solver import generate
    task = Task(dataset=[Sample(input='fixture', target='ok'), Sample(input='negative', target='ok')],
                solver=generate(), scorer=match())
    model = get_model('mockllm/model', custom_outputs=[ModelOutput.from_content(model='mockllm', content=text) for text in ('ok', 'wrong')])
    logs = eval(task, model=model, max_retries=0, max_samples=1, message_limit=2,
                log_dir=str(ROOT / 'artifacts/substrate-migration/inspect'))
    assert len(logs) == 1 and logs[0].status == 'success'
    scores = [list(sample.scores.values())[0].value for sample in logs[0].samples]
    assert scores == ['C', 'I'], scores
    return {'status': 'PASS', 'scores': scores, 'paid_calls': 0,
            'scope': 'fixed mock samples; existing business oracle remains outside this runner'}


def trace_trial():
    from opentelemetry import trace
    tracer = trace.get_tracer('cgkn.offline-trial')
    with tracer.start_as_current_span('project', attributes={'project.id': 'offline'}):
        with tracer.start_as_current_span('attempt', attributes={'run.id': 'run', 'node.id': 'node', 'attempt.id': 'attempt'}):
            assert not trace.get_current_span().is_recording()
    return {'status': 'PASS', 'exporters': 0, 'scope': 'API-only no-op; no durable evidence replacement'}


if __name__ == '__main__':
    results = {}
    for name, trial in [('pydantic_ai', pydantic_trial), ('inspect_ai', inspect_trial), ('opentelemetry', trace_trial)]:
        try:
            results[name] = trial()
        except Exception as error:
            results[name] = {'status': 'FAIL', 'error': f'{type(error).__name__}: {error}'}
    (ROOT / 'artifacts/substrate-migration/optional-trials.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
    print(json.dumps(results))

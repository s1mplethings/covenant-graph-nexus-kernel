"""Offline progress-policy tests: virtual time is not supplier stability evidence."""
import json
import pytest
from cgkn.providers.streaming_sse import (
    MeaningfulProgressWatchdog, StreamError, StreamLimits, SSEEvent,
    collect_chat_completions, collect_responses, sse_events,
)

class Clock:
    def __init__(self): self.now = 0
    def __call__(self): return self.now
    def advance(self, seconds): self.now += seconds


def event(delta=None, finish=None, **extra):
    return SSEEvent(json.dumps(dict(id='req', model='fixture', choices=[dict(index=0, delta=delta or {}, finish_reason=finish)], **extra)))


@pytest.mark.parametrize('duration', [86, 91, 301, 3601, 36000])
def test_continuous_meaningful_output_has_no_total_deadline(duration):
    clock=Clock(); watch=MeaningfulProgressWatchdog(clock=clock); watch.submitted()
    def events():
        for _ in range((duration+59)//60):
            clock.advance(60)
            yield event({'content':'x'})
        yield event(finish='stop', usage={'prompt_tokens':1,'completion_tokens':1})
        yield SSEEvent('[DONE]')
    def progress(row):
        watch.progress(row['meaningful_events'])
    result=collect_chat_completions(events(),on_progress=progress)
    assert result.finish_reason=='stop' and clock.now>=duration
    assert watch.snapshot()['started']
    watch.check()


def test_queue_time_is_not_initial_wait():
    clock=Clock();watch=MeaningfulProgressWatchdog(clock=clock)
    clock.advance(10000);watch.check();watch.submitted()
    clock.advance(179);watch.check()
    clock.advance(1)
    with pytest.raises(StreamError,match='NO_INITIAL_MEANINGFUL_PROGRESS'):watch.check()


def test_heartbeat_and_whitespace_do_not_refresh_initial_wait():
    clock=Clock();watch=MeaningfulProgressWatchdog(clock=clock);watch.submitted()
    rows=[]
    def lines():
        for _ in range(4):
            clock.advance(50)
            watch.check()
            yield b': keep-alive\n\n'
            yield ('data: '+event({'content':' \t'}).data+'\n').encode()
            yield b'\n'
    with pytest.raises(StreamError,match='NO_INITIAL_MEANINGFUL_PROGRESS'):
        collect_chat_completions(sse_events(lines(),limits=StreamLimits()),on_progress=rows.append)
    assert all(row['meaningful_events']==0 for row in rows)


def test_midstream_whitespace_usage_and_duplicate_progress_do_not_refresh():
    clock=Clock();watch=MeaningfulProgressWatchdog(clock=clock);watch.submitted();watch.progress(1)
    clock.advance(119)
    assert watch.progress(1) is False
    watch.check();clock.advance(1)
    with pytest.raises(StreamError,match='NO_MEANINGFUL_PROGRESS'):watch.check()
    with pytest.raises(StreamError,match='NO_MEANINGFUL_PROGRESS'):watch.progress(2)


def test_reasoning_is_meaningful_but_not_business_text_or_diagnostics():
    rows=[]
    result=collect_chat_completions([
        event({'reasoning_content':'private thought'}),event({'reasoning':'more thought'}),
        event({'content':'answer'}),event(finish='stop'),SSEEvent('[DONE]')],on_progress=rows.append)
    assert result.text=='answer'
    assert [r['meaningful_events'] for r in rows]==[1,2,3,3]
    assert 'thought' not in json.dumps(rows)
    assert result.reasoning_chars==len('private thoughtmore thought')


def test_reasoning_can_continue_without_body_past_initial_timeout():
    clock=Clock();watch=MeaningfulProgressWatchdog(clock=clock);watch.submitted()
    def events():
        clock.advance(179);yield event({'reasoning_content':'thinking'})
        for _ in range(8):
            clock.advance(100);yield event({'reasoning_content':'more'})
        yield event({'content':'ok'});yield event(finish='stop');yield SSEEvent('[DONE]')
    result=collect_chat_completions(events(),on_progress=lambda row:watch.progress(row['meaningful_events']))
    assert result.text=='ok' and clock.now==979


def test_responses_progress_excludes_status_usage_and_whitespace():
    rows=[]
    def e(kind,**kw):return SSEEvent(json.dumps(dict(type=kind,**kw)))
    result=collect_responses([
        e('response.created',response={'id':'r'}),e('response.in_progress',response={'id':'r'}),
        e('response.reasoning_text.delta',delta='secret'),
        e('response.reasoning_summary_text.delta',delta='thinking'),
        e('response.output_text.delta',delta=' '),e('response.output_text.delta',delta='answer'),
        e('response.completed',response={'id':'r','status':'completed','model':'fixture','output_text':' answer','usage':{'input_tokens':1,'output_tokens':2}})
    ],on_progress=rows.append)
    assert result.text==' answer'
    assert [r['meaningful_events'] for r in rows]==[0,0,1,2,2,3,3]
    assert 'secret' not in json.dumps(rows) and 'secret' not in result.text


@pytest.mark.parametrize('events,code', [
    ([event({'content':'partial'})], 'stream_eof_without_done'),
    ([event({'content':'partial'}),SSEEvent('[DONE]')], 'stream_incomplete_or_tool_finish'),
    ([event({'content':'partial'}),event(finish='length'),SSEEvent('[DONE]')], 'stream_incomplete_or_tool_finish'),
    ([SSEEvent('{')], 'stream_invalid_json'),
])
def test_progress_never_overrides_terminal_contract(events,code):
    with pytest.raises(StreamError,match=code):collect_chat_completions(events)


def test_usage_missing_remains_explicitly_empty_for_budget_owner():
    result=collect_chat_completions([event({'content':'ok'}),event(finish='stop'),SSEEvent('[DONE]')])
    assert result.usage=={}


def test_independent_requests_and_remote_event_ages():
    clock=Clock();one=MeaningfulProgressWatchdog(clock=clock);two=MeaningfulProgressWatchdog(clock=clock)
    one.submitted(age=10);two.submitted();one.progress(1,age=5)
    clock.advance(119)
    two.progress(1)
    with pytest.raises(StreamError,match='NO_MEANINGFUL_PROGRESS'):one.check()
    two.check()
    assert 'at' not in one.snapshot()


@pytest.mark.parametrize('value',[0,-1,float('inf'),float('nan'),True])
def test_invalid_policy_rejected(value):
    with pytest.raises(ValueError):MeaningfulProgressWatchdog(initial_timeout=value)


def test_zero_status_progress_does_not_start_generation():
    clock=Clock();watch=MeaningfulProgressWatchdog(clock=clock);watch.submitted()
    assert watch.progress(0) is False
    assert watch.snapshot()['started'] is False
    clock.advance(180)
    with pytest.raises(StreamError,match='NO_INITIAL_MEANINGFUL_PROGRESS'):watch.progress(0)


def test_watchdog_concurrent_duplicate_updates_are_atomic():
    from concurrent.futures import ThreadPoolExecutor
    watch=MeaningfulProgressWatchdog();watch.submitted()
    with ThreadPoolExecutor(max_workers=8) as pool:
        accepted=list(pool.map(lambda _:watch.progress(1),range(64)))
    assert sum(accepted)==1
    assert watch.snapshot()['meaningful_events']==1


def test_existing_byte_and_event_bounds_remain_active():
    with pytest.raises(StreamError,match='stream_text_too_large'):
        collect_chat_completions([event({'content':'long'})],limits=StreamLimits(max_text_bytes=2))
    with pytest.raises(StreamError,match='stream_too_many_events'):
        collect_chat_completions([event({'content':'x'}),event(finish='stop')],limits=StreamLimits(max_events=1))


def test_atomic_save_refuses_insufficient_disk_before_creating_result(tmp_path,monkeypatch):
    from cgkn.providers import streaming_sse as module
    from types import SimpleNamespace
    monkeypatch.setattr(module.shutil,'disk_usage',lambda _:SimpleNamespace(free=100))
    with pytest.raises(StreamError,match='completed_response_disk_space_low'):
        module.save_immutable_json(tmp_path/'result.json',{'output_text':'ok'})
    assert list(tmp_path.iterdir())==[]


def test_atomic_save_retains_immutable_result(tmp_path):
    from cgkn.providers.streaming_sse import save_immutable_json
    path=tmp_path/'result.json'
    save_immutable_json(path,{'output_text':'original'})
    with pytest.raises(FileExistsError):save_immutable_json(path,{'output_text':'other'})
    assert json.loads(path.read_text())['output_text']=='original'
    assert len(list(tmp_path.iterdir()))==1

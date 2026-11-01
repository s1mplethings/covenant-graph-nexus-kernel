"""The saved non-thinking contract must reach the actual outbound request."""
import pytest
from dataclasses import replace
from tests.providers.test_streaming_runtime import runtime

@pytest.mark.parametrize("provider",["qwen","deepseek"])
def test_saved_none_reaches_upstream(runtime,provider):
    from cgkn.providers.client import ModelRoleConfig
    config=ModelRoleConfig("agent" if provider=="qwen" else "worker",provider,10,128,0.0,"none",model_id=provider+"-fixture")
    runtime["client"].complete(system="Return text",user="ok",schema_name="text",schema=None,config=config)
    assert len(runtime["posts"])==1
    assert runtime["posts"][0]["reasoning_effort"]=="none"
    assert runtime["posts"][0]["max_tokens"]==128

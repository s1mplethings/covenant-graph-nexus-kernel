from __future__ import annotations

import json

from cgkn.application.capability_builder import CapabilityBuilderService, CapabilityRisk, CapabilitySpec, CapabilityStore
from cgkn.application.self_growth import SelfGrowthService
from cgkn.providers import ModelRoleConfig, ProviderCompletion


class CountingClient:
    calls = 0
    def complete(self, **kwargs):
        self.calls += 1
        prompt = json.loads(kwargs["user"]); before = prompt["current_sources"]["executor.py"]
        code = 'def execute(value):\n    return value.lower().replace(" ", "-")\n'
        value = {"schema_version":"1.0","node_id":prompt["node_id"],"summary":"done","actions":[{"action":"patch_file","path":"executor.py","find":before,"replace":code}],"expected_outputs":["tests pass"],"confidence":1.0,"needs_escalation":False,"escalation_reason":""}
        return ProviderCompletion(json.dumps(value), {"total_tokens": 12})


def test_growth_build_resume_then_reuse_without_builder(tmp_path):
    spec = CapabilitySpec("text.slugify", "1", "slugify", {}, {}, ({"input":"Hello World","output":"hello-world"},), ("works",))
    client = CountingClient(); store = CapabilityStore(tmp_path / "store")
    builder = CapabilityBuilderService(client, ModelRoleConfig("worker","grok",30,1000,0,"low"), provider_id="grok", mode="SINGLE_PROVIDER_MODE", store=store)
    growth = SelfGrowthService(builder, store, provider_id="grok", mode="SINGLE_PROVIDER_MODE", history_path=tmp_path / "history.json")
    first = growth.ensure_and_resume(tmp_path / "candidates", spec, "Hello World")
    assert first.status == "PASS" and first.growth_invoked and first.builder_invoked and first.output == "hello-world"
    second = growth.ensure_and_resume(tmp_path / "unused", spec, "Again Now")
    assert second.status == "PASS" and second.reused and not second.growth_invoked and not second.builder_invoked
    assert second.provider_calls == 0 and second.output == "again-now" and client.calls == 1
    assert len(json.loads((tmp_path / "history.json").read_text())["events"]) == 1


def test_growth_classifies_builder_failure(tmp_path):
    spec = CapabilitySpec("text.slugify", "1", "slugify", {}, {}, ({"input":"Hello World","output":"different"},), ("works",))
    client = CountingClient(); store = CapabilityStore(tmp_path / "store")
    builder = CapabilityBuilderService(client, ModelRoleConfig("worker","grok",30,1000,0,"low"), provider_id="grok", mode="SINGLE_PROVIDER_MODE", store=store)
    outcome = SelfGrowthService(builder, store, provider_id="grok", mode="SINGLE_PROVIDER_MODE", history_path=tmp_path / "history.json").ensure_and_resume(tmp_path / "candidates", spec, "x")
    assert outcome.status == "FAIL" and outcome.failure_class == "BUILD_FAILED" and not outcome.admitted


def test_capability_spec_rejects_unsafe_risk():
    try:
        CapabilitySpec("unsafe", "1", "unsafe", {}, {}, ({"input":1,"output":1},), ("works",), risk="NETWORK_WRITE")
    except ValueError as exc:
        assert "canonical capability risks" in str(exc)
    else:
        raise AssertionError("unsafe risk was accepted")


class MappingClient:
    def __init__(self, sources):
        self.sources = sources
        self.calls = 0

    def complete(self, **kwargs):
        self.calls += 1
        prompt = json.loads(kwargs["user"])
        before = prompt["current_sources"]["executor.py"]
        code = self.sources[prompt["node_id"]]
        value = {"schema_version":"1.0","node_id":prompt["node_id"],"summary":"done","actions":[{"action":"patch_file","path":"executor.py","find":before,"replace":code}],"expected_outputs":["tests pass"],"confidence":1.0,"needs_escalation":False,"escalation_reason":""}
        return ProviderCompletion(json.dumps(value), {"total_tokens": 20})


class FakePublicNetwork:
    def __init__(self, payload): self.payload = payload
    def get(self, url): return dict(self.payload, final_url=url)


def test_network_capability_can_feed_declared_grown_dependency(tmp_path):
    repo_data = {"full_name":"octo/demo","description":None,"default_branch":"main","language":"Python","stargazers_count":2,"forks_count":1,"open_issues_count":0,"html_url":"https://github.com/octo/demo"}
    network_response = {"status_code":200,"final_url":"https://api.github.com/repos/octo/demo","content_type":"application/json","text":json.dumps(repo_data),"truncated":False,"bytes_read":100}
    sources = {
        "web.fetch.public@1": 'def execute(value, ctx):\n    result = ctx.network_public.get(value["url"])\n    return {key: result[key] for key in ("status_code", "final_url", "content_type", "text", "truncated")}\n',
        "github.repo.inspect.public@1": 'import json\n\ndef execute(value, ctx):\n    fetched = ctx.capabilities.invoke("web.fetch.public@1", {"url": "https://api.github.com/repos/%s/%s" % (value["owner"], value["repo"])})\n    data = json.loads(fetched["text"])\n    return {"full_name":data["full_name"],"description":data.get("description"),"default_branch":data["default_branch"],"language":data.get("language"),"stars":data["stargazers_count"],"forks":data["forks_count"],"open_issues":data["open_issues_count"],"html_url":data["html_url"]}\n',
    }
    web_output = {key: network_response[key] for key in ("status_code", "final_url", "content_type", "text", "truncated")}
    github_output = {"full_name":"octo/demo","description":None,"default_branch":"main","language":"Python","stars":2,"forks":1,"open_issues":0,"html_url":"https://github.com/octo/demo"}
    web = CapabilitySpec("web.fetch.public","1","fetch",{}, {}, ({"input":{"url":"https://api.github.com/repos/octo/demo"},"output":web_output,"runtime":{"network_response":network_response}},), ("bounded runtime",), CapabilityRisk.READ_ONLY_PUBLIC_NETWORK)
    github = CapabilitySpec("github.repo.inspect.public","1","inspect",{}, {}, ({"input":{"owner":"octo","repo":"demo"},"output":github_output,"runtime":{"dependency_results":{"web.fetch.public@1":web_output}}},), ("uses web fetch",), CapabilityRisk.READ_ONLY_PUBLIC_NETWORK_COMPOSITE, allowed_dependencies=("web.fetch.public@1",))
    client = MappingClient(sources); store = CapabilityStore(tmp_path / "store")
    builder = CapabilityBuilderService(client, ModelRoleConfig("worker","grok",30,1000,0,"low"), provider_id="grok", mode="SINGLE_PROVIDER_MODE", store=store)
    growth = SelfGrowthService(builder, store, provider_id="grok", mode="SINGLE_PROVIDER_MODE", history_path=tmp_path / "history.json", network_public=FakePublicNetwork(network_response))
    assert growth.ensure_and_resume(tmp_path / "candidates", web, {"url":"https://api.github.com/repos/octo/demo"}).status == "PASS"
    outcome = growth.ensure_and_resume(tmp_path / "candidates", github, {"owner":"octo","repo":"demo"})
    assert outcome.status == "PASS" and outcome.output == github_output and client.calls == 2
    reused = growth.ensure_and_resume(tmp_path / "unused", github, {"owner":"octo","repo":"demo"})
    assert reused.status == "PASS" and reused.reused and reused.provider_calls == 0 and client.calls == 2


def test_missing_declared_dependency_stops_before_builder(tmp_path):
    spec = CapabilitySpec("dependent", "1", "depends", {}, {}, ({"input":1,"output":1,"runtime":{"dependency_results":{"missing@1":1}}},), ("works",), allowed_dependencies=("missing@1",))
    client = CountingClient(); store = CapabilityStore(tmp_path / "store")
    builder = CapabilityBuilderService(client, ModelRoleConfig("worker","grok",30,1000,0,"low"), provider_id="grok", mode="SINGLE_PROVIDER_MODE", store=store)
    outcome = SelfGrowthService(builder, store, provider_id="grok", mode="SINGLE_PROVIDER_MODE", history_path=tmp_path / "history.json").ensure_and_resume(tmp_path / "candidates", spec, 1)
    assert outcome.failure_class == "DEPENDENCY_UNAVAILABLE" and client.calls == 0

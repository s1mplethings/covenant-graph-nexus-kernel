"""Exact old/new behavior, including ordering, diagnostics and nested mutation."""
import ast
from collections import defaultdict, deque
import copy
from pathlib import Path
import random
import os
import ssl
import urllib.request
from urllib.parse import urlparse
from types import MappingProxyType
from typing import Any, Mapping

import pytest

from experiments.execution_dedup.candidates import freeze, thaw, ordered_nodes

BASE = Path('D:/CGKN/.service_worktree/substrate-migration-20261101')


def original(path, names):
    tree = ast.parse((BASE / path).read_text(encoding='utf-8-sig'))
    nodes = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name in names]
    for n in nodes: n.decorator_list = []
    scope = dict(Any=Any, Mapping=Mapping, MappingProxyType=MappingProxyType,
                 defaultdict=defaultdict, deque=deque, os=os, urlparse=urlparse, ssl=ssl, urllib=urllib)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), path, 'exec'), scope)
    return scope


@pytest.mark.parametrize('path', ['cgkn/component/spec.py', 'cgkn/execution/contracts.py',
                                 'cgkn/orchestration/capability_tree.py', 'cgkn/orchestration/execution_dag.py'])
def test_freeze_shared_behavior(path):
    old = original(path, {'_freeze', '_thaw'})
    rng = random.Random(251)
    def value(depth):
        if depth == 0: return rng.choice([None, True, False, 0, 1.5, '中文', b'raw'])
        return rng.choice([lambda: [value(depth-1) for _ in range(3)],
                           lambda: {rng.choice(['a','b',7]):value(depth-1) for _ in range(3)},
                           lambda: tuple(value(depth-1) for _ in range(3))])()
    for _ in range(300):
        raw=value(3); before=copy.deepcopy(raw)
        expected=old['_freeze'](raw); actual=freeze(raw)
        assert actual == expected
        assert thaw(actual) == old['_thaw'](expected)
        assert raw == before
    raw={'a':[{'x':1}]}; result=freeze(raw)
    raw['a'][0]['x']=2
    assert result['a'][0]['x']==1
    with pytest.raises(TypeError): result['a'][0]['x']=3
    unsupported=object()
    assert freeze(unsupported) is unsupported and old['_freeze'](unsupported) is unsupported
    assert thaw([{'x':(1,)}]) == old['_thaw']([{'x':(1,)}])


@pytest.mark.parametrize('seed', range(20))
def test_graph_shared_order_and_cycle_remainder(seed):
    old_dag=original('cgkn/orchestration/execution_dag.py', {'topological_order'})['topological_order']
    old_artifact=original('cgkn/compiler/artifact_graph.py', {'_topological_order'})['_topological_order']
    from types import SimpleNamespace
    rng=random.Random(seed)
    for size in range(25):
        nodes=[f'n{i}' for i in range(size)]; rng.shuffle(nodes)
        deps={n:[m for m in nodes if rng.random()<.09] for n in nodes}
        if nodes: deps[nodes[0]]*=2  # Duplicate edges retain old behavior.
        edges=[(p,n) for n,items in deps.items() for p in items]
        obj=SimpleNamespace(by_id=deps,nodes=[SimpleNamespace(id=n,depends_on=items) for n,items in deps.items()])
        ordered=ordered_nodes(deps)
        try: expected=old_dag(obj)
        except ValueError as exc:
            assert str(exc)=='execution_dag.cycle:'+','.join(sorted(set(deps)-set(ordered)))
        else: assert tuple(ordered)==expected
        expected=old_artifact(deps,edges)
        actual=ordered_nodes(deps,fifo=True)
        assert (actual if len(actual)==len(nodes) else None)==expected


def test_sorting_policy_is_preserved():
    graph={'z':(), 'a':(), 'b':('a',)}
    assert ordered_nodes(graph)==['a','b','z']
    assert ordered_nodes(graph,fifo=True)==['a','z','b']


def test_provider_policy_equivalence(monkeypatch):
    from scripts import provider_transport as candidate
    names={'_normalize_base_url','_is_gptsapi_base_url','_is_alibaba_model_studio_base_url','_tls_verify_enabled'}
    old=original('scripts/check_connectivity.py',names)
    urls=[None,'','https://api.gptsapi.net/v1','http://gptsapi.net',
          'https://dashscope.aliyuncs.com/compatible-mode/v1','https://dashscope-intl.aliyuncs.com',
          'https://cn-test.maas.aliyuncs.com','https://dashscope.aliyuncs.com.evil.invalid',
          'https://example.org','https://[bad','not a url','//dashscope.aliyuncs.com']
    for url in urls:
        for value in (url,str(url).upper(),'  '+str(url)+'///  '):
            for name in ('_is_gptsapi_base_url','_is_alibaba_model_studio_base_url'):
                def result(call):
                    try:return ('value',call(value))
                    except Exception as exc:return ('error',type(exc).__name__,str(exc))
                assert result(old[name])==result(getattr(candidate,name))
    for raw in ('0','false','FALSE','no','off','1','yes','true','', 'unknown'):
        monkeypatch.setenv('CGKN_API_TLS_VERIFY',raw)
        assert old['_tls_verify_enabled']()==candidate.tls_verify_enabled()


@pytest.mark.parametrize('domestic', [False, True])
@pytest.mark.parametrize('fail', [False, True])
def test_post_route_single_dispatch_and_exception_equivalence(monkeypatch,domestic,fail):
    from scripts import provider_transport
    from cgkn.providers import application_network,canonical_gateway_adapter,legacy_transport
    old=original('scripts/check_connectivity.py',{'_post_json'})['_post_json']
    monkeypatch.setattr(application_network,'settings',lambda: {'enabled':True} if domestic else None)
    calls=[]
    def handler(*args,**kwargs):
        calls.append((args,kwargs))
        if fail:raise RuntimeError('fixture blocked; no fallback allowed')
        return {'reply':'same'} if domestic else ({'reply':'same'},'')
    def forbidden(*args,**kwargs):raise AssertionError('unexpected alternate route')
    monkeypatch.setattr(canonical_gateway_adapter,'post_payload',handler if domestic else forbidden)
    monkeypatch.setattr(legacy_transport,'post_json_once',forbidden if domestic else handler)
    outcomes=[]
    for call in (old,provider_transport.post_json_once):
        calls.clear()
        try:outcome=('value',call('http://127.0.0.1:1/v1/responses',{'model':'qwen'},'fake',3))
        except RuntimeError as exc:outcome=('error',type(exc).__name__,str(exc))
        outcomes.append((outcome,list(calls)))
        assert len(calls)==1
    assert outcomes[0]==outcomes[1]


@pytest.mark.parametrize('domestic', [False, True])
@pytest.mark.parametrize('tls', ['0', '1'])
@pytest.mark.parametrize('fail', [False, True])
def test_urlopener_policy_exact_equivalence(monkeypatch, domestic, tls, fail):
    from scripts import provider_transport
    from cgkn.providers import application_network
    old=original('scripts/check_connectivity.py', {'_urlopen','_tls_verify_enabled'})['_urlopen']
    monkeypatch.setenv('CGKN_API_TLS_VERIFY',tls)
    monkeypatch.setattr(application_network,'settings',lambda: {'enabled':True} if domestic else None)
    calls=[];marker=object()
    def handler(*args,**kwargs):
        context=kwargs.get('context')
        calls.append({'args':args,'timeout':kwargs.get('timeout'),
                      'tls_verify':context.verify_mode if context is not None else None})
        if fail:raise OSError('controlled socket failure')
        return marker
    def forbidden(*args,**kwargs):raise AssertionError('unexpected alternate opener')
    monkeypatch.setattr(application_network,'open_legacy',handler if domestic else forbidden)
    monkeypatch.setattr(urllib.request,'urlopen',forbidden if domestic else handler)
    outcomes=[];request=urllib.request.Request('http://127.0.0.1:1')
    for call in (old,provider_transport._urlopen):
        calls.clear()
        try:value=call(request,3)
        except OSError as exc:value=(type(exc).__name__,str(exc))
        outcomes.append((value,list(calls)))
        assert len(calls)==1
    assert outcomes[0]==outcomes[1]

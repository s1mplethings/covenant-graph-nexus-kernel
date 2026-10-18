from __future__ import annotations

import json
from pathlib import Path

from cgkn.application.learning import FileLessonStore, ProductionGenerationClient, StoreLessonReader
from cgkn.application.project_campaign import CampaignCompletionClient, MultiProjectCampaignService, campaign_matrix
from cgkn.providers import ModelRoleConfig, ProviderCompletion
from cgkn.execution import BlockExecutionRequest, BlockExecutionResult, BlockStatus, ExecutionError, ExecutionErrorCode, TaskContext
from cgkn.application.project_campaign.service import _CoreExecutor, _repair_evidence
from cgkn.providers import ProviderConnectionError
from scripts.import_historical_lessons import import_lessons


ROOT = Path(__file__).resolve().parents[3]

PYPROJECT_EXECUTOR = '''import json
def execute(v):
 lines=['[build-system]','requires = ["setuptools>=68"]','build-backend = "setuptools.build_meta"','','[project]','name = '+json.dumps(v['name']),'version = '+json.dumps(v['version']),'description = '+json.dumps(v['description']),'requires-python = '+json.dumps(v['requires_python'])]
 if v.get('console_script'):
  name,target=v['console_script'].split('=',1); lines += ['', '[project.scripts]', name+' = '+json.dumps(target)]
 return {'pyproject_toml':'\\n'.join(lines)+'\\n'}
'''

TEXT_CORE = '''from pathlib import Path
def stats(path):
 data=Path(path).read_bytes(); text=data.decode('utf-8'); return {'line_count':len(text.splitlines()),'word_count':len(text.split()),'character_count':len(text),'byte_count':len(data)}
'''
TEXT_MAIN = '''import argparse,json,sys
from .core import stats
def main(argv=None):
 p=argparse.ArgumentParser(); p.add_argument('file'); p.add_argument('--json',action='store_true'); a=p.parse_args(argv)
 try: value=stats(a.file)
 except Exception as e: print(str(e),file=sys.stderr); return 2
 print(json.dumps(value,sort_keys=True) if a.json else '\\n'.join(f'{k}: {v}' for k,v in value.items())); return 0
if __name__=='__main__': raise SystemExit(main())
'''

FLAT_CORE = '''def flatten(value,prefix=''):
 out={}
 if isinstance(value,dict):
  for k in sorted(value): out.update(flatten(value[k],f'{prefix}.{k}' if prefix else k))
 elif isinstance(value,list):
  for i,item in enumerate(value): out.update(flatten(item,f'{prefix}.{i}'))
 else: out[prefix]=value
 return out
'''
FLAT_MAIN = '''import argparse,json,sys
from pathlib import Path
from .core import flatten
def main(argv=None):
 p=argparse.ArgumentParser(); p.add_argument('input'); p.add_argument('output'); a=p.parse_args(argv)
 try:
  value=json.loads(Path(a.input).read_text());
  if not isinstance(value,dict): raise ValueError('top-level JSON must be object')
  Path(a.output).write_text(json.dumps(flatten(value),sort_keys=True,separators=(',',':'))+'\\n')
 except Exception as e: print(str(e),file=sys.stderr); return 2
 return 0
if __name__=='__main__': raise SystemExit(main())
'''


class Provider:
    def __init__(self): self.calls=[]
    def complete(self, **kwargs):
        schema=kwargs['schema_name']; self.calls.append(schema); prompt=json.loads(kwargs['user'])
        if schema=='capability_candidate_patch':
            before=prompt['current_sources']['executor.py']; actions=[{'action':'patch_file','path':'executor.py','find':before,'replace':PYPROJECT_EXECUTOR}]
        elif schema=='campaign_text_stats_cli_actions':
            actions=[{'action':'write_file','path':'text_stats/__init__.py','content':'from .core import stats\n'},{'action':'write_file','path':'text_stats/__main__.py','content':TEXT_MAIN},{'action':'write_file','path':'text_stats/core.py','content':TEXT_CORE}]
        elif schema=='campaign_json_flatten_cli_actions':
            actions=[{'action':'write_file','path':'json_flatten/__init__.py','content':'from .core import flatten\n'},{'action':'write_file','path':'json_flatten/__main__.py','content':FLAT_MAIN},{'action':'write_file','path':'json_flatten/core.py','content':FLAT_CORE}]
        elif schema=='campaign_existing_repo_path_bug_actions':
            current=prompt['current_sources']['pathfix/core.py']; fixed="def normalize_relative(value):\n    parts=[p for p in value.replace('\\\\','/').split('/') if p not in ('','.')]\n    return '/'.join(parts)\n"; actions=[{'action':'patch_file','path':'pathfix/core.py','find':current,'replace':fixed}]
        else: raise AssertionError(schema)
        body={'schema_version':'1.0','node_id':prompt['node_id'],'summary':'fake','actions':actions,'expected_outputs':['PASS'],'confidence':1.0,'needs_escalation':False,'escalation_reason':''}
        return ProviderCompletion(json.dumps(body),'grok','fake-'+str(len(self.calls)),{'input_tokens':10,'output_tokens':10,'total_tokens':20},1)


def service(tmp_path):
    learning=tmp_path/'learning'; import_lessons(ROOT,learning,tmp_path/'import.json'); store=FileLessonStore(learning)
    provider=Provider(); generation=ProductionGenerationClient(provider,StoreLessonReader(store),store=store,max_provider_calls=36)
    svc=MultiProjectCampaignService(ROOT,tmp_path/'campaign',generation,ModelRoleConfig('worker','grok',60,8000,0,'low'),campaign_matrix())
    return svc,provider


def test_matrix_freezes_fifteen_distinct_cases_and_holdout_hashes():
    rows=campaign_matrix()
    assert len(rows)==15 and len({row.project_id for row in rows})==15
    assert {row.wave for row in rows}=={'A','B','C'}
    assert sum(row.existing_repo for row in rows)==3
    assert all(row.case_hash.startswith('sha256:') and row.hidden_hash.startswith('sha256:') for row in rows)


def test_campaign_harness_disables_unrelated_host_pytest_plugins():
    from cgkn.application.project_campaign import service as campaign_service
    source=Path(campaign_service.__file__).read_text(encoding='utf-8')
    assert source.count('PYTEST_DISABLE_PLUGIN_AUTOLOAD') >= 2


def test_campaign_provider_ledger_rejects_route_switch_and_counts_usage():
    provider=Provider(); ledger=CampaignCompletionClient(provider)
    config=ModelRoleConfig('worker','grok',60,8000,0,'low')
    ledger.complete(system='s',user=json.dumps({'node_id':'n'}),schema_name='campaign_text_stats_cli_actions',schema={},config=config)
    assert ledger.snapshot()=={'calls':1,'input_tokens':10,'output_tokens':10,'cost_in_usd_ticks':0}
    bad=ModelRoleConfig('worker','qwen',60,8000,0,'low')
    try: ledger.complete(system='s',user='{}',schema_name='x',schema={},config=bad)
    except RuntimeError as exc: assert 'CRITICAL_PROVIDER_ROUTE_CHANGED' in str(exc)
    else: raise AssertionError('route switch was accepted')


def test_hidden_failure_evidence_is_withheld_from_provider():
    result=BlockExecutionResult('p','r','a','hidden','x',BlockStatus.FAILED,error=ExecutionError(ExecutionErrorCode.EXECUTION_ERROR,'secret hidden assertion'))
    evidence=_repair_evidence('hidden',result)
    assert evidence['details']=='WITHHELD_BY_POLICY'
    assert 'secret' not in json.dumps(evidence)


def test_provider_transport_failure_preserves_failure_domain_and_bounds_repair(tmp_path):
    class ClosedTransport:
        config=None
        def complete(self,**kwargs):
            self.config=kwargs['config']
            raise ProviderConnectionError('PROVIDER_TRANSPORT_FAILURE','remote closed',outcome_unknown=False)
    transport=ClosedTransport(); store=FileLessonStore(tmp_path/'lessons')
    generation=ProductionGenerationClient(transport,StoreLessonReader(store),store=store,max_provider_calls=4)
    case=campaign_matrix()[0]; workspace=tmp_path/'workspace'; workspace.mkdir()
    executor=_CoreExecutor(case,workspace,generation,ModelRoleConfig('worker','grok',180,7000,0,'medium'))
    request=BlockExecutionRequest('p','r','a','core-generate','c',executor.descriptor.executor_ref,TaskContext('repair',node_config={'failure_evidence':{'failure_code':'X'}}))
    result=executor.execute(request)
    assert result.error.details['failure_domain']=='PROVIDER_TRANSPORT_FAILURE'
    assert result.retryable is True
    assert transport.config.max_output_tokens==4000 and transport.config.reasoning_effort=='low'


def test_fake_projects_grow_then_reuse_and_patch_existing_repo(tmp_path):
    svc,provider=service(tmp_path); by_id={row.project_id:row for row in campaign_matrix()}
    first=svc.run_project(by_id['text_stats_cli']); second=svc.run_project(by_id['json_flatten_cli']); existing=svc.run_project(by_id['existing_repo_path_bug'])
    assert first['final_status']==second['final_status']==existing['final_status']=='PASS'
    assert first['grown_capabilities']==['project.python.pyproject.render@1']
    assert second['reused_capabilities']==['project.python.pyproject.render@1']
    assert first['applied_lesson_ids']
    assert existing['repository_change']['unrelated_edits']==[]
    assert existing['repository_change']['interface_preservation']=='PASS'
    revision=tmp_path/'campaign/projects/text_stats_cli/candidates/revision-001/revision.json'
    assert json.loads(revision.read_text())['immutable'] is True
    assert len(provider.calls)==4

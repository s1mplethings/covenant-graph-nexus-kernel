"""Current configured public CLI -> real core -> fake loopback gateway.

Historical controller tests remain unchanged. This covers their original budget
and false-pass invariants using the required canonical ProjectSession profile.
"""
import hashlib,json,sys
import pytest
from tests.providers.test_domestic_repair import isolated,fake_gateway,admit


@pytest.mark.parametrize('admission',['budgeted','none','exhausted'])
def test_current_profile_formal_cli_budget_and_false_pass(fake_gateway,isolated,monkeypatch,tmp_path,admission):
 from scripts import run_codex_conversation_generation as cli
 project=tmp_path/'controller';(project/'.cgkn').mkdir(parents=True)
 candidate=tmp_path/'candidate'
 consumer=tmp_path/'consumer.py'
 consumer.write_text("raise SystemExit('NO_VALID_DECLARATION_NO_ACCEPTANCE')\n")
 goal='Create an offline tested sample'
 profile={'kind':'CGKNProjectSessionProfile','schema_version':'1.0','project_id':'budget-fixture','run_id':'one',
  'workspace':str(candidate),'intent':{'overall_goal':goal,'user_visible_outcomes':['tested module'],
   'constraints':['offline fixture'],'forbidden_operations':['external network'],
   'delivery_expectations':['validated module'],'major_acceptance_categories':['correctness']},
  'requirements':{'R':{'must':True,'checker_keys':['independent']}},
  'independent_consumer':{'path':str(consumer),'sha256':hashlib.sha256(consumer.read_bytes()).hexdigest(),
   'public_fields':['value']},'checkpoint_interval':1}
 from tests.session_authority_support import authorization
 profile['execution_authorization']=authorization('budget-fixture',
  ('code.implement@1','project.acceptance.external@1'),goal)
 (project/'.cgkn/project-session.json').write_text(json.dumps(profile))
 if admission=='budgeted':admit(monkeypatch,tmp_path)
 elif admission=='exhausted':admit(monkeypatch,tmp_path,CGKN_PROVIDER_MAX_API_CALLS='0')
 output=tmp_path/'result.json'
 job=tmp_path/'job.json'
 monkeypatch.setattr(sys,'argv',['formal','--project-root',str(project),'--goal',goal,'--result',str(output),
  '--generation-job-state',str(job),'--generation-job-id','fixture-job','--generation-attempt-id','fixture-attempt'])
 from cgkn.providers.gateway_client import GatewayCompletionError
 from scripts.provider_api_budget import ProviderBudgetExhausted
 expected=GatewayCompletionError if admission=='budgeted' else ProviderBudgetExhausted
 with pytest.raises(expected,match='schema_validation_failed' if admission=='budgeted' else 'PROVIDER_BUDGET_EXHAUSTED'):
  cli.main()
 posts=fake_gateway[0]
 assert 1<=len(posts)<=5 if admission=='budgeted' else len(posts)==0
 ledger=json.loads((tmp_path/'budget.json').read_text()) if (tmp_path/'budget.json').exists() else {'calls':[]}
 assert len(ledger['calls'])==len(posts)
 assert [r['request_identity'] for r in ledger['calls']]==['sha256:'+h for h in fake_gateway[1]['wire_sha256']]
 assert not output.exists()  # No fabricated normal result after rejected transport/schema.
 terminal=json.loads(job.read_text())
 assert terminal['state']=='FAILED' and terminal['terminal_reason']==expected.__name__
 assert terminal['job_id']=='fixture-job' and terminal['attempt_id']=='fixture-attempt'
 assert not (candidate/'delivery_manifest.json').exists()
 assert all(r['model'] in ('qwen','deepseek') for r in posts)

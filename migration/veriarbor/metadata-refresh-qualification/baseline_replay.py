import importlib.util,sys,pytest
from cgkn.agent.project_loop import ProjectSession
spec=importlib.util.spec_from_file_location('cgkn.agent._metadata_before',sys.argv[1])
module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
ProjectSession._refresh_milestone_subjects=module.ProjectSession._refresh_milestone_subjects
ProjectSession._reconcile_completed_checks=module.ProjectSession._reconcile_completed_checks
raise SystemExit(pytest.main(['tests/agent/test_metadata_refresh_without_verdict.py','-q','-p','no:cacheprovider']))

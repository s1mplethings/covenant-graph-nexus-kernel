def test_executor_and_worker_compatibility_names_keep_one_owner():
    from cgkn.execution.contracts import ExecutorDescriptor
    from cgkn.executors.protocol import ExecutorDescriptor as CompatibilityDescriptor
    from cgkn.execution.file_actions import BoundedFileActions, ProposalError
    from cgkn.executors.llm import BoundedFileActions as CompatibilityActions
    from cgkn.executors.llm import ProposalError as CompatibilityError
    from cgkn.agent.project_loop import AgentProjectLoop, ProjectSession

    assert CompatibilityDescriptor is ExecutorDescriptor
    assert CompatibilityActions is BoundedFileActions
    assert CompatibilityError is ProposalError
    assert AgentProjectLoop is ProjectSession


def test_effect_scope_and_admission_compatibility_names_keep_one_owner():
    from veriarbor import execution_effects
    from cgkn.execution import node_effects
    from cgkn.agent import project_agent
    from cgkn.orchestration import admission
    from cgkn.artifacts.hash import file_hash
    from cgkn.runtime.node_authority import file_hash as CompatibilityFileHash

    for name in ('execution_scope', 'require_provider_context', 'guard_effect',
                 'perform_scoped_effect', 'governed_provider_open'):
        assert getattr(node_effects, name) is getattr(execution_effects, name)
    for name in ('ProjectProposal', 'AdmissionPolicy', 'AdmissionResult', 'admit_proposal'):
        assert getattr(project_agent, name) is getattr(admission, name)
    assert CompatibilityFileHash is file_hash

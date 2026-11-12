"""Promote the qualified controller and remove both old controller bodies."""
import ast
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]


def replace(path,name,source):
    text=path.read_text(encoding='utf-8');lines=text.splitlines(keepends=True)
    node=next(n for n in ast.parse(text).body if isinstance(n,ast.FunctionDef) and n.name==name)
    path.write_text(''.join(lines[:node.lineno-1])+source+'\n'+''.join(lines[node.end_lineno:]),encoding='utf-8',newline='\n')


if __name__=='__main__':
    engine=(ROOT/'artifacts/execution-authority-convergence/qualified-candidate-source.txt').read_text(encoding='utf-8')
    engine=engine[engine.index('def _run_action_loop'):]
    replace(ROOT/'scripts/agent_conversation_loop.py','run_agent_loop',engine+'''

def run_agent_loop(
    *,
    session_path: str | pathlib.Path,
    project_dir: str | pathlib.Path,
    model: str = "gpt-5.4-nano",
    timeout: int = 120,
    max_turns: int = 12,
    agent: AgentCallable | None = None,
) -> dict[str, Any]:
    session_file = pathlib.Path(session_path).resolve()
    project = pathlib.Path(project_dir).resolve()
    executor = local_agent_actions.LocalAgentActionExecutor(project)
    return _run_action_loop(
        session_file=session_file, project=project, model=model, timeout=timeout,
        max_turns=max_turns, agent=agent or call_default_agent, execute=executor.execute,
    )
''')
    replace(ROOT/'scripts/dynamic_pipeline_runner.py','_run_agent_turn','''def _run_agent_turn(
    *,
    session_file: pathlib.Path,
    executor: local_agent_actions.LocalAgentActionExecutor,
    manifest: dict[str, Any],
    step: dict[str, Any],
    model: str,
    timeout: int,
    max_turns: int,
    agent: AgentCallable | None,
) -> dict[str, Any]:
    role = _role_by_id(manifest, str(step.get("role", "")))
    allowed_actions = {str(item) for item in step.get("allowed_actions", [])}

    def prepare_action(action):
        if str(action.get("type") or action.get("action") or "") != "package_project":
            return action
        audit = pre_package_audit(session_file, executor.project_dir, manifest)
        limits = list(action.get("known_limits", []) if isinstance(action.get("known_limits"), list) else [])
        limits.extend(audit.get("known_limits", []))
        return {**action, "known_limits": limits}

    return agent_conversation_loop._run_action_loop(
        session_file=session_file, project=executor.project_dir, model=model,
        timeout=timeout, max_turns=max_turns,
        agent=agent if agent is not None else lambda events, model, timeout: _call_step_agent(events, model, timeout, role=role, step=step),
        execute=lambda action: _execute_manifest_action(executor, action, allowed_actions),
        event_context={"role": role.get("id"), "step_id": step.get("id")},
        read_events=lambda: _history_for_step(session_file, _system_prompt(role, step, manifest)),
        prepare_action=prepare_action,
    )
''')

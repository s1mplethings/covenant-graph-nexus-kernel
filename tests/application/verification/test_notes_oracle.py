from pathlib import Path

from cgkn.application.requirements import NOTES_DEPENDENCY_POLICY, compile_local_json_notes
from cgkn.application.verification import OracleExecutor, OraclePlanCompiler


def _project(root: Path) -> None:
    package = root / "notes"; tests = root / "tests"
    package.mkdir(); tests.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "__main__.py").write_text('''import argparse, json
from pathlib import Path
p=argparse.ArgumentParser(); s=p.add_subparsers(dest="command", required=True)
a=s.add_parser("add"); a.add_argument("text"); a.add_argument("--tag")
l=s.add_parser("list"); l.add_argument("--tag")
sh=s.add_parser("show"); sh.add_argument("id", type=int)
d=s.add_parser("delete"); d.add_argument("id", type=int)
args=p.parse_args(); path=Path("notes.json")
state=json.loads(path.read_text()) if path.exists() else {"next_id":1,"notes":[]}
def line(n): return f"{n['id']}\\t{n['text']}\\t{n.get('tag') or ''}"
try:
    if args.command == "add":
        note={"id":state["next_id"],"text":args.text,"tag":args.tag}; state["next_id"]+=1; state["notes"].append(note); path.write_text(json.dumps(state)); print(note["id"])
    elif args.command == "list":
        for note in sorted(state["notes"], key=lambda n:n["id"]):
            if args.tag is None or note.get("tag") == args.tag: print(line(note))
    elif args.command == "show": print(line(next(n for n in state["notes"] if n["id"] == args.id)))
    else:
        next(n for n in state["notes"] if n["id"] == args.id); state["notes"]=[n for n in state["notes"] if n["id"] != args.id]; path.write_text(json.dumps(state)); print(f"deleted {args.id}")
except (StopIteration, ValueError):
    p.error("note not found")
''', encoding="utf-8")
    (root / "README.md").write_text("python -m notes add list show delete --tag", encoding="utf-8")
    (tests / "test_smoke.py").write_text("def test_smoke(): assert True\n", encoding="utf-8")


def test_notes_oracle_is_complete_and_stateful_groups_are_isolated(tmp_path: Path) -> None:
    _project(tmp_path)
    compilation = compile_local_json_notes()
    plan = OraclePlanCompiler().compile_notes(compilation.obligations, NOTES_DEPENDENCY_POLICY)
    assert len(plan.source_obligation_ids) == 17 and len(plan.specs) == 7
    evidence = OracleExecutor((NOTES_DEPENDENCY_POLICY,)).execute_plan(plan, tmp_path)
    assert {item.status.value for item in evidence} == {"PASS"}
    assert not (tmp_path / "notes.json").exists()


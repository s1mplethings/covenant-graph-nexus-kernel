from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from cgkn.application.requirements import ObligationDAGService
from cgkn.providers import ModelRoleConfig, ProviderCompletion


MODEL = '''from dataclasses import dataclass
@dataclass(frozen=True)
class Note:
    id: int
    text: str
    tag: str | None = None
'''

STORE = '''import json
from pathlib import Path
def load(path):
    path=Path(path)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"next_id":1,"notes":[]}
def save(path, state):
    Path(path).write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
'''

SERVICE = '''from .store import load, save
def add_note(path, text, tag=None):
    state=load(path); note={"id":state["next_id"],"text":text,"tag":tag}; state["next_id"] += 1; state["notes"].append(note); save(path,state); return note
def list_notes(path, tag=None):
    notes=sorted(load(path)["notes"], key=lambda n:n["id"]); return [n for n in notes if tag is None or n.get("tag") == tag]
def show_note(path, note_id):
    return next((n for n in load(path)["notes"] if n["id"] == note_id), None)
def delete_note(path, note_id):
    state=load(path); note=next((n for n in state["notes"] if n["id"] == note_id), None)
    if note is None: return False
    state["notes"]=[n for n in state["notes"] if n["id"] != note_id]; save(path,state); return True
'''

CLI = '''import argparse
from pathlib import Path
from .service import add_note, list_notes, show_note, delete_note
def line(n): return f"{n['id']}\\t{n['text']}\\t{n.get('tag') or ''}"
def main(argv=None):
    p=argparse.ArgumentParser(); subs=p.add_subparsers(dest="command",required=True)
    add=subs.add_parser("add"); add.add_argument("text"); add.add_argument("--tag")
    listing=subs.add_parser("list"); listing.add_argument("--tag")
    show=subs.add_parser("show"); show.add_argument("id",type=int)
    delete=subs.add_parser("delete"); delete.add_argument("id",type=int)
    args=p.parse_args(argv); path=Path("notes.json")
    if args.command == "add": print(add_note(path,args.text,args.tag)["id"])
    elif args.command == "list":
        for note in list_notes(path,args.tag): print(line(note))
    elif args.command == "show":
        note=show_note(path,args.id)
        if note is None: p.error("note not found")
        print(line(note))
    else:
        if not delete_note(path,args.id): p.error("note not found")
        print(f"deleted {args.id}")
    return 0
if __name__ == "__main__": raise SystemExit(main())
'''

README = """# Notes\n\nUse `python -m notes add TEXT [--tag TAG]`, `python -m notes list [--tag TAG]`, `python -m notes show ID`, and `python -m notes delete ID`.\n"""


class NotesProvider:
    def __init__(self, *, cli_defect: bool = False, pretty_output: bool = False, core_defect: str = "") -> None:
        self.calls: list[dict[str, Any]] = []
        self.cli_defect = cli_defect
        self.pretty_output = pretty_output
        self.core_defect = core_defect
        self.counts: dict[str, int] = {}

    def complete(self, *, system: str, user: str, schema_name: str, schema: Mapping[str, Any], config: Any) -> ProviderCompletion:
        payload=json.loads(user); node=payload["node_id"]; self.calls.append(payload); self.counts[node]=self.counts.get(node,0)+1
        if node == "WU-CORE":
            service = SERVICE
            if self.counts[node] == 1 and self.core_defect == "id_reuse":
                service = service.replace('state["next_id"] += 1', 'state["next_id"] = len(state["notes"]) + 1')
            if self.counts[node] == 1 and self.core_defect == "tag_filter":
                service = service.replace('n.get("tag") == tag', 'True')
            actions=[{"action":"write_file","path":"notes/__init__.py","content":""}, {"action":"write_file","path":"notes/model.py","content":MODEL}, {"action":"write_file","path":"notes/store.py","content":STORE}, {"action":"write_file","path":"notes/service.py","content":service}]
        elif node == "WU-CLI":
            cli=CLI
            if self.cli_defect and self.counts[node] == 1:
                cli=cli.replace('show.add_argument("id",type=int)', 'show.add_argument("--id",type=int,required=True)')
            if self.pretty_output and self.counts[node] == 1:
                cli=cli.replace('print(add_note(path,args.text,args.tag)["id"])', 'print(f"Note added with ID: {add_note(path,args.text,args.tag)[\'id\']}")')
            actions=[{"action":"write_file","path":"notes/__main__.py","content":cli}]
        else:
            actions=[{"action":"write_file","path":"README.md","content":README}]
        value={"schema_version":"1.0","node_id":node,"summary":"implemented","actions":actions,"expected_outputs":["contract satisfied"],"confidence":1.0,"needs_escalation":False,"escalation_reason":""}
        return ProviderCompletion(json.dumps(value),config.model,f"fake-{len(self.calls)}",{"prompt_tokens":10,"completion_tokens":10,"total_tokens":20})


def run(tmp_path: Path, provider: NotesProvider):
    return ObligationDAGService(Path.cwd(),provider,ModelRoleConfig("worker","fake-worker")).run_notes(tmp_path/"workspace",tmp_path/"runs")


def test_notes_fake_provider_passes_canonical_oracle_tests_and_hidden_acceptance(tmp_path: Path) -> None:
    provider=NotesProvider(); result=run(tmp_path,provider)
    assert result.status == "PASS"
    assert result.public_pytest == result.oracle_status == result.hidden_acceptance == "PASS"
    assert provider.counts == {"WU-CORE":1,"WU-CLI":1,"WU-DOCS":1}
    cli_prompt=next(x for x in provider.calls if x["node_id"] == "WU-CLI")
    assert len(cli_prompt["dependency_interface_contracts"]) == 4


def test_notes_show_optional_id_is_rejected_before_commit_then_corrected(tmp_path: Path) -> None:
    provider=NotesProvider(cli_defect=True); result=run(tmp_path,provider)
    assert result.status == "PASS" and provider.counts["WU-CLI"] == 2
    assert any(any(row["failure_class"] == "POSITIONAL_TO_OPTIONAL" for row in call.get("interface_contract_evidence",[])) for call in provider.calls)
    assert 'show.add_argument("id"' in (tmp_path/"workspace"/"notes/__main__.py").read_text(encoding="utf-8")


def test_notes_id_reuse_and_tag_filter_defects_repair_core_only(tmp_path: Path) -> None:
    for index, defect in enumerate(("id_reuse","tag_filter")):
        provider=NotesProvider(core_defect=defect); result=run(tmp_path/f"case-{index}",provider)
        assert result.status == "PASS" and result.repair_owners == ("WU-CORE",), result.as_dict()
        assert provider.counts == {"WU-CORE":2,"WU-CLI":1,"WU-DOCS":1}
        assert {"WU-CLI","WU-DOCS","CONTRACT-TESTS"} <= set(result.reused_work_units)


def test_notes_pretty_output_is_owned_and_repaired_by_cli_only(tmp_path: Path) -> None:
    provider=NotesProvider(pretty_output=True); result=run(tmp_path,provider)
    assert result.status == "PASS" and result.repair_owners == ("WU-CLI",), result.as_dict()
    assert provider.counts == {"WU-CORE":1,"WU-CLI":2,"WU-DOCS":1}
    assert {"WU-CORE","WU-DOCS","CONTRACT-TESTS"} <= set(result.reused_work_units)

from cgkn.application.interfaces import InterfaceContractCompiler, extract_interfaces, guard_interfaces
from cgkn.application.requirements import compile_local_json_notes


SERVICE = '''def add_note(path, text, tag=None): pass
def list_notes(path, tag=None): pass
def show_note(path, note_id): pass
def delete_note(path, note_id): pass
'''

CLI = '''import argparse
p = argparse.ArgumentParser()
subs = p.add_subparsers(dest="command")
add = subs.add_parser("add")
add.add_argument("text")
add.add_argument("--tag")
listing = subs.add_parser("list")
listing.add_argument("--tag")
show = subs.add_parser("show")
show.add_argument("id")
delete = subs.add_parser("delete")
delete.add_argument("id")
'''


def contracts():
    return InterfaceContractCompiler().compile_notes(compile_local_json_notes().obligations)


def sources(cli: str = CLI, service: str = SERVICE):
    return {"notes/__init__.py": "", "notes/service.py": service, "notes/__main__.py": cli}


def test_notes_interface_contracts_round_trip_and_pass_exact_shape() -> None:
    compiled = contracts()
    assert len(compiled.contracts) == 6
    assert compiled.from_dict(compiled.as_dict()).as_dict() == compiled.as_dict()
    assert {item.status.value for item in guard_interfaces(compiled, extract_interfaces(sources()))} == {"PASS"}


def test_notes_guard_rejects_renamed_command_optional_id_and_signature_drift() -> None:
    renamed = CLI.replace('add_parser("delete")', 'add_parser("remove")')
    evidence = guard_interfaces(contracts(), extract_interfaces(sources(renamed)))
    assert next(item for item in evidence if item.contract_id == "INTERFACE-NOTES-CLI-001").failure_class in {"MISSING_SUBCOMMAND", "EXTRA_FORBIDDEN_SUBCOMMAND"}
    optional_id = CLI.replace('show.add_argument("id")', 'show.add_argument("--id")')
    cli_evidence = next(item for item in guard_interfaces(contracts(), extract_interfaces(sources(optional_id))) if item.contract_id == "INTERFACE-NOTES-CLI-001")
    assert cli_evidence.status.value == "FAIL" and cli_evidence.failure_class == "POSITIONAL_TO_OPTIONAL"
    drift = SERVICE.replace("def show_note(path, note_id)", "def show_note(note_id, path)")
    fn_evidence = next(item for item in guard_interfaces(contracts(), extract_interfaces(sources(service=drift))) if item.contract_id == "INTERFACE-NOTES-SHOW-001")
    assert fn_evidence.status.value == "FAIL" and fn_evidence.failure_class == "SIGNATURE_MISMATCH"


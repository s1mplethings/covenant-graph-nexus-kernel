from __future__ import annotations

from .contracts import ProjectCase


def _arg(dest: str, *, option: str = "", nargs=None, action: str = "STORE", required: bool = False) -> dict:
    return {"argument_id": dest, "kind": "OPTION" if option else "POSITIONAL", "flags": [option] if option else [dest],
            "dest": dest, "value_type": "INTEGER" if dest == "id" else ("PATH" if dest in {"file", "input", "output", "root", "left", "right", "zip", "store"} else "STRING"),
            "required": required, "default": False if action == "STORE_TRUE" else None,
            "nargs": nargs, "repeatable": action == "APPEND", "action": action, "choices": [], "metavar": ""}


def _explicit_cli_contract(project_id: str, package: str) -> dict:
    """Explicit migration authority. Display command strings are deliberately not parsed."""
    shapes = {
        "text_stats_cli": ([ _arg("file"), _arg("json", option="--json", action="STORE_TRUE")],),
        "json_flatten_cli": ([_arg("input"), _arg("output")],),
        "directory_diff_cli": ([_arg("left"), _arg("right"), _arg("json", option="--json", action="STORE_TRUE")],),
        "markdown_toc_cli": ([_arg("input")],),
        "ini_merge_cli": ([_arg("output"), _arg("inputs", nargs="+")],),
        "duplicate_finder_cli": ([_arg("root"), _arg("exclude", option="--exclude"), _arg("json", option="--json", action="STORE_TRUE")],),
        "zip_manifest_cli": ([_arg("zip"), _arg("json", option="--json", action="STORE_TRUE")],),
        "env_audit_cli": ([_arg("file"), _arg("json", option="--json", action="STORE_TRUE")],),
        "csv_column_profile_cli": ([_arg("file"), _arg("json", option="--json", action="STORE_TRUE")],),
        "rename_plan_cli": ([_arg("root"), _arg("pattern", option="--pattern", required=True), _arg("template", option="--template", required=True), _arg("json", option="--json", action="STORE_TRUE")],),
        "log_summary_library": ([_arg("file"), _arg("json", option="--json", action="STORE_TRUE")],),
        "line_select_cli": ([_arg("input"), _arg("query"), _arg("ignore_case", option="--ignore-case", action="STORE_TRUE"), _arg("json", option="--json", action="STORE_TRUE")],),
        "mapping_overlay_library": ([_arg("output"), _arg("inputs", nargs="+")],),
    }
    persistent = {
        "todo_json_cli": {"add": [_arg("text"), _arg("tag", option="--tag")], "list": [_arg("tag", option="--tag")], "done": [_arg("id")], "delete": [_arg("id")]},
        "notes_search_cli": {"add": [_arg("text"), _arg("tag", option="--tag")], "search": [_arg("query")], "tag": [_arg("tag")], "show": [_arg("id")], "delete": [_arg("id")]},
        "bookmark_store_cli": {"add": [_arg("url"), _arg("title", option="--title"), _arg("tag", option="--tag")], "list": [_arg("tag", option="--tag")], "show": [_arg("id")], "remove": [_arg("id")]},
    }
    global_options = [_arg("store", option="--store", required=True)] if project_id in persistent else []
    commands = []
    definitions = persistent.get(project_id)
    if definitions:
        for name, args in definitions.items():
            mapping = {item["dest"]: f'$args.{item["dest"]}' for item in global_options + args}
            commands.append({"command_id": name, "subcommand_name": name, "help_text": name, "positionals": [item for item in args if item["kind"] == "POSITIONAL"],
                             "options": [item for item in args if item["kind"] == "OPTION"], "dispatch": {"domain_module": f"{package}.core", "callable_name": "execute", "operation": name, "parameter_mapping": mapping},
                             "output": {"mode": "COMMAND_OUTCOME", "json_flag_dest": "", "stable_json": True, "trailing_newline": True},
                             "error_mappings": [{"exception_name": "ProjectError", "exit_code": 2, "stream": "stderr", "message_policy": "EXCEPTION_MESSAGE"}], "obligation_refs": []})
    else:
        args = list(shapes[project_id][0])
        parameter_names = {"env_audit_cli": {"file": "path"}, "csv_column_profile_cli": {"file": "path"}}
        mapping = {parameter_names.get(project_id, {}).get(item["dest"], item["dest"]): f'$args.{item["dest"]}' for item in args}
        operations = {"duplicate_finder_cli": "find_duplicates", "env_audit_cli": "audit", "csv_column_profile_cli": "profile", "rename_plan_cli": "plan"}
        commands.append({"command_id": "main", "subcommand_name": "", "help_text": "", "positionals": [item for item in args if item["kind"] == "POSITIONAL"],
                         "options": [item for item in args if item["kind"] == "OPTION"], "dispatch": {"domain_module": f"{package}.core", "callable_name": "cli_execute" if project_id in {"log_summary_library", "mapping_overlay_library"} else "execute", "operation": operations.get(project_id, "merge" if project_id == "mapping_overlay_library" else project_id.removesuffix("_cli")), "parameter_mapping": mapping},
                         "output": {"mode": "COMMAND_OUTCOME", "json_flag_dest": "json" if any(item["dest"] == "json" for item in args) else "", "stable_json": True, "trailing_newline": True,
                                    "value_path": "groups" if project_id == "duplicate_finder_cli" else "",
                                    "error_when_false": "ok" if project_id == "rename_plan_cli" else "",
                                    "error_message": "collision" if project_id == "rename_plan_cli" else "domain operation failed"},
                         "error_mappings": [{"exception_name": "ProjectError", "exit_code": 2, "stream": "stderr", "message_policy": "EXCEPTION_MESSAGE"}], "obligation_refs": []})
    return {"program_name": package, "module_name": f"{package}.__main__", "entrypoint": f"python -m {package}", "commands": commands,
            "global_options": global_options, "help_contract": {"exit_code": 0, "business_file_side_effects": "FORBIDDEN"},
            "error_mappings": [{"exception_name": "ProjectError", "exit_code": 2, "stream": "stderr", "message_policy": "EXCEPTION_MESSAGE"}],
            "output_policy": {"stable_json": True}, "side_effect_policy": {"help": "FORBIDDEN"},
            "domain_contract": {"callable_name": "execute", "error_type": "ProjectError", "outcome_kinds": ["text", "json", "json_lines", "silent"],
                                "accept_legacy_raw": project_id in {"duplicate_finder_cli", "env_audit_cli", "csv_column_profile_cli", "rename_plan_cli"}}, "plan_version": "1.0"}


def _cli(
    project_id: str,
    wave: str,
    project_type: str,
    package: str,
    goal: str,
    commands: list[str],
    behavior: dict,
    public: list[dict],
    hidden: list[dict],
    *,
    capabilities: tuple[str, ...] = ("project.python.pyproject.render@1",),
) -> ProjectCase:
    return ProjectCase(
        project_id, wave, project_type, package, goal,
        {"entrypoint": f"python -m {package}", "commands": commands, "stderr_errors": True, "no_aliases": True},
        {**behavior, "runtime": "PYTHON_STDLIB_ONLY", "network": "FORBIDDEN", "shell": "FORBIDDEN", "deterministic": True},
        (f"{package}/__init__.py", f"{package}/__main__.py", f"{package}/core.py"),
        tuple(public), tuple(hidden), capabilities, cli_contract=_explicit_cli_contract(project_id, package),
    )


def campaign_matrix() -> tuple[ProjectCase, ...]:
    cases: list[ProjectCase] = [
        _cli("text_stats_cli", "A", "GREENFIELD_CLI", "text_stats", "Report deterministic UTF-8 text statistics.", ["FILE", "FILE --json"],
             {"fields":["line_count","word_count","character_count","byte_count"],"line_rule":"splitlines count; empty file is zero; a final missing newline still counts its line","word_rule":"Unicode whitespace split","character_rule":"decoded Unicode code points","byte_rule":"raw UTF-8 bytes"},
             [{"files":{"sample.txt":"one two\nthree"},"steps":[{"argv":["sample.txt","--json"],"code":0,"json":{"line_count":2,"word_count":3,"character_count":13,"byte_count":13}}]}],
             [{"files":{"empty.txt":""},"steps":[{"argv":["empty.txt","--json"],"code":0,"json":{"line_count":0,"word_count":0,"character_count":0,"byte_count":0}}]},{"steps":[{"argv":["missing.txt"],"code":2,"stderr_nonempty":True}]}]),
        _cli("json_flatten_cli", "A", "GREENFIELD_CLI", "json_flatten", "Flatten nested JSON objects and arrays to dotted keys.", ["INPUT OUTPUT"],
             {"object_keys":"lexical order","arrays":"numeric dotted segments","top_level":"object only","output":"canonical JSON object with sorted keys and trailing newline"},
             [{"files":{"in.json":"{\"z\":1,\"user\":{\"name\":\"Ada\"},\"items\":[{\"name\":\"x\"}]}"},"steps":[{"argv":["in.json","out.json"],"code":0,"file_json":{"path":"out.json","value":{"items.0.name":"x","user.name":"Ada","z":1}}}]}],
             [{"files":{"bad.json":"not json"},"steps":[{"argv":["bad.json","out.json"],"code":2,"stderr_nonempty":True}]},{"files":{"scalar.json":"7"},"steps":[{"argv":["scalar.json","out.json"],"code":2,"stderr_nonempty":True}]}]),
        _cli("todo_json_cli", "A", "PERSISTENT_CRUD", "todo_json", "Maintain a deterministic local JSON todo store.", ["--store FILE add TEXT [--tag TAG]","--store FILE list [--tag TAG]","--store FILE done ID","--store FILE delete ID"],
             {"store_schema":{"next_id":"monotonic integer","items":"ordered objects id,text,tag,done"},"list":"stable ID order and JSON lines","missing_id":"nonzero","invalid_store":"nonzero; never overwrite"},
             [{"steps":[{"argv":["--store","todos.json","add","alpha","--tag","x"],"code":0,"stdout_contains":"1"},{"argv":["--store","todos.json","add","beta"],"code":0,"stdout_contains":"2"},{"argv":["--store","todos.json","done","1"],"code":0},{"argv":["--store","todos.json","list"],"code":0,"stdout_contains_all":["alpha","beta"]}]}],
             [{"files":{"bad.json":"[]"},"steps":[{"argv":["--store","bad.json","list"],"code":2,"stderr_nonempty":True}]},{"steps":[{"argv":["--store","todos.json","delete","999"],"code":2,"stderr_nonempty":True}]}]),
        _cli("directory_diff_cli", "A", "FILESYSTEM", "directory_diff", "Compare two directory trees with SHA-256.", ["LEFT RIGHT","LEFT RIGHT --json"],
             {"paths":"relative POSIX","symlink_directories":"never traverse","result":{"added":"right only sorted","removed":"left only sorted","changed":"same path different SHA-256 sorted","unchanged_count":"integer"}},
             [{"dirs":["left","right"],"files":{"left/a.txt":"a","left/old.txt":"old","right/a.txt":"b","right/new.txt":"new"},"steps":[{"argv":["left","right","--json"],"code":0,"json":{"added":["new.txt"],"removed":["old.txt"],"changed":["a.txt"],"unchanged_count":0}}]}],
             [{"dirs":["left/n","right/n"],"files":{"left/n/x":"same","right/n/x":"same"},"steps":[{"argv":["left","right","--json"],"code":0,"json":{"added":[],"removed":[],"changed":[],"unchanged_count":1}}]}]),
        _cli("markdown_toc_cli", "A", "GREENFIELD_CLI", "markdown_toc", "Generate a stable Markdown table of contents.", ["INPUT"],
             {"headings":"ATX # through ###### outside fenced code","toc":"two spaces per nesting level relative to first heading","slug":"lowercase alnum/hyphen; spaces and punctuation collapse","duplicates":"second and later append -1, -2"},
             [{"files":{"doc.md":"# Title\n## Intro Here\n```\n# Hidden\n```\n## Intro Here\n"},"steps":[{"argv":["doc.md"],"code":0,"stdout_contains_all":["[Title](#title)","[Intro Here](#intro-here)","(#intro-here-1)"],"stdout_not_contains":"Hidden"}]}],
             [{"files":{"doc.md":"### Deep! Heading\n#### Child\n"},"steps":[{"argv":["doc.md"],"code":0,"stdout_contains_all":["deep-heading","child"]}]}]),
        _cli("ini_merge_cli", "A", "GREENFIELD_CLI", "ini_merge", "Merge INI files with later values overriding earlier files.", ["OUTPUT INPUT1 INPUT2 ..."],
             {"merge":"later files override earlier values","ordering":"DEFAULT keys lexical then sections lexical and keys lexical","default_section":"supported","invalid_ini":"nonzero without output"},
             [{"files":{"a.ini":"[DEFAULT]\nx=1\n[app]\na=old\n","b.ini":"[app]\na=new\nb=2\n"},"steps":[{"argv":["out.ini","a.ini","b.ini"],"code":0,"file_contains_all":{"path":"out.ini","values":["x = 1","a = new","b = 2"]}}]}],
             [{"files":{"bad.ini":"[broken\n"},"steps":[{"argv":["out.ini","bad.ini"],"code":2,"stderr_nonempty":True}]}], capabilities=("project.python.pyproject.render@1","project.readme.cli_examples.render@1")),
        _cli("duplicate_finder_cli", "B", "FILESYSTEM", "duplicate_finder", "Find duplicate files by SHA-256.", ["ROOT [--exclude GLOB] [--json]"],
             {"groups":"only hashes with at least two files","paths":"relative POSIX sorted","groups_order":"hash lexical","symlinks":"ignore","output_self":"ignore when output redirected or named duplicates.json"},
             [{"dirs":["data/sub"],"files":{"data/a":"same","data/sub/b":"same","data/c":"other"},"steps":[{"argv":["data","--json"],"code":0,"json_list_length":1,"stdout_contains_all":["a","sub/b"]}]}],
             [{"dirs":["data"],"files":{"data/a.tmp":"x","data/b.tmp":"x"},"steps":[{"argv":["data","--exclude","*.tmp","--json"],"code":0,"json":[]}]}]),
        _cli("zip_manifest_cli", "B", "ARCHIVE", "zip_manifest", "Inspect a ZIP without extracting and flag unsafe entry paths.", ["ZIP [--json]"],
             {"fields":["path","size","compressed_size","crc","dangerous"],"dangerous":"../ traversal, absolute POSIX path, or drive-letter path","ordering":"entry path lexical","extract":"forbidden"},
             [{"zip":{"path":"sample.zip","entries":{"safe/a.txt":"abc","../escape.txt":"x","/abs.txt":"y","C:/drive.txt":"z"}},"steps":[{"argv":["sample.zip","--json"],"code":0,"json_list_length":4,"stdout_contains_all":["dangerous","../escape.txt","C:/drive.txt"]}]}],
             [{"files":{"bad.zip":"not zip"},"steps":[{"argv":["bad.zip","--json"],"code":2,"stderr_nonempty":True}]}], capabilities=("project.python.pyproject.render@1","project.python.license.render@1")),
        _cli("env_audit_cli", "B", "SECURITY_CLI", "env_audit", "Audit a dotenv-style file without exposing values or reading process environment.", ["FILE [--json]"],
             {"line":"NAME=VALUE; blank and # comment ignored","output_fields":["name","empty","suspected_secret","redacted"],"redacted":"always *** for nonempty; empty remains empty","secret_rule":"name contains KEY,TOKEN,SECRET,PASSWORD,AUTH case-insensitive","invalid_line":"nonzero and no value echo"},
             [{"files":{"app.env":"USER=ada\nAPI_TOKEN=abcd\nEMPTY=\n"},"steps":[{"argv":["app.env","--json"],"code":0,"stdout_contains_all":["API_TOKEN","***","suspected_secret"],"stdout_not_contains":"abcd"}]}],
             [{"files":{"bad.env":"GOOD=x\nnot valid\n"},"steps":[{"argv":["bad.env","--json"],"code":2,"stderr_nonempty":True,"stderr_not_contains":"x"}]}]),
        _cli("notes_search_cli", "B", "PERSISTENT_CRUD", "notes_search", "Maintain and search deterministic local JSON notes.", ["--store FILE add TEXT [--tag TAG]","--store FILE search QUERY","--store FILE tag TAG","--store FILE show ID","--store FILE delete ID"],
             {"ids":"monotonic","search":"case-insensitive substring","tag":"exact case-sensitive match","ordering":"ID ascending","store":"validated JSON object; invalid is error"},
             [{"steps":[{"argv":["--store","notes.json","add","Hello World","--tag","Work"],"code":0},{"argv":["--store","notes.json","add","second","--tag","work"],"code":0},{"argv":["--store","notes.json","search","hello"],"code":0,"stdout_contains":"Hello World"},{"argv":["--store","notes.json","tag","Work"],"code":0,"stdout_contains":"Hello World","stdout_not_contains":"second"}]}],
             [{"steps":[{"argv":["--store","notes.json","show","999"],"code":2,"stderr_nonempty":True}]}]),
    ]

    cases.extend(_existing_cases())
    cases.extend([
        _cli("rename_plan_cli", "C", "GREENFIELD_CLI", "rename_plan", "Plan deterministic batch renames without modifying files.", ["ROOT --pattern GLOB --template TEMPLATE [--json]"],
             {"dry_run":"never rename or write target files","index":"1-based over lexical relative POSIX source paths","template":"must contain exactly {index}; optional {stem} and {suffix}","collision":"detect duplicate destinations and existing non-source destinations","symlinks":"ignore"},
             [{"dirs":["data"],"files":{"data/b.txt":"b","data/a.txt":"a"},"steps":[{"argv":["data","--pattern","*.txt","--template","file-{index}.txt","--json"],"code":0,"stdout_contains_all":["a.txt","file-1.txt","b.txt","file-2.txt"],"files_unchanged":["data/a.txt","data/b.txt"]}]}],
             [{"dirs":["data"],"files":{"data/a.txt":"a","data/file-1.txt":"occupied"},"steps":[{"argv":["data","--pattern","a.txt","--template","file-{index}.txt","--json"],"code":2,"stderr_contains":"collision"}]},{"dirs":["data"],"steps":[{"argv":["data","--pattern","*.txt","--template","bad.txt"],"code":2,"stderr_nonempty":True}]}]),
        _cli("log_summary_library", "C", "LIBRARY", "log_summary", "Provide summarize(lines) plus a CLI for deterministic log summaries.", ["FILE [--json]"],
             {"public_api":"log_summary.summarize(lines)","format":"ISO timestamp whitespace LEVEL whitespace message","levels":"counts sorted lexically","timestamps":"first and last valid in input order","malformed":"count and tolerate","return":{"level_counts":"object","first_timestamp":"string or null","last_timestamp":"string or null","malformed_count":"integer"}},
             [{"files":{"app.log":"2026-01-01T00:00:00Z INFO start\nBAD\n2026-01-01T00:01:00Z ERROR fail\n"},"steps":[{"argv":["app.log","--json"],"code":0,"json":{"level_counts":{"ERROR":1,"INFO":1},"first_timestamp":"2026-01-01T00:00:00Z","last_timestamp":"2026-01-01T00:01:00Z","malformed_count":1}}]}],
             [{"python":"from log_summary import summarize; import json; print(json.dumps(summarize([]),sort_keys=True))","code":0,"json":{"level_counts":{},"first_timestamp":None,"last_timestamp":None,"malformed_count":0}}], capabilities=("project.python.pyproject.render@1","project.python.license.render@1")),
    ])
    return tuple(cases)


def _existing_cases() -> list[ProjectCase]:
    common_pyproject = '[build-system]\nrequires=["setuptools>=68"]\nbuild-backend="setuptools.build_meta"\n[project]\nname="fixture-cli"\nversion="0.1.0"\nrequires-python=">=3.11"\n'
    b05_files = {
        "fixture_cli/__init__.py": "from .core import render\n",
        "fixture_cli/core.py": "def render(value):\n    return f'VALUE: {value}'\n",
        "fixture_cli/__main__.py": "import argparse\nfrom .core import render\np=argparse.ArgumentParser(); p.add_argument('value'); a=p.parse_args(); print(render(a.value))\n",
        "pyproject.toml": common_pyproject,
        "README.md": "# fixture-cli\n",
        "tests/test_existing.py": "from fixture_cli import render\ndef test_render(): assert render('x')=='VALUE: x'\n",
    }
    b06_files = {
        "pathfix/__init__.py": "from .core import normalize_relative\n",
        "pathfix/core.py": "def normalize_relative(value):\n    return value.replace('/', '\\\\')\n",
        "pathfix/__main__.py": "import argparse\nfrom .core import normalize_relative\np=argparse.ArgumentParser(); p.add_argument('path'); a=p.parse_args(); print(normalize_relative(a.path))\n",
        "pyproject.toml": common_pyproject.replace("fixture-cli", "pathfix"),
        "README.md": "# pathfix\n",
        "tests/test_existing.py": "from pathfix import normalize_relative\ndef test_simple(): assert normalize_relative('a')=='a'\n",
    }
    c01_files = {
        "refactor_cli/__init__.py": "from .main import build_parser, main\n",
        "refactor_cli/main.py": "import argparse\ndef build_parser():\n p=argparse.ArgumentParser(); p.add_argument('name'); return p\ndef main(argv=None):\n a=build_parser().parse_args(argv); print('hello '+a.name); return 0\n",
        "refactor_cli/__main__.py": "from .main import main\nraise SystemExit(main())\n",
        "pyproject.toml": common_pyproject.replace("fixture-cli", "refactor-cli"),
        "README.md": "# refactor-cli\n",
        "tests/test_existing.py": "from refactor_cli import build_parser, main\ndef test_import(): assert build_parser().parse_args(['Ada']).name=='Ada'\n",
    }
    return [
        ProjectCase("existing_repo_json_feature", "B", "EXISTING_REPO_FEATURE", "fixture_cli", "Add --json without changing render(value) or text output.", {"entrypoint":"python -m fixture_cli VALUE [--json]","public_api":"fixture_cli.render(value) unchanged"}, {"json":"{\"value\": input, \"rendered\": render(input)} canonical JSON","text":"unchanged VALUE: value"}, ("fixture_cli/__main__.py",), ({"steps":[{"argv":["x"],"code":0,"stdout_contains":"VALUE: x"},{"argv":["x","--json"],"code":0,"json":{"rendered":"VALUE: x","value":"x"}}]},), ({"python":"from fixture_cli import render; assert render('z')=='VALUE: z'","code":0},), (), b05_files, ("fixture_cli/__main__.py",), True),
        ProjectCase("existing_repo_path_bug", "B", "EXISTING_REPO_BUG", "pathfix", "Repair cross-platform relative path normalization.", {"entrypoint":"python -m pathfix PATH","public_api":"pathfix.normalize_relative(value) unchanged"}, {"normalization":"both backslash and slash become POSIX slash; remove repeated separators and leading ./; do not resolve filesystem"}, ("pathfix/core.py",), ({"steps":[{"argv":["a\\b/c"],"code":0,"stdout_exact":"a/b/c"}]},), ({"python":"from pathfix import normalize_relative; assert normalize_relative(r'.\\a\\\\b')=='a/b'","code":0},), (), b06_files, ("pathfix/core.py",), True),
        ProjectCase("existing_repo_parser_refactor", "C", "EXISTING_REPO_REFACTOR", "refactor_cli", "Extract parser helper to parser.py while preserving public imports and behavior.", {"entrypoint":"python -m refactor_cli NAME","public_api":"from refactor_cli import build_parser, main remains valid"}, {"refactor":"build_parser implementation lives in refactor_cli/parser.py and main imports it","behavior":"hello NAME unchanged"}, ("refactor_cli/__init__.py","refactor_cli/main.py","refactor_cli/parser.py"), ({"steps":[{"argv":["Ada"],"code":0,"stdout_exact":"hello Ada"}]},), ({"python":"from refactor_cli import build_parser, main; assert build_parser().__class__.__name__=='ArgumentParser'","code":0},), (), c01_files, ("refactor_cli/__init__.py","refactor_cli/main.py","refactor_cli/parser.py"), True),
    ]

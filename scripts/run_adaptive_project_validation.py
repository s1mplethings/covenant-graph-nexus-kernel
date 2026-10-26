from __future__ import annotations

"""Compatibility name for ITER-028 fixtures and the canonical supervised runner.

The former implementation started the provider-api-lab Gateway whose upstream
adapter had a fixed 90-second timeout. Executing this module now delegates to
the supervised connector data plane; it cannot reopen the legacy route.
"""

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cgkn.application.project_campaign.contracts import ProjectCase
from cgkn.application.project_campaign.matrix import _explicit_cli_contract


def cases() -> tuple[ProjectCase, ...]:
    return (
        ProjectCase("line_select_cli", "A", "GREENFIELD_CLI", "line_select", "Select matching UTF-8 lines.",
                    {"entrypoint":"python -m line_select","commands":["INPUT QUERY [--ignore-case] [--json]"]},
                    {"operation":"line_select","text":"LINE_NUMBER:TEXT","json":"objects line,text","missing_or_invalid_utf8":"exit 2","empty":"success"},
                    ("line_select/__init__.py","line_select/__main__.py","line_select/core.py"),
                    ({"files":{"x.txt":"Alpha\nbeta\nalpha\n"},"steps":[{"argv":["x.txt","alpha","--ignore-case","--json"],"code":0,"json":[{"line":1,"text":"Alpha"},{"line":3,"text":"alpha"}]}]},),
                    ({"steps":[{"argv":["missing.txt","x"],"code":2,"stderr_nonempty":True}]},), cli_contract=_explicit_cli_contract("line_select_cli","line_select")),
        ProjectCase("bookmark_store_cli", "A", "PERSISTENT_CRUD", "bookmark_store", "Maintain a JSON bookmark store.",
                    {"entrypoint":"python -m bookmark_store","commands":["--store FILE add URL [--title TITLE] [--tag TAG]","--store FILE list [--tag TAG]","--store FILE show ID","--store FILE remove ID"]},
                    {"store":"JSON object next_id/items","ids":"monotonic","order":"ID","tag":"exact","invalid":"exit 2 no overwrite"},
                    ("bookmark_store/__init__.py","bookmark_store/__main__.py","bookmark_store/core.py"),
                    ({"steps":[{"argv":["--store","b.json","add","https://a","--title","A","--tag","x"],"code":0,"stdout_contains":"1"},{"argv":["--store","b.json","list","--tag","x"],"code":0,"stdout_contains":"https://a"},{"argv":["--store","b.json","show","1"],"code":0,"stdout_contains":"https://a"}]},),
                    ({"steps":[{"argv":["--store","b.json","show","999"],"code":2,"stderr_nonempty":True}]},), cli_contract=_explicit_cli_contract("bookmark_store_cli","bookmark_store")),
        ProjectCase("mapping_overlay_library", "A", "LIBRARY", "mapping_overlay", "Merge mapping layers without mutation.",
                    {"entrypoint":"python -m mapping_overlay","commands":["OUTPUT INPUT1 INPUT2 ..."],"public_api":"mapping_overlay.merge_layers(layers)"},
                    {"public_api":"mapping_overlay.merge_layers(layers)","objects":"recursive","arrays_scalars":"replace","inputs":"not mutated","output":"sorted JSON"},
                    ("mapping_overlay/__init__.py","mapping_overlay/__main__.py","mapping_overlay/core.py"),
                    ({"files":{"a.json":"{\"x\":{\"a\":1}}","b.json":"{\"x\":{\"b\":2}}"},"steps":[{"argv":["out.json","a.json","b.json"],"code":0,"file_json":{"path":"out.json","value":{"x":{"a":1,"b":2}}}}]},),
                    ({"python":"from mapping_overlay import merge_layers; a={'x':{'a':1}}; r=merge_layers([a,{'x':{'b':2}}]); assert a=={'x':{'a':1}} and r=={'x':{'a':1,'b':2}}","code":0},), cli_contract=_explicit_cli_contract("mapping_overlay_library","mapping_overlay")),
    )


def main() -> int:
    from scripts.run_supervised_multitype_validation import main as supervised_main
    return supervised_main()


if __name__ == "__main__":
    raise SystemExit(main())

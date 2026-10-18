from __future__ import annotations

import json
from pathlib import Path

from cgkn.application.learning import FileLessonStore, ProductionGenerationClient, StoreLessonReader
from cgkn.application.project_production import AutonomousProjectProductionService
from cgkn.providers import ModelRoleConfig, ProviderCompletion
from scripts.import_historical_lessons import import_lessons


ROOT = Path(__file__).resolve().parents[3]


CAPABILITY_SOURCE = '''import json\n\ndef execute(value):\n    lines = [\n        '[build-system]',\n        'requires = ["setuptools>=68"]',\n        'build-backend = "setuptools.build_meta"',\n        '',\n        '[project]',\n        'name = ' + json.dumps(value['name']),\n        'version = ' + json.dumps(value['version']),\n        'description = ' + json.dumps(value['description']),\n        'requires-python = ' + json.dumps(value['requires_python']),\n    ]\n    script = value.get('console_script')\n    if script:\n        name, target = script.split('=', 1)\n        lines.extend(['', '[project.scripts]', name + ' = ' + json.dumps(target)])\n    return {'pyproject_toml': '\\n'.join(lines) + '\\n'}\n'''


CORE_SOURCE = r'''from __future__ import annotations
import fnmatch, hashlib, json, os
from pathlib import Path

def _validate_root(root):
    root=Path(root)
    if not root.exists(): raise ValueError("ROOT does not exist")
    if not root.is_dir(): raise ValueError("ROOT is not a directory")
    return root.resolve()

def _excluded(relative, patterns):
    return relative==".git" or relative.startswith(".git/") or relative=="__pycache__" or "/__pycache__/" in "/"+relative+"/" or any(fnmatch.fnmatch(relative,p) for p in patterns)

def scan_data(root, manifest, excludes=()):
    root=_validate_root(root); manifest=Path(manifest).resolve(); rows=[]
    for base, dirs, files in os.walk(root, followlinks=False):
        base_path=Path(base)
        dirs[:]=sorted(d for d in dirs if not (base_path/d).is_symlink() and not _excluded((base_path/d).relative_to(root).as_posix(), excludes))
        for name in sorted(files):
            path=base_path/name
            if path.is_symlink() or path.resolve()==manifest: continue
            rel=path.relative_to(root).as_posix()
            if _excluded(rel, excludes): continue
            data=path.read_bytes(); rows.append({"path":rel,"size":len(data),"sha256":hashlib.sha256(data).hexdigest()})
    rows.sort(key=lambda x:x["path"])
    return {"version":1,"algorithm":"sha256","files":rows}

def write_manifest(root, manifest, excludes=()):
    path=Path(manifest); path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(scan_data(root,path,excludes),sort_keys=True,separators=(",",":"))+"\n",encoding="utf-8")

def load_manifest(path):
    path=Path(path)
    if not path.is_file(): raise ValueError("Manifest does not exist")
    try: doc=json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc: raise ValueError("Manifest is invalid JSON") from exc
    if not isinstance(doc,dict) or doc.get("version")!=1 or doc.get("algorithm")!="sha256" or not isinstance(doc.get("files"),list): raise ValueError("Manifest schema is invalid")
    for row in doc["files"]:
        if not isinstance(row,dict) or set(row)!={"path","size","sha256"} or not isinstance(row["path"],str) or not isinstance(row["size"],int) or not isinstance(row["sha256"],str): raise ValueError("Manifest schema is invalid")
    return doc

def verify_data(root, manifest):
    expected=load_manifest(manifest); actual=scan_data(root,manifest)
    left={x["path"]:x for x in expected["files"]}; right={x["path"]:x for x in actual["files"]}
    return {"changed":sorted(p for p in left.keys()&right.keys() if left[p]!=right[p]),"missing":sorted(left.keys()-right.keys()),"extra":sorted(right.keys()-left.keys())}

def summary(path):
    doc=load_manifest(path); return {"algorithm":doc["algorithm"],"file_count":len(doc["files"]),"total_size":sum(x["size"] for x in doc["files"])}
'''


MAIN_SOURCE = r'''import argparse, json, sys
from .core import load_manifest, scan_data, summary, verify_data, write_manifest

def parser():
    p=argparse.ArgumentParser(prog="folder_manifest"); sub=p.add_subparsers(dest="command",required=True)
    scan=sub.add_parser("scan"); scan.add_argument("root"); scan.add_argument("manifest"); scan.add_argument("--exclude",action="append",default=[])
    verify=sub.add_parser("verify"); verify.add_argument("root"); verify.add_argument("manifest")
    show=sub.add_parser("show"); show.add_argument("manifest")
    return p

def main(argv=None):
    try:
        args=parser().parse_args(argv)
        if args.command=="scan": write_manifest(args.root,args.manifest,args.exclude); print("manifest written"); return 0
        if args.command=="verify":
            diff=verify_data(args.root,args.manifest)
            if any(diff.values()): print(json.dumps(diff,sort_keys=True)); return 1
            print("verification successful"); return 0
        print(json.dumps(summary(args.manifest),sort_keys=True)); return 0
    except Exception as exc: print(str(exc),file=sys.stderr); return 2

if __name__=="__main__": raise SystemExit(main())
'''


class ScriptedProvider:
    def __init__(self, *, broken_first_core=False):
        self.calls = []
        self.broken_first_core = broken_first_core

    def complete(self, **kwargs):
        self.calls.append(kwargs["schema_name"])
        prompt=json.loads(kwargs["user"]); schema=kwargs["schema_name"]
        if schema=="capability_candidate_patch":
            before=prompt["current_sources"]["executor.py"]
            actions=[{"action":"patch_file","path":"executor.py","find":before,"replace":CAPABILITY_SOURCE}]
        elif schema=="folder_manifest_core_actions":
            core = "def broken(:\n" if self.broken_first_core and self.calls.count(schema)==1 else CORE_SOURCE
            actions=[{"action":"write_file","path":"folder_manifest/__init__.py","content":"__version__ = '0.1.0'\n"},{"action":"write_file","path":"folder_manifest/__main__.py","content":MAIN_SOURCE},{"action":"write_file","path":"folder_manifest/core.py","content":core}]
        else: raise AssertionError(schema)
        body={"schema_version":"1.0","node_id":prompt["node_id"],"summary":"scripted candidate","actions":actions,"expected_outputs":["contract pass"],"confidence":1.0,"needs_escalation":False,"escalation_reason":""}
        return ProviderCompletion(json.dumps(body),"grok","fake-"+str(len(self.calls)),{"total_tokens":10},1)


def service(tmp_path, provider):
    learning=tmp_path/"learning-artifacts"; import_lessons(ROOT,learning,tmp_path/"import.json")
    store=FileLessonStore(learning)
    generation=ProductionGenerationClient(provider,StoreLessonReader(store),store=store)
    return AutonomousProjectProductionService(ROOT,tmp_path/"production",generation,ModelRoleConfig("worker","grok",60,8000,0,"low"))


def test_fake_missing_capability_growth_resume_package_and_reuse(tmp_path):
    provider=ScriptedProvider(); result=service(tmp_path,provider).run_folder_manifest()
    assert result.status=="PASS"
    assert provider.calls==["folder_manifest_core_actions","capability_candidate_patch"]
    assert result.receipt["whole_replans"]==0 and result.receipt["manual_edits"]==0
    assert "project-core-generate" in result.receipt["reused_nodes"]
    assert result.receipt["capability_reuse"]["growth_calls"]==0
    assert Path(result.package_path).is_file()


def test_fake_candidate_defect_uses_one_bounded_repair(tmp_path):
    provider=ScriptedProvider(broken_first_core=True); result=service(tmp_path,provider).run_folder_manifest()
    assert result.status=="PASS" and result.receipt["repair_rounds"]==1
    assert provider.calls.count("folder_manifest_core_actions")==2


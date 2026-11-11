"""Repository-wide static evidence; unresolved dynamic calls are never deletion proof."""
import ast
import json
from pathlib import Path
import re
import subprocess

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'artifacts/substrate-replacement-v2'
GROUPS={
 'A_network':r'provider|transport|gateway|stream|sse|retry|http|socket',
 'B_agent':r'agent|worker|action|permission|scope|conversation',
 'C_concurrency':r'dag|graph|queue|thread|process|lock|cancel|timeout|scheduler',
 'D_storage':r'store|cache|checkpoint|atomic|jsonl|ledger|persist|immutable|freeze|thaw',
 'E_knowledge':r'knowledge|retriev|index|token|context|similar|snapshot',
 'F_validation':r'valid|schema|test|oracle|accept|sandbox|evidence|check',
 'G_observability':r'log|trace|metric|usage|audit|duration|identity',
 'H_toolchain':r'cli|config|environment|install|plugin|mcp|argparse|lint',
}


def main():
    files=subprocess.check_output(['git','ls-files','--cached','--others','--exclude-standard','-z'],cwd=ROOT).decode().split('\0')
    modules=[]; all_functions=[]; dynamic=[]
    for rel in sorted(set(files)):
        p=ROOT/rel
        if not rel.endswith('.py') or not p.is_file() or rel.startswith(('.service_', '.api_lab_', 'experiments/substrate_migration', 'experiments/execution_dedup')):continue
        try:tree=ast.parse(p.read_text(encoding='utf-8-sig'))
        except (SyntaxError,UnicodeError):continue
        imports=[];calls=[];functions=[]
        for node in ast.walk(tree):
            if isinstance(node,ast.Import):imports.extend(a.name for a in node.names)
            elif isinstance(node,ast.ImportFrom):imports.append('.'*node.level+(node.module or ''))
            elif isinstance(node,ast.Call):
                name=ast.unparse(node.func)
                calls.append({'line':node.lineno,'target':name})
                if any(x in name for x in ('getattr','import_module','entry_points','register','add_parser','add_argument')):
                    dynamic.append({'file':rel,'line':node.lineno,'expression':ast.unparse(node)[:450]})
            elif isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):
                row={'file':rel,'function':node.name,'line':node.lineno,'lines':node.end_lineno-node.lineno+1,
                     'groups':[k for k,v in GROUPS.items() if re.search(v,rel+' '+node.name,re.I)]}
                functions.append(row);all_functions.append(row)
        role='TEST_ONLY' if rel.startswith(('tests/','benchmarks/')) else 'EXPERIMENTAL' if rel.startswith('experiments/') else 'REQUIRES_ENTRYPOINT_REVIEW'
        modules.append({'file':rel,'imports':imports,'calls':calls,'functions':functions,'classification':role,
                        'cli':any(isinstance(n,ast.If) and '__name__' in ast.unparse(n.test) for n in tree.body)})
    (OUT/'static-callgraph.json').write_text(json.dumps({'scope':'all tracked/nonignored Python excluding copied service scratch and this experiment; syntactic callsites, not complete points-to analysis', 'modules':modules,'dynamic_entrypoints':dynamic},indent=2))
    (OUT/'capability-scan.json').write_text(json.dumps({k:[r for r in all_functions if k in r['groups']] for k in GROUPS},indent=2))
    print(json.dumps({'modules':len(modules),'functions':len(all_functions),'calls':sum(len(m['calls']) for m in modules),'dynamic_sites':len(dynamic),'category_hits':{k:sum(k in r['groups'] for r in all_functions) for k in GROUPS}}))


if __name__=='__main__':main()

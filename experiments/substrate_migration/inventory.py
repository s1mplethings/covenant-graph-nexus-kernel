"""Reproducible static import/call inventory; dynamic edges remain explicit limits."""
import ast
import json
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'artifacts/substrate-migration'
rows = []
edges = {}
for folder in ('cgkn', 'scripts', 'src', 'tests'):
    for path in sorted((ROOT / folder).rglob('*.py')):
        source = path.read_text(encoding='utf-8-sig')
        tree = ast.parse(source)
        imports = []
        module = path.relative_to(ROOT).with_suffix('').as_posix().replace('/', '.')
        if module.endswith('.__init__'):
            module = module[:-9]
        package = module if path.name == '__init__.py' else module.rpartition('.')[0]
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(n.name for n in node.names)
            elif isinstance(node, ast.ImportFrom):
                name = '.' * node.level + (node.module or '')
                try:
                    name = importlib.util.resolve_name(name, package)
                except (ImportError, ValueError):
                    pass
                imports.append(name)
                imports.extend(name + '.' + item.name for item in node.names)
        edges[module] = set(imports)
        rows.append({'path': path.relative_to(ROOT).as_posix(), 'lines': len(source.splitlines()),
                     'imports': sorted(set(imports)),
                     'call_sites': sum(isinstance(n, ast.Call) for n in ast.walk(tree))})


def closure(seeds):
    visited = set()
    pending = list(seeds)
    while pending:
        module = pending.pop()
        if module in visited or module not in edges:
            continue
        visited.add(module)
        for target in edges[module]:
            while target and target not in edges:
                target = target.rpartition('.')[0]
            if target:
                pending.append(target)
    return visited


canonical = closure(['cgkn.agent.project_loop', 'cgkn.runtime.dag_runner',
                     'cgkn.executors.factory', 'cgkn.providers.domestic_gateway'])
compatibility = closure(['scripts.codex_conversation', 'scripts.run_codex_conversation_generation',
                         'scripts.run_local_pipeline', 'scripts.provider_jobs'])
tests = closure([name for name in edges if name.startswith('tests.')])
for row in rows:
    module = row['path'][:-3].replace('/', '.')
    if module.endswith('.__init__'):
        module = module[:-9]
    if module.startswith('tests.'):
        status = 'TEST_ONLY'
    elif module in canonical:
        status = 'CANONICAL'
    elif module in compatibility:
        status = 'COMPATIBILITY'
    elif module in tests:
        status = 'TEST_ONLY'
    else:
        status = 'EXPERIMENTAL'
    row['static_classification'] = status
    row['classification_limit'] = 'Static seed reachability only; dynamic/plugin/script entrypoints require review. Not deletion authority.'
OUT.mkdir(parents=True, exist_ok=True)
(OUT / 'static-inventory.json').write_text(json.dumps(rows, indent=2), encoding='utf-8')
print(json.dumps({'modules': len(rows), 'lines': sum(r['lines'] for r in rows),
                  'import_edges': sum(len(r['imports']) for r in rows),
                  'call_sites': sum(r['call_sites'] for r in rows)}))

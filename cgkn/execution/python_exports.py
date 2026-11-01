"""Read-only structural Python export observations, not business acceptance.

Direct declarations are verified statically. Dynamic/imported bindings require a
registered runtime checker and remain unresolved here; candidate code is never
executed by this helper. The caller supplies the frozen public declaration.
"""
import ast
import hashlib
from pathlib import Path


def python_export_declarations(path, exports):
    path = Path(path)
    raw = path.read_bytes() if path.is_file() else b''
    observation = {'path':str(path), 'sha256':hashlib.sha256(raw).hexdigest(),
                   'scope':'static declared export surface only', 'exports':[]}
    try:
        tree = ast.parse(raw.decode('utf-8-sig'))
    except (ValueError, SyntaxError, UnicodeError) as exc:
        return {'passed':False, 'observed':{**observation,'parse_error':str(exc)}}
    bound = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            bound[node.name] = 'function' if not node.decorator_list else 'UNRESOLVED'
        elif isinstance(node, ast.ClassDef):
            bound[node.name] = 'class' if not node.decorator_list else 'UNRESOLVED'
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):bound[target.id] = 'constant'
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:bound[alias.asname or alias.name.split('.')[0]] = 'UNRESOLVED'
        elif isinstance(node, ast.Delete):
            for target in node.targets:
                if isinstance(target, ast.Name):bound.pop(target.id, None)
        else:
            # A control-flow binding can replace a previously declared name.
            for child in ast.walk(node):
                if isinstance(child, (ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)):
                    bound[child.name]='UNRESOLVED'
                elif isinstance(child, ast.Name) and isinstance(child.ctx,(ast.Store,ast.Del)):
                    bound[child.id]='UNRESOLVED'
    passed = bool(raw)
    for item in exports:
        name,kind=item.get('name'),item.get('kind')
        if not isinstance(name,str) or not name or kind not in {'class','exception','function','constant'}:
            raise ValueError('explicit valid public export declaration required')
        actual=bound.get(name,'MISSING')
        expected='class' if kind=='exception' else kind
        ok=actual==expected
        observation['exports'].append({'name':name,'declared_kind':kind,'observed_binding':actual,'passed':ok})
        passed=passed and ok
    return {'passed':passed,'observed':observation}

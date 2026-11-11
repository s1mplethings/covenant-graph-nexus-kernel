"""Trusted declarative file predicates installed in the existing ExecutorRegistry."""
import hashlib
import json
from pathlib import Path
from jsonschema import Draft202012Validator
from cgkn.execution.deliverables import FileDeliverableChecker


def install_file_checks(registry, root, document):
    if document.get('schema_version')!='1.0' or document.get('kind')!='CGKNFileCheckerBindings':
        raise ValueError('explicit versioned checker bindings required')
    specifications=document.get('checks')
    if not isinstance(specifications,dict) or not specifications:raise ValueError('registered checks required')
    checks={}
    for name,spec in specifications.items():
        if not isinstance(name,str) or not name or not isinstance(spec,dict):raise ValueError('invalid checker specification')
        if spec.get('kind') not in {'sha256','utf8_equals','json_schema'}:raise ValueError('unsupported deterministic predicate')
        if spec['kind']=='json_schema':Draft202012Validator.check_schema(spec['schema'])
        def check(base,contract,spec=dict(spec)):
            path=spec['path']
            if path not in contract['target_scope']:raise ValueError('checker object outside declared scope')
            target=(Path(base)/path).resolve()
            if Path(base).resolve() not in target.parents:raise ValueError('checker object escapes root')
            if not target.is_file():return {'passed':False,'observed':{'missing':path}}
            raw=target.read_bytes();sha=hashlib.sha256(raw).hexdigest()
            if spec['kind']=='sha256':passed=sha==spec['expected']
            elif spec['kind']=='utf8_equals':passed=raw.decode('utf-8')==spec['expected']
            else:
                try:passed=Draft202012Validator(spec['schema']).is_valid(json.loads(raw))
                except (ValueError,UnicodeError):passed=False
            return {'passed':passed,'observed':{'path':path,'sha256':sha,'predicate':spec['kind']},
                    'artifact_verdicts':{path:passed}}
        checks[name]=check
    registry.register(FileDeliverableChecker(root,checks))
    return {'files':'deliverable.files@1'}

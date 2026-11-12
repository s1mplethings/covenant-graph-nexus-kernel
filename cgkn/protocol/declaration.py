"""Declaration-only lexical admission and mechanical public-contract binding.

No extraction rule chooses between different product intents. Rejected raw
text remains in exchange receipts; corrections are calls within one decision.
"""
from __future__ import annotations
import copy
import json
from pathlib import PurePosixPath
from .normalization import ContractError, _object, _finite_float, digest

PREFIXES = ('Here is the JSON:', 'Here is the declaration:', 'Declaration:')
SUFFIXES = ('End of declaration.', 'End of JSON.')


def extract_declaration(text):
    if not isinstance(text, str):
        raise ContractError('DECLARATION_TEXT_REQUIRED')
    original_hash = digest(text.encode())
    clean = text.strip().lstrip('\ufeff').strip()
    rules = []
    if clean != text:
        rules.append('BOM_OR_WHITESPACE')
    for prefix in PREFIXES:
        if clean.startswith(prefix):
            clean = clean[len(prefix):].strip()
            rules.append('EXPLICIT_PREFIX')
            break
    for suffix in SUFFIXES:
        if clean.endswith(suffix):
            clean = clean[:-len(suffix)].strip()
            rules.append('FIXED_SUFFIX')
            break
    if clean.startswith('```'):
        lines = clean.splitlines()
        if len(lines) >= 3 and lines[0] in ('```', '```json') and lines[-1] == '```':
            clean = '\n'.join(lines[1:-1]).strip()
            rules.append('JSON_FENCE')
    def nonfinite(value):
        raise ContractError('NONFINITE_NUMBER')
    decoder = json.JSONDecoder(object_pairs_hook=_object, parse_float=_finite_float, parse_constant=nonfinite)
    values = []
    offset = 0
    try:
        while offset < len(clean):
            value, end = decoder.raw_decode(clean, offset)
            values.append(value)
            offset = end
            while offset < len(clean) and clean[offset].isspace():
                offset += 1
    except RecursionError as exc:
        raise ContractError('JSON_PARSER_RESOURCE_LIMIT', details={'failure_domain':'RESOURCE_LIMIT', 'raw_sha256':original_hash}) from exc
    except (json.JSONDecodeError, ContractError) as exc:
        details = {'raw_sha256': original_hash, 'top_level_value_count': len(values),
                   'object_hashes': [digest(v) for v in values],
                   'position': getattr(exc, 'pos', offset),
                   'parse_error': getattr(exc, 'msg', str(exc)),
                   'declaration_correction': True,
                   'instruction': 'Return exactly one complete declaration object. Do not add prose or a second value. Preserve the original goal; do not invent missing business semantics.'}
        raise ContractError('DECLARATION_JSON_REJECTED', repair_class='R5',
                            vector_key='syntax_errors', details=details) from exc
    if not values or not all(isinstance(v, dict) for v in values):
        raise ContractError('DECLARATION_OBJECT_REQUIRED', repair_class='R5',
                            details={'declaration_correction': True, 'top_level_value_count': len(values)})
    hashes = [digest(v) for v in values]
    if len(set(hashes)) != 1:
        keys = set().union(*(v.keys() for v in values))
        differing = sorted(k for k in keys if any(k not in v for v in values)
                           or len({digest(v.get(k)) for v in values}) > 1)
        raise ContractError('CONFLICTING_DECLARATIONS', repair_class='R5',
                            vector_key='semantic_contradictions', details={
                                'declaration_correction': True, 'top_level_value_count': len(values),
                                'object_hashes': hashes, 'differing_keys': differing,
                                'raw_sha256': original_hash,
                                'instruction': 'Return exactly one declaration object consistent with the original goal. No object has been selected or merged.'})
    if len(values) > 1:
        rules.append('IDENTICAL_OBJECT_DEDUPLICATION')
    return values[0], {'before_hash': original_hash, 'after_hash': hashes[0],
                       'applied_rules': rules, 'semantics_changed': False,
                       'top_level_value_count': len(values), 'repair_class': 'R1' if rules else 'R0'}


def compile_declaration(packet, *, source_ref, acceptance_bindings, version=1):
    """Bind semantic fields to existing registry; identities come from caller.

Typed field leaves carry type/required/consumers. The compiler creates redundant
field rows, shapes and export references, never their business semantics.
"""
    from .contract_integrity import ContractIntegrityChecker, SECTIONS, field_rows
    required = {'artifacts', 'public_interface', 'test_command', 'reason_summary'}
    def reject(code, fields, **details):
        raise ContractError(code, fields=fields, repair_class='R5',
                            vector_key='missing_semantic_fields', details=details)
    if not isinstance(packet, dict):
        reject('DECLARATION_OBJECT_REQUIRED', [])
    if set(packet) != required:
        reject('DECLARATION_FIELDS_REQUIRED', sorted(required ^ set(packet)), allowed_fields=sorted(required))
    design = copy.deepcopy(packet)
    artifacts = design['artifacts']
    if not isinstance(artifacts, list) or not artifacts:
        reject('ARTIFACT_DECLARATIONS_REQUIRED', ['artifacts'])
    seen = set()
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            reject('ARTIFACT_DECLARATION_INVALID', ['artifacts'])
        path = artifact.get('path')
        if not isinstance(path, str) or not path or path in seen or path == '.' or PurePosixPath(path).is_absolute() or '..' in PurePosixPath(path).parts or any(ch in path for ch in ':\\*?') or any(p.lower() in {'.git', '.hg', '.svn'} for p in PurePosixPath(path).parts):
            reject('DECLARATION_PATH_INVALID', ['artifacts'])
        seen.add(path)
        if not isinstance(artifact.get('purpose'), str) or not artifact['purpose'].strip():
            reject('ARTIFACT_PURPOSE_REQUIRED', ['artifacts'])
    definition = design['public_interface']
    if not isinstance(definition, dict) or any(not definition.get(k) for k in SECTIONS):
        reject('COMPLETE_PUBLIC_CONTRACT_REQUIRED', ['public_interface'], required_sections=list(SECTIONS))
    if 'acceptance_bindings' in definition:
        reject('PROGRAM_OWNED_ACCEPTANCE_BINDING', ['public_interface'])
    argv = design['test_command']
    if not isinstance(argv, list) or not argv or not all(isinstance(x, str) and x for x in argv):
        reject('TEST_COMMAND_REQUIRED', ['test_command'],
               expected_type='nonempty array of nonempty strings',
               actual_type=type(argv).__name__,
               instruction='Return test_command as a JSON argv array, not a shell command string or object. Each element is one argument. If multiple test commands are needed, declare a test runner artifact and invoke it in this argv. No shell splitting or command inference is performed.')
    if not isinstance(design['reason_summary'], str) or not design['reason_summary'].strip():
        reject('REASON_REQUIRED', ['reason_summary'])
    bindings = copy.deepcopy(acceptance_bindings)
    if not bindings or len({b['contract_id'] for b in bindings}) != 1:
        raise ValueError('trusted acceptance bindings for exactly one contract required')
    ident = bindings[0]['contract_id']
    entry = {'contract_id': ident, 'feature': design['reason_summary'], 'source_decision': source_ref,
             'version': version, 'status': 'DECLARED', 'evidence_refs': [source_ref],
             'change_policy': 'immutable during witness; implementation must conform',
             'integrity_version': 2, 'must_acceptance_ids': [b['acceptance_id'] for b in bindings],
             'artifact_declarations': artifacts, 'required_sections': list(SECTIONS),
             'artifact_paths': [a['path'] for a in artifacts] + [b['object_ref'] for b in bindings],
             'definition': definition}
    # Legacy explicit metadata is validated, never silently replaced.
    if 'field_contracts' not in definition:
        rows = []
        for row in field_rows(definition['fields']):
            node = definition['fields']
            if row['owner'] != '$contract':
                for part in row['owner'].split('/'):
                    node = node[part]
            leaf = node[row['name']]
            if not isinstance(leaf, dict) or type(leaf.get('required')) is not bool or not isinstance(leaf.get('consumers'), list) or not leaf['consumers']:
                reject('FIELD_SEMANTICS_REQUIRED', ['public_interface'], field=row,
                       instruction='Each field leaf requires explicit type, required boolean and consumers; the compiler cannot infer them.')
            rows.append({**row, 'required': leaf['required'], 'consumers': leaf['consumers']})
        definition['field_contracts'] = rows
    rows = field_rows(definition['fields'])
    definition.setdefault('return_shapes', {r['owner']: sorted(x['name'] for x in rows if x['owner'] == r['owner']) for r in rows})
    definition['acceptance_bindings'] = bindings
    document, projections = ContractIntegrityChecker.project_exports({'kind': 'PublicContractRegistry', 'entries': [entry]})
    definition = document['entries'][0]['definition']
    if 'exception_bindings' not in definition:
        exception_rows = []
        for export in definition['exports']:
            if export['kind'] != 'exception':
                continue
            name = export['name']
            test_refs = [a['path'] for a in artifacts if name in a.get('interfaces', {}).get('test_for', [])]
            policy = definition['exceptions'].get(name) if isinstance(definition['exceptions'], dict) else None
            if not test_refs or not policy:
                reject('EXCEPTION_SEMANTICS_REQUIRED', ['public_interface', 'artifacts'], exception=name,
                       instruction='Declare the exception policy and explicit test_for names on its test artifact; no test relationship is inferred.')
            exception_rows.append({'name': name, 'policy': policy,
                                   'implementation_ref': export['owner'], 'test_refs': test_refs,
                                   'acceptance_refs': [b['acceptance_id'] for b in bindings]})
        definition['exception_bindings'] = exception_rows
    ContractIntegrityChecker.require(document)
    # Bind program identities/provenance outside semantic public content.
    receipt = {'kind': 'DeclarationCompilationReceipt', 'schema_version': '1.0',
               'semantic_hash': digest(packet), 'registry_hash': digest(document),
               'source_ref': source_ref, 'export_ids': [digest({'contract': ident, **e}) for e in document['entries'][0]['definition']['exports']],
               'projections': projections, 'business_semantics_inferred': False}
    return design, document, receipt


class MilestoneContractCompiler:
    """Mechanical front end to the existing declaration/registry compiler.

    One current milestone supplies semantics. Paths, identifiers, bindings and
    test obligations are generated here; no test implementation or business
    answer is synthesized. The normal integrity checker remains authoritative.
    """
    fields = frozenset({'semantic_goal', 'public_behavior', 'operations', 'fields',
                        'failure_semantics', 'persistence', 'concurrency', 'acceptance_intent'})

    def compile(self, packet, *, source_ref, requirement_refs, namespace, checker_ref, subject_ref=None, artifact_subject=False, artifact_layout=None):
        import re
        def reject(code, fields, **details):
            raise ContractError(code, fields=fields, repair_class='R5',
                                vector_key='missing_semantic_fields', details=details)
        if not isinstance(packet, dict) or set(packet) != self.fields:
            reject('MILESTONE_SEMANTIC_FIELDS_REQUIRED',
                   sorted(self.fields ^ set(packet)) if isinstance(packet, dict) else [],
                   allowed_fields=sorted(self.fields))
        if (not source_ref or not requirement_refs or not namespace or not checker_ref
                or not all(isinstance(r, str) and r for r in requirement_refs)):
            raise ValueError('trusted source, requirement bindings and namespace required')
        for key in ('semantic_goal', 'public_behavior', 'persistence', 'concurrency'):
            if not isinstance(packet[key], str) or not packet[key].strip():
                reject('MILESTONE_SEMANTICS_REQUIRED', [key])
        if (not isinstance(packet['acceptance_intent'], list) or not packet['acceptance_intent']
                or not all(isinstance(v, str) and v.strip() for v in packet['acceptance_intent'])):
            reject('MILESTONE_ACCEPTANCE_REQUIRED', ['acceptance_intent'])
        operations = packet['operations']
        if not isinstance(operations, list) or not 1 <= len(operations) <= 8:
            reject('MILESTONE_NEEDS_DECOMPOSITION', ['operations'], maximum_operations=8)
        names = set()
        required = {'name','kind','parameters','returns','behavior','failures','idempotency','ordering'}
        for index, operation in enumerate(operations):
            field = 'operations/' + str(index)
            if not isinstance(operation, dict) or set(operation) != required:
                reject('OPERATION_SEMANTICS_REQUIRED', [field], required_fields=sorted(required))
            name = operation['name']
            if (not isinstance(name, str) or not re.fullmatch(r'[A-Za-z_]\w*', name)
                    or name in names or not isinstance(operation['kind'], str)
                    or operation['kind'] not in {'function','class'}):
                reject('PUBLIC_OPERATION_INVALID', [field])
            names.add(name)
            for key in ('parameters','returns','behavior','idempotency','ordering'):
                if not operation[key]: reject('OPERATION_SEMANTICS_REQUIRED', [field + '/' + key])
            if (not isinstance(operation['failures'], list)
                    or not all(isinstance(v, str) for v in operation['failures'])):
                reject('FAILURE_SEMANTICS_REQUIRED', [field + '/failures'])
        failures = packet['failure_semantics']
        if not isinstance(failures, dict):
            reject('FAILURE_SEMANTICS_REQUIRED', ['failure_semantics'])
        for name, policy in failures.items():
            if (not isinstance(name, str) or not re.fullmatch(r'[A-Za-z_]\w*', name)
                    or name in names or not isinstance(policy, dict)
                    or set(policy) != {'behavior','base'}):
                reject('EXCEPTION_SEMANTICS_REQUIRED', ['failure_semantics/' + str(name)])
            if not isinstance(policy['behavior'], str) or not policy['behavior'].strip():
                reject('EXCEPTION_BEHAVIOR_REQUIRED', ['failure_semantics/' + name + '/behavior'])
            if not isinstance(policy['base'], str):
                reject('EXCEPTION_BASE_UNRESOLVED', ['failure_semantics/' + name + '/base'])
            if policy['base'] and policy['base'] not in failures and policy['base'] not in {'Exception','ValueError','RuntimeError','TypeError','LookupError','OSError'}:
                reject('EXCEPTION_BASE_UNRESOLVED', ['failure_semantics/' + name + '/base'])
        for name, policy in failures.items():
            seen = {name}; base = policy['base']
            while base in failures:
                if base in seen:
                    reject('EXCEPTION_INHERITANCE_CYCLE', ['failure_semantics/' + name + '/base'],
                           cycle_members=sorted(seen),
                           instruction='Replace this inheritance edge with a non-cyclic declared or standard base; an existing builtin may declare an empty base. The compiler will recheck the complete graph.')
                seen.add(base)
                next_policy = failures[base]
                if not isinstance(next_policy, dict): break
                base = next_policy.get('base', '')
        for index, operation in enumerate(operations):
            if not set(operation['failures']) <= failures.keys():
                reject('OPERATION_FAILURE_UNRESOLVED', ['operations/' + str(index) + '/failures'])

        # Validate source semantic leaves before projecting into public_interface.
        # Correction must address the model's field, not a compiler-owned object.
        def validate_fields(value, path):
            if not isinstance(value,dict) or not value:
                reject('FIELD_SEMANTICS_REQUIRED',['/'.join(path)],instruction='Declare a nonempty field map with explicit type, required boolean and nonempty consumers.')
            for name,leaf in value.items():
                current=path+[str(name)]
                if isinstance(leaf,dict) and 'type' not in leaf:
                    validate_fields(leaf,current)
                    continue
                if not isinstance(leaf,dict):
                    reject('FIELD_SEMANTICS_REQUIRED',['/'.join(current)],instruction='Declare type, required boolean and nonempty consumers for this field.')
                for key,valid in (
                    ('type',isinstance(leaf.get('type'),str) and bool(leaf.get('type','').strip())),
                    ('required',type(leaf.get('required')) is bool),
                    ('consumers',isinstance(leaf.get('consumers'),list) and bool(leaf.get('consumers')) and all(isinstance(x,str) and x.strip() for x in leaf.get('consumers',[])))):
                    if not valid:
                        reject('FIELD_SEMANTICS_REQUIRED',['/'.join(current+[key])],
                            instruction='Correct only this declared field metadata leaf: type is nonempty text, required is boolean, consumers is a nonempty list of explicit consumer names. No field meaning is inferred.')
        validate_fields(packet['fields'],['fields'])

        # Stable identities are bound to the caller's milestone namespace, not
        # model-supplied IDs or mutable prose. Revisions cannot rename the goal.
        milestone_id = 'milestone-' + digest(namespace).split(':')[-1][:20]
        folder = 'milestones/' + milestone_id.replace('-', '_')
        source_path, test_path = folder + '/api.py', 'tests/test_' + milestone_id.replace('-', '_') + '.py'
        support=[]
        if artifact_layout is not None:
            from pathlib import PurePosixPath
            if (not isinstance(artifact_layout,dict) or not {'source','test'}<=set(artifact_layout)
                    or set(artifact_layout)-{'source','test','support'}):
                raise ValueError('trusted artifact layout requires source and test paths')
            support=artifact_layout.get('support',[])
            if (not isinstance(support,list) or len(support)>4 or any(not isinstance(a,dict)
                    or set(a)!={'path','purpose'} or not isinstance(a['purpose'],str) or not a['purpose'].strip() for a in support)):
                raise ValueError('support artifacts require bounded explicit public purposes')
            names=[artifact_layout['source'],artifact_layout['test'],*[a['path'] for a in support]]
            for name in names:
                if (not isinstance(name,str) or '\\' in name or ':' in name
                        or PurePosixPath(name).is_absolute() or '..' in PurePosixPath(name).parts
                        or PurePosixPath(name).as_posix()!=name
                        or PurePosixPath(name).parts[0].lower() in {'.git','.cgkn','cgkn','governance','benchmarks'}):
                    raise ValueError('unsafe trusted milestone artifact path')
            if len({n.casefold() for n in names})!=len(names):
                raise ValueError('duplicate milestone artifact ownership')
            source_path,test_path=artifact_layout['source'],artifact_layout['test']
            if (not source_path.endswith('.py') or not test_path.endswith('.py')
                    or not test_path.startswith('tests/') or source_path.startswith('tests/')):
                raise ValueError('source and public test ownership must be distinct')
        bindings = [{'acceptance_id':'accept-' + digest([namespace, i]).split(':')[-1][:20],
                     'contract_id':milestone_id, 'object_ref':source_path if artifact_subject else subject_ref or folder,
                     'checker_ref':checker_ref, 'version':1,
                     'requirement_refs':list(requirement_refs)}
                    for i in range(len(packet['acceptance_intent']))]
        exports = [{'name':op['name'], 'kind':op['kind']} for op in operations]
        exports += [{'name':name, 'kind':'exception'} for name in sorted(failures)]
        declaration = {
            'artifacts':[
                {'path':source_path, 'purpose':packet['semantic_goal'], 'interfaces':{'public_exports':exports}},
                {'path':test_path, 'purpose':'Exercise the declared current milestone contract',
                 'interfaces':{'public_exports':[], 'test_for':sorted(failures)}},
                *[{**a,'interfaces':{'public_exports':[]}} for a in support]],
            'public_interface':{
                'interface':{op['name']:copy.deepcopy(op) for op in operations},
                'fields':copy.deepcopy(packet['fields']),
                'types':{'declared_fields':copy.deepcopy(packet['fields'])},
                'exceptions':copy.deepcopy(failures) or {'declared_public_exceptions':[]},
                'idempotency':{op['name']:op['idempotency'] for op in operations},
                'persistence':packet['persistence'], 'ordering':{op['name']:op['ordering'] for op in operations},
                'concurrency':packet['concurrency'], 'edge_behavior':packet['public_behavior']},
            'test_command':['python','-m','pytest','-q',test_path], 'reason_summary':packet['semantic_goal']}
        design, registry, receipt = compile_declaration(declaration, source_ref=source_ref,
                                                        acceptance_bindings=bindings)
        receipt.update(mode='MILESTONE_MODE', milestone_id=milestone_id,
                       semantic_hash=digest(packet), requirement_refs=list(requirement_refs),
                       operation_exception_mapping={op['name']:list(op['failures']) for op in operations},
                       test_binding_skeleton=[{**b, 'intent':intent, 'test_artifact':test_path,
                                               'subject_refs':([source_path,*[a['path'] for a in support]] if artifact_subject else [b['object_ref']]),
                                               'status':'UNIMPLEMENTED_NOT_VERIFIED'}
                                              for b,intent in zip(bindings,packet['acceptance_intent'])],
                       checker_ref=checker_ref,
                       artifact_layout={'source':source_path,'test':test_path,'support':support},
                       business_implementation_generated=False)
        return design, registry, receipt


def apply_semantic_patch(original, patch, *, allowed_paths, immutable_paths=()):
    """Apply exact, server-admitted semantic leaves; no merge or whole rewrite.

    Paths are arrays of field names/list offsets, not executable expressions.
    The caller recompiles the entire resulting object before committing it.
    """
    if not isinstance(patch, dict) or set(patch) != {'patches'} or not isinstance(patch['patches'], list) or not 1 <= len(patch['patches']) <= 4:
        raise ContractError('BOUNDED_PATCH_REQUIRED')
    allowed = {tuple(p) for p in allowed_paths}
    immutable = [tuple(p) for p in immutable_paths]
    result = copy.deepcopy(original)
    touched = set()
    for row in patch['patches']:
        if not isinstance(row, dict) or set(row) != {'op','path','value'} or row['op'] not in {'add','replace'}:
            raise ContractError('SEMANTIC_PATCH_INVALID')
        if not isinstance(row['path'], list) or not row['path'] or not all(type(k) in (str,int) for k in row['path']):
            raise ContractError('SEMANTIC_PATCH_PATH_INVALID')
        path = tuple(row['path'])
        if path not in allowed or path in touched or any(path[:len(p)] == p or p[:len(path)] == path for p in immutable):
            raise ContractError('SEMANTIC_PATCH_NOT_AUTHORIZED')
        node = result
        try:
            for key in path[:-1]: node = node[key]
            key = path[-1]
            if isinstance(node, list):
                if type(key) is not int or not 0 <= key < len(node) or row['op'] != 'replace':
                    raise KeyError(key)
            elif isinstance(node, dict):
                if not isinstance(key, str) or (key in node) != (row['op'] == 'replace'):
                    raise KeyError(key)
            else: raise TypeError('not a semantic container')
            node[key] = copy.deepcopy(row['value'])
        except (KeyError, IndexError, TypeError) as exc:
            raise ContractError('SEMANTIC_PATCH_TARGET_MISMATCH') from exc
        touched.add(path)
    return result, {'before_hash':digest(original), 'after_hash':digest(result),
                    'changed_paths':[list(p) for p in sorted(touched, key=str)],
                    'committed':False, 'full_compilation_required':True}

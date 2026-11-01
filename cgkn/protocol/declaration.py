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

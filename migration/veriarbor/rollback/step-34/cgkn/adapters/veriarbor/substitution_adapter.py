"""Authenticate same-boundary replacement with the existing provenance gate.

No certificate database is created. Proofs are derived from immutable check
receipts in the original FileRunStore. Historical checks keep their subjects.
"""
import json
from veriarbor.block import Block
from veriarbor.contract import Contract, canonical
from veriarbor.port import Port
from veriarbor.effects import EffectContract
from veriarbor.variant import Variant
from veriarbor.certificate import Certificate
from veriarbor.substitution import CertifiedReplacement, substitution_cover
from veriarbor.model import stable_hash


def milestone_block(goal, subjects):
    contract = goal['milestone_contract']
    interface = contract['design']['public_interface']
    own = set(goal['subject_refs']) - set(contract.get('dependency_artifacts', ()))
    artifacts = {p: subjects[p] for p in own if subjects.get(p)}
    if not artifacts or not all(k in interface for k in ('interface', 'edge_behavior', 'persistence', 'idempotency', 'ordering', 'concurrency')):
        raise ValueError('BLOCK_BOUNDARY_UNQUALIFIED')
    # Existing textual contracts are exact opaque predicates. No inferred
    # schema compatibility or automatic adapter generation for legacy text.
    boundary = Contract.create({'host_contract': interface}, canonical(interface))
    effects = EffectContract(reads=tuple(contract.get('dependency_goal_ids', ())),
        writes=tuple(sorted(artifacts)), external_effects=('opaque:' + stable_hash(interface),),
        persistence=canonical(interface['persistence']), idempotency=canonical(interface['idempotency']),
        ordering=canonical(interface['ordering']), concurrency=canonical(interface['concurrency']),
        rollback='host recovery contract; never implicit replay')
    variant = Variant(stable_hash(artifacts), tuple(artifacts.items()))
    return Block(goal['id'], contract['compilation']['milestone_id'],
        (Port('request', '1', 'input', boundary, compatibility_policy='exact'),),
        (Port('response', '1', 'output', boundary, compatibility_policy='exact'),),
        effects, (variant,), variant.variant_id)


def _authenticate(acceptance, gate, goal, row):
    from cgkn.execution import BlockExecutionResult
    from cgkn.state.acceptance import identity
    raw = json.loads((acceptance.root/'attempts'/row['node_id']/(row['attempt_id']+'.json')).read_text(encoding='utf-8'))
    if identity(raw) != row['receipt_hash'] or row['condition_hash'] != identity(goal['acceptance']):
        return None
    proof = gate.verify_check(BlockExecutionResult.from_dict(raw), goal, row['subjects'])
    if proof.get('status') != 'TRUSTED' or proof['chain'].get('verdict') != 'VERIFIED':
        return None
    return proof


def _certificate(block, goal, row, proof):
    checker = proof['chain']['checker']
    return Certificate(block.block_id, block.active_variant, *block.boundary_hashes,
        (goal['id'],), block.variant.artifacts, ((checker['ref'], checker['hash']),),
        ('Exact frozen host contract and independent predicate only; not unconstrained semantic equivalence.',),
        ('sha256:' + row['receipt_hash'],), 'original-check:' + row['attempt_id'])


def replacements(acceptance, gate):
    """Current independently checked owners only; any current FAIL blocks reuse."""
    if not gate or not acceptance.data.get('plans'):
        return (), {}
    from cgkn.state.acceptance import identity
    binding = gate.binding()
    from pathlib import Path
    from cgkn.state.provenance import file_hash
    current = acceptance.data['subjects']
    # Authoritative observations must agree with live bytes, not cached metadata.
    for name, path in binding.get('current_artifacts', {}).items():
        if current.get(name) and (not Path(path).is_file() or file_hash(path) != current[name]):
            return (), {}
    output, checkers = [], {}
    for goal in acceptance.data['plans'][-1]['goals']:
        if not goal.get('milestone_contract'):
            continue
        wanted = {p: current.get(p) for p in goal['subject_refs']}
        rows = [r for r in acceptance.data['checks'] if r['goal_id'] == goal['id']
                and r['condition_hash'] == identity(goal['acceptance'])]
        now = [r for r in rows if r['subjects'] == wanted]
        superseded = {h for r in now for h in r.get('supersedes_receipts', ())}
        now = [r for r in now if r['receipt_hash'] not in superseded]
        if not now or any(r['verdict'] != 'VERIFIED' for r in now):
            continue
        dependencies = set(goal['milestone_contract'].get('dependency_artifacts', ()))
        historical = [r for r in rows if r['verdict'] == 'VERIFIED' and r['subjects'] != wanted
                      and all(r['subjects'].get(p) == wanted.get(p) for p in dependencies)]
        if not historical:
            continue
        try:
            new_row = now[-1]
            proof = _authenticate(acceptance, gate, goal, new_row)
            if not proof:
                continue
            new = milestone_block(goal, wanted)
            new_cert = _certificate(new, goal, new_row, proof)
            checkers.update(dict(new_cert.checker_hashes))
            for old_row in historical:
                peers = [r for r in rows if r['subjects'] == old_row['subjects']]
                superseded_old = {h for r in peers for h in r.get('supersedes_receipts', ())}
                if old_row['receipt_hash'] in superseded_old or any(r['verdict'] != 'VERIFIED'
                        for r in peers if r['receipt_hash'] not in superseded_old):
                    continue
                # Do not infer equivalence when the owner's own dependencies
                # also changed; that needs a separate local composition proof.
                if any(old_row['subjects'].get(p) != wanted.get(p) for p in dependencies):
                    continue
                old_proof = _authenticate(acceptance, gate, goal, old_row)
                if not old_proof or old_proof['chain']['checker'] != proof['chain']['checker']:
                    continue
                old = milestone_block(goal, old_row['subjects'])
                output.append(CertifiedReplacement(_certificate(old, goal, old_row, old_proof),
                                                   new, new_cert, True))
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return tuple(output), checkers


def reuse_cover(goal, row, current, replacement_proofs, checkers):
    if row.get('verdict') != 'VERIFIED':
        return None
    return substitution_cover(row.get('subjects') or {}, current,
        dependency_artifacts=goal.get('milestone_contract', {}).get('dependency_artifacts', ()),
        replacements=replacement_proofs, checkers=checkers)

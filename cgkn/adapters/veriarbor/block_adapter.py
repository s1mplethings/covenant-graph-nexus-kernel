"""Project host contracts into immutable library values; no runtime or store."""
from veriarbor.block import Block
from veriarbor.port import Port
from veriarbor.contract import Contract, canonical
from veriarbor.effects import EffectContract
from veriarbor.variant import Variant
from veriarbor.model import stable_hash
from veriarbor.expansion import progressive_boundary_expansion
from veriarbor.compatibility import PortCompatibility
from veriarbor.dedup import VerificationKey


def component_port(spec, *, direction, schema, semantic):
    """Schema comes from the host registry, never guessed from a type name."""
    return Port(spec.name, spec.artifact_type.rsplit('@', 1)[1], direction,
                Contract.create(schema, semantic), required=spec.required)


def leaf_block(node, *, artifacts, boundary):
    """A boundary must be explicitly supplied by the frozen host contract.

    Missing typed contracts are opaque, not automatically replaceable. In
    particular a list of Python file paths cannot stand in for input/output.
    """
    expected = {'input_ports', 'output_ports', 'effects'}
    if set(boundary) != expected:
        raise ValueError('BLOCK_BOUNDARY_UNQUALIFIED')
    def ports(rows, direction):
        return tuple(Port(p['port_id'], p['version'], direction,
                          Contract.create(p['schema'], p['semantic']),
                          required=p.get('required', True),
                          default_json=canonical(p.get('default')),
                          compatibility_policy=p.get('compatibility_policy', 'structural-v1')) for p in rows)
    variant = Variant(stable_hash(artifacts), tuple(artifacts.items()))
    return Block(node.id, node.capability_ref, ports(boundary['input_ports'], 'input'),
                 ports(boundary['output_ports'], 'output'), EffectContract(**boundary['effects']),
                 (variant,), variant.variant_id)


def local_scope(dag, changed_nodes, *, boundary_relations=None):
    """Initial repair inspection expands at most one hop, never schedules work.

    A missing boundary cannot justify certificate reuse: report it as BREAKING
    and ask for a neighbor check. Further hops require a fresh boundary result.
    """
    changed = set(changed_nodes)
    if not changed <= set(dag.by_id):
        raise ValueError('unknown invalidation nodes')
    relations = boundary_relations or {}
    affected, bubbles = set(), []
    for key in sorted(changed):
        neighbors = {n.id for n in dag.nodes if key in n.depends_on}
        neighbors.update(dag.by_id[key].depends_on)
        bubble = progressive_boundary_expansion(key, neighbors, relations.get(key, PortCompatibility.BREAKING))
        affected.update(bubble.changed_blocks)
        affected.update(bubble.direct_neighbors)
        bubbles.append(bubble)
    return tuple(n for n in dag.topological_order() if n in affected), tuple(bubbles)


def verification_key(block, acceptance_id, checker_hash, neighbors=(), qualification=''):
    return VerificationKey(block.block_id, block.active_variant, *block.boundary_hashes,
                           acceptance_id, checker_hash, tuple(neighbors), block.variant.artifacts, qualification)

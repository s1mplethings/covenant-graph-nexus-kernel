"""Map explicit failed strategy identities onto existing repair checkpoints."""
from dataclasses import asdict
from veriarbor.learning import DecisionCheckpoint, backtrack


def recommendation(tree, failed_strategy):
    checkpoints = []
    for sequence, node in enumerate(tree.nodes):
        repair = node.config.get('repair_contract', {})
        checkpoint = repair.get('decision_checkpoint', {})
        fingerprint = repair.get('strategy_fingerprint')
        if checkpoint.get('reversible') and fingerprint:
            checkpoints.append(DecisionCheckpoint(node.id, sequence, ('strategy:' + fingerprint,),
                                                   'capability_tree:' + node.id,
                                                   tuple(checkpoint.get('restore_scope', ()))))
    selected = backtrack(('strategy:' + failed_strategy,), checkpoints)
    return ({**asdict(selected), 'authority': 'Agent recommendation only; explicit TreeEdit and existing recovery required',
             'conflict_basis': 'exact failed strategy identity, not inferred causal minimality'} if selected else None)

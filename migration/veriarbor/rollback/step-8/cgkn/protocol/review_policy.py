"""Evidence policy helpers; neither model review nor policy grants acceptance."""


def review_kind(producer, reviewer):
    def known(value):
        return isinstance(value, str) and value.strip().upper() not in {'', 'UNKNOWN', 'UNAVAILABLE'}
    if not known(producer) or not known(reviewer):
        return 'UNQUALIFIED_REVIEW'
    return 'SELF_CRITIQUE' if producer.strip().casefold() == reviewer.strip().casefold() else 'CROSS_MODEL_REVIEW'


def evaluator_disposition(evidence):
    """Only explicit observations trigger suspicion, never model ability guesses."""
    signals = ('checker_failed', 'empty_test_collection', 'object_version_mismatch',
               'contract_contradiction', 'positive_control_failed',
               'negative_control_passed', 'mutation_control_passed')
    reasons = [key for key in signals if evidence.get(key) is True]
    return {'status': 'EVALUATOR_SUSPECTED' if reasons else 'NOT_SUSPECTED',
            'reasons': reasons, 'business_repair_allowed': not reasons}


def qualify_evaluator(receipt):
    required = ('contract_ref', 'object_hash', 'checker_hash', 'test_ids',
                'positive_control_ref', 'negative_control_ref')
    bound = all(receipt.get(key) for key in required)
    correct = (receipt.get('positive_control_passed') is True
               and receipt.get('negative_control_rejected') is True
               and receipt.get('object_version_verified') is True
               and receipt.get('contract_derived') is True)
    if receipt.get('mutation_applicable'):
        correct = correct and receipt.get('mutation_rejected') is True and bool(receipt.get('mutation_control_ref'))
    return 'QUALIFIED' if bound and correct else 'INVALID_EVALUATOR'


def review_needed(reason):
    return reason in {'semantic_ambiguity', 'architecture_decision', 'business_acceptance_boundary',
                      'evaluator_suspected', 'repair_strategy_switch', 'irreversible_risk',
                      'repeated_no_progress', 'public_claim', 'high_risk_self_reduction'}

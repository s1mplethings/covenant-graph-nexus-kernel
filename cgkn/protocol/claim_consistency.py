"""Fail-closed public claim checks; never manufacture missing evidence."""


def claim_errors(claims):
    evidence=claims.get('real_world_evidence',{})
    errors=[]
    if claims.get('real_world_validated') is True and evidence.get('valid') is not True:
        errors.append('CLAIM_CONTRADICTS_EVIDENCE:real_world_validated')
    if claims.get('representative') is True and evidence.get('representative') is not True:
        errors.append('CLAIM_CONTRADICTS_EVIDENCE:representative')
    if claims.get('holdout_validated') is True and claims.get('holdout_status') not in {'PASS','VERIFIED'}:
        errors.append('CLAIM_CONTRADICTS_EVIDENCE:holdout')
    return errors

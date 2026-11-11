"""Receipt-backed wiring into the existing Skill lifecycle and registry."""
from dataclasses import replace
from veriarbor.skills import SkillRegistry, SkillValidation
from veriarbor.capability import CapabilityGateState
from .capability_adapter import load


class GovernedSkillLifecycle:
    def __init__(self, root, authorities):
        self.authorities=tuple(authorities)
        self.registry=SkillRegistry(root,receipt_validator=self.validate,lineage_recorder=self.record)

    def source(self, receipt_id):
        for authority in self.authorities:
            try:return authority,authority.validate_receipt(receipt_id)
            except ValueError:continue
        raise ValueError('RECEIPT_INVALID: skill source')

    def candidate(self, manifest, receipt_ids):
        sources=[self.source(rid) for rid in receipt_ids]
        if not sources:raise ValueError('COMMIT_RECEIPT_REQUIRED')
        reference=sources[0][1]
        if any(r.capability_id!=reference.capability_id or r.contract_hash!=reference.contract_hash
               or r.checker_identities!=reference.checker_identities for _,r in sources):
            raise ValueError('CHECKER_IDENTITY_MISMATCH: heterogeneous skill sources')
        if manifest.dependency_contract_hashes.get(reference.capability_id)!=reference.contract_hash:
            raise ValueError('CONTRACT_BINDING_REJECT')
        candidate=replace(manifest,status='CANDIDATE',source_capability=reference.capability_id,
                          source_receipts=tuple(receipt_ids),checker_identities=dict(reference.checker_identities))
        validations=[]
        for a,r in sources:
            row=load(a.store,a.project_id,a.run_id)['nodes'].get(r.node_id,{})
            validations.append(SkillValidation(a.run_id,a.project_id,a.run_id,candidate.strategy_hash,
                CapabilityGateState(**row.get('gates',{})),tuple(r.output_hashes),True,True,r.receipt_id,
                dict(r.checker_identities),r.contract_hash))
        return candidate,tuple(validations)

    def validate(self, validation):
        authority,_=self.source(validation.commit_receipt_id)
        return authority.validate_skill_lineage(validation)

    def record(self, manifest):
        for rid in manifest.source_receipts:
            authority,receipt=self.source(rid)
            if (manifest.dependency_contract_hashes.get(receipt.capability_id)!=receipt.contract_hash
                    or manifest.checker_identities!=receipt.checker_identities):
                raise ValueError('CHECKER_IDENTITY_MISMATCH')
            authority.record_skill_lineage(rid,manifest)

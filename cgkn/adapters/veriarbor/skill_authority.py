"""Receipt-backed wiring into the existing Skill lifecycle and registry."""
from dataclasses import replace
from veriarbor.skills import SkillRegistry, SkillValidation
from veriarbor.capability import CapabilityGateState
from .capability_adapter import load


class GovernedSkillLifecycle:
    def __init__(self, root, authorities):
        self.authorities=tuple(authorities)
        self.registry=SkillRegistry(root,receipt_validator=self.validate,lineage_recorder=self.record,manifest_validator=self.validate_manifest)

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

    def validate_manifest(self, manifest):
        from veriarbor.skills import SkillManifest
        if not manifest.source_receipts:raise ValueError('COMMIT_RECEIPT_REQUIRED')
        for rid in manifest.source_receipts:
            authority,receipt=self.source(rid)
            if (manifest.source_capability!=receipt.capability_id or
                manifest.dependency_contract_hashes.get(receipt.capability_id)!=receipt.contract_hash or
                manifest.checker_identities!=receipt.checker_identities):
                raise ValueError('SKILL_CURRENT_BINDING_REJECT')
            rows=[e['data']['skill_state'] for e in authority.events()
                  if e['event_type']=='NODE_SKILL_LINEAGE' and e['data'].get('receipt_id')==rid
                  and e['data']['skill_state'].get('skill_id')==manifest.skill_id
                  and e['data']['skill_state'].get('version')==manifest.version]
            if not rows or rows[-1].get('status')!='VERIFIED' or SkillManifest(**rows[-1]).strategy_hash!=manifest.strategy_hash:
                raise ValueError('SKILL_LINEAGE_IDENTITY_REJECT')
        return True

    def export(self, skill_id, version):
        from veriarbor.model import stable_hash
        manifest=self.registry.lookup(skill_id,version)
        if manifest.status!='VERIFIED':raise ValueError('only qualified skills may be exported')
        self.validate_manifest(manifest)
        if manifest.private_assumptions:
            raise ValueError('private assumptions require an explicitly portable strategy version')
        raw=manifest.as_dict()
        # Evidence paths stay at their source authority; receipt IDs travel.
        raw['created_from_evidence']=[]
        import json,re
        encoded=json.dumps(raw,ensure_ascii=False)
        if re.search(r'[A-Za-z]:[\\/]|/(?:home|Users|tmp)/',encoded):
            raise ValueError('skill contains nonportable host assumptions; author a portable strategy version')
        packet={'format':'veriarbor.skill/1','manifest':raw,'strategy_hash':manifest.strategy_hash}
        packet['identity']=stable_hash(packet)
        return packet

    def validate_origin(self, packet):
        from veriarbor.model import stable_hash
        from veriarbor.skills import SkillManifest
        if set(packet)!={'format','manifest','strategy_hash','identity'} or packet['format']!='veriarbor.skill/1':
            raise ValueError('invalid skill export envelope')
        if stable_hash({k:v for k,v in packet.items() if k!='identity'})!=packet['identity']:
            raise ValueError('skill export identity mismatch')
        source=SkillManifest(**packet['manifest'])
        if source.private_assumptions:
            raise ValueError('source skill has nonportable private assumptions')
        if source.status!='VERIFIED' or source.strategy_hash!=packet['strategy_hash']:
            raise ValueError('source strategy is not qualified')
        return self.validate_manifest(source)

    def import_candidate(self, packet, *, project_id, version=None):
        from veriarbor.skills import SkillManifest
        self.validate_origin(packet)
        source=SkillManifest(**packet['manifest'])
        manifest=replace(source,version=version or source.version,project_id=project_id,scope='PROJECT',
            status='NEEDS_REVALIDATION',source_receipts=(),historical_metrics={},token_metrics={},
            created_from_evidence=('portable-skill:'+packet['identity'],))
        return self.registry.import_candidate(manifest,packet,source_validator=self.validate_origin)

    def requalify(self, skill_id, version, receipt_ids, *, project_id):
        manifest=self.registry.lookup(skill_id,version)
        if manifest.scope!='PROJECT' or manifest.project_id!=project_id:
            raise ValueError('target project qualification required')
        if any(self.source(rid)[1].project_id!=project_id for rid in receipt_ids):
            raise ValueError('source-project receipts cannot qualify a target-project import')
        candidate,validations=self.candidate(manifest,receipt_ids)
        return self.registry.requalify(candidate,validations)


    def trial_manifest(self, trial, *, project_id, task):
        from veriarbor.skills import dependencies_match
        manifest=self.registry.lookup(trial['skill_id'],trial['version'])
        if manifest.status not in {'CANDIDATE','NEEDS_REVALIDATION'} or manifest.project_id!=project_id:
            raise ValueError('skill trial must name an unqualified target-project candidate')
        if (manifest.scope!='PROJECT' or manifest.task_family!=task.get('task_family') or
                task.get('capability_id') not in manifest.capability_contract_refs or
                tuple(task.get('inputs',()))!=manifest.inputs or tuple(task.get('outputs',()))!=manifest.outputs):
            raise ValueError('skill trial task or port applicability mismatch')
        if not dependencies_match(manifest.as_dict(),task['dependency_versions'],task['dependency_contract_hashes'],
                task.get('checker_identities'),task.get('environment_identity')):
            raise ValueError('skill trial dependencies or current environment differ')
        if not all(task.get('context',{}).get(k)==v for k,v in manifest.preconditions.items()):
            raise ValueError('skill trial applicability mismatch')
        return manifest


def lifecycle_for_run(config, store, authority):
    """Discover only operator-declared source authorities, never paths from a Skill."""
    from pathlib import Path
    from cgkn.state import FileRunStore
    from cgkn.runtime.node_authority import ExecutionAuthority
    authorities=[authority]
    for source in config.get('skill_sources',()):
        if set(source)!={'store_root','project_id','run_id'}:raise ValueError('explicit skill source locator required')
        root=Path(source['store_root']).resolve()
        if not root.is_dir():raise ValueError('skill source store does not exist')
        other=FileRunStore(root)
        if not other.run_dir(source['project_id'],source['run_id']).is_dir():raise ValueError('skill source run does not exist')
        authorities.append(ExecutionAuthority(other,source['project_id'],source['run_id']))
    return GovernedSkillLifecycle(store.run_dir(config['project_id'],config['run_id'])/'skills',authorities)

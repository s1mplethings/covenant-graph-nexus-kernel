"""Explicit local-only operator policy for typed artifact regression tasks."""
from dataclasses import asdict
from cgkn.agent.project_agent import AdmissionPolicy
from cgkn.runtime import ArtifactModuleRunner as CanonicalArtifactModuleRunner
from veriarbor.capability import CapabilityContract


class artifact_runner(CanonicalArtifactModuleRunner):
    def __init__(self,root,run_dir,flow_ref,**kwargs):
        super().__init__(root,run_dir,flow_ref,**kwargs)
        capabilities={n['uses'] for n in self.flow['nodes'] if not n.get('structural')}
        self.admission_policy=AdmissionPolicy(project_id='artifact-flow',incremental_mode=False,
            max_tree_edits=len(self.flow['nodes']),max_new_nodes=len(self.flow['nodes']),
            allowed_effect_domains=frozenset({'filesystem'}),execution_budget={'calls':0},
            capability_contracts={cap:asdict(CapabilityContract(cap,
                'Schema-valid typed artifacts with exact input provenance',critical=False,
                positive_controls=('registered typed artifact checker',),
                evidence_requirements={'allow_imported_unmanaged':True})) for cap in capabilities})

"""Explicit offline operator authorization used by public entry regressions."""
from dataclasses import asdict
from veriarbor.capability import CapabilityContract,GoalGap


def authorization(project,capabilities,goal,*,calls=4,planning_decisions=32):
    contracts={cap:asdict(CapabilityContract(cap,goal,critical=False,
        positive_controls=('independent current-object observation',))) for cap in capabilities}
    contracts['host.planning@1']=asdict(CapabilityContract('host.planning@1',
        'Produce a bounded public proposal for the authorized root goal',critical=False,
        positive_controls=('public-proposal-captured',),evidence_requirements={'allow_imported_unmanaged':True}))
    return {'admission_policy':{'project_id':project,'incremental_mode':False,
        'capability_contracts':contracts,'goal_gaps':{cap:asdict(GoalGap(cap,goal,'independent-verification',1,0,
            capability_ids=(cap,))) for cap in capabilities},'max_new_nodes':8,'max_tree_edits':16,
        'allowed_effect_domains':['filesystem','external_network','local_process','measurement'],
        'allow_remote_effects':True,'execution_budget':{'calls':calls}},
        'max_planning_decisions':planning_decisions,'calls_per_decision':min(calls,4)}

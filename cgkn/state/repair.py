"""Repair lifecycle evidence in the existing append-only run event stream."""
import uuid
from .models import EventRecord
from cgkn.protocol.repair import plain,repair_progress

PHASES={'REPAIR_PENDING','REPAIR_ADMITTED','REPAIR_EXECUTED','TARGETED_RETEST',
    'REPAIR_TEST_FAILED','ACCEPTANCE_RECHECK','REPAIR_ACCEPTANCE_FAILED','REPAIR_VERIFIED','REPAIR_BLOCKED'}


def record_repair_phase(store,project_id,run_id,node_id,phase,data):
    if phase not in PHASES:raise ValueError('unknown repair phase')
    store.append_event(EventRecord(str(uuid.uuid4()),project_id,run_id,phase,
        data={'node_id':node_id,**plain(data)}))


class TargetedRepairVerification:
    """Reusable bounded test capability; caller retains executor/acceptance authority.

    Both callbacks execute actual checkers. A targeted failure never starts
    final acceptance, and no predicate/requirement is rewritten here.
    """
    def __init__(self,targeted,acceptance):self.targeted=targeted;self.acceptance=acceptance

    def execute(self,failed_ids,*,record):
        ids=list(dict.fromkeys(failed_ids))
        if not ids:raise ValueError('targeted repair verification needs failed acceptance IDs')
        record('TARGETED_RETEST',{'failed_acceptance_ids':ids})
        target=self.targeted(ids)
        checked=target.get('checks',{})
        if set(checked)!=set(ids) or not all(type(v) is bool for v in checked.values()):
            raise ValueError('targeted checker omitted/changed requested predicates')
        if not all(checked.values()):
            record('REPAIR_TEST_FAILED',{'checks':checked,'evidence_refs':target.get('evidence_refs',[])})
            return {'passed':False,'phase':'REPAIR_TEST_FAILED','targeted':target,'final':None}
        record('ACCEPTANCE_RECHECK',{'evidence_refs':target.get('evidence_refs',[])})
        final=self.acceptance()
        checks=final.get('checks',{})
        passed=bool(checks) and all(v is True for v in checks.values()) and final.get('passed') is True
        # This verdict is a checker observation. Only GoalAcceptance + provenance
        # may turn it into formal VERIFIED project state.
        record('REPAIR_VERIFIED' if passed else 'REPAIR_ACCEPTANCE_FAILED',
            {'checks':checks,'evidence_refs':final.get('evidence_refs',[]),'formal_goal_verdict':'DEFER_TO_GOAL_ACCEPTANCE'})
        return {'passed':passed,'phase':'REPAIR_VERIFIED' if passed else 'REPAIR_ACCEPTANCE_FAILED','targeted':target,'final':final}

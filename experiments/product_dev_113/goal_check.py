"""Bound a real isolated Observer measurement to a public goal.

This is proxy engineering evidence, not external acceptance or human approval.
The adapter never reads the external evaluator's files.
"""
from dataclasses import replace
from cgkn.execution import BlockExecutionResult, BlockStatus
from cgkn.executors.protocol import ExecutorDescriptor
from cgkn.state.acceptance import identity


class GoalCheckExecutor:
    descriptor=ExecutorDescriptor('isolated.goal-check@1','goal_check',('*',))
    def __init__(self, acceptance, observer, subject_supplier):
        self.acceptance,self.observer,self.subject_supplier=acceptance,observer,subject_supplier

    def execute(self, request):
        cfg=request.task_context.as_dict()['node_config']
        goal=next(g for g in self.acceptance.view()['goals'] if g['id']==cfg['goal_id'])
        subjects=self.subject_supplier()
        self.acceptance.bind_subjects(subjects)
        context=replace(request.task_context,node_config={
            'goal': 'Independently measure this public goal. '+goal['acceptance']+
                    '\nOriginal requirements: '+str({r:self.acceptance.requirements[r] for r in goal['requirement_refs']})+
                    '\nDo not infer success from producer statements. Scope verdict to observed properties.',
            'requirement_ref':goal['requirement_refs'],'requirement_version':'public-v1',
            'provider':cfg.get('provider','grok')})
        measured=self.observer.execute(replace(request,task_context=context))
        rows=measured.as_dict()['outputs'].get('checks',[])
        verdicts=[r['assessment']['verdict'] for r in rows]
        verdict='FAILED' if 'FAILED' in verdicts else 'VERIFIED' if verdicts and all(v=='VERIFIED' for v in verdicts) else 'INSUFFICIENT_EVIDENCE'
        coverage={ref for row in rows for ref in (row['claim'].get('requirement_ref',[]) if isinstance(row['claim'].get('requirement_ref'),list) else [row['claim'].get('requirement_ref')])}
        if not set(goal['requirement_refs'])<=coverage:verdict='INSUFFICIENT_EVIDENCE'
        after=self.subject_supplier()
        unchanged=all(subjects.get(r)==after.get(r) for r in goal['subject_refs'])
        check={'goal_id':goal['id'],'condition_hash':identity(goal['acceptance']),
               'subjects':{r:subjects.get(r) for r in goal['subject_refs']},
               'execution':'VALID' if measured.status==BlockStatus.SUCCEEDED and unchanged else 'INVALID',
               'verdict':verdict,'review_type':'DOMAIN_PROXY_REVIEW',
               'evidence_refs':[{'node_id':request.node_id,'attempt_id':request.attempt_id,'observer_history':True}] if rows else [],
               'observed':measured.as_dict()['outputs']}
        return BlockExecutionResult(project_id=request.project_id,run_id=request.run_id,
            node_id=request.node_id,attempt_id=request.attempt_id,executor_ref=request.executor_ref,
            status=BlockStatus.SUCCEEDED,outputs={'goal_check':check})

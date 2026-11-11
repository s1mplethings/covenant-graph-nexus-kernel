"""Rebuildable capability observations in FileRunStore; advisory routing only."""
import json
import statistics
from dataclasses import asdict
from cgkn.state.task_feedback import digest


def deterministic_facts(feedback, identity, acceptance=None):
    fact=feedback.attempt(identity)
    receipt=json.loads((feedback.root/fact['receipt_ref']).read_text(encoding='utf-8'))
    usage=receipt.get('usage',{});route=usage.get('routing',{});error=receipt.get('error') or {}
    details=error.get('details',{});acceptance_result='INSUFFICIENT_EVIDENCE';evidence=[]
    if acceptance is not None:
        if acceptance.project_id!=feedback.project_id or acceptance.run_id!=feedback.run_id:
            raise ValueError('acceptance scope mismatch')
        for item in feedback.statistics(acceptance)['contributions']:
            if item['node_id']==fact['node_id'] and item['attempt_id']==fact['attempt_id']:
                acceptance_result=item['acceptance'];evidence=item['evidence']
    domain=('UNKNOWN' if details.get('outcome_unknown') else
        details.get('failure_domain') if details.get('failure_domain') in {'HARNESS','TRANSPORT','MODEL_OUTPUT'} else
        'BUSINESS' if acceptance_result=='FAILED' else 'NONE' if acceptance_result=='VERIFIED' else 'UNKNOWN')
    return dict(task_id=fact['node_id'],attempt_id=fact['attempt_id'],source_identity=identity,
        capability_scope=fact.get('capability_scope',{}),
        task_class=fact.get('task_class',fact['capability_ref']),operation=fact.get('operation',fact['capability_ref']),
        provider_id=route.get('provider_id','UNKNOWN'),requested_model=route.get('requested_model','UNKNOWN'),
        bound_model=route.get('bound_model',route.get('requested_model','UNKNOWN')),
        actual_model=usage.get('model','UNKNOWN'),role=fact.get('role','worker'),
        config_hash=fact.get('config_hash','UNKNOWN'),result_status=fact['status'],
        checker_result=acceptance_result,acceptance_result=acceptance_result,failure_domain=domain,
        latency_ms=receipt.get('duration_ms'),token_usage={k:usage[k] for k in ('input_tokens','output_tokens','prompt_tokens','completion_tokens') if k in usage},
        accounted_cost=usage.get('accounted_cost'),estimated_cost=usage.get('estimated_cost'),
        repair_count=fact.get('repair_count',0),transport_error=domain=='TRANSPORT',harness_error=domain=='HARNESS',
        final_artifact_hash=receipt.get('metadata',{}).get('artifact_hashes',{}),
        input_context_refs={'context_hash':usage.get('context_hash'),'receipt_ref':fact['receipt_ref']},
        evidence_refs=[fact['receipt_ref']],checker_evidence=evidence,receipt_sha256=fact['receipt_sha256'],
        meta=fact['evaluation_state']=='NOT_REQUIRED_META',last_updated=receipt.get('ended_at'))


class CapabilityLedger:
    """Derived immutable revisions. Never rewrite TaskFeedback or acceptance."""
    def __init__(self,store,project_id):
        self.store=store;store._validate_segment(project_id)
        self.root=store.root/project_id/'capability_observations'

    def capture(self,feedback,identity,acceptance=None):
        facts=deterministic_facts(feedback,identity,acceptance)
        if facts['meta']:raise ValueError('evaluator observations cannot evaluate themselves')
        evaluation=feedback.attempt(identity)['evaluation']
        if evaluation is None:raise ValueError('evaluation required before capability publication')
        revision=evaluation['revision']
        record={'facts':facts,'evaluation':evaluation,'run_id':feedback.run_id,'revision':revision,
            'key':digest([facts[k] for k in ('provider_id','actual_model','task_class','config_hash','operation','capability_scope')])}
        self.store.immutable_json(self.root/identity/f'{revision:06d}.json',record)
        return record

    def records(self):
        values=[]
        for directory in sorted(self.root.glob('*')):
            paths=sorted(directory.glob('*.json'))
            if paths:values.append(json.loads(paths[-1].read_text(encoding='utf-8')))
        return values

    def view(self):
        groups={}
        for record in self.records():
            f=record['facts'];key=record['key']
            g=groups.setdefault(key,dict(key=key,provider_id=f['provider_id'],actual_model=f['actual_model'],
                task_class=f['task_class'],config_hash=f['config_hash'],operation=f.get('operation','UNKNOWN'),capability_scope=f.get('capability_scope',{}),attempts=0,qualified_attempts=0,accepted=0,
                failed_business=0,transport_failed=0,harness_invalid=0,unknown=0,repair_success=0,repair_failure=0,
                latency_samples=[],token_usage=[],costs=[],evidence_refs=[],known_strengths=[],known_weaknesses=[],contradictions=[],routing_support=0,last_updated=None))
            g['attempts']+=1
            valid=f['actual_model']!='UNKNOWN' and f['provider_id']!='UNKNOWN' and f['failure_domain'] in {'BUSINESS','NONE'}
            if valid:
                g['qualified_attempts']+=1;g['accepted' if f['failure_domain']=='NONE' else 'failed_business']+=1
                if f['repair_count']:g['repair_success' if f['failure_domain']=='NONE' else 'repair_failure']+=1
                advisory=record['evaluation']['advisory']
                if advisory.get('informative_for_routing') is True:
                    g['routing_support']+=1
                    g['known_strengths' if f['failure_domain']=='NONE' else 'known_weaknesses'].append(advisory.get('why_this_recommendation',''))
            else:g[{'TRANSPORT':'transport_failed','HARNESS':'harness_invalid'}.get(f['failure_domain'],'unknown')]+=1
            if isinstance(f['latency_ms'],(float,int)):g['latency_samples'].append(f['latency_ms'])
            g['token_usage'].append(f['token_usage']);g['costs'].append({'accounted':f['accounted_cost'],'estimated':f['estimated_cost']})
            g['evidence_refs'].append({'run_id':record['run_id'],'identity':f['source_identity'],'receipt_sha256':f['receipt_sha256'],'revision':record['revision']})
            g['last_updated']=max(g['last_updated'] or '',f['last_updated'] or '')
        for g in groups.values():
            lat=g.pop('latency_samples');g.update(mean_latency_ms=statistics.mean(lat) if lat else None,
                median_latency_ms=statistics.median(lat) if lat else None,evidence_count=len(g['evidence_refs']),
                sample_support=g['qualified_attempts'],confidence='LOW' if g['qualified_attempts']<3 else 'BOUNDED_SAMPLE')
            if g['accepted'] and g['failed_business']:g['contradictions'].append('mixed checked outcomes; do not automatically rank')
        return {'records':sorted(groups.values(),key=lambda x:x['key']),'snapshot_hash':digest(self.records()),'authority':'derived checked observations, not model score'}

    def route(self,task_class,configs,default,*,minimum_support=3,operation=None,capability_scope=None,max_age_days=90):
        """Choose only among Agent-approved bounded executors, never plan a project."""
        if default not in configs:raise ValueError('default route not approved')
        snapshot=self.view();candidates=[];scope_evidence=[]
        from datetime import datetime,timezone,timedelta
        cutoff=datetime.now(timezone.utc)-timedelta(days=max_age_days)
        for name,config in configs.items():
            h=digest(asdict(config))
            for row in snapshot['records']:
                try: fresh=datetime.fromisoformat(row['last_updated']) >= cutoff
                except (ValueError,TypeError): fresh=False
                exact = (operation is not None and row.get('operation')==operation and bool(capability_scope)
                    and row.get('capability_scope')==capability_scope and 'UNKNOWN' not in capability_scope.values())
                if row['provider_id']==config.model and row['actual_model']==config.model_id:
                    assessment=('EXACT_MATCH' if exact and row['task_class']==task_class else
                        'NEAR_MATCH' if row['task_class']==task_class and operation is not None and row.get('operation')==operation else
                        'WEAK_PRIOR' if row['task_class']==task_class else 'INSUFFICIENT')
                    scope_evidence.append({'config':name,'assessment':assessment,'fresh':fresh,
                        'support':row['routing_support'],'confidence':row.get('confidence','UNKNOWN'),
                        'contradictions':row['contradictions'],'evidence_refs':row['evidence_refs']})
                if (row['task_class']==task_class and row['provider_id']==config.model and
                    row['actual_model']==config.model_id and row['config_hash']==h and
                    exact and fresh and row['routing_support']>=minimum_support and not row['contradictions'] and row['accepted']>0):
                    candidates.append((row['accepted']/row['qualified_attempts'],name,row))
        candidates.sort(key=lambda x:(-x[0],x[1]))
        # A tie is not evidence to displace the main Agent's default.
        chosen=candidates[0] if candidates and (len(candidates)==1 or candidates[0][0]>candidates[1][0]) else None
        return {'selected_config':chosen[1] if chosen else default,'task_class':task_class,
            'scope_assessment':'EXACT_MATCH' if chosen else 'INSUFFICIENT',
            'candidate_scope_evidence':scope_evidence,
            'scope_match':'EXACT' if chosen else 'INSUFFICIENT_EVIDENCE','operation':operation,'capability_scope':capability_scope,
            'reason_summary':'checked task-class evidence meets support bound' if chosen else 'insufficient or conflicting support; retain Agent default',
            'evidence_refs':chosen[2]['evidence_refs'] if chosen else [],'snapshot_hash':snapshot['snapshot_hash'],
            'scope':'bounded executor selection; project-level choices remain with Agent'}

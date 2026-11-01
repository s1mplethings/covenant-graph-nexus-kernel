"""Production metric projection from resolved run evidence; no model calls."""
import copy
import json
from decimal import Decimal
from cgkn.execution import BlockExecutionResult
from cgkn.state.acceptance import GoalAcceptance, identity
from cgkn.state.provenance import ProvenanceGate, ProvenanceError
from .effectiveness import effectiveness, task_cost, task_time


def trusted_effectiveness(store, project_id, run_id, sample_refs):
    gate=ProvenanceGate(store,project_id,run_id);binding=gate.binding()
    cfg=binding['configuration'];accepted=[];excluded=[];chains=[]
    current=GoalAcceptance(store,project_id,run_id,binding['requirements'],binding['checker_bindings'])
    resolved=[]
    for ref in sample_refs:
        try:
            row=gate.resolve(ref,'MetricRevision');resolved.append((ref,row))
        except ProvenanceError as exc:excluded.append({'ref':ref,'status':exc.status,'reason':exc.reason})
    latest=max((r['revision'] for _,r in resolved),default=0)
    for ref,row in resolved:
        try:
            if row['task_id']!=binding['logical_task_id'] or row['configuration']!=cfg:
                raise ProvenanceError('INVALID_PROVENANCE','task/configuration mismatch')
            snap=gate.resolve(row['acceptance_ref'],'AcceptanceSnapshot')
            state=snap['state']
            if state['requirements']!=binding['requirements'] or state['checker_bindings']!=binding['checker_bindings']:
                raise ProvenanceError('INVALID_PROVENANCE','snapshot original bindings mismatch')
            known={r['receipt_hash']:r for r in current.data['checks']}
            if any(known.get(r['receipt_hash'])!=r for r in state['checks']):
                raise ProvenanceError('INVALID_PROVENANCE','snapshot contains unrecorded/altered checks')
            projection=copy.copy(current);projection.data=state
            view=projection.view(reload=False)
            for goal in view['goals']:
                ev=goal.get('evidence')
                if not ev:raise ProvenanceError('INSUFFICIENT_EVIDENCE','missing effective goal evidence')
                path=gate.root/'attempts'/ev['node_id']/(ev['attempt_id']+'.json')
                raw=json.loads(path.read_text(encoding='utf-8'))
                if identity(raw)!=ev['receipt_hash']:raise ProvenanceError('INVALID_PROVENANCE','receipt hash mismatch')
                report=gate.verify_check(BlockExecutionResult.from_dict(raw),goal,{k:state['subjects'][k] for k in goal['subject_refs']})
                if report['status']!='TRUSTED':raise ProvenanceError(report['status'],report['reason'])
                chains.append(report['chain'])
            if row['revision']==latest and state!=current.data:
                raise ProvenanceError('STALE','latest revision does not match current acceptance')
            if row['revision']==latest and view['hard_verdict']!=current.view()['hard_verdict']:
                raise ProvenanceError('STALE','current artifact differs from accepted snapshot')
            y={'VERIFIED':1,'FAILED':0}.get(view['hard_verdict'])
            if row['business']!=y or row['delivery']==1 and not view['complete']:
                raise ProvenanceError('CONFLICT','declared outcome differs from acceptance authority')
            timing=gate.resolve(row['time_ref'],'TaskTiming')
            if timing['logical_task_id']!=row['task_id']:raise ProvenanceError('INVALID_PROVENANCE','timing task mismatch')
            times=task_time(**timing['measurement'])
            charges=[];models=[]
            worker_artifacts={}
            worker_versions=[]
            seen_calls=set()
            for provider_ref in row['provider_refs']:
                provider=gate.resolve(provider_ref,'ProviderWitness')
                request=json.loads(gate.resolve(provider['request_ref']))
                response=json.loads(gate.resolve(provider['response_ref']))
                if request['identity']!=response['identity'] or request['identity']!=provider['call_id']:
                    raise ProvenanceError('INVALID_PROVENANCE','provider request/response identity mismatch')
                if provider['logical_task_id']!=row['task_id']:
                    raise ProvenanceError('INVALID_PROVENANCE','provider logical task mismatch')
                execution=json.loads(gate.resolve(provider['execution_ref']))
                if execution['usage'].get('request_id')!=response['request_id'] or execution['usage'].get('model')!=response['model']:
                    raise ProvenanceError('INVALID_PROVENANCE','provider receipt not bound to worker execution')
                if binding.get('require_artifact_lineage'):
                    if json.loads(response['text'])!=execution['metadata'].get('proposal'):
                        raise ProvenanceError('INVALID_PROVENANCE','worker proposal differs from provider output')
                    worker_artifacts.update(execution['metadata'].get('artifact_hashes',{}))
                    worker_versions.append(execution['metadata'].get('artifact_hashes',{}))
                    if not timing['ready_unix']<=request['started_at']<=response['ended_at']<=timing['finished_unix']:
                        raise ProvenanceError('INVALID_PROVENANCE','provider timing outside full task interval')
                seen_calls.add(provider['call_id'])
                model=response.get('routing',{})
                requested=request['config'].get('model_id')
                actual=model.get('actual_model')
                bound=requested  # Explicit outbound binding, not inferred from a Provider alias.
                if model.get('identity_status')!='MATCH' or model.get('requested_model')!=requested or not actual or not bound or actual!=response['model'] or actual!=cfg['actual_model'] or requested!=actual:
                    raise ProvenanceError('INSUFFICIENT_EVIDENCE','UNCONFIRMED_MODEL_IDENTITY')
                if request['config']['model']!=binding['provider_id']:
                    raise ProvenanceError('INVALID_PROVENANCE','provider binding mismatch')
                models.append({'requested':requested,'bound':bound,'actual':actual,'provider':binding['provider_id'],'request_id':response['request_id']})
                usage=response.get('usage',{})
                inp=usage.get('input_tokens',usage.get('prompt_tokens'));out=usage.get('output_tokens',usage.get('completion_tokens'))
                price=binding['pricing']
                known=all(type(n) is int and n>=0 for n in (inp,out))
                amount=(Decimal(inp)*Decimal(str(price['input_per_million']))+Decimal(out)*Decimal(str(price['output_per_million'])))/Decimal(1000000) if known else None
                charges.append({'call_id':provider['call_id'],'amount':str(amount) if amount is not None else None,'outcome':'KNOWN' if known else 'UNKNOWN','cost_kind':'usage_based_estimate','currency':price['currency'],'price_version':price['version']})
            if not models:raise ProvenanceError('INSUFFICIENT_EVIDENCE','no actual provider evidence')
            if binding.get('require_artifact_lineage'):
                expected_calls=set()
                for path in (gate.root/'provider_calls').glob('*/request.json'):
                    request=json.loads(path.read_text(encoding='utf-8'))
                    if request['started_at']<=timing['finished_unix']:expected_calls.add(request['identity'])
                for imported in binding.get('imported_request_refs',[]):
                    request=json.loads(gate.resolve(imported))
                    if request['started_at']<=timing['finished_unix']:expected_calls.add(request['identity'])
                if seen_calls!=expected_calls:raise ProvenanceError('INSUFFICIENT_EVIDENCE','task request history omitted or includes future call')
                if row.get('fault_injection_ref'):
                    fault=gate.resolve(row['fault_injection_ref'],'FaultInjection')
                    if fault['after_subjects']!=state['subjects'] or fault['before_subjects'] not in worker_versions:
                        raise ProvenanceError('INVALID_PROVENANCE','host fault injection lineage mismatch')
                elif not any(all(artifacts.get(k)==v for k,v in state['subjects'].items()) for artifacts in worker_versions):
                    raise ProvenanceError('INVALID_PROVENANCE','candidate not bound to actual worker output')
            money=task_cost(charges,currency=binding['pricing']['currency'],price_version=binding['pricing']['version'])
            metric={k:row[k] for k in ['task_id','configuration','revision','delivery','business']}
            if row['revision']>1:metric['supersedes']=row['supersedes']
            metric.update(model_confirmed=True,acceptance_ref=row['acceptance_ref'],duration=times['complete_duration'],cost=float(money['complete_total']) if money['complete_total'] is not None else None,first_pass=row.get('first_pass'),attempt_count=len(charges),repair_count=row.get('repair_count',0),additional_provider_attempts=max(0,len(charges)-1),evaluator_intervention=binding.get('continuation'),time_breakdown=times,cost_evidence=money,models=models,completion=view['completion'],evidence_coverage=view['evidence_coverage'],sample_origin='host_fault_injection' if row.get('fault_injection_ref') else 'provider_execution')
            accepted.append(metric)
        except ProvenanceError as exc:excluded.append({'ref':ref,'status':exc.status,'reason':exc.reason})
        except (KeyError,ValueError,TypeError,OSError) as exc:excluded.append({'ref':ref,'status':'INVALID_PROVENANCE','reason':str(exc)})
    # A rejected current revision cannot silently expose the older success.
    invalid_current=any(r['revision']==latest and not any(a['revision']==latest for a in accepted) for _,r in resolved)
    if invalid_current:accepted=[]
    if accepted:
        initial=min(accepted,key=lambda a:a['revision'])
        first=(initial['business']==1) if initial['revision']==1 and initial['sample_origin']=='provider_execution' else None
        for item in accepted:item['first_pass']=first
    try:
        report=effectiveness(accepted,task_ids=[binding['logical_task_id']],configuration=cfg,**binding['metrics'])
    except ValueError as exc:
        excluded.append({'status':'CONFLICT','reason':str(exc)})
        report=effectiveness([],task_ids=[binding['logical_task_id']],configuration=cfg,**binding['metrics'])
    report.update(provenance_mode='VERIFIED_FILE_RUN_STORE',excluded=excluded,n_excluded=len(excluded),resolved_chains=chains,
                  sample_limit='样本极少，不能形成稳定模型排名',cost_kind='usage_based_estimate_not_supplier_invoice')
    latest_rows=[max((a for a in accepted if a['task_id']==task),key=lambda a:a['revision']) for task in report['settled_task_ids']]
    report['mean_active_time']=sum(a['time_breakdown']['active_execution_time'] for a in latest_rows)/len(latest_rows) if latest_rows else None
    report['current_samples']=latest_rows
    report['protocol_status']='EVALUATOR_INTERVENTION' if binding.get('continuation') else 'AS_RECORDED'
    report['eligible_for_clean_protocol_calibration']=bool(latest_rows) and not binding.get('continuation') and not excluded
    if binding.get('continuation'):
        report['calibration']='PROVISIONAL_EVALUATOR_CORRECTED_OBSERVATION'
        if report['status']=='COMPUTABLE':report['status']='PROVISIONAL'
    if excluded and report['status']=='COMPUTABLE':report['status']='PROVISIONAL'
    return report

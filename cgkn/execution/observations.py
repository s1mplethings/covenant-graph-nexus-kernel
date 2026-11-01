"""Explicit evidence types and public projections over the existing run store.

Only json_document decodes JSON. Raw bytes and coordinator-declared structured
fields are separate; previews are never evidence. No evaluator filesystem scan.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from cgkn.execution.contracts import utc_now
from cgkn.state.acceptance import identity
from cgkn.state.provenance import reference, file_hash

TYPES=frozenset({'process_result','command_result','stdout_text','stderr_text','file_bytes','file_text','state_snapshot','json_document','http_result','database_result','checker_result','artifact_result','unknown_observation'})
FORBIDDEN_PUBLIC=frozenset({'argv','command','source','checker_source','hidden_input','hidden_answer','expected_hidden','injection','private','raw','stdout','stderr'})

class ObservationError(ValueError):
    def __init__(self,message,raw_ref=None):
        self.raw_ref=raw_ref
        super().__init__(message)

class Observations:
    def __init__(self,store,project_id,run_id):
        self.store=store;self.project_id=project_id;self.run_id=run_id
        self.root=store.run_dir(project_id,run_id)

    def record(self,raw,*,observation_type,producer,subject,node_id=None,attempt_id=None,
               encoding='utf-8',media_type='text/plain',structured=None,argv=None,created_at=None):
        if not isinstance(raw,(bytes,str)) or not producer or not isinstance(subject,dict) or not subject:
            raise ValueError('raw bytes/text, producer and subject identity required')
        if argv is not None and observation_type not in {'process_result','command_result'}:
            raise ValueError('argv only belongs to process/command observations')
        content=raw.encode(encoding) if isinstance(raw,str) else raw
        h=hashlib.sha256(content).hexdigest();path=self.root/'observations/raw'/(h+'.blob')
        self.store.immutable_blob(path,content);ref=reference(self.store.root,path)
        fields=json.loads(json.dumps(structured or {},ensure_ascii=False,allow_nan=False))
        if not isinstance(fields,dict):raise ObservationError('structured fields must be a mapping',ref)
        kind=observation_type if observation_type in TYPES else 'unknown_observation';error=None
        if kind=='json_document':
            try:fields['document']=json.loads(content.decode(encoding))
            except (ValueError,UnicodeError) as exc:error={'classification':'HARNESS','code':'INVALID_DECLARED_JSON','message':type(exc).__name__}
        doc={'kind':'TypedObservation','schema_version':'1.0','observation_type':kind,'declared_type':observation_type,
             'producer':producer,'project_id':self.project_id,'run_id':self.run_id,'node_id':node_id,'attempt_id':attempt_id,
             'subject':subject,'raw_ref':ref,'encoding':encoding,'media_type':media_type,'created_at':created_at or utc_now(),
             'integrity_hash':h,'size_bytes':len(content),'structured':fields,'normalization_error':error,
             'preview':content[:1024].decode(encoding,errors='replace') if encoding!='binary' else content[:128].hex(),
             'preview_truncated':len(content)>(128 if encoding=='binary' else 1024)}
        if argv is not None:doc['argv']=list(argv)
        doc['observation_id']=identity(doc)
        target=self.root/'observations/typed'/(doc['observation_id']+'.json');self.store.immutable_json(target,doc)
        return reference(self.store.root,target)

    def resolve(self,ref):
        def bytes_at(r):
            p=self.store.root/Path(r['path'])
            if Path(r['path']).is_absolute() or '..' in Path(r['path']).parts or not p.resolve().is_relative_to(self.root):raise ObservationError('reference outside run',r)
            if any(x.is_symlink() for x in [p,*p.parents] if x.is_relative_to(self.store.root)):raise ObservationError('symlink observation',r)
            if file_hash(p)!=r['sha256']:raise ObservationError('evidence hash mismatch',r)
            return p.read_bytes()
        try:
            doc=json.loads(bytes_at(ref));ident=doc.pop('observation_id')
            if identity(doc)!=ident or doc['kind']!='TypedObservation' or doc['run_id']!=self.run_id or doc['project_id']!=self.project_id:raise ObservationError('observation identity mismatch',ref)
            doc['observation_id']=ident;raw=bytes_at(doc['raw_ref'])
            if hashlib.sha256(raw).hexdigest()!=doc['integrity_hash']:raise ObservationError('raw integrity mismatch',doc['raw_ref'])
            return doc
        except (OSError,KeyError,ValueError) as exc:
            if isinstance(exc,ObservationError):raise
            raise ObservationError('unresolvable observation: '+type(exc).__name__,ref) from exc

    def public_feedback(self,refs,*,requirement_id,goal,current_object,expected,public_fields,
                        failure_domain='UNKNOWN',reason='UNKNOWN/UNRESOLVED'):
        if not requirement_id or not goal or not current_object or not expected:raise ValueError('requirement, goal, current object and public expectation required')
        if failure_domain not in {'BUSINESS','HARNESS','TRANSPORT','UNKNOWN','NONE'}:raise ValueError('invalid failure domain')
        if any(k in FORBIDDEN_PUBLIC or k.startswith('_') or '.' in k for k in public_fields):raise ValueError('private/raw fields cannot enter public feedback')
        if not refs:raise ObservationError('no observation evidence')
        actual=[]
        for ref in refs:
            doc=self.resolve(ref)
            if doc['subject']!=current_object:raise ObservationError('stale object observation',doc['raw_ref'])
            if doc['normalization_error']:raise ObservationError('HARNESS: invalid declared JSON',doc['raw_ref'])
            source=doc['structured'].get('document',{}) if doc['observation_type']=='json_document' else doc['structured']
            source=source if isinstance(source,dict) else {}
            selected={k:source[k] for k in public_fields if k in source}
            # Public fields are a trusted coordinator policy, never model supplied.
            if any(isinstance(v,(dict,list)) for v in selected.values()):raise ObservationError('nested values require a separately qualified public projection',doc['raw_ref'])
            actual.append({'observation_id':doc['observation_id'],'observation_type':doc['observation_type'],'facts':selected,'fact_status':'OBSERVED' if selected else 'UNKNOWN','evidence_ref':ref,'raw_ref':doc['raw_ref']})
        result={'kind':'RuntimeFeedback','requirement_id':requirement_id,'goal':goal,'current_object':current_object,
                'expected':expected,'actual':actual,'evidence_refs':refs,'failure_domain':failure_domain,'reason_summary':reason,
                'authority':'public evidence navigation; not acceptance'}
        result['feedback_id']=identity(result);self.store.immutable_json(self.root/'runtime_feedback'/(result['feedback_id']+'.json'),result)
        return result

def repair_request(feedback,public_contract):
    if feedback.get('kind')!='RuntimeFeedback' or feedback.get('failure_domain')!='BUSINESS':
        raise ObservationError('repair requires an attributed business failure',feedback.get('evidence_refs'))
    return {'public_contract':public_contract,'feedback':feedback,'instruction':'Repair only against the public requirement and observed facts; no private oracle is provided.'}

def failure_domain(result,checker=None):
    """Execution failure is not automatically a model business failure."""
    body=result.as_dict();error=body.get('error') or {};details=error.get('details',{})
    if details.get('outcome_unknown'):return 'UNKNOWN'
    if details.get('failure_domain') in {'TRANSPORT','HARNESS'}:return details['failure_domain']
    if checker is None:return 'UNKNOWN'
    check=checker.as_dict()
    if check['status']!='SUCCEEDED':return 'HARNESS'
    observation=check['outputs'].get('goal_check',{})
    if observation.get('execution')!='VALID':return 'HARNESS'
    return {'FAILED':'BUSINESS','VERIFIED':'NONE'}.get(observation.get('verdict'),'UNKNOWN')

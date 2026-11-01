"""Structured pytest observations; console text and exit zero are not tests.

The caller allocates a fresh report outside the candidate before dispatch.
These observations measure product tests, never independent business acceptance.
"""
from __future__ import annotations
import hashlib
from collections.abc import Mapping
from pathlib import Path
from xml.etree import ElementTree as ET


def read_pytest_report(path, root, exit_code):
    root=Path(root).resolve();path=Path(path)
    result={'kind':'PytestExecutionObservation','status':'INVALID','collected':0,'executed':0,
            'passed':0,'failed':0,'errors':0,'skipped':0,'files':[],'failure_details':[],
            'returncode':exit_code,'temporary_report_path':str(path),'report_sha256':None,'raw_report':None,
            'raw_evidence_location':'enclosing execution receipt: test_observation.raw_report'}
    try:
        raw=path.read_bytes();result.update(report_sha256=hashlib.sha256(raw).hexdigest(),raw_report=raw.decode('utf8'))
        if b'<!DOCTYPE' in raw.upper():raise ValueError('DOCTYPE not allowed in test receipt')
        document=ET.fromstring(raw)
        if document.tag not in {'testsuite','testsuites'}:raise ValueError('unexpected test receipt root')
        cases=document.findall('.//testcase');files={}
        for case in cases:
            value=case.get('file')
            if not value:raise ValueError('test case source binding missing')
            source=(root/value).resolve()
            if source==root or root not in source.parents or not source.is_file():
                raise ValueError('test source is outside current candidate or missing')
            files[source.relative_to(root).as_posix()]=hashlib.sha256(source.read_bytes()).hexdigest()
            key='failed' if case.find('failure') is not None else 'errors' if case.find('error') is not None else 'skipped' if case.find('skipped') is not None else 'passed'
            result[key]+=1
            if key!='passed':
                tag={'failed':'failure','errors':'error','skipped':'skipped'}[key]
                detail=case.find(tag)
                diagnostic=(detail.get('message','')+'\n'+(detail.text or '')).strip()
                result['failure_details'].append({
                    'test_id':case.get('classname','')+'::'+case.get('name',''),
                    'test_file':source.relative_to(root).as_posix(),
                    'source_sha256':files[source.relative_to(root).as_posix()],
                    'outcome':key,'reported_type':detail.get('type'),
                    'diagnostic':diagnostic[:4096],
                    'diagnostic_truncated':len(diagnostic)>4096})
        result.update(collected=len(cases),executed=result['passed']+result['failed']+result['errors'],
                      files=[{'path':p,'sha256':h} for p,h in sorted(files.items())])
        result['status']='PASS' if exit_code==0 and result['passed']>0 and not any(result[k] for k in ('failed','errors','skipped')) else 'FAIL'
    except (OSError,ValueError,ET.ParseError) as exc:
        result['error']={'type':type(exc).__name__,'message':str(exc)}
    return result


def public_test_feedback(observation):
    """Expose measured public test facts, not an inferred cause or private oracle.

    Only the candidate-bound product-test report is accepted. Diagnostic text is
    a bounded view; the immutable enclosing receipt retains the complete XML.
    """
    if (observation.get('kind')!='PytestExecutionObservation'
            or observation.get('status') not in {'PASS','FAIL'}
            or not observation.get('report_sha256')):
        raise ValueError('Valid current product-test evidence required for public feedback')
    def mutable(value):
        if isinstance(value,Mapping):return {key:mutable(item) for key,item in value.items()}
        if isinstance(value,(tuple,list)):return [mutable(item) for item in value]
        return value
    return {key:mutable(observation[key]) for key in (
        'status','collected','executed','passed','failed','errors','skipped','files','failure_details')} | {
        'failure_domain':'BUSINESS' if observation['status']=='FAIL' else None,
        'root_cause':'UNRESOLVED' if observation['status']=='FAIL' else None,
        'report_sha256':observation['report_sha256'],
        'raw_report_ref':{'sha256':observation['report_sha256'],
                          'location':observation['raw_evidence_location']}}

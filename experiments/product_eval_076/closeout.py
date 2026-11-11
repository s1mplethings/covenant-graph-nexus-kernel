"""Read-only evidence reconciliation; never grades unexecuted product obligations."""
import argparse
import hashlib
import json
import pathlib
import subprocess
from datetime import datetime, timezone


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--root', required=True, type=pathlib.Path)
    p.add_argument('--output', required=True, type=pathlib.Path)
    args = p.parse_args()
    root = args.root.resolve()
    admission = json.loads((root/'dev-admission.json').read_text())
    ledger = json.loads((root/'global-provider-budget.json').read_text())
    rows = []
    for run_id in admission['runs']:
        d = root/run_id
        result = json.loads((d/'dev-result.json').read_text())
        frozen = root/('frozen-'+run_id)
        manifest = json.loads((frozen/'manifest.json').read_text())
        freeze = json.loads((frozen/'freeze.json').read_text())
        assert freeze['exit_code'] == 0 and freeze['development_container_absent']
        calls = [c for c in ledger['calls'] if c['run_id'] == run_id]
        assert len(calls) == result['calls']
        actual_input = actual_output = unknown = 0
        models = set()
        for raw_path in (d/'provider').glob('*.result.json'):
            raw = json.loads(raw_path.read_text(encoding='utf-8'))
            if raw.get('upstream_model'): models.add(raw['upstream_model'])
            usage = raw.get('usage') or {}
            i, o = usage.get('prompt_tokens'), usage.get('completion_tokens')
            if isinstance(i, int) and isinstance(o, int):
                actual_input += i
                actual_output += o
            else: unknown += 1
        rows.append({'run_id':run_id, 'route':result['receipt']['route'],
                     'end':result['receipt']['result'], 'requests':len(calls),
                     'actual_known_input_tokens':actual_input,
                     'actual_known_output_tokens':actual_output,
                     'unknown_usage_calls':unknown,
                     'upper_tariff_cost_cny':result['upper_tariff_cost_cny'],
                     'provider_seconds':sum(c.get('duration_seconds') or 0 for c in calls),
                     'actual_response_models':sorted(models),
                     'candidate_manifest':str(frozen/'manifest.json'),
                     'candidate_hash':freeze['candidate_zip_sha256'],
                     'candidate_files':[f['path'] for f in manifest['files']],
                     'audit':result['audit'],
                     'host_semantic_assistance_count':result['host_semantic_assistance_count'],
                     'formal_product_scores':None})
    assert len(rows) == 8
    active = subprocess.check_output(['docker','ps','-a','--filter','name=eval076-','--format','{{.Names}}'], text=True).strip()
    if active: raise RuntimeError('Remaining evaluator containers: '+active)
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    matrix_bytes = (root/'preflight-20261027/matrix.json').read_bytes()
    matrix = json.loads(matrix_bytes)
    assert len(matrix['rows']) == 32 and all(r['status']=='NOT_RUN' for r in matrix['rows'])
    (out/'matrix.json').write_bytes(matrix_bytes)
    code = pathlib.Path(__file__).parent
    hashes = {f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in code.iterdir() if f.is_file()}
    summary = {'created_at':datetime.now(timezone.utc).isoformat(),
               'status':'DEV_LIMIT_EXHAUSTED_FORMAL_NOT_FROZEN',
               'head':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
               'source_hashes':hashes, 'formal_started':0, 'formal_completed':0,
               'formal_not_run':32, 'dev_started':len(rows), 'dev_completed':len(rows),
               'rows':rows, 'ledger_totals':ledger['totals'],
               'actual_bill':'NOT_QUERIED', 'remaining_evaluator_containers':[],
               'matrix_sha256':hashlib.sha256(matrix_bytes).hexdigest(),
               'missing_formal_prerequisites':['launchable equal TAKEOVER snapshots',
                  'task-specific observable obligation mappings and private oracles',
                  'validated product evaluator and negative variants',
                  'successful full DEV calibration', 'formal freeze and runner admission'],
               'public_publishing':'NOT_AUTHORIZED', 'human_review':'NOT_STARTED'}
    (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'dev':len(rows),'requests':sum(r['requests'] for r in rows),
                      'cost_upper_cny':sum(r['upper_tariff_cost_cny'] for r in rows),
                      'formal_started':0,'summary':str(out/'summary.json')}))


if __name__ == '__main__': main()

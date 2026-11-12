"""Collect only PID-verified pytest artifacts and summarize sampled resources."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tempfile

from jsonschema import Draft202012Validator
import psutil

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'artifacts/leanloop-v1'


def read(path): return json.loads(path.read_text(encoding='utf-8'))
def write(path,value): path.write_text(json.dumps(value,indent=2),encoding='utf-8')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('label');args=parser.parse_args()
    run=OUT/args.label;start=read(run/'start.json');roots=[]
    temp=Path(tempfile.gettempdir())/'pytest-of-sunom'
    for marker in temp.glob('pytest-*/.lock'):
        if marker.read_text().strip()==str(start['pid']):roots.append(str(marker.parent.resolve()))
    saved=run/'temp-roots.json'
    if roots:write(saved,{'pid':start['pid'],'roots':roots,'verification':'pytest .lock contains exact suite PID'})
    elif saved.exists():roots=read(saved)['roots']
    if not (run/'completion.json').exists():
        print(json.dumps({'phase':'running','verified_temp_roots':roots}));return
    assert read(run/'completion.json')['postprocessing']=='complete'
    samples=[json.loads(line) for line in (run/'resources.jsonl').read_text().splitlines()]
    summary={'samples':len(samples),'sampled_seconds':samples[-1]['epoch']-samples[0]['epoch'],
        'peak_owned_process_count':max(len(r['processes']) for r in samples),
        'current_test_labels_observed':len({r['test'] for r in samples}),
        'completion':read(run/'resource-completion.json')}
    for key,field in [('threads','threads'),('handles','handles'),('rss_bytes','rss')]:
        summary['peak_owned_'+key]=max(sum(p[field] for p in r['processes']) for r in samples)
    write(run/'resource-summary.json',summary)
    destination=OUT/('entrypoint-reports' if args.label=='candidate-full' else args.label+'-reports')
    destination.mkdir(exist_ok=True);inventory=[];errors=[];steps=0;excluded=[]
    validator=Draft202012Validator(read(OUT/'step-observation-schema.json'))
    for root in map(Path,roots):
        for source in sorted(root.rglob('lean-report.json')):
            if source.is_symlink():
                excluded.append({'source':str(source),'reason':'symlink test fixture; target not copied'});continue
            try:doc=read(source)
            except (OSError,ValueError):
                excluded.append({'source':str(source),'reason':'unreadable/malformed fixture'});continue
            if not isinstance(doc,dict) or not {'steps','task_profile','observed_task_status','schema_version'}.issubset(doc):
                excluded.append({'source':str(source),'reason':'not a complete emitted report; synthetic or corrupt fixture'});continue
            target=destination/root.name/source.relative_to(root);target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(source,target)
            markdown=source.with_suffix('.md')
            if markdown.is_file() and not markdown.is_symlink() and markdown.resolve().is_relative_to(root):
                shutil.copy2(markdown,target.with_suffix('.md'))
            doc=read(target)
            inventory.append({'source':str(source),'copy':str(target.relative_to(OUT)),
                'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'profile':doc['task_profile'],
                'status':doc['observed_task_status'],'steps':len(doc['steps'])})
            for row in doc['steps']:
                steps+=1
                errors.extend({'file':str(target),'error':e.message} for e in validator.iter_errors(row))
    write(destination/'inventory.json',inventory)
    write(destination/'excluded-fixtures.json',excluded)
    write(OUT/'schema-validation.json',{'label':args.label,'reports':len(inventory),'steps':steps,'errors':errors,
        'profiles':sorted({r['profile'] for r in inventory})})
    traces={}
    for label in ['baseline-full',args.label]:
        traces[label]={}
        for source in sorted((OUT/label).glob('watchdog-stacks-*.log')):
            text=source.read_text(encoding='utf-8',errors='replace')
            traces[label][source.name]={'bytes':source.stat().st_size,
                'CreateProcess_samples':text.count('line 1551 in _execute_child'),
                'listener_samples':text.count('line 65 in listeners')}
    write(OUT/'watchdog-investigation/final-paired-stacks.json',traces)
    retained=[]
    for root in map(Path,roots):
        for folder in root.glob('test_real_mihomo*'):
            if folder.is_symlink():continue
            for name in ('config.yaml','watchdog.json','state/watchdog.jsonl','recovery-evidence.json','fallback-evidence.json'):
                source=folder/name
                if not source.is_file() or source.is_symlink() or not source.resolve().is_relative_to(root):continue
                target=OUT/'watchdog-investigation'/args.label/folder.name/name
                target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
                retained.append(str(target.relative_to(OUT)))
    live=[];inaccessible=0
    for process in psutil.process_iter():
        try:
            args_text=' '.join(process.cmdline()).casefold()
            if any(str(Path(root)).casefold() in args_text for root in roots):
                live.append({'pid':process.pid,'created':process.create_time(),'name':process.name()})
        except psutil.Error:inaccessible+=1
    write(run/'post-run-owned-path-scan.json',{'verified_roots':roots,'matching_live_processes':live,
        'inaccessible_processes':inaccessible,'limitation':'Read-only supplement; processes without a verified temp path in arguments are not classified by this scan.',
        'retained_watchdog_files':retained})
    print(json.dumps({'resources':summary,'reports':len(inventory),'schema_errors':len(errors)}))


if __name__=='__main__':main()

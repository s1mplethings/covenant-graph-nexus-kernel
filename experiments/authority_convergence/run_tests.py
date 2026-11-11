"""Identical offline regression environment; persist pytest exit before processing."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'artifacts/execution-authority-convergence'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, default=ROOT)
    parser.add_argument('--label', required=True)
    parser.add_argument('--profile', action='store_true')
    parser.add_argument('tests', nargs='*')
    args = parser.parse_args()
    run = OUT / args.label
    run.mkdir(parents=True, exist_ok=True)
    guard = OUT / 'offline_guard'
    guard.mkdir(exist_ok=True)
    (guard / 'sitecustomize.py').write_text('''import sys, os, ipaddress, json, faulthandler
from pathlib import Path
out=Path(os.environ['CGKN_TRIAL_EVIDENCE'])
def guard(event,args):
    if event != 'socket.connect' or not isinstance(args[1],tuple):return
    host=args[1][0]
    try: allowed=ipaddress.ip_address(host).is_loopback
    except ValueError: allowed=host=='localhost'
    if not allowed:
        with (out/('blocked-'+str(os.getpid())+'.jsonl')).open('a') as f:f.write(json.dumps({'host':host,'port':args[1][1]})+'\\n')
        raise OSError('OFFLINE_NETWORK_DENIED')
sys.addaudithook(guard)
if any(str(a).endswith('network_watchdog.py') for a in sys.argv):
    trace=(out/('watchdog-stacks-'+str(os.getpid())+'.log')).open('w')
    faulthandler.dump_traceback_later(2,repeat=True,file=trace)
''', encoding='utf-8')
    env = dict(os.environ, PYTHONUTF8='1', PYTHONIOENCODING='utf-8', PYTHONDONTWRITEBYTECODE='1',
               PYTEST_DISABLE_PLUGIN_AUTOLOAD='1', CGKN_PYTEST_PROGRESS='0',
               CGKN_APPLICATION_PROFILE=str(OUT / 'offline-profile.json'),
               CGKN_TRIAL_EVIDENCE=str(run), PYTHONPATH=str(guard) + os.pathsep + str(args.source))
    command = [sys.executable, '-X', 'utf8', '-m', 'pytest', '-q', *args.tests, '--junitxml=' + str(run / 'results.xml')]
    if args.profile:
        command = [sys.executable, '-X', 'utf8', '-m', 'cProfile', '-o', str(run/'profile.pstats'), '-m', 'pytest', '-q', *args.tests, '--junitxml=' + str(run/'results.xml')]
    start = time.time()
    with (run / 'pytest.log').open('wb') as log:
        proc = subprocess.Popen(command, cwd=args.source, env=env, stdout=log, stderr=subprocess.STDOUT)
        (run / 'start.json').write_text(json.dumps({'pid':proc.pid,'source':str(args.source),'command':command,'epoch':start,'environment':'shared offline legacy profile, external socket guard, identical watchdog stack timer'},indent=2))
        code = proc.wait()
    receipt = {'pytest_exit_code':code,'wrapper_exit_code':code,'seconds':time.time()-start,'postprocessing':'pending'}
    (run / 'completion.json').write_text(json.dumps(receipt,indent=2))
    # Raw credential assertions are evidence of failure, not publishable values.
    import re
    xml = run / 'results.xml'
    names = []
    if xml.exists():
        tree = ET.parse(xml)
        for case in tree.findall('.//testcase'):
            if any(s in case.get('classname','') for s in ('test_provider_credentials','test_qwen_provider_alignment')):
                for node in case:
                    if node.tag in ('failure','error'):
                        names.append(case.get('name','').split('[')[0])
                        node.set('message','Credential assertion details redacted')
                        node.text='Credential assertion details redacted; raw hash retained.'
        receipt['raw_xml_sha256']=hashlib.sha256(xml.read_bytes()).hexdigest()
        tree.write(xml,encoding='utf-8',xml_declaration=True)
    log = run / 'pytest.log'
    raw=log.read_bytes();receipt['raw_log_sha256']=hashlib.sha256(raw).hexdigest()
    chunks=re.split(r'(?m)^(?=_{3,} .* _{3,}\s*$)',raw.decode('utf-8',errors='replace'))
    for i,chunk in enumerate(chunks):
        header=chunk.splitlines()[0] if chunk else ''
        if header.startswith('___') and any(n in header for n in names):
            tail=re.search(r'(?m)^={3,} ',chunk)
            chunks[i]=header+'\n[Credential assertion traceback redacted]\n'+(chunk[tail.start():] if tail else '')
    log.write_text(''.join(chunks),encoding='utf-8',newline='\n')
    receipt['postprocessing']='complete'
    (run / 'completion.json').write_text(json.dumps(receipt,indent=2))
    print(json.dumps(receipt))
    return code


if __name__ == '__main__':
    raise SystemExit(main())

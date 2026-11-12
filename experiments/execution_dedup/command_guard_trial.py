"""Same CommandExecutor and fake process boundary; never executes dangerous argv."""
import json
from pathlib import Path
import re
import subprocess
import sys
import types

from cgkn.execution import BlockExecutionRequest, TaskContext

OUT=Path(__file__).resolve().parents[2]/'artifacts/substrate-replacement-v2'
OLD=Path('D:/CGKN/.service_worktree/substrate-migration-20261101/cgkn/executors/local.py')
SOURCE='if any(token in rendered for token in self._blocked):'
REPLACEMENT='if any(re.search(r"(?<!\\w)" + re.escape(token) + r"(?!\\w)", rendered) for token in self._blocked):'


def load(candidate):
    text=OLD.read_text()
    if candidate:text=text.replace(SOURCE,REPLACEMENT).replace('import pathlib','import re\nimport pathlib',1)
    module=types.ModuleType('cgkn.executors._guard_trial_'+str(candidate))
    module.__package__='cgkn.executors';sys.modules[module.__name__]=module
    exec(compile(text,str(OLD),'exec'),module.__dict__)
    return module.CommandExecutor


def main():
    denied=[['rm','-rf','/'],['rmdir','/s','C:\\Windows'],['del','file'],['format','C:'],
            ['shutdown','/s'],['reboot'],['diskpart'],['git','clean','-fd'],['git','reset','--hard'],
            ['cmd','/c','del file'],['powershell','-Command','shutdown /s'],['/bin/rm','file']]
    allowed=[[sys.executable,'-m','pytest','--junitxml=C:/Temp/cgkn-pycache-xo_lurm4/current-tests.xml'],
             [sys.executable,'-m','pytest','test_model.py'],[sys.executable,'-c',"print('ok')"]]
    classes={'old':load(False),'candidate':load(True)};rows=[];real_run=subprocess.run
    try:
        for expected,commands in ((False,denied),(True,allowed)):
            for argv in commands:
                row={'argv':argv,'expected_dispatch':expected}
                for label,cls in classes.items():
                    calls=[]
                    def fake(*args,**kwargs):calls.append(args);return subprocess.CompletedProcess(args[0],0,'ok','')
                    subprocess.run=fake
                    request=BlockExecutionRequest(project_id='p',run_id='r',attempt_id='a',node_id='n',component_ref='c@1',executor_ref='local.command@1',task_context=TaskContext('offline guard check',{'command':argv}))
                    result=cls(OUT).execute(request)
                    row[label]={'dispatched':bool(calls),'status':result.status.value,'error':result.error.message if result.error else None}
                assert row['candidate']['dispatched']==expected
                if not expected:assert row['old']['dispatched'] is False
                rows.append(row)
    finally:subprocess.run=real_run
    (OUT/'command-guard-trial.json').write_text(json.dumps({'rows':rows,'decision':'MIGRATE','scope':'preserve denied command tokens; correct accidental matches inside longer words. Denylist remains defense-in-depth, not a sandbox. No malicious command executed.'},indent=2))
    print(json.dumps({'cases':len(rows),'dangerous_commands_still_denied':len(denied),'confirmed_old_false_positives':sum(r['expected_dispatch'] and not r['old']['dispatched'] for r in rows)}))


if __name__=='__main__':main()

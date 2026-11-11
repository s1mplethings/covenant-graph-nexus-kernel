"""Small local Mihomo fallback patch; private YAML stays outside the repository."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import time

import yaml

from cgkn.providers.network_health import write_json
from scripts.network_watchdog import controller


def digest(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def patch(config,receipt):
    path=Path(config['proxy_config'])
    doc=yaml.safe_load(path.read_text(encoding='utf-8'))
    if doc.get('tun',{}).get('enable') or doc.get('allow-lan'):
        raise ValueError('DEDICATED_LOOPBACK_CONFIG_REQUIRED')
    names={n['name'] for n in doc.get('proxies',[])}
    if not {'api-primary-node','api-backup-node'}<=names: raise ValueError('EXPECTED_NODES_MISSING')
    backup=path.with_name('config.before-network-'+str(time.time_ns())+'.yaml')
    shutil.copy2(path,backup)  # same private directory and inherited ACL
    groups=[]
    for label,nodes in [('primary',['api-primary-node','api-backup-node']),('backup',['api-backup-node','api-primary-node'])]:
        groups.append(dict(name='api-'+label+'-fallback',type='fallback',proxies=nodes,
            url='https://www.gstatic.com/generate_204',interval=60,lazy=False,timeout=8000,**{'max-failed-times':2}))
    protected={g['name'] for g in groups}
    doc['proxy-groups']=[g for g in doc.get('proxy-groups',[]) if g['name'] not in protected]+groups
    for listener in doc['listeners']:
        if listener['port']==17890: listener['proxy']='api-primary-fallback'
        elif listener['port']==17891: listener['proxy']='api-backup-fallback'
    candidate=path.with_name('config.network-candidate.yaml')
    candidate.write_text(yaml.safe_dump(doc,allow_unicode=True,sort_keys=False),encoding='utf-8')
    checked=subprocess.run([config['executable'],'-t','-d',str(path.parent),'-f',str(candidate)],capture_output=True,timeout=30)
    if checked.returncode: raise RuntimeError('MIHOMO_CONFIG_VALIDATION_FAILED')
    before=digest(path)
    candidate.replace(path)
    result=dict(before_sha256=before,after_sha256=digest(path),backup=str(backup),validation_exit=checked.returncode,
                groups=groups,listeners=[{k:l[k] for k in ('port','proxy')} for l in doc['listeners']],reload='NOT_ATTEMPTED')
    write_json(receipt,result)
    try:
        controller(config,'/configs?force=true','PUT',{'payload':path.read_text(encoding='utf-8')})
        result['reload']='SUCCEEDED'
    except Exception:
        # Restore on failed activation; never output the exception or private content.
        shutil.copy2(backup,path)
        result['reload']='FAILED_RESTORED_FILE'
        raise RuntimeError('RELOAD_FAILED_BACKUP_RESTORED') from None
    finally: write_json(receipt,result)
    return result


def rollback(config,receipt):
    saved=json.loads(Path(receipt).read_text(encoding='utf-8'))
    path=Path(config['proxy_config']); backup=Path(saved['backup'])
    if digest(path)!=saved['after_sha256'] or digest(backup)!=saved['before_sha256']:
        raise ValueError('ROLLBACK_HASH_MISMATCH')
    shutil.copy2(backup,path)
    controller(config,'/configs?force=true','PUT',{'payload':path.read_text(encoding='utf-8')})
    return {'rollback':'SUCCEEDED','sha256':digest(path)}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['apply','rollback'])
    p.add_argument('--config',type=Path,required=True);p.add_argument('--receipt',type=Path,required=True)
    a=p.parse_args(); c=json.loads(a.config.read_text(encoding='utf-8'))
    if a.action=='apply' and a.receipt.exists(): raise ValueError('RECEIPT_ALREADY_EXISTS')
    print(json.dumps((patch if a.action=='apply' else rollback)(c,a.receipt),indent=2))

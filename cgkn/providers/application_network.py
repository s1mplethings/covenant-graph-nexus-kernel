"""Saved CGKN application routing; never changes global environment/networking."""
from __future__ import annotations
import hashlib,json,os,subprocess,sys,time
import logging
from cgkn.providers.evidence_journal import EvidenceJournal
from contextlib import contextmanager
from pathlib import Path
from urllib.request import Request,build_opener,ProxyHandler
ROOT=Path(__file__).resolve().parents[2]
_logged=set()

def normalize_profile_override():
    value=os.environ.get('CGKN_APPLICATION_PROFILE')
    if value:
        path=Path(value)
        os.environ['CGKN_APPLICATION_PROFILE']=str((ROOT/path).resolve())

@contextmanager
def bootstrap_lock(path, *, deadline=None):
    from scripts.network_watchdog import InstanceLock
    until=deadline if deadline is not None else time.monotonic()+18
    while True:
        lock=InstanceLock(path)
        try:
            lock.__enter__()
            break
        except RuntimeError as exc:
            if str(exc)!='WATCHDOG_ALREADY_RUNNING':raise
            if time.monotonic()>until:raise RuntimeError('DOMESTIC_BOOTSTRAP_BUSY_NO_FALLBACK') from None
            time.sleep(.05)
    try:yield
    finally:lock.__exit__(None,None,None)

def settings():
    normalize_profile_override()
    override=os.environ.get('CGKN_APPLICATION_PROFILE')
    marker=ROOT/'.cgkn/agent-kit.json'
    if override:path=Path(override).resolve()
    else:
        try:
            doc=json.loads(marker.read_text(encoding='utf-8')) if marker.exists() else {}
            selected=doc.get('network_profile')
        except (OSError,ValueError,AttributeError):
            raise RuntimeError('CGKN_APPLICATION_NETWORK_CONFIG_MISMATCH') from None
        if not selected:
            selected='config/domestic_application.json'
            if not (ROOT/selected).exists():raise RuntimeError('CGKN_APPLICATION_NETWORK_CONFIG_MISSING')
        path=(ROOT/selected).resolve()
    try:
        doc=json.loads(path.read_text(encoding='utf-8'))
        if doc.get('mode')=='legacy':
            if os.environ.get('CGKN_NETWORK_MODE','').strip().lower()=='domestic':raise ValueError()
            return None
        if doc.get('kind')!='CGKNApplicationNetwork' or doc.get('mode')!='domestic':raise ValueError()
        for key in ('network_config','model_routing','gateway_state_dir','interface_guid','gateway_python'):
            if not isinstance(doc.get(key),str) or not doc[key]:raise ValueError()
        for key in ('network_config','model_routing','gateway_state_dir'):
            doc[key]=str((path.parent/doc[key]).resolve())
        routes=json.loads(Path(doc['network_config']).read_text(encoding='utf-8'))
        routing=json.loads(Path(doc['model_routing']).read_text(encoding='utf-8'))
        if routes.get('network_policy')!='domestic' or routes.get('trust_env') is not False or routes.get('verify_tls') is not True:raise ValueError()
        if routing.get('fallback')!='deny' or routing.get('allowed_providers')!=['qwen','deepseek']:raise ValueError()
        if routing['roles']['agent']['provider_id']!='qwen' or routing['roles']['worker']['provider_id']!='deepseek':raise ValueError()
        for provider in ('qwen','deepseek'):
            route=routes['transport_profiles'][routes['provider_bindings'][provider]]
            if route.get('interface_guid','').lower()!=doc['interface_guid'].lower() or route.get('proxy_url') or route.get('fallback'):raise ValueError()
        requested=os.environ.get('CGKN_NETWORK_MODE','').strip().lower()
        if requested and requested!='domestic':raise ValueError()
        doc['profile_path']=str(path)
        doc['network_sha256']=hashlib.sha256(Path(doc['network_config']).read_bytes()).hexdigest()
        doc['profile_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
        return doc
    except (OSError,ValueError,KeyError,TypeError,AttributeError):
        raise RuntimeError('CGKN_APPLICATION_NETWORK_CONFIG_MISMATCH') from None

def routing_path(default):
    config=settings()
    return Path(config['model_routing']) if config else Path(default)

def process_identity(pid):
    """OS creation time + executable: PID reuse never establishes identity."""
    import psutil
    try:
        p=psutil.Process(int(pid))
        if not p.is_running() or p.status()==psutil.STATUS_ZOMBIE:return {'state':'DEAD'}
        return dict(state='ALIVE',pid=p.pid,created_at=p.create_time(),executable=str(Path(p.exe()).resolve()),
                    argv=p.cmdline(),cwd=p.cwd())
    except psutil.NoSuchProcess:return {'state':'DEAD'}
    except (psutil.AccessDenied,OSError,ValueError):return {'state':'UNKNOWN'}

def _read_pair(config, *, transition_timeout=.4):
    state=Path(config['gateway_state_dir']);until=time.monotonic()+transition_timeout
    while True:
        try:
            info=json.loads((state/'session.json').read_text(encoding='utf-8'))
            status=json.loads((state/'status.json').read_text(encoding='utf-8'))
            if not info.get('session_id') or not status.get('process_created_at'):
                raise RuntimeError('DOMESTIC_LEGACY_SESSION_REQUIRES_CONTROLLED_RESTART')
            keys=('session_id','pid','process_created_at','base_url')
            if all(info.get(key)==status.get(key) for key in keys):return info,status
            reason='DOMESTIC_SESSION_IDENTITY_MISMATCH'
        except FileNotFoundError:
            reason='DOMESTIC_GATEWAY_NO_SESSION'
        except (ValueError,AttributeError,KeyError):
            reason='DOMESTIC_SESSION_PUBLICATION_INVALID'
        if time.monotonic()>=until:raise RuntimeError(reason)
        time.sleep(.02)

def _instance_state(status,config):
    identity=process_identity(status.get('pid',0))
    if identity['state']!='ALIVE':return identity['state']
    if abs(identity['created_at']-float(status['process_created_at']))>.001:return 'OLD_INSTANCE_EXITED_PID_REUSED'
    if Path(identity['executable'])!=Path(config['gateway_python']).resolve():return 'IDENTITY_MISMATCH'
    args=identity.get('argv',[])
    try:
        actual_config=Path(identity['cwd'])/args[args.index('--config')+1]
        actual_state=Path(identity['cwd'])/args[args.index('--state-dir')+1]
        if 'scripts.domestic_gateway' not in args or 'serve' not in args:return 'IDENTITY_MISMATCH'
        if actual_config.resolve()!=Path(config['network_config']) or actual_state.resolve()!=Path(config['gateway_state_dir']):return 'IDENTITY_MISMATCH'
    except (ValueError,IndexError,KeyError):return 'IDENTITY_MISMATCH'
    return 'ALIVE'

def _validate(config,info,status, *, health_timeout=1):
    if not status.get('running') or status.get('network_sha256')!=config['network_sha256'] or status.get('interface_guid','').lower()!=config['interface_guid'].lower():
        raise RuntimeError('DOMESTIC_GATEWAY_CONFIGURATION_MISMATCH')
    from .gateway_client import _loopback_base_url
    base=_loopback_base_url(info['base_url'])
    req=Request(base+'/v1/models',headers={'Authorization':'Bearer '+info['access_token']})
    try:
        with build_opener(ProxyHandler({})).open(req,timeout=health_timeout) as response:
            doc=json.load(response)
        if {row['id'] for row in doc['data']}!={'qwen','deepseek'}:raise ValueError()
    except Exception:raise RuntimeError('DOMESTIC_GATEWAY_TEMPORARILY_UNREACHABLE_NO_RESTART') from None
    return info,status

def _start(config,deadline):
    state=Path(config['gateway_state_dir'])
    # Exclusion is separate from the recovery lock: an alive instance is never replaced.
    from scripts.network_watchdog import InstanceLock
    try:
        with InstanceLock(state/'instance.lock'):pass
    except RuntimeError:raise RuntimeError('DOMESTIC_GATEWAY_INSTANCE_LOCK_HELD_NO_RESTART') from None
    if not Path(config['gateway_python']).is_file():raise RuntimeError('DOMESTIC_GATEWAY_PYTHON_UNAVAILABLE')
    env=dict(os.environ)
    with (state/'startup.stderr.log').open('ab') as errors:
        child=subprocess.Popen([config['gateway_python'],'-X','utf8','-m','scripts.domestic_gateway','serve',
            '--config',config['network_config'],'--state-dir',str(state),
            '--provider-parallelism',str(config.get('provider_parallelism',1))],cwd=ROOT,env=env,
            stdout=subprocess.DEVNULL,stderr=errors,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    while time.monotonic()<deadline:
        try:
            info,status=_read_pair(config,transition_timeout=0)
            if status.get('pid')==child.pid and _instance_state(status,config)=='ALIVE':
                return _validate(config,info,status,health_timeout=min(1,max(.05,deadline-time.monotonic())))
        except RuntimeError:pass
        if child.poll() is not None:raise RuntimeError('DOMESTIC_GATEWAY_START_FAILED_NO_FALLBACK')
        time.sleep(.05)
    raise RuntimeError('DOMESTIC_GATEWAY_START_DEADLINE_NO_FALLBACK')

def session(config, *, autostart=True, timeout=18):
    deadline=time.monotonic()+min(18,max(.1,float(timeout)))
    state=Path(config['gateway_state_dir'])
    try:
        info,status=_read_pair(config)
    except RuntimeError as exc:
        if str(exc)!='DOMESTIC_GATEWAY_NO_SESSION':raise
        info=status=None
    if status:
        existing=_instance_state(status,config)
        if existing=='ALIVE':return _validate(config,info,status)
        if existing not in ('DEAD','OLD_INSTANCE_EXITED_PID_REUSED'):
            raise RuntimeError('DOMESTIC_GATEWAY_PROCESS_'+existing+'_NO_RESTART')
    if not autostart or not config.get('auto_start_gateway'):
        raise RuntimeError('DOMESTIC_GATEWAY_UNAVAILABLE_NO_FALLBACK')
    state.mkdir(parents=True,exist_ok=True)
    with bootstrap_lock(state/'bootstrap.lock',deadline=deadline):
        try:
            fresh,fresh_status=_read_pair(config,transition_timeout=0)
            existing=_instance_state(fresh_status,config)
            if existing=='ALIVE':return _validate(config,fresh,fresh_status)
            if existing not in ('DEAD','OLD_INSTANCE_EXITED_PID_REUSED'):
                raise RuntimeError('DOMESTIC_GATEWAY_PROCESS_'+existing+'_NO_RESTART')
        except RuntimeError as exc:
            if str(exc)!='DOMESTIC_GATEWAY_NO_SESSION':raise
        return _start(config,deadline)

def network_status():
    """Local diagnostic only: no startup, no DNS, no Provider requests."""
    try:
        config=settings()
        if not config:return dict(mode='legacy',state='LEGACY_EXPLICIT_OR_UNCONFIGURED')
        result=dict(mode='domestic',state='CONFIGURED',profile=config['profile_path'],
                    interface_guid=config['interface_guid'],network_sha256=config['network_sha256'])
        try:
            info,status=_read_pair(config,transition_timeout=0)
            result.update(state=_instance_state(status,config),gateway=info['base_url'],gateway_pid=status['pid'],session_id=status['session_id'])
            if status.get('network_sha256')!=config['network_sha256'] or status.get('interface_guid','').lower()!=config['interface_guid'].lower():
                result.update(state='CONFIGURATION_MISMATCH')
        except RuntimeError as exc:result.update(state='UNAVAILABLE',reason=str(exc))
        return result
    except Exception as exc:return dict(mode='domestic',state='CONFIG_ERROR',reason=str(exc) if isinstance(exc,RuntimeError) else type(exc).__name__)

def bootstrap():
    config=settings()
    if not config:return None
    info,status=session(config)
    return record_selection(config,info,status)

def record_selection(config,info,status):
    public=dict(mode='domestic',gateway=info['base_url'],gateway_pid=status['pid'],pid=os.getpid(),
        parent_pid=os.getppid(),providers=['qwen','deepseek'],interface_guid=config['interface_guid'],
        model_routing=config['model_routing'],network_sha256=config['network_sha256'],profile_sha256=config['profile_sha256'])
    key=(os.getpid(),status['pid'],config['profile_sha256'])
    if key not in _logged:
        state=Path(config['gateway_state_dir']);state.mkdir(parents=True,exist_ok=True)
        handler=EvidenceJournal(state/'application-startup.jsonl')
        try:handler.emit(logging.LogRecord('cgkn.application_network',logging.INFO,'',0,json.dumps(public),(),None))
        finally:handler.close()
        _logged.add(key)
    return public

def credentials():
    config=settings()
    if not config:return None
    bootstrap()
    info,_=session(config)
    return dict(api_key=info['access_token'],base_url=info['base_url'],api_key_source='application_domestic_gateway',
        base_url_source='saved_application_profile',api_key_conflict_sources=[],base_url_conflict_sources=[])

def open_legacy(req,timeout):
    """Prevent old callers bypassing saved routing or budgeted submission safety."""
    config=settings()
    if not config:return None
    info,_=session(config)
    from .gateway_client import _loopback_base_url
    if req.get_method()!='GET':raise RuntimeError('DOMESTIC_LEGACY_POST_REQUIRES_BUDGETED_GATEWAY_CLIENT')
    if req.full_url!=_loopback_base_url(info['base_url'])+'/v1/models':raise RuntimeError('DOMESTIC_OLD_ENDPOINT_REFUSED_NO_FALLBACK')
    return build_opener(ProxyHandler({})).open(req,timeout=timeout)

def probe_models():
    from .gateway_client import completion_client_from_environment
    client=completion_client_from_environment()
    from concurrent.futures import ThreadPoolExecutor
    def probe(provider):
        try:return client.models(provider)
        except Exception as exc:
            return dict(provider=provider,ok=False,reason=getattr(exc,'category',None) or type(exc).__name__,
                        gateway_http_status=getattr(exc,'code',None),upstream_http_status=None,generation_calls=0)
    with ThreadPoolExecutor(max_workers=2) as pool:return list(pool.map(probe,('qwen','deepseek')))

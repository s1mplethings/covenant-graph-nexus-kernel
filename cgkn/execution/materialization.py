"""Isolated file candidate staging; evidence lives inside the existing run store."""
from copy import copy
from pathlib import Path
import shutil
import threading
import hashlib
import json
import base64
import os
import tempfile

_commit_lock = threading.RLock()  # short CAS/publish section, never worker execution


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def stage_file_worker(executor, checker, contract, directory, prior=None):
    from cgkn.execution.file_actions import BoundedFileActions, candidate_files, writable_path
    directory = Path(directory)
    directory.mkdir(parents=True,exist_ok=False)
    original = executor.candidate_root if hasattr(executor, 'in_candidate_workspace') else executor.actions.root
    if checker.root != original: raise ValueError('checker/worker root mismatch')
    for name in {*candidate_files(original, contract), *contract.get('read_scope',())}:
        src = BoundedFileActions(original)._path(name)
        dest = directory / src.relative_to(original)
        if src.is_file():
            dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dest)
    for name,expected in contract.get('read_subjects',{}).items():
        if name not in contract.get('read_scope',()) or name in contract['target_scope']:
            raise ValueError('dependency input must be read-only and explicitly scoped')
        if not isinstance(expected,str) or file_hash(BoundedFileActions(directory)._path(name)) != expected:
            raise ValueError('OBJECT_VERSION_MISMATCH: verified dependency input changed')
    reused = {}
    for name, evidence in (prior or {}).items():
        src = Path(evidence['path']).resolve()
        # Only this leaf's earlier candidate directories can provide a partial;
        # an arbitrary absolute path in a tampered receipt is not a read grant.
        if directory.parent.resolve() not in src.parents:
            raise ValueError('partial artifact outside node candidate history')
        if not writable_path(contract,name) or file_hash(src) != evidence['sha256']:
            raise ValueError('partial artifact identity mismatch')
        dest=directory/name
        # A previous partial is evidence, not authority to overwrite a newer
        # live dependency version copied above. Keep the current input bytes.
        if dest.is_file() and file_hash(dest) != evidence['sha256']:
            continue
        dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dest)
        reused[name]=evidence['sha256']
    if hasattr(executor, 'in_candidate_workspace'):
        worker=executor.in_candidate_workspace(directory)
    else:
        # Preserve application action restrictions when changing workspace.
        # Replacing a qualified subclass with the base class drops its policy.
        worker=copy(executor);worker.actions=copy(executor.actions)
        worker.actions.root=directory.resolve()
    verifier=copy(checker);verifier.root=directory.resolve()
    return worker,verifier,reused


def publish_candidate(root, staged, before, after, *, store=None, intent_path=None, result=None):
    """Short cross-process CAS publish with a durable, immutable recovery intent.

    The journal is evidence in FileRunStore. It never authorizes worker replay.
    A crash between replacements is UNKNOWN until independent reconciliation.
    """
    from cgkn.artifacts.locking import exclusive_file
    root,staged=Path(root).resolve(),Path(staged).resolve()
    if not set(before)<=set(after):raise ValueError('publication cannot silently delete existing artifacts')
    before={name:before.get(name) for name in after}
    for name in before:
        if root not in (root/name).resolve().parents or staged not in (staged/name).resolve().parents:
            raise ValueError('publication path escapes root')
    # The shared OS lock is control state, never a candidate source artifact.
    # Key it by canonical workspace so separate runs still serialize the same
    # short publication CAS, without changing historical candidate manifests.
    lock_root=root.parent/'.cgkn-publication-locks'
    lock_name=hashlib.sha256(os.path.normcase(str(root)).encode('utf-8')).hexdigest()+'.lock'
    with _commit_lock, exclusive_file(lock_root,lock_root/lock_name,wait_seconds=10):
        if {name:file_hash(root/name) for name in before} != before:
            raise ValueError('OBJECT_VERSION_MISMATCH: live subject changed')
        if {name:file_hash(staged/name) for name in after} != after:
            raise ValueError('OBJECT_VERSION_MISMATCH: candidate changed')
        originals={name:(root/name).read_bytes() if (root/name).is_file() else None for name in before}
        if store is not None:
            if intent_path is None or result is None:raise ValueError('publication intent/result required')
            store.immutable_json(intent_path,{'schema_version':'1.0','root':str(root),'staged':str(staged),
                'before':before,'after':after,'result':result.as_dict(),
                'original_bytes':{n:base64.b64encode(b).decode('ascii') if b is not None else None for n,b in originals.items()}})
        try:
            for name in after:
                target=root/name;target.parent.mkdir(parents=True,exist_ok=True)
                fd,temporary=tempfile.mkstemp(prefix='.cgkn-publish-',dir=target.parent)
                try:
                    with os.fdopen(fd,'wb') as handle:
                        handle.write((staged/name).read_bytes());handle.flush();os.fsync(handle.fileno())
                    Path(temporary).replace(target)
                finally:Path(temporary).unlink(missing_ok=True)
        except Exception:
            for name,content in originals.items():
                target=root/name
                if content is None:target.unlink(missing_ok=True)
                else:target.write_bytes(content)
            raise


def inspect_publication(store, intent_path, *, expected_root, expected_staged, contract_hash):
    """Read-only reconstruction; never publishes, rolls forward or replays work."""
    row=json.loads(Path(intent_path).read_text(encoding='utf-8'))
    root,staged=Path(expected_root).resolve(),Path(expected_staged).resolve()
    if row['root']!=str(root) or row['staged']!=str(staged):raise ValueError('publication root identity mismatch')
    if row['result']['metadata'].get('leaf_contract_hash')!=contract_hash:raise ValueError('publication contract identity mismatch')
    if set(row['before'])!=set(row['after']):raise ValueError('publication scope mismatch')
    for name in row['after']:
        if root not in (root/name).resolve().parents or staged not in (staged/name).resolve().parents:
            raise ValueError('publication evidence path escapes root')
    current={n:file_hash(root/n) for n in row['after']}
    candidate={n:file_hash(staged/n) for n in row['after']}
    if candidate!=row['after']:return {'disposition':'UNKNOWN','reason':'candidate identity changed'}
    if current==row['after']:return {'disposition':'COMPLETED','result':row['result']}
    if current==row['before']:return {'disposition':'NOT_APPLIED','reason':'original live versions intact'}
    return {'disposition':'UNKNOWN','reason':'mixed or externally changed live versions'}

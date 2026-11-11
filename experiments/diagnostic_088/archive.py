"""Append diagnostic to the existing canonical Project Corpus; no new store."""
import importlib
import json
import sqlite3
import sys
import types
from .capture import ROOT,OLD,save,sha
from pathlib import Path

def main():
    corpus=Path('F:/CGKN-ITER-060/project-corpus');source=OLD/'preflight-20261027/canonical-corpus-source'
    assert (corpus/'corpus.json').exists()
    expected={'contracts.py':'0b05c341dbe9b534d063a8993b27cc4cbd58b191f38c3d20121968104b9365ac','store.py':'ccf425647e874b495bb96bffb6b8fd7a6473c0364ae67a8fd9f7e74341a4fa21'}
    for n,h in expected.items():assert sha(source/n)==h
    import cgkn.application
    pkg=types.ModuleType('cgkn.application.project_corpus');pkg.__path__=[str(source)];sys.modules[pkg.__name__]=pkg
    store=importlib.import_module(pkg.__name__+'.store');contracts=importlib.import_module(pkg.__name__+'.contracts')
    entry='entry-iter088-state-budget-dev-preparation'
    summary=json.loads((ROOT/'summary.json').read_text(encoding='utf-8'))
    receipt=store.ProjectCorpus(corpus).capture_attempt(family_id='iter076-infrastructure',attempt_id='iter088-offline-v1',run_id='iter088-offline-v1',source_version=summary['head'],generator_version='iter088-offline-v1',status='PARTIAL',provenance='generated_original',public_packet={'goal':'State contract and budget offline diagnosis, one new DEV pair prepared; no product success','provider_requests':0},snapshots=[{'stage':'POST_MATERIALIZATION','files':{'summary.json':json.dumps(summary,ensure_ascii=False,indent=2),'report.md':Path('project_management/summaries/ITER-088-state-budget-dev-preparation.md').read_text(encoding='utf-8')}}],split='DEVELOPMENT',corpus_entry_id=entry,metadata={'record_kind':'OFFLINE_DIAGNOSIS_AND_DEV_PREPARATION','linked_prior':'entry-iter076-closeout-v8','not_product_success':True,'paid_authorization':False})
    doc=json.loads((corpus/'manifests'/f'{entry}.json').read_text())
    snaps=[contracts.SnapshotManifest.from_dict(json.loads((corpus/'snapshots'/f"{x['snapshot_id']}.json").read_text())) for x in doc['snapshot_refs']]
    valid=contracts.AttemptManifest.from_dict(doc,snapshots=snaps)
    for snap in snaps:
        for f in snap.files:
            h=f.content_hash.removeprefix('sha256:');assert sha(corpus/'objects'/h[:2]/h[2:])==h
    with sqlite3.connect(corpus/'catalog.sqlite3') as db:assert db.execute('SELECT entry_id FROM attempts WHERE entry_id=?',(entry,)).fetchone()==(entry,)
    save(ROOT/'corpus-receipt.json',{'receipt':receipt.as_dict(),'manifest_hash':valid.manifest_hash,'verification':'PASS_THIS_ENTRY_ONLY','previous_entry':'entry-iter076-closeout-v8'})
    print(entry)
if __name__=='__main__':main()

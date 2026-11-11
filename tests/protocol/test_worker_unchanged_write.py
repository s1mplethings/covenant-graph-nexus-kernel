import pytest
from cgkn.protocol.compiler import TableSnapshot,compile_worker
from cgkn.protocol.normalization import ContractError,digest


def test_visible_identical_source_not_admitted_as_implementation():
    s=TableSnapshot({'paths':[{'path':'module.py','readable':True,'writable':True,'observed_content_sha256':digest(b'old')}]})
    assert s.public_document['paths'][0]['observed_content_sha256']==digest(b'old')
    with pytest.raises(ContractError,match='WRITE_UNCHANGED_CONTEXT'):
        compile_worker({'op':2,'path':0,'payload':'old'},s,bound_hash=s.hash,node_id='n')
    assert compile_worker({'op':2,'path':0,'payload':'new'},s,bound_hash=s.hash,node_id='n')['actions'][0]['content']=='new'


def test_changed_or_unseen_source_still_requires_normal_execution_verification():
    s=TableSnapshot({'paths':[{'path':'module.py','readable':True,'writable':True}]})
    assert compile_worker({'op':2,'path':0,'payload':'old'},s,bound_hash=s.hash,node_id='n')['actions']

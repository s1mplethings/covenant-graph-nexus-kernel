import os
import pytest
from cgkn.protocol.claim_consistency import claim_errors
from cgkn.execution.resource_identity import guard_output


def test_false_real_world_and_holdout_claims_blocked():
    assert claim_errors({'real_world_validated':True,'real_world_evidence':{'valid':False}})
    assert claim_errors({'holdout_validated':True,'holdout_status':'NOT_EVALUATED'})
    assert claim_errors({'representative':True,'real_world_evidence':{'valid':True,'representative':False},'holdout_status':'PASS'})
    assert not claim_errors({'maturity_level':'TARGET_VALIDATED','real_world_validated':False,'real_world_evidence':{'valid':False}})
    assert not claim_errors({'maturity_level':'TARGET_VALIDATED','real_world_evidence':{'valid':True,'representative':True},'holdout_status':'VERIFIED'})


@pytest.mark.boundary
@pytest.mark.negative
def test_same_path_and_hardlink_rejected_without_mutation(tmp_path):
    source=tmp_path/'input.txt';source.write_text('original')
    alias=tmp_path/'alias.txt';os.link(source,alias)
    for destination in (source,tmp_path/'.'/'input.txt',alias):
        with pytest.raises(PermissionError,match='INPUT_OUTPUT_IDENTITY_COLLISION'):
            guard_output([source],destination)
    assert source.read_text()=='original'
    assert guard_output([source],alias,atomic_inplace=True)
    assert not guard_output([source],tmp_path/'different.txt')


@pytest.mark.boundary
@pytest.mark.happy_path
def test_case_alias_on_windows(tmp_path):
    if os.name!='nt':pytest.skip('Windows identity')
    p=tmp_path/'mixed.txt';p.write_text('original')
    with pytest.raises(PermissionError):guard_output([p],tmp_path/'MIXED.TXT')

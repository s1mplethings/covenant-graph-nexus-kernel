import copy
import json
import pytest
from cgkn.protocol.compiler import TableSnapshot
from cgkn.protocol.exchange import exchange
from cgkn.protocol.normalization import ContractError
from cgkn.protocol.progress import admit_progress
from cgkn.providers import ModelRoleConfig,ProviderCompletion


def exercise(illegal=False):
    packet={'action':4,'target':89,'goal':'Repair the producer','capability':0,
        'strategy':{'problem':'response schema','owner':'server','projection':'public fields'},
        'hypothesis':{'previous':'client parsing can fix it','new':'producer response needs correction',
            'expected_novel_delta':'required fields are returned','falsifying_evidence':['unbound']}}
    original=copy.deepcopy(packet);ref={'path':'attempts/node/attempt.json','receipt_hash':'actual'}
    calls=[];events=[];table=TableSnapshot({'paths':[]})
    class Client:
        def complete(self,**kwargs):
            calls.append(kwargs);prompt=json.loads(kwargs['user'])
            if len(calls)==1:answer=packet
            else:
                assert 'previous_packet' not in prompt and 'context' not in prompt
                assert prompt['allowed_patches'][0]['path']==['hypothesis','falsifying_evidence']
                answer={'patches':[{'op':'replace','path':['capability'] if illegal else ['hypothesis','falsifying_evidence'],
                    'value':1 if illegal else [ref]}]}
            return ProviderCompletion(json.dumps(answer),'fixture-model',str(len(calls)),{'input_tokens':1,'output_tokens':1})
    def compile(packet,bound):
        admit_progress(packet,[{'evidence_refs':[ref]}],[])
        return packet
    result=exchange(Client(),ModelRoleConfig('agent','fixture-model'),system='Return JSON',context={'goal':'real'},
        snapshot=table,semantic_attempt_id='test',compiler=compile,normalization={},trace=events.append)
    return original,result,calls,ref


def test_evidence_correction_keeps_every_other_field_without_resending_packet():
    original,result,calls,ref=exercise();expected=copy.deepcopy(original)
    expected['hypothesis']['falsifying_evidence']=[ref]
    assert result[0]==expected and len(calls)==2
    assert result[2]['admission_correction_attempts']==1


def test_evidence_correction_cannot_change_capability_binding():
    with pytest.raises(ContractError):exercise(illegal=True)

import copy,json
import pytest
from cgkn.protocol.compiler import TableSnapshot
from cgkn.protocol.exchange import exchange
from cgkn.protocol.normalization import ContractError
from cgkn.protocol.progress import admit_progress
from cgkn.providers import ModelRoleConfig,ProviderCompletion


def exercise(illegal=False, unbound=False):
    ref={'path':'attempts/node/a.json','receipt_hash':'bound'}
    packet={'action':4,'target':9,'capability':0,'goal':'Repair existing UI',
            'strategy':{'problem':'state race','mechanism':'change state flow'},
            'hypothesis':{'previous':'state was ready','new':'state must settle before actions',
                'expected_novel_delta':'valid ID on every operation','falsifying_evidence':['wrong'] if unbound else [ref]}}
    original=copy.deepcopy(packet);calls=[]
    fixed={'problem':'state race','state_owner':'current selected backend object','action_boundary':'prerequisites settled'}
    class Client:
        def complete(self,**kwargs):
            calls.append(kwargs);prompt=json.loads(kwargs['user'])
            if len(calls)==1:answer=packet
            else:
                assert 'previous_packet' not in prompt and 'context' not in prompt
                path=prompt['allowed_patches'][0]['path']
                if path==['strategy']:
                    assert prompt['exact_error']['minimum_properties']==3
                    value=fixed
                else:
                    assert path==['hypothesis','falsifying_evidence'];value=[ref]
                answer={'patches':[{'op':'replace','path':['target'] if illegal else path,'value':100 if illegal else value}]}
            return ProviderCompletion(json.dumps(answer),'fixture',str(len(calls)),{'input_tokens':1,'output_tokens':1})
    def compile(packet,bound):admit_progress(packet,[{'evidence_refs':[ref]}],[]);return packet
    result=exchange(Client(),ModelRoleConfig('agent','fixture'),system='JSON',context={'goal':'original'},snapshot=TableSnapshot({'paths':[]}),semantic_attempt_id='test',compiler=compile,normalization={},trace=lambda e:None)
    expected=copy.deepcopy(original);expected['strategy']=fixed;expected['hypothesis']['falsifying_evidence']=[ref]
    return result,calls,expected


@pytest.mark.parametrize('unbound',[False,True])
def test_strategy_and_evidence_are_corrected_without_full_packet_regeneration(unbound):
    result,calls,expected=exercise(unbound=unbound)
    assert result[0]==expected and len(calls)==(3 if unbound else 2)
    assert result[2]['admission_correction_attempts']==len(calls)-1


def test_strategy_correction_cannot_change_target():
    with pytest.raises(ContractError):exercise(illegal=True)

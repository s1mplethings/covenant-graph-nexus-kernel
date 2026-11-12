"""A missing-field repair must retain the business task and strict boundaries."""
import json
import pytest
from cgkn.protocol.compiler import TableSnapshot
from cgkn.protocol.exchange import exchange
from cgkn.protocol.normalization import ContractError
from cgkn.protocol.progress import admit_progress
from cgkn.providers import ModelRoleConfig, ProviderCompletion


@pytest.mark.parametrize('corrupt', [None, 'target', 'evidence', 'unchanged'])
def test_missing_strategy_and_hypothesis_remain_task_bound(corrupt):
    ref = {'path': 'attempts/gui/a.json', 'receipt_hash': 'bound-current'}
    original = {'action': 4, 'target': 91, 'goal': 'Repair GUI saved content identity',
                'expected': ['Review receives persisted non-null content ID']}
    calls = []
    class Client:
        def complete(self, **kwargs):
            prompt = json.loads(kwargs['user']); calls.append(prompt)
            if len(calls) == 1:
                answer = original
            else:
                anchor = prompt['task_anchor']
                assert anchor['goal'] == original['goal'] and anchor['expected'] == original['expected']
                path = prompt['allowed_patches'][0]['path']
                if path == ['strategy']:
                    value = {'problem': 'saved ID race', 'state_owner': 'saved record', 'ordering': 'await save before review'}
                else:
                    assert path == ['hypothesis']
                    assert prompt['exact_error']['allowed_evidence_refs'] == [ref]
                    value = {'previous': 'button click implies saved content', 'new': 'await saved record identity',
                             'expected_novel_delta': 'non-null ID passed to review',
                             'falsifying_evidence': [{'path': 'unbound'}] if corrupt == 'evidence' else [ref]}
                    if corrupt == 'unchanged': value['new'] = value['previous']
                answer = {'patches': [{'op': 'replace' if corrupt == 'target' else 'add',
                                      'path': ['target'] if corrupt == 'target' else path,
                                      'value': 92 if corrupt == 'target' else value}]}
            return ProviderCompletion(json.dumps(answer), 'fixture', str(len(calls)), {'input_tokens': 1, 'output_tokens': 1})
    def compile(packet, snapshot):
        admit_progress(packet, [{'evidence_refs': [ref]}], [])
        return packet
    def run():
        return exchange(Client(), ModelRoleConfig('agent', 'fixture'), system='JSON', context={},
            snapshot=TableSnapshot({'paths': []}), semantic_attempt_id='task-anchor', compiler=compile,
            normalization={}, trace=lambda event: None)
    if corrupt:
        with pytest.raises(ContractError): run()
    else:
        result = run()[0]
        assert all(result[k] == v for k, v in original.items())
        assert len(calls) == 3 and result['hypothesis']['falsifying_evidence'] == [ref]

import copy
import json

from cgkn.protocol.adapters import SemanticWorkerClient
from cgkn.protocol.context_pack import project_worker_observations
from cgkn.protocol.normalization import digest
from cgkn.protocol.repair import plain
from cgkn.orchestration.tree_edits import apply_tree_edits
from cgkn.providers import ModelRoleConfig, ProviderCompletion
from test_repair_path import initial, failed_snapshot, repair_packet, run


def fixture():
    snapshot,tree=initial()
    tree=apply_tree_edits(tree,run(repair_packet(),failed_snapshot(snapshot),tree)['edits'],known_capabilities={'code'})
    config=plain(tree.by_id['n'].config)
    content='DEPENDENCY_BODY_SENTINEL\n'*200
    config['leaf_contract'].update(read_scope=['dependency.py'],read_subjects={'dependency.py':digest(content.encode())})
    raw={'node_id':'n','goal':'Complete all response branches','config':config,'observations':[
        {'action':'read_file','path':'dependency.py','content':content,'sha256':digest(content.encode()),'input_origin':'verified_milestone_dependency'},
        {'action':'read_file','path':'module.py','content':'old'}]}
    return raw


def test_only_bound_automatic_dependency_bodies_are_referenced_without_mutation():
    raw=fixture();before=copy.deepcopy(raw);projected=project_worker_observations(raw)
    assert raw==before and projected['observations']==[raw['observations'][1]]
    assert projected['verified_dependency_refs'][0]['sha256']==raw['observations'][0]['sha256']
    assert project_worker_observations(projected)==projected
    # Explicitly requested dependency reads retain complete content.
    raw['observations'].append({k:v for k,v in raw['observations'][0].items() if k!='input_origin'})
    assert project_worker_observations(raw)['observations'][-1]['content']==raw['observations'][0]['content']


def test_unverified_or_nonrepair_inputs_are_not_silently_hidden():
    for change in ('hash','repair','version'):
        raw=fixture()
        if change=='hash':raw['observations'][0]['sha256']='wrong'
        elif change=='repair':raw['config'].pop('repair_contract')
        else:raw['config']['action_version']=1
        assert project_worker_observations(raw)['observations']==raw['observations']


def test_full_file_repair_retains_actual_declared_inputs_and_hashes():
    raw=fixture()
    raw['config']['repair_contract'].setdefault('strategy_semantics',{})['full_file_write']=True
    before=copy.deepcopy(raw)
    assert project_worker_observations(raw)==before
    class Client:
        def complete(self,**kw):
            request=json.loads(kw['user'])
            assert 'DEPENDENCY_BODY_SENTINEL' in kw['user']
            row=next(x for x in request['tables']['paths'] if x['path']=='dependency.py')
            assert row['observed_content_sha256']==raw['observations'][0]['sha256']
            assert not row['writable']
            target=next(x for x in request['tables']['paths'] if x['writable'])
            return ProviderCompletion(json.dumps({'op':2,'path':target['id'],'payload':'fixed'}),'fixture-model','request',{})
    result=SemanticWorkerClient(Client(),lambda e:None).complete(config=ModelRoleConfig('worker','fixture-model'),user=json.dumps(raw))
    assert json.loads(result.text)['actions'][0]['content']=='fixed'
    assert raw==before


def test_actual_worker_can_read_referenced_input_without_false_read_once_rejection():
    raw=fixture();seen=[]
    class Client:
        def complete(self,**kw):
            seen.append(kw);request=json.loads(kw['user'])
            assert 'DEPENDENCY_BODY_SENTINEL' not in kw['user']
            assert 'A write or patch batch ends this delegation' in kw['system']
            row=next(x for x in request['tables']['paths'] if x['path']=='dependency.py')
            assert 'observed_content_sha256' not in row
            return ProviderCompletion(json.dumps({'op':0,'path':row['id']}),'fixture-model','request',{})
    result=SemanticWorkerClient(Client(),lambda e:None).complete(config=ModelRoleConfig('worker','fixture-model'),user=json.dumps(raw))
    assert len(seen)==1 and json.loads(result.text)['actions']==[{'action':'read_file','path':'dependency.py'}]

"""Real existing CSV project through two deterministic Component transforms."""
from __future__ import annotations

import ast
import json
from pathlib import Path

from cgkn.artifacts import ArtifactInstance, Producer, Provenance
from cgkn.runtime.runner import ArtifactModuleRunner
from cgkn.application.verification import OracleSpec, OracleKind
from tests.application.verification.test_oracle_executors import project

FLOW='flow.lean_csv@1'
COMPONENT='module.lean_normalize@1'


def normalize_python(inputs, context):
    assert context == {}, 'pure-input transforms cannot read node/run/store context'
    return {'normalized':{'files':{name:ast.unparse(ast.parse(source))+'\n' for name,source in inputs['source']['files'].items()}}}


def setup_specs(root):
    def put(relative,doc):
        p=root/relative;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(doc),encoding='utf-8')
    put('schemas/source.json',{'type':'object','required':['files'],'properties':{'files':{'type':'object','additionalProperties':{'type':'string'}}},'additionalProperties':False})
    put('specs/artifacts/source.json',{'kind':'ArtifactType','id':'artifact.lean_source','version':'1','schema_ref':'schemas/source.json'})
    module={'kind':'ModuleContract','id':'module.lean_normalize','version':'1',
        'ports':{'input':{'source':{'artifact_type':'artifact.lean_source@1','required':True}},'output':{'normalized':{'artifact_type':'artifact.lean_source@1'}}},
        'requires':{'capabilities':[],'context':[]},'effects':{},
        'compatibility':{'replaceable':True,'movable':True,'surface_rule':'same_or_compatible','effect_rule':'subset_or_equal'},
        'context':{'maxChars':1000000,'requiredArtifactPorts':['source'],'optionalArtifactPorts':[],'includeDecisionLedger':False,'recentConversationTurns':0},
        'implementation':{'kind':'local_function','entrypoint':'tests.leanloop_support:normalize_python','lean_input_only':True,'cacheable':True},
        'metadata':{'lean_protections':[]}}
    put('specs/modules/normalize.json',module)
    put('specs/policies/lean.json',{'kind':'Policy','id':'policy.lean_csv','version':'1','effect_constraints':[]})
    put('specs/flows/lean.json',{'kind':'FlowSpec','id':'flow.lean_csv','version':'1','policy_ref':'policy.lean_csv@1',
        'inputs':{'source':'artifact.lean_source@1'},'outputs':{'left':'artifact.lean_source@1','right':'artifact.lean_source@1'},
        'nodes':[{'id':name,'uses':COMPONENT} for name in ('normalize_for_tests','normalize_for_package')],
        'edges':[{'from':{'flow_input':'source'},'to':{'node':name,'port':'source'}} for name in ('normalize_for_tests','normalize_for_package')]+[
            {'from':{'node':'normalize_for_tests','port':'normalized'},'to':{'flow_output':'left'}},
            {'from':{'node':'normalize_for_package','port':'normalized'},'to':{'flow_output':'right'}}],
        'metadata':{'artifact_driven':True}})
    return module


def run_csv(workspace, *, fault='', run_name='run', source_files=None):
    specs=workspace/'specs-root';setup_specs(specs)
    project(workspace)
    if fault=='wrong':
        (workspace/'csv_cleaner/core.py').write_text('def clean(input_path,output_path,column=None,fill=None):\n return [],[]\n',encoding='utf-8')
    files=source_files or {p.relative_to(workspace).as_posix():p.read_text(encoding='utf-8') for p in (workspace/'csv_cleaner').glob('*.py')}
    runner=ArtifactModuleRunner(specs,workspace/run_name,FLOW)
    ref=runner.store.write_artifact(ArtifactInstance(id=runner.store.allocate_id('artifact.lean_source@1'),artifact_type='artifact.lean_source@1',
        run_id=run_name,producer=Producer('input','module.fixture@1','source'),content={'files':files},provenance=Provenance()))
    result=runner.run({'source':ref})
    outputs=[runner.store.resolve_artifact_ref(result['outputs'][name]).content['files'] for name in ('left','right')]
    assert outputs[0]==outputs[1]
    for name,content in outputs[1].items():
        p=workspace/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(content,encoding='utf-8')
    if fault=='missing': (workspace/'csv_cleaner/core.py').unlink()
    return runner,result


def cases():
    def oracle(index,rows):
        return OracleSpec(oracle_id='ORACLE-LEAN-'+str(index),obligation_ids=('OBL-LEAN-CSV',),oracle_kind=OracleKind.CSV,
            subject_ref='csv_cleaner',setup={'input_path':'input.csv','output_path':'output.csv','header':['id','name'],'rows':rows},
            operation={'argv':['python','-m','csv_cleaner','input.csv','output.csv']},
            expected={'exit_code':0,'header':['id','name'],'rows':[rows[0],rows[-1]]})
    return [{'id':str(i),'input':{'fault':fault},'split':split,'expected_pass':not fault,
        'subjects':['csv_cleaner/core.py'],'oracles':[oracle(i,rows)]}
        for i,(split,fault,rows) in enumerate([
            ('qualification','',[['1','a'],['1','a'],['2','b']]),
            ('qualification','wrong',[['1','a'],['1','a'],['2','b']]),
            ('holdout','',[['7','猫'],['7','猫'],['8','狗']]),
            ('holdout','missing',[['7','猫'],['7','猫'],['8','狗']])])]

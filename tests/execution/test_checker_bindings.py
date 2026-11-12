import hashlib
import pytest
from cgkn.execution.checker_bindings import install_file_checks
from cgkn.executors import ExecutorRegistry


def install(root,**spec):
    registry=ExecutorRegistry()
    bindings=install_file_checks(registry,root,{'kind':'CGKNFileCheckerBindings','schema_version':'1.0',
        'checks':{'exact':spec}})
    assert bindings=={'files':'deliverable.files@1'}
    return registry.resolve('deliverable.files@1','deliverable.check@1')


@pytest.mark.happy_path
@pytest.mark.boundary
@pytest.mark.parametrize('kind',['sha256','utf8_equals','json_schema'])
def test_registered_predicate_reads_exact_current_bytes(tmp_path,kind):
    raw=b'{"value":42}';path=tmp_path/'result.json';path.write_bytes(raw)
    spec={'kind':kind,'path':'result.json'}
    if kind=='sha256':spec['expected']=hashlib.sha256(raw).hexdigest()
    elif kind=='utf8_equals':spec['expected']=raw.decode()
    else:spec['schema']={'type':'object','required':['value'],'properties':{'value':{'const':42}}}
    checker=install(tmp_path,**spec)
    contract={'target_scope':['result.json']}
    assert checker.checks['exact'](tmp_path,contract)['passed'] is True
    path.write_text('{"value":0}')
    assert checker.checks['exact'](tmp_path,contract)['passed'] is False


@pytest.mark.negative
@pytest.mark.boundary
@pytest.mark.parametrize('path,scope',[('other.txt',['result.txt']),('../outside.txt',['../outside.txt'])])
def test_checker_cannot_read_outside_explicit_scope(tmp_path,path,scope):
    checker=install(tmp_path,kind='utf8_equals',path=path,expected='never read')
    with pytest.raises(ValueError,match='outside|escapes'):
        checker.checks['exact'](tmp_path,{'target_scope':scope})

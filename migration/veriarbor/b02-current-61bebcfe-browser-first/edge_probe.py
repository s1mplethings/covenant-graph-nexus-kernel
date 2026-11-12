
import base64,hashlib,importlib.util,json,os,pathlib,sys,tempfile
workspace,out,png=map(pathlib.Path,sys.argv[1:]);sys.path.insert(0,str(workspace))
temp=out/'edge-temporary';temp.mkdir();os.environ['TEMP']=os.environ['TMP']=str(temp);tempfile.tempdir=None
spec=importlib.util.spec_from_file_location('edge_product',workspace/'main.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
data=out/'edge-data';data.mkdir();project=mod.handle(str(data),{'milestone':'M1','op':'project.create','name':'Adapter edge'})
original=mod.HANDLERS['M11'];seen=[];fail=False;raw=png.read_bytes()
def spy(folder,request):
    if request['op']=='media.import':
        path=pathlib.Path(request['path']);assert path.is_absolute() and path.is_file();assert path.resolve().is_relative_to(out.resolve());assert path.read_bytes()==raw
        seen.append(str(path))
        if fail:raise ValueError('injected downstream import failure')
    return original(folder,request)
mod.HANDLERS['M11']=spy;mod.m11_handle=spy
request={'milestone':'M11','op':'media.import','project_id':project['id'],'kind':'image','filename':'pixel.png','data':base64.b64encode(raw).decode()}
record=mod.handle(str(data),request);assert seen and not pathlib.Path(seen[-1]).exists();assert pathlib.Path(record['path']).read_bytes()==raw
fail=True
try:mod.handle(str(data),request)
except ValueError as error:assert 'injected downstream' in str(error)
else:raise AssertionError('backend error swallowed')
assert len(seen)==2 and not pathlib.Path(seen[-1]).exists()
fail=False;request['filename']='../qualification-escape.png'
try:mod.handle(str(data),request)
except ValueError:pass
assert all(not pathlib.Path(path).exists() for path in seen)
assert not list(temp.rglob('*.png'))
print(json.dumps({'status':'PASS','temporary_paths':seen,'checks':['real path passed to original M11','confined absolute temporary file','untrusted filename cannot escape','success cleanup','downstream failure cleanup','durable original M11 copy']}))

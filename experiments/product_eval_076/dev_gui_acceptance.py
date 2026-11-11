"""Independent DEV operator, separate browser process/filesystem from candidate."""
import argparse, hashlib, json, pathlib, subprocess, zipfile

IMAGE='sha256:1059097764b634a5b1e2ed4bf035700d6ce47dfd206044c1b9bf63300523ee20'
APP='eval076-accept-promo-app'
BROWSER='eval076-accept-promo-browser'

def main():
    p=argparse.ArgumentParser();p.add_argument('--root',required=True,type=pathlib.Path)
    p.add_argument('operation',choices=['setup','browser','restart','tests','close'])
    p.add_argument('--request',type=pathlib.Path);a=p.parse_args();root=a.root.resolve()
    if a.operation=='setup':root.mkdir(parents=True,exist_ok=False)
    def run(argv,stdin=None,timeout=120):
        r=subprocess.run(argv,input=stdin,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=timeout)
        row={'argv':argv,'stdin':stdin,'exit_code':r.returncode,'stdout':r.stdout,'stderr':r.stderr}
        with (root/'operator.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(row)+'\n')
        print(json.dumps(row))
        return r
    if a.operation=='setup':
        # Snapshot produced by trusted freeze container; still reject unsafe names.
        w=root/'workspace';w.mkdir();b=root/'browser';b.mkdir()
        archive=pathlib.Path('F:/CGKN-ITER-076/frozen-dev-promo-direct-03/candidate.zip')
        with zipfile.ZipFile(archive) as z:
            for name in z.namelist():
                rel=pathlib.PurePosixPath(name)
                if rel.is_absolute() or '..' in rel.parts or ':' in name:raise ValueError('Unsafe snapshot path')
                dest=w.joinpath(*rel.parts);dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(z.read(name))
        (root/'candidate-hash.txt').write_text(hashlib.sha256(archive.read_bytes()).hexdigest())
        common=['--read-only','--cap-drop','ALL','--security-opt','no-new-privileges','--user','65534:65534','--pids-limit','256','--memory','1536m','--cpus','2','--init','--tmpfs','/tmp:rw,nosuid,nodev,size=536870912']
        r=run(['docker','run','-d','--name',APP,'--network','none',*common,'--mount',f'type=bind,source={w},target=/workspace','--mount','type=bind,source=F:/CGKN-ITER-076/dev-promo-direct-03/run/public,target=/input,readonly',IMAGE,'python','app.py'])
        if r.returncode:raise SystemExit(r.returncode)
        r=run(['docker','run','-d','--name',BROWSER,'--network','container:'+APP,*common,'--mount',f'type=bind,source={b},target=/workspace',IMAGE])
        if r.returncode:raise SystemExit(r.returncode)
    elif a.operation=='browser':
        req=a.request.read_text(encoding='utf-8')
        run(['docker','exec','-i',BROWSER,'python','/opt/evaltools/browser.py'],req)
    elif a.operation=='restart':run(['docker','restart',APP])
    elif a.operation=='tests':run(['docker','exec',APP,'python','-m','pytest','test_app.py','-v'])
    else:
        run(['docker','rm','-f',BROWSER,APP])
        run(['docker','inspect',APP,BROWSER])

if __name__=='__main__':main()

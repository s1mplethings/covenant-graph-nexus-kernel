"""Public read-only blackbox checks. No candidate imports or mutation."""
import argparse, hashlib, json, subprocess, urllib.request
p=argparse.ArgumentParser();sub=p.add_subparsers(dest='check',required=True)
d=sub.add_parser('download');d.add_argument('--url',required=True);d.add_argument('--expected-file',required=True)
m=sub.add_parser('media');m.add_argument('--path',required=True);m.add_argument('--duration',type=float,required=True);m.add_argument('--tolerance',type=float,default=1)
a=p.parse_args()
if a.check=='download':
 from pathlib import Path
 expected=Path(a.expected_file).read_bytes();actual=urllib.request.urlopen(a.url,timeout=15).read()
 assert actual==expected, json.dumps({'expected_sha256':hashlib.sha256(expected).hexdigest(),'actual_sha256':hashlib.sha256(actual).hexdigest()})
else:
 raw=subprocess.check_output(['ffprobe','-v','error','-show_format','-show_streams','-of','json',a.path]);v=json.loads(raw)
 types={s['codec_type'] for s in v['streams']};assert {'audio','video'}<=types,types
 duration=float(v['format']['duration']);assert abs(duration-a.duration)<=a.tolerance,{'expected':a.duration,'actual':duration,'tolerance':a.tolerance}
 subprocess.run(['ffmpeg','-v','error','-i',a.path,'-f','null','-'],check=True,capture_output=True)
print(json.dumps({'status':'PASS','check':a.check,'limits':'This check alone does not verify GUI, source alignment, persistence or candidate-authored tests.'}))

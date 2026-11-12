"""Read-only codec probe, run inside an isolated inspection environment.

Inputs are public source and candidate export, never a private answer file.
Does not import or execute candidate Python. Content judgement remains separate.
"""
import array
import json
import math
import subprocess
import sys

def audio(path,start,duration):
    p=subprocess.run(['ffmpeg','-v','error','-ss',str(start),'-i',path,'-t',str(duration),'-vn','-ac','1','-ar','1000','-f','s16le','-'],capture_output=True,check=True)
    a=array.array('h');a.frombytes(p.stdout);return a
def frame(path,at):
    return subprocess.check_output(['ffmpeg','-v','error','-ss',str(at),'-i',path,'-frames:v','1','-vf','crop=iw:ih*0.7:0:0,scale=64:48','-pix_fmt','rgb24','-f','rawvideo','-'])
def compare(source,export,start,end):
    a=audio(source,start,end-start);b=audio(export,0,end-start)
    similarities=[]
    for shift in range(-1000,1001,10):
        pairs=list(zip(a[max(0,shift)::10],b[max(0,-shift)::10]))
        if not pairs:continue
        dot=sum(x*y for x,y in pairs);norm=math.sqrt(sum(x*x for x,y in pairs)*sum(y*y for x,y in pairs))
        similarities.append(dot/norm if norm else 0)
    errors=[]
    for t in [1,(end-start)/2,end-start-1]:
        x=frame(source,start+t);y=frame(export,t)
        if len(x)!=len(y) or not x:errors.append(255)
        else:errors.append(sum(abs(i-j) for i,j in zip(x,y))/len(x))
    return {'audio_correlation':max(similarities,default=0),'frame_mae':errors,'pass':max(similarities,default=0)>=.90 and max(errors,default=255)<20,'human_semantic_quality':'UNTESTED'}
if __name__=='__main__':print(json.dumps(compare(sys.argv[1],sys.argv[2],float(sys.argv[3]),float(sys.argv[4]))))

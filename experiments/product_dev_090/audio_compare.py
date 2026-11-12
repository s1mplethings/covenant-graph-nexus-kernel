"""Audio envelope alignment tolerates codec phase; independent controls required."""
import array,json,math,subprocess,sys

def envelope(path,start,duration):
 raw=subprocess.check_output(['ffmpeg','-v','error','-ss',str(start),'-i',path,'-t',str(duration),'-vn','-ac','1','-ar','8000','-f','s16le','-'])
 a=array.array('h');a.frombytes(raw)
 return [math.sqrt(sum(x*x for x in a[i:i+160])/160) for i in range(0,len(a)-159,80)]
def correlation(a,b):
 if len(a)<50:return 0
 ma=sum(a)/len(a);mb=sum(b)/len(b)
 dot=sum((x-ma)*(y-mb) for x,y in zip(a,b));norm=math.sqrt(sum((x-ma)**2 for x in a)*sum((y-mb)**2 for y in b))
 return dot/norm if norm else 0

def compare(source,clip,start,end):
 a=envelope(source,start,end-start);b=envelope(clip,0,end-start)
 scores=[]
 for shift in range(-100,101):
  x=a[max(0,shift):];y=b[max(0,-shift):];n=min(len(x),len(y));scores.append((correlation(x[:n],y[:n]),shift/100))
 best=max(scores)
 return {'version':'audio-envelope-v2','correlation':best[0],'lag_seconds':best[1],'threshold':.90,'pass':best[0]>=.90,'meaning':'source speech energy/time alignment; independent picture/decoding/domain checks still required'}
if __name__=='__main__':print(json.dumps(compare(sys.argv[1],sys.argv[2],float(sys.argv[3]),float(sys.argv[4]))))

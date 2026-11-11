"""Trusted management of the controlled target; never registered as a model tool."""
import pathlib

def start_target(boundary):
 state=boundary.root/'target-state';state.mkdir(exist_ok=False)
 source=pathlib.Path(__file__).with_name('controlled_target.py').resolve()
 name=boundary.name+'-target'
 boundary.control(['run','-d','--name',name,'--network','container:'+boundary.name,'--read-only','--cap-drop','ALL','--security-opt','no-new-privileges','--user','65534:65534','--pids-limit','32','--memory','128m','--cpus','.5','--tmpfs','/tmp','--mount',f'type=bind,source={source},target=/service/target.py,readonly','--mount',f'type=bind,source={state},target=/state',boundary.policy.image,'python','/service/target.py','--account',boundary.run_id])
 boundary.record('controlled_target',{'container':name,'state_directory_not_mounted_in_candidate':str(state),'account':boundary.run_id,'endpoint':'http://127.0.0.1:9001','evidence_level':'CONTROLLED_PROTOCOL_ONLY'})
 return name

def close_target(boundary,name):
 if name:boundary.control(['rm','-f',name])

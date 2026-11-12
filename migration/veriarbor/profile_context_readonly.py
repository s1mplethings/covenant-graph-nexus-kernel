"""Profile pure context projection from an immutable original context receipt."""
from pathlib import Path
import json,hashlib,cProfile,pstats,time,sys
from cgkn.agent.composer import AgentDecisionContext,AgentComposer
from cgkn.orchestration.capability_tree import CapabilityTree
S=Path('F:/CGKN-ITER-132/production-core-convergence-v1/promotion/run-05/state/iter132-promotion-studio/promotion-05')
p=max((S/'agent').glob('context-*.json'),key=lambda x:x.stat().st_mtime)
raw=p.read_bytes();value=json.loads(raw)
value['tree']=CapabilityTree.from_dict(value['tree'])
value['known_capabilities']=tuple(value['known_capabilities'])
context=AgentDecisionContext(**value)
out=Path(__file__).parent/('performance-context-'+sys.argv[1]);out.mkdir(exist_ok=False)
profile=cProfile.Profile();start=time.monotonic()
table=profile.runcall(AgentComposer._milestone_snapshot,context)
elapsed=time.monotonic()-start
profile.dump_stats(str(out/'projection.pstats'))
with (out/'profile.txt').open('w',encoding='utf-8') as f:pstats.Stats(profile,stream=f).sort_stats('cumulative').print_stats(20)
doc={'kind':'ReadOnlyContextProjectionProfile','source_context':str(p),'source_sha256':hashlib.sha256(raw).hexdigest(),
 'seconds':elapsed,'scopes':[s['path'] for s in table.document['scopes']],
 'snapshot_sha256':table.hash,'snapshot_bytes':len(json.dumps(table.document)),
 'owner_binding_count':len(table.document.get('dependency_owner_repairs',[])),
 'provider_calls':0,'state_mutations':0,'acceptance_authority':False}
assert p.read_bytes()==raw
(out/'receipt.json').write_text(json.dumps(doc,indent=2),encoding='utf-8')
print(json.dumps({k:doc[k] for k in ('seconds','snapshot_bytes','owner_binding_count','source_context')}))

"""Read-only profiling of authenticated feedback hydration; no Provider calls."""
from pathlib import Path
import cProfile,pstats,json,time
from cgkn.state import FileRunStore
from cgkn.state.task_feedback import TaskFeedback
M=Path(__file__).parent;out=M/'performance-feedback-1';out.mkdir(exist_ok=False)
root=Path('F:/CGKN-ITER-132/production-core-convergence-v1/promotion/run-05/state')
feedback=TaskFeedback(FileRunStore(root),'iter132-promotion-studio','promotion-05')
profile=cProfile.Profile();start=time.monotonic();context=profile.runcall(feedback.context)
profile.dump_stats(str(out/'context.pstats'))
with (out/'profile.txt').open('w',encoding='utf-8') as f:pstats.Stats(profile,stream=f).sort_stats('cumulative').print_stats(22)
receipt={'kind':'ReadOnlyFeedbackProfile','seconds':time.monotonic()-start,'context_items':len(context.get('items',[])),'provider_calls':0,'acceptance_authority':False}
(out/'receipt.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8');print(json.dumps(receipt))

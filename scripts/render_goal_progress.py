"""Render an existing FileRunStore goal view; never change acceptance records."""
import argparse
import html
import json
from pathlib import Path


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--run-dir',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    import sys
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    from cgkn.state import FileRunStore
    from cgkn.runtime.acceptance import open_goal_acceptance as GoalAcceptance
    root=args.run_dir.resolve()
    data=json.loads((root/'goal_acceptance.json').read_text(encoding='utf-8'))
    bindings={g['checker']:None for plan in data['plans'] for g in plan['goals']}
    # Reading a view does not dispatch checkers. Their registry is unnecessary.
    view=GoalAcceptance(FileRunStore(root.parent.parent),root.parent.name,root.name,data['requirements'],bindings).view()
    esc=lambda x:html.escape(str(x))
    body='<h1>Project goal evidence</h1><p>Execution batches are not business milestones. Proxy checks do not replace external acceptance or required human review.</p>'
    body+='<p>'+esc(view['progress_basis'])+'</p><table border="1"><tr><th>Phase</th><th>Goal / condition</th><th>Execution</th><th>Acceptance</th><th>Next action</th><th>Evidence</th></tr>'
    for g in view['goals']:
        record=g['evidence'];execution='NOT_RUN';link=''
        if record:
            path=root/'attempts'/record['node_id']/(record['attempt_id']+'.json')
            if path.is_file():execution=json.loads(path.read_text(encoding='utf-8'))['status']
            link=f'<a href="{html.escape(path.as_uri(),quote=True)}">{esc(record["node_id"])}</a>'
        values=[esc(g['phase_id']),esc(g['id']+': '+g['acceptance']),esc(execution),esc(g['verdict']),esc('review remaining requirements' if g['verdict']=='VERIFIED' else 'inspect current gap'),link]
        body+='<tr>'+''.join('<td>'+v+'</td>' for v in values)+'</tr>'
    body+='</table><h2>Relative milestone dependencies</h2><p>No reliable calendar estimates supplied.</p><ul>'
    for phase in view['phases']:
        body+='<li>'+esc(phase['id'])+' ← '+esc(phase.get('depends_on',[]))+' : '+esc(phase['acceptance'])+'</li>'
    body+='</ul><p>Uncovered MUST: '+esc(view['uncovered_must'])+'</p>'
    phases={p['id']:p for p in view['phases']}
    def depth(pid, trail=()):
        if pid in trail:return 0
        return max([depth(d,trail+(pid,))+1 for d in phases[pid].get('depends_on',[]) if d in phases] or [0])
    positions={pid:(30+270*depth(pid),40+100*i) for i,pid in enumerate(phases)}
    width=max([x+250 for x,y in positions.values()] or [400]);height=max([y+85 for x,y in positions.values()] or [100])
    body+='<h2>Milestone dependency view</h2><p>Relative dependency levels, not calendar dates or measured durations. Box colour shows acceptance, not execution completion.</p>'
    body+=f'<svg role="img" aria-label="Relative milestone dependencies" viewBox="0 0 {width} {height}" style="width:100%;min-width:640px"><defs><marker id="arrow" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto"><path d="M0,0 L0,6 L8,3 z" fill="#666"/></marker></defs>'
    for pid,p in phases.items():
        x,y=positions[pid]
        for dep in p.get('depends_on',[]):
            if dep in positions:
                dx,dy=positions[dep];body+=f'<path d="M {dx+230} {dy+28} L {x} {y+28}" stroke="#666" fill="none" marker-end="url(#arrow)"/>'
    for pid,p in phases.items():
        x,y=positions[pid];colour={'VERIFIED':'#d7f1df','FAILED':'#f8d7da','INSUFFICIENT_EVIDENCE':'#fff0c2'}.get(p['acceptance'],'#eeeeee')
        body+=f'<g><title>{esc(p.get("outcome",""))}</title><rect x="{x}" y="{y}" width="230" height="65" rx="6" fill="{colour}" stroke="#666"/><text x="{x+10}" y="{y+23}" font-size="14">{esc(pid)}</text><text x="{x+10}" y="{y+48}" font-size="12">{esc(p["acceptance"])}</text></g>'
    body+='</svg>'

    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text('<!doctype html><meta charset="utf-8"><title>CGKN goal progress</title><style>body{font:16px system-ui;margin:30px}td,th{padding:9px;text-align:left;vertical-align:top}table{border-collapse:collapse}</style>'+body,encoding='utf-8')
    print(json.dumps({'output':str(args.output),'complete':view['complete'],'goals':len(view['goals'])}))


if __name__=='__main__':main()

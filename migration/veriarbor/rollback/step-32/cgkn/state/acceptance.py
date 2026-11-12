"""Versioned goal evidence in FileRunStore; execution status is not acceptance.

The controller supplies immutable requirements and trusted checker bindings.
Plans are Agent proposals. Check records must come from dispatched checker
receipts, never candidate files or producer statements.
"""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from functools import wraps


def identity(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def serialized_update(method):
    @wraps(method)
    def update(self, *args, **kwargs):
        with self.store.exclusive_file(self.root/'acceptance.lock',wait_seconds=10):
            self._reload()
            return method(self,*args,**kwargs)
    return update


class GoalAcceptance:
    def __init__(self, store, project_id, run_id, requirements, checkers):
        self.store, self.project_id, self.run_id = store, project_id, run_id
        self.root = store.run_dir(project_id, run_id)
        self.requirements = deepcopy(requirements)
        self.checkers = dict(checkers)
        import math
        for req in self.requirements.values():
            weight = req.get('weight', 1)
            if isinstance(weight, bool) or not isinstance(weight, (int, float)) or not math.isfinite(weight) or weight < 0:
                raise ValueError('invalid requirement weight')
            if req.get('operator', 'AND') not in {'AND', 'OR'}:
                raise ValueError('invalid requirement connective')
        for key, req in self.requirements.items():
            if not isinstance(key, str) or not key or not isinstance(req.get('must'), bool):
                raise ValueError('requirement identity and explicit necessity required')
        seen, pending = set(), set()
        def validate_requirement(key):
            if key in pending or key not in self.requirements:
                raise ValueError('invalid requirement tree')
            if key in seen: return
            pending.add(key)
            children = self.requirements[key].get('children', [])
            if len(children) != len(set(children)): raise ValueError('duplicate child obligation')
            for child in children: validate_requirement(child)
            pending.remove(key); seen.add(key)
        for key in self.requirements: validate_requirement(key)
        visited_dependencies=set()
        def validate_dependencies(key,stack):
            if key in stack: raise ValueError('requirement dependency cycle')
            if key in visited_dependencies: return
            dependencies=self.requirements[key].get('depends_on',[])
            if (not isinstance(dependencies,list) or any(not isinstance(d,str) or d not in self.requirements for d in dependencies)
                    or len(dependencies)!=len(set(dependencies))):
                raise ValueError('invalid requirement dependencies')
            for dependency in dependencies: validate_dependencies(dependency,stack|{key})
            visited_dependencies.add(key)
        for key in self.requirements: validate_dependencies(key,set())
        path = self.root / 'goal_acceptance.json'
        self.data = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {
            'schema_version': '1.0', 'requirements': self.requirements, 'checker_bindings': self.checkers,
            'plans': [], 'checks': [], 'subjects': {},
        }
        if self.data.get('checker_bindings', self.checkers) != self.checkers:
            raise ValueError('checker binding change requires explicit new contract version')
        if self.data['requirements'] != self.requirements:
            raise ValueError('requirement change needs a new authorized run/version')

    def save(self):
        self.store.atomic_json(self.root / 'goal_acceptance.json', self.data)
        self.render()

    def _reload(self):
        path=self.root/'goal_acceptance.json'
        if path.exists():
            data=json.loads(path.read_text(encoding='utf-8'))
            if data['requirements']!=self.requirements or data.get('checker_bindings',self.checkers)!=self.checkers:
                raise ValueError('immutable acceptance bindings changed')
            self.data=data

    def propose(self, plan, tree):
        """Validate before committing either plan or executable tree."""
        phases = {p['id']: p for p in plan['phases']}
        goals = {g['id']: g for g in plan['goals']}
        if len(phases) != len(plan['phases']) or len(goals) != len(plan['goals']):
            raise ValueError('duplicate phase or goal identity')
        previous = {g['id']: g for g in self.data['plans'][-1]['goals']} if self.data['plans'] else {}
        for gid, old in previous.items():
            if gid not in goals:
                raise ValueError('goals cannot disappear during re-planning')
            if any(goals[gid].get(key) != old.get(key) for key in ('requirement_refs','acceptance','checker','subject_refs','checker_version','milestone_contract')):
                raise ValueError('goal conditions cannot be weakened by re-planning')
        for g in goals.values():
            if len(g['requirement_refs']) != len(set(g['requirement_refs'])):
                raise ValueError('duplicate obligation mapping')
            if not g['acceptance'] or not g['subject_refs'] or g['phase_id'] not in phases:
                raise ValueError('goal needs condition, subject and phase')
            if not g['requirement_refs'] or not set(g['requirement_refs']) <= self.requirements.keys():
                raise ValueError('unknown goal requirement')
            if g['checker'] not in self.checkers:
                raise ValueError('unregistered checker; allowed keys: '+', '.join(sorted(self.checkers)))
            if not set(g['subject_refs']) <= self.data['subjects'].keys():
                raise ValueError('unknown subject identity; allowed keys: '+', '.join(sorted(self.data['subjects'])))
            if any(n not in tree.by_id for n in g.get('task_refs', [])):
                raise ValueError('unknown executable task')
        visiting, visited = set(), set()
        def visit(pid):
            if pid in visiting: raise ValueError('phase dependency cycle')
            if pid in visited: return
            if pid not in phases: raise ValueError('unknown phase dependency')
            visiting.add(pid)
            for dep in phases[pid].get('depends_on', []): visit(dep)
            visiting.remove(pid); visited.add(pid)
        for pid in phases: visit(pid)
        # Checks inspect failed/unverified inputs. Do not impose acceptance as
        # an execution dependency: the existing DAG alone schedules actions.
        return deepcopy(plan)

    @serialized_update
    def commit(self, plan):
        version = deepcopy(plan)
        from .provenance import freeze_goal_bindings
        freeze_goal_bindings(self.store,self.project_id,self.run_id,version)
        version['revision'] = len(self.data['plans']) + 1
        self.data['plans'].append(version)
        self.save()

    @serialized_update
    def bind_subjects(self, subjects):
        self.data['subjects'] = deepcopy(subjects)
        self.save()

    @serialized_update
    def record(self, goal_id, result, *, executor_ref):
        goals = {g['id']: g for g in self.data['plans'][-1]['goals']}
        g = goals[goal_id]
        binding = self.checkers[g['checker']]
        if executor_ref != binding or result.executor_ref != binding:
            raise ValueError('producer cannot attest a goal')
        if (result.project_id, result.run_id) != (self.project_id, self.run_id):
            raise ValueError('checker receipt belongs to another run')
        saved = self.store.load_result(self.project_id, self.run_id, result.node_id)
        if identity(saved.as_dict()) != identity(result.as_dict()):
            raise ValueError('checker receipt is not current stored execution')
        observed = result.as_dict()['outputs'].get('goal_check', {})
        expected = {ref: self.data['subjects'].get(ref) for ref in g['subject_refs']}
        bindings_valid = (observed.get('execution') == 'VALID'
                 and observed.get('goal_id') == goal_id
                 and (g.get('checker_version') is None or observed.get('checker_version') == g['checker_version'])
                 and observed.get('condition_hash') == identity(g['acceptance'])
                 and observed.get('subjects') == expected and all(expected.values())
                 and bool(observed.get('evidence_refs')) and observed.get('observed') is not None
                 and observed.get('observed') not in ('', {}, []))
        valid = result.status.value == 'SUCCEEDED' and bindings_valid
        verdict = observed.get('verdict') if valid else 'INSUFFICIENT_EVIDENCE'
        provenance = {'status':'INSUFFICIENT_EVIDENCE','reason':'legacy evidence; no production provenance contract'}
        if (self.root/'provenance_contract.json').exists():
            from .provenance import ProvenanceGate
            provenance = ProvenanceGate(self.store,self.project_id,self.run_id).verify_check(result,g,expected)
            if provenance['status'] != 'TRUSTED':
                valid=False
                verdict='INSUFFICIENT_EVIDENCE'
            elif bindings_valid and provenance['chain']['verdict'] == 'FAILED':
                valid=True
                verdict='FAILED'
        if verdict not in {'VERIFIED', 'FAILED', 'HUMAN_DECISION_REQUIRED'}:
            verdict = 'INSUFFICIENT_EVIDENCE'
        row = {'goal_id': goal_id, 'verdict': verdict, 'subjects': observed.get('subjects'),
               'condition_hash': observed.get('condition_hash'), 'attempt_id': result.attempt_id,
               'node_id': result.node_id, 'run_id': result.run_id,
               'receipt_hash': identity(result.as_dict()), 'observation': observed,
               'plan_revision': self.data['plans'][-1]['revision'], 'provenance':provenance}
        if any(r['receipt_hash'] == row['receipt_hash'] and r['goal_id'] == goal_id for r in self.data['checks']):
            return next(r for r in self.data['checks'] if r['receipt_hash'] == row['receipt_hash'] and r['goal_id'] == goal_id)
        comparable = [r for r in self.data['checks'] if r['goal_id'] == goal_id
                      and r['subjects'] == row['subjects'] and r['condition_hash'] == row['condition_hash']]
        supersedes = list(observed.get('supersedes_receipts', []))
        if supersedes and not valid:
            raise ValueError('invalid observation cannot supersede evidence')
        if not set(supersedes) <= {r['receipt_hash'] for r in comparable}:
            raise ValueError('supersession must reference applicable evidence for the same goal')
        supersedes += [r['receipt_hash'] for r in comparable
                       if valid and r['node_id'] == row['node_id'] and r['attempt_id'] < row['attempt_id']]
        row['supersedes_receipts'] = sorted(set(supersedes))
        self.data['checks'].append(row)
        self.save()
        return row

    def view(self, *, reload=True):
        if not (self.root/'provenance_contract.json').exists():
            return self._view(reload=reload)
        from .provenance import ProvenanceGate, ProvenanceError
        gate = ProvenanceGate(self.store, self.project_id, self.run_id)
        try:
            with gate.read_binding_snapshot():
                result = self._view(reload=reload, provenance_gate=gate)
            return result
        except ProvenanceError:
            # A changing/unavailable contract cannot yield trusted statistics.
            return self._view(reload=reload, provenance_gate=False)

    def _view(self, *, reload=True, provenance_gate=None):
        if reload:self._reload()
        plan = self.data['plans'][-1] if self.data['plans'] else {'goals': [], 'phases': []}
        from cgkn.adapters.veriarbor.substitution_adapter import replacements, reuse_cover
        replacement_proofs, replacement_checkers = replacements(self, provenance_gate)
        rows = []
        for g in plan['goals']:
            subjects = {ref: self.data['subjects'].get(ref) for ref in g['subject_refs']}
            native_available = any(r['goal_id'] == g['id'] and r['subjects'] == subjects
                                   and r['condition_hash'] == identity(g['acceptance'])
                                   for r in self.data['checks'])
            matching = []
            for historical in self.data['checks']:
                if historical['goal_id'] != g['id'] or historical['condition_hash'] != identity(g['acceptance']):
                    continue
                if historical['subjects'] == subjects:
                    matching.append(historical)
                    continue
                if native_available:
                    continue
                peers = [r for r in self.data['checks'] if r['goal_id'] == g['id']
                         and r['subjects'] == historical['subjects']
                         and r['condition_hash'] == historical['condition_hash']]
                superseded_peers = {h for r in peers for h in r.get('supersedes_receipts', ())}
                if historical['receipt_hash'] in superseded_peers or any(r['verdict'] != 'VERIFIED'
                        for r in peers if r['receipt_hash'] not in superseded_peers):
                    continue
                cover = reuse_cover(g, historical, subjects, replacement_proofs, replacement_checkers)
                if cover:
                    matching.append({**historical, 'certified_substitutions': cover,
                                     'effective_subjects': subjects})
            superseded = {h for r in matching for h in r.get('supersedes_receipts', [])}
            effective = [deepcopy(r) for r in matching if r['receipt_hash'] not in superseded]
            if provenance_gate is not None:
                from cgkn.execution import BlockExecutionResult
                gate=provenance_gate
                for row in effective:
                    try:
                        if gate is False:raise ValueError('untrusted binding snapshot')
                        path=self.root/'attempts'/row['node_id']/(row['attempt_id']+'.json')
                        raw=json.loads(path.read_text(encoding='utf-8'))
                        if identity(raw)!=row['receipt_hash']:raise ValueError('changed stored receipt')
                        verified=gate.verify_check(BlockExecutionResult.from_dict(raw),g,row['subjects'])
                        if verified['status']!='TRUSTED':row['verdict']='INSUFFICIENT_EVIDENCE'
                        if reload:
                            from pathlib import Path
                            from .provenance import file_hash
                            for subject,path in gate.binding().get('current_artifacts',{}).items():
                                if subject in subjects and (not Path(path).is_file() or file_hash(path)!=subjects[subject]):
                                    row['verdict']='INSUFFICIENT_EVIDENCE'
                    except (OSError,ValueError,KeyError,TypeError):row['verdict']='INSUFFICIENT_EVIDENCE'
            # A counterexample is not outvoted by a later independent PASS.
            rank = {'FAILED': 0, 'HUMAN_DECISION_REQUIRED': 1, 'INSUFFICIENT_EVIDENCE': 2, 'VERIFIED': 3}
            record = min(effective, key=lambda r: (rank[r['verdict']], r['receipt_hash'])) if effective else None
            rows.append({**g, 'verdict': record['verdict'] if record else 'INSUFFICIENT_EVIDENCE',
                         'evidence': ({k:v for k,v in record.items() if k!='observation'} | {'evidence_refs':record['observation'].get('evidence_refs',[]),'reason':record['observation']['observed'].get('reason') if isinstance(record['observation'].get('observed'),dict) else None}) if record else None, 'must': any(self.requirements[r]['must'] for r in g['requirement_refs'])})
        uncovered = [r for r, req in self.requirements.items() if req['must'] and not req.get('children') and
                     not any(r in g['requirement_refs'] for g in rows)]
        phases = []
        for p in plan['phases']:
            required = [g for g in rows if g['phase_id'] == p['id'] and g['must']]
            phase_status = 'NOT_REQUIRED' if not required else 'VERIFIED' if all(g['verdict']=='VERIFIED' for g in required) else 'FAILED' if any(g['verdict']=='FAILED' for g in required) else 'INSUFFICIENT_EVIDENCE'
            phases.append({**p, 'acceptance': phase_status})
        for _ in phases:
            for p in phases:
                if any(next(x for x in phases if x['id']==dep)['acceptance'] not in {'VERIFIED','NOT_REQUIRED'} for dep in p.get('depends_on', [])):
                    if p['acceptance'] != 'FAILED': p['acceptance']='INSUFFICIENT_EVIDENCE'
        from cgkn.adapters.veriarbor.acceptance_adapter import obligation_rollup
        reduction = obligation_rollup(self.requirements, rows)
        obligations = reduction['obligations']
        completion = reduction['completion']
        coverage = reduction['evidence_coverage']
        hard_verdict = reduction['hard_verdict']
        total = sum(r['weight'] for r in obligations.values())
        complete = bool(rows) and not uncovered and hard_verdict == 'VERIFIED' and total > 0 and all(p['acceptance'] in {'VERIFIED','NOT_REQUIRED'} for p in phases)
        return {'obligations':obligations, 'hard_verdict':hard_verdict, 'completion':completion, 'evidence_coverage':coverage,
                'requirements': self.requirements, 'checker_bindings':self.checkers, 'subject_identities':self.data['subjects'], 'goals': rows, 'phases': phases,
                'uncovered_must': uncovered, 'complete': complete,
                'evidence_mode':'production_provenance' if (self.root/'provenance_contract.json').exists() else 'legacy_unverified_provenance',
                'progress_basis': 'verified required goals; not executed tasks or elapsed time'}

    def revalidation_scope(self, dag, *, changed_nodes=(), changed_checkers=()):
        """Project dependency impact onto goals; do not schedule or mutate evidence."""
        from cgkn.adapters.veriarbor.block_adapter import local_scope
        affected, bubbles = local_scope(dag, changed_nodes)
        affected = set(affected)
        goals = self.data['plans'][-1]['goals'] if self.data['plans'] else []
        return {'affected_tasks': sorted(affected),
                'recheck_goals': sorted(g['id'] for g in goals if
                    affected.intersection(g.get('task_refs', [])) or g['checker'] in changed_checkers),
                'authority': 'one-hop impact inspection only; no automatic execution or certificate reuse',
                'boundary_recheck_required': sorted(changed_nodes)}

    def render(self):
        """Escaped, read-only report from the same records; no invented dates."""
        import html
        view = self.view()
        esc = lambda value: html.escape(str(value))
        rows = ''.join('<tr>' + ''.join('<td>'+esc(value)+'</td>' for value in
            (g['phase_id'], g['id'], g['acceptance'], g['verdict'],
             'inspect evidence gap' if g['verdict']!='VERIFIED' else 'verified properties only',
             g['evidence']['node_id'] if g['evidence'] else 'not checked')) + '</tr>' for g in view['goals'])
        page = '<!doctype html><meta charset="utf-8"><title>Goal acceptance</title><h1>Goal acceptance</h1>'
        page += '<p>Relative milestones; no reliable calendar estimate supplied. Execution completion is not acceptance.</p>'
        page += '<p>Uncovered MUST: '+esc(view['uncovered_must'])+'</p>'
        page += '<table border="1"><tr><th>Phase</th><th>Goal</th><th>Condition</th><th>Acceptance</th><th>Next</th><th>Receipt node</th></tr>'+rows+'</table>'
        page += '<pre>'+esc(json.dumps(view['phases'], ensure_ascii=False, indent=2))+'</pre>'
        path = self.root / 'stage-view.html'
        path.write_text(page, encoding='utf-8')
        return path

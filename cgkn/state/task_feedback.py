"""Derived task feedback in FileRunStore, never an acceptance authority.

Terminal facts are immutable and immediately visible. Semantic evaluations are
versioned hypotheses; only existing goal acceptance can establish delivery.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path

from cgkn.component.spec import _thaw
from cgkn.artifacts.evidence_identity import digest




class TaskFeedback:
    def __init__(self, store, project_id, run_id):
        self.store = store
        self.project_id, self.run_id = project_id, run_id
        self.root = store.run_dir(project_id, run_id)

    def terminal(self, result, node):
        """Called by the coordinator only after the immutable receipt commits."""
        receipt = self.root / 'attempts' / result.node_id / (result.attempt_id + '.json')
        raw = json.loads(receipt.read_text(encoding='utf-8'))
        if raw != result.as_dict():
            raise ValueError('feedback receipt mismatch')
        ref = receipt.relative_to(self.root).as_posix()
        identity = digest([self.project_id, self.run_id, result.node_id, result.attempt_id])
        path = self.root / 'feedback' / (identity + '.json')
        row = dict(identity=identity, node_id=result.node_id, attempt_id=result.attempt_id,
            parent_id=node.parent_id, goal=str(node.config.get('leaf_contract',{}).get('leaf_goal',node.config.get('goal', result.node_id))),
            receipt_ref=ref, receipt_sha256=digest(raw), status=result.status.value,
            error=raw.get('error'), capability_ref=node.capability_ref,
            actual_model=raw.get('usage', {}).get('model') or 'UNKNOWN',
            routing=raw.get('usage', {}).get('routing', {}),
            evaluation_state='NOT_REQUIRED_META' if node.config.get('meta_operation') or raw.get('metadata',{}).get('reconciliation') or result.executor_ref == 'task.evaluate@1' else 'PENDING',
            business_acceptance='INSUFFICIENT_EVIDENCE')
        row.update(task_class=str(node.config.get('task_class',node.capability_ref)),
            operation=str(node.config.get('operation',node.capability_ref)),
            config_hash=str(raw.get('usage',{}).get('config_hash','UNKNOWN')),
            repair_count=int(node.config.get('repair_count',0)),role=str(node.config.get('role','worker')))
        refs=raw.get('metadata',{}).get('typed_observation_refs',[])
        row['deliverable_verdict'] = raw.get('metadata',{}).get('deliverable_verdict','LEGACY_UNQUALIFIED_DELIVERABLE')
        row['implementation_progress'] = raw.get('metadata',{}).get('implementation_progress')
        row['capability_scope'] = {k:_thaw(node.config.get(k,'UNKNOWN')) for k in ('artifact_domain','environment','tool_identity')}
        if refs:
            from cgkn.execution.observations import Observations
            observations=Observations(self.store,self.project_id,self.run_id)
            for ref in refs:observations.resolve(ref)
            row['typed_observation_refs']=refs
        if path.exists():
            if json.loads(path.read_text(encoding='utf-8')) != row:
                raise ValueError('conflicting terminal feedback')
        else:
            self.store.immutable_json(path, row)
        return row

    def revise(self, identity, revision, evaluation, *, supersedes=None):
        """Trusted evaluator output is advisory, including when it says success.

        Explicit predecessor revisions prevent arrival order from deciding truth.
        Replayed identical revisions are idempotent; conflicts are rejected.
        """
        self.store._validate_segment(identity)
        facts = json.loads((self.root / 'feedback' / (identity + '.json')).read_text(encoding='utf-8'))
        if facts['evaluation_state'] == 'NOT_REQUIRED_META':
            raise ValueError('meta operations must not recursively evaluate themselves')
        if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
            raise ValueError('positive evaluation revision required')
        if supersedes != (revision - 1 if revision > 1 else None):
            raise ValueError('explicit contiguous predecessor required')
        directory = self.root / 'evaluations' / identity
        if revision > 1 and not (directory / f'{supersedes:06d}.json').exists():
            raise ValueError('evaluation predecessor missing')
        allowed = {'observations', 'evidence_refs', 'hypothesis', 'uncertainty',
                   'required_capabilities', 'candidate_lesson', 'recommendation', 'model'}
        v2 = {'evaluation_id','source_attempt_id','capability_tags','outcome_interpretation',
              'failure_domain','failure_reason_summary','confidence','informative_for_routing',
              'why_this_recommendation','unresolved_questions'}
        if set(evaluation) not in (allowed, allowed | v2) or not isinstance(evaluation['evidence_refs'], list):
            raise ValueError('invalid advisory evaluation contract')
        if not evaluation['evidence_refs'] or any(r != facts['receipt_ref'] for r in evaluation['evidence_refs']):
            raise ValueError('evaluation must cite the exact public attempt receipt')
        row = dict(identity=identity, revision=revision, supersedes=supersedes,
                   receipt_sha256=facts['receipt_sha256'], advisory=evaluation,
                   acceptance_authority=False)
        from cgkn.protocol.review_policy import review_kind
        row['review_kind'] = review_kind(facts.get('actual_model'), evaluation.get('model'))
        row['producer_actual_model'] = facts.get('actual_model', 'UNKNOWN')
        row['reviewer_actual_model'] = evaluation.get('model', 'UNKNOWN')
        path = directory / f'{revision:06d}.json'
        if path.exists():
            if json.loads(path.read_text(encoding='utf-8')) != row:
                raise ValueError('conflicting evaluation revision')
        else:
            self.store.immutable_json(path, row)
        return row

    def attempt(self, identity):
        """Resolve an exact attempt; bounded context is only a navigation view."""
        self.store._validate_segment(identity)
        fact = json.loads((self.root / 'feedback' / (identity + '.json')).read_text(encoding='utf-8'))
        self.store._validate_segment(fact['node_id'])
        self.store._validate_segment(fact['attempt_id'])
        expected_ref = f"attempts/{fact['node_id']}/{fact['attempt_id']}.json"
        if fact['identity'] != identity or identity != digest([
                self.project_id, self.run_id, fact['node_id'], fact['attempt_id']]):
            raise ValueError('feedback identity mismatch')
        if fact['receipt_ref'] != expected_ref:
            raise ValueError('feedback receipt reference mismatch')
        receipt = json.loads((self.root / expected_ref).read_text(encoding='utf-8'))
        if digest(receipt) != fact['receipt_sha256']:
            raise ValueError('feedback receipt hash mismatch')
        revisions = sorted((self.root / 'evaluations' / identity).glob('*.json'))
        return {**fact, 'evaluation': json.loads(revisions[-1].read_text(encoding='utf-8')) if revisions else None}

    def context(self, *, node_ids=None, limit=8):
        """Bounded public feedback. No scan of private acceptance directories."""
        rows = []
        for path in sorted((self.root / 'feedback').glob('*.json')):
            fact = json.loads(path.read_text(encoding='utf-8'))
            if node_ids is not None and fact['node_id'] not in node_ids:
                continue
            rows.append(self.attempt(fact['identity']))
        # Highest attempt per logical node is current; old failures remain on disk.
        latest = {}
        for row in rows:
            if row['attempt_id'] > latest.get(row['node_id'], {}).get('attempt_id', ''):
                latest[row['node_id']] = row
        selected = sorted(latest.values(), key=lambda r: (r['status'] == 'SUCCEEDED', r['node_id']))
        stagnant = {}
        for row in rows:
            progress = row.get('implementation_progress') or {}
            if progress.get('verdict') == 'NO_IMPLEMENTATION_PROGRESS':
                # A new observation can justify another attempt. A new receipt
                # ID alone is not new evidence; compare normalized observations.
                key = (row['node_id'], progress.get('strategy_hash'), progress.get('observation_hash'))
                if key[1] and key[2]:
                    stagnant.setdefault(key, []).append(row['receipt_ref'])
        return {'items': selected[:limit], 'total_nodes': len(latest),
                'progress_signals':[{'signal':'REPEATED_NO_PROGRESS_STRATEGY', 'node_id':key[0],
                    'strategy_hash':key[1], 'observation_hash':key[2],
                    'evidence_refs':refs,'suggested_actions':['inspect','split','change_route','different_strategy']}
                    for key,refs in stagnant.items() if len(refs)>1],
                'business_successes': 0, 'statistics_scope': 'execution observations; acceptance not inferred'}

    def localized(self, tree, node_id, *, limit=8):
        """Navigation over ownership and dependency closure; no sibling broadcast."""
        nodes = tree.by_id
        if node_id not in nodes:
            raise ValueError('unknown feedback target')
        relevant, pending = set(), [node_id]
        while pending:
            ident = pending.pop()
            if ident in relevant:
                continue
            relevant.add(ident)
            node = nodes[ident]
            pending.extend(node.depends_on)
            if node.parent_id:
                pending.append(node.parent_id)
        # A structural owner sees descendant summaries, never their private raw data.
        if not nodes[node_id].executable:
            pending = [node_id]
            while pending:
                children = [n.id for n in tree.children(pending.pop())]
                relevant.update(children)
                pending.extend(children)
        result = self.context(node_ids=relevant, limit=limit)
        result['closure'] = sorted(relevant)
        result['authority'] = 'raw receipt references; runtime navigation only'
        return result

    def statistics(self, acceptance=None):
        """Rebuild current contributions; never turn advisory confidence into wins.

        A trusted goal checker may explicitly cite affected task receipt hashes
        in goal_check.task_receipts. Older unlinked checks remain unassessed.
        """
        current = self.context(limit=100000)['items']
        goals = acceptance.view()['goals'] if acceptance else []
        contributions = []
        for fact in current:
            checks = []
            for goal in goals:
                evidence = goal.get('evidence') or {}
                matching = [row for row in acceptance.data['checks']
                            if row.get('receipt_hash') == evidence.get('receipt_hash')]
                if matching and fact['receipt_sha256'] in matching[-1]['observation'].get('task_receipts', []):
                    checks.append({'goal_id': goal['id'], 'verdict': goal['verdict'],
                                   'receipt_hash': evidence['receipt_hash']})
            verdict = ('FAILED' if any(c['verdict'] == 'FAILED' for c in checks)
                       else 'VERIFIED' if checks and all(c['verdict'] == 'VERIFIED' for c in checks)
                       else 'INSUFFICIENT_EVIDENCE')
            contributions.append({'node_id': fact['node_id'], 'attempt_id': fact['attempt_id'],
                'actual_model': fact.get('actual_model', 'UNKNOWN'), 'capability_ref': fact['capability_ref'],
                'execution': fact['status'], 'acceptance': verdict, 'evidence': checks,
                'confirmed_model_success': verdict == 'VERIFIED' and fact['status'] == 'SUCCEEDED' and fact.get('actual_model', 'UNKNOWN') != 'UNKNOWN' and fact.get('routing', {}).get('identity_status') == 'MATCH',
                'evaluation_revision': (fact['evaluation'] or {}).get('revision')})
        return {'snapshot_sha256': digest(contributions), 'contributions': contributions,
                'scope': 'linked checked properties only; not a model ranking or whole-project delivery'}

    def publish_candidate(self, identity, revision):
        """Publish an advisory candidate via the existing knowledge schema.

        It remains excluded from approved retrieval until the existing review
        process validates it. No automatic acceptance from a model score.
        """
        from src.cgnk_knowledge.store import new_project_knowledge_pack, upsert_knowledge_items
        self.store._validate_segment(identity)
        row = json.loads((self.root / 'evaluations' / identity / f'{revision:06d}.json').read_text(encoding='utf-8'))
        source = f'evaluations/{identity}/{revision:06d}.json'
        item = {'kind': 'KnowledgeItem', 'id': 'evaluation-' + identity + '-' + str(revision),
            'title': 'Task evaluation candidate', 'type': 'research_finding',
            'scope': 'project', 'content': row['advisory']['candidate_lesson'],
            'source_refs': [source], 'tags': row['advisory']['required_capabilities'],
            'importance': 'medium', 'need_state': 'needed_later', 'retention': 'keep',
            'review_state': 'candidate', 'status': 'uncertain', 'visibility': 'public',
            'supersedes': [], 'stable_hash': digest(row), 'diagnostics': []}
        pack = upsert_knowledge_items(new_project_knowledge_pack(self.project_id), [item])
        path = self.root / 'knowledge_candidates' / (item['id'] + '.json')
        if path.exists() and json.loads(path.read_text(encoding='utf-8')) != pack:
            raise ValueError('candidate publication identity conflict')
        self.store.immutable_json(path, pack)
        return {'path': path.relative_to(self.root).as_posix(), 'sha256': digest(pack),
                'review_state': 'candidate', 'publication': 'not approved reusable experience'}


class FrozenKnowledge:
    """Adapter to the existing ProjectKnowledgePack retrieval contract.

    The caller supplies an explicitly public, finalized snapshot. This adapter
    never scans the Corpus, private files, or live candidate knowledge.
    """
    def __init__(self, pack):
        if pack.get('kind') != 'ProjectKnowledgePack':
            raise ValueError('existing ProjectKnowledgePack required')
        self.pack = json.loads(json.dumps(pack))
        self.version = digest(self.pack)

    def retrieve(self, tags):
        from src.cgnk_knowledge.retrieve import retrieve_relevant_knowledge
        # Existing retrieval ranks broad candidates. Narrow visibility here to
        # approved, current, relevant facts before invoking that same retriever.
        public = {**self.pack, 'all_items': [item for item in self.pack.get('all_items', [])
            if item.get('review_state') == 'accepted' and item.get('status') == 'active'
            and item.get('visibility') == 'public'
            and set(item.get('tags', [])) & set(tags)]}
        result = retrieve_relevant_knowledge(public, {'selected_modules': list(tags), 'max_items': 4})
        value = {'snapshot_sha256': self.version, 'selected_items': result['selected_items'],
                 'applied_lesson_ids': [i['id'] for i in result['selected_items']],
                 'scope': 'finalized public knowledge only'}
        return {**value, 'context_sha256': digest(value)}

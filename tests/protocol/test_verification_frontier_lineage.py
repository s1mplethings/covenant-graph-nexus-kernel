from cgkn.protocol.context_pack import dependency_ready_goals


def goal(name, verdict, dependencies=()):
    return {'id': name, 'verdict': verdict,
            'milestone_contract': {'dependency_goal_ids': list(dependencies)}}


def test_materialized_but_unverified_upstream_never_unlocks_downstream():
    upstream = goal('a', 'INSUFFICIENT_EVIDENCE')
    upstream['artifact_exists'] = True
    rows = [upstream, goal('b', 'INSUFFICIENT_EVIDENCE', ['a'])]
    assert [g['id'] for g in dependency_ready_goals(rows)] == ['a']


def test_failed_ancestor_blocks_cached_verified_child_and_only_affected_branch():
    rows = [goal('a', 'FAILED'), goal('b', 'VERIFIED', ['a']),
            goal('c', 'INSUFFICIENT_EVIDENCE', ['b']),
            goal('independent', 'INSUFFICIENT_EVIDENCE')]
    assert [g['id'] for g in dependency_ready_goals(rows)] == ['a', 'independent']
    rows[0]['verdict'] = 'VERIFIED'
    assert [g['id'] for g in dependency_ready_goals(rows)] == ['c', 'independent']


def test_missing_or_cyclic_verified_dependency_fails_closed():
    rows = [goal('a', 'VERIFIED', ['b']), goal('b', 'VERIFIED', ['a']),
            goal('c', 'FAILED', ['a']), goal('d', 'FAILED', ['missing'])]
    assert dependency_ready_goals(rows) == []


def test_unknown_effect_blocks_only_affected_goal_branch():
    a=goal('a','VERIFIED');a['subject_refs']=['a.py']
    b=goal('b','FAILED',['a']);b['subject_refs']=['b.py','a.py']
    c=goal('c','INSUFFICIENT_EVIDENCE');c['subject_refs']=['c.py']
    assert [g['id'] for g in dependency_ready_goals([a,b,c],['a.py'])]==['c']
    from cgkn.protocol.context_pack import task_readiness_projection
    projection=task_readiness_projection([a,b,c],{'a.py':'hash','b.py':'hash'},['a.py'])
    assert projection[0]['artifact_exists'] and not projection[0]['acceptance_verified']
    assert projection[1]['state']=='BLOCKED'
    assert projection[2]['state']=='READY'


def test_shared_dependency_dag_does_not_expand_as_recursive_paths():
    rows=[goal(str(i),'VERIFIED',[str(j) for j in range(i)]) for i in range(45)]
    rows.append(goal('next','FAILED',[str(i) for i in range(45)]))
    assert [g['id'] for g in dependency_ready_goals(rows)]==['next']

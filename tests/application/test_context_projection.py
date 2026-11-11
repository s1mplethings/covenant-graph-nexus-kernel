from cgkn.application.goal_driven import deduplicate_gap_view

def test_shared_context_is_losslessly_referenced_without_result_multiplication():
    acceptance={'requirements':{f'R{i}':{'description':f'requirement {i}'} for i in range(7)},
                'goals':[{'id':'root','requirement_refs':[f'R{i}' for i in range(7)],'verdict':'INSUFFICIENT_EVIDENCE'}]}
    feedback=[{'source':'user','text':'retain original negative feedback'}]
    for count in [1,8]:
        results={str(i):{'status':'SUCCEEDED','outputs':{'summary':'bounded observation'}} for i in range(count)}
        old=[{'requirement_ref':r,'requirement':v['description'],'acceptance':acceptance['goals'],'user_feedback':feedback,
              'observations':[dict(node_id=n,**v) for n,v in results.items()],'cause_status':'unverified'} for r,v in acceptance['requirements'].items()]
        new=deduplicate_gap_view(old,acceptance,results,feedback)
        rebuilt=[]
        for g in new:
            rebuilt.append({'requirement_ref':g['requirement_ref'],'requirement':acceptance['requirements'][g['requirement_ref']]['description'],
                'acceptance':[x for x in acceptance['goals'] if x['id'] in g['acceptance_goal_ids']],
                'user_feedback':feedback,'observations':[dict(node_id=n,**results[n]) for n in g['observation_node_ids']], 'cause_status':g['cause_status']})
        assert rebuilt==old
        assert all('outputs' not in str(g) for g in new)

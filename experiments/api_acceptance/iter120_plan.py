"""Prepare an unapproved, bounded two-call plan. Never submits or authorizes."""
import json,time
from experiments.api_acceptance import iter119_pair as pair
from experiments.api_acceptance.iter120_audit import OUT,OLD,save

def prepare():
    plan=pair.read(OLD/'plan.json');plan.update(kind='ITER120AuthorizedPair',max_cny=.2)
    q,d=plan['requests'];d['output_limit']=2048
    q['system']='Return only a PlanningProposal JSON satisfying the schema. Propose three core capabilities, two workstreams, a concrete user workflow and testable acceptance anchors. Ground capabilities in exact fragments of the raw goal. Keep descriptions concise and useful. This is a bounded proposal for Agent review, not canonical project planning or execution.'
    q['user']='Raw goal: Build an offline personal expense CSV analyzer for one user. Import CSV rows with date, category and amount, validate malformed rows with line-number errors, and show monthly category totals. Allow exporting the summarized totals as CSV. No cloud accounts or network access. Propose implementation boundaries, acceptance checks and relevant failure handling; do not write a full application.'
    d['system']='Return only one JSON object matching the supplied schema. Design a small deterministic Python utility and its tests. No tools, network, project files or dependencies. This task is independent of every other request.'
    d['user']='Design normalize_intervals(intervals), a Python function accepting integer half-open intervals. Reject reversed intervals and non-integer endpoints (including bool), discard empty intervals, sort and merge overlapping or touching intervals without mutating the input. Return the signature, a complete concise implementation, six concrete test cases with expected results or errors, complexity, and a short explanation of boundary choices.'
    d['schema']={'type':'object','additionalProperties':False,'required':['signature','implementation','tests','complexity','boundary_notes'],
        'properties':{'signature':{'type':'string'},'implementation':{'type':'string'},'complexity':{'type':'string'},'boundary_notes':{'type':'string'},
            'tests':{'type':'array','minItems':6,'maxItems':6,'items':{'type':'object','additionalProperties':False,'required':['name','input','expected'],
                'properties':{'name':{'type':'string'},'input':{'type':'string'},'expected':{'type':'string'}}}}}}
    path=OUT/'live-plan-pending';path.mkdir(exist_ok=True)
    save(path/'plan.json',plan)
    pricing=dict(verified_unix=time.time(),currency='CNY',unit='per_million_tokens',qwen=dict(input=.8,output=2.7,region='Beijing',source='https://help.aliyun.com/zh/model-studio/qwen3-8-flash'),
        deepseek=dict(input=2,output=8,mode='peak_cache_miss',source='https://api-docs.deepseek.com/zh-cn/quick_start/pricing/'),
        provider_price_upper_cny=.0448512,budget_reservation_rates=dict(input=4,output=16),budget_upper_cny=.131072,
        reread_before_submission=True,free_quota_assumed=False)
    save(path/'pricing.json',pricing)
    save(path/'preflight.json',pair.preflight(plan))
    save(path/'authorization.json',dict(authorized=False,status='BLOCKED_AUTHORIZATION',max_posts=2,max_cny=.2,
        plan_sha256=pair.digest(path/'plan.json'),pricing_sha256=pair.digest(path/'pricing.json'),
        note='No new paid authorization in ITER-120. No attempt or worker may be claimed. Recheck prices and freeze reviewed source/Gateway identity after explicit authorization.'))
    return path

if __name__=='__main__':print(prepare())

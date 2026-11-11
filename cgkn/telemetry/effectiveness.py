"""Read-only projections of task evidence; never a router or acceptance authority."""
from decimal import Decimal
import math


def number(value, *, positive=False):
    if isinstance(value, bool) or value is None:
        raise ValueError('finite numeric value required')
    value = float(value)
    if not math.isfinite(value) or value < 0 or (positive and value == 0):
        raise ValueError('invalid nonnegative value')
    return value


def request_counts(records):
    """Classify application requests independently from configured roles."""
    unique = {}
    for row in records:
        key = row['request_id']
        if key in unique and unique[key] != row:
            raise ValueError('conflicting request notification')
        unique[key] = dict(row)
    purposes = {}
    roles = {}
    tasks = set()
    for row in unique.values():
        purpose = row['schema']
        purposes[purpose] = purposes.get(purpose, 0) + 1
        roles[row['role']] = roles.get(row['role'], 0) + 1
        tasks.add(row['logical_task_id'])
    return {'application_requests':len(unique), 'logical_tasks':len(tasks), 'purposes':purposes,
            'roles':roles, 'upstream_http_requests':None,
            'scope':'upstream attempts require separate transport receipts'}


def utility(p_safe, time, cost, *, time_reference, cost_reference, time_weight=.5, cost_weight=.5):
    p, t, c = map(number, (p_safe, time, cost))
    tr, cr = number(time_reference, positive=True), number(cost_reference, positive=True)
    tw, cw = number(time_weight), number(cost_weight)
    if p > 1 or not math.isclose(tw + cw, 1, rel_tol=0, abs_tol=1e-12):
        raise ValueError('invalid probability or weights')
    return 100 * p / (1 + tw * t / tr + cw * c / cr)


def beta_lower(successes, failures, *, alpha=1, beta=1, quantile=.05):
    from scipy.special import betaincinv
    if any(isinstance(n, bool) or not isinstance(n, int) or n < 0 for n in (successes, failures)):
        raise ValueError('counts must be nonnegative integers')
    a, b, q = number(alpha, positive=True), number(beta, positive=True), number(quantile, positive=True)
    if q >= 1:
        raise ValueError('quantile must be below one')
    return float(betaincinv(a + successes, b + failures, q))


def task_cost(receipts, *, currency, price_version):
    """One actual request identity per charge; repeated notifications are idempotent."""
    unique = {}
    for row in receipts:
        key = row['call_id']
        if not key or row['currency'] != currency or row['price_version'] != price_version:
            raise ValueError('identity/currency/price scope mismatch')
        if key in unique and unique[key] != row:
            raise ValueError('conflicting charge receipts require explicit reconciliation')
        unique[key] = dict(row)
    total = Decimal(0)
    unknown = []
    kinds = set()
    for key, row in unique.items():
        kinds.add(row['cost_kind'])
        if row.get('amount') is None or row.get('outcome') == 'UNKNOWN':
            unknown.append(key)
            if row.get('amount') is None:
                continue
        amount = Decimal(str(row['amount']))
        if not amount.is_finite() or amount < 0:
            raise ValueError('invalid amount')
        total += amount
    if len(kinds) > 1:
        raise ValueError('estimates and actual charges must remain separate')
    return {'known_total': str(total), 'complete_total': None if unknown else str(total),
            'unknown_call_ids': sorted(unknown), 'request_count': len(unique),
            'currency': currency, 'price_version': price_version, 'cost_kinds': sorted(kinds),
            'receipts': list(unique.values())}


def task_time(*, ready, ended, now, intervals, clock_id):
    ready, now = number(ready), number(now)
    if now < ready or not clock_id:
        raise ValueError('invalid clock interval')
    stop = now if ended is None else number(ended)
    if not ready <= stop <= now:
        raise ValueError('invalid end time')
    accumulated = 0
    categories = {k:0 for k in ('provider_wait_time','tool_time','acceptance_time','repair_time','external_blocked_time')}
    for row in intervals:
        if row['clock_id'] != clock_id:
            raise ValueError('incompatible clocks')
        a, b = number(row['start']), number(row['end'])
        if not ready <= a <= b <= stop:
            raise ValueError('branch outside task interval')
        accumulated += b - a
        category=row.get('category','tool_time')
        if category not in categories:raise ValueError('unknown time category')
        categories[category] += b-a
        if row.get('phase')=='repair' and category!='repair_time':categories['repair_time']+=b-a
    return {'elapsed': stop-ready, 'complete_duration': None if ended is None else stop-ready,
            'branch_execution_sum': accumulated, 'active_execution_time':accumulated-categories['external_blocked_time'],
            **categories, 'task_wall_time':stop-ready, 'excluded_time':0,
            'censored': ended is None, 'clock_id': clock_id}


def effectiveness(samples, *, task_ids, configuration, time_reference, cost_reference,
                  alpha=1, beta=1, quantile=.05, time_weight=.5, cost_weight=.5, p_required=None):
    """A fixed task cohort, with all terms calculated on exactly one settled subset."""
    if p_required is not None and number(p_required) > 1:
        raise ValueError('invalid reliability display threshold')
    if not isinstance(configuration, dict) or any(not configuration.get(k) for k in
            ('actual_model','model_version','task_family','difficulty','tools','context','repair_protocol')):
        raise ValueError('explicit confirmed model and comparison conditions required')
    if len(task_ids) != len(set(task_ids)):
        raise ValueError('duplicate logical task in cohort')
    utility(0, 0, 0, time_reference=time_reference, cost_reference=cost_reference,
            time_weight=time_weight, cost_weight=cost_weight)
    beta_lower(0, 0, alpha=alpha, beta=beta, quantile=quantile)
    versions = {}
    for sample in samples:
        if sample['task_id'] not in task_ids or sample['configuration'] != configuration:
            raise ValueError('sample outside fixed comparison scope')
        revision = sample['revision']
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
            raise ValueError('invalid revision')
        key = (sample['task_id'], revision)
        if key in versions and versions[key] != sample:
            raise ValueError('conflicting revision')
        if sample['delivery'] not in (0, 1, None) or sample['business'] not in (0, 1, None):
            raise ValueError('invalid verdict')
        if sample['delivery'] == 1 and (sample['business'] != 1 or not sample.get('acceptance_ref')):
            raise ValueError('delivery success requires business acceptance')
        for metric in ('duration', 'cost'):
            if sample.get(metric) is not None:
                number(sample[metric])
        if revision > 1 and sample.get('supersedes') != revision-1:
            raise ValueError('explicit revision chain required')
        versions[key] = dict(sample)
    for (task, rev) in versions:
        if rev > 1 and (task, rev-1) not in versions:
            raise ValueError('missing revision history')
    settled, pending = [], []
    for task in task_ids:
        history = [s for (t, _), s in versions.items() if t == task]
        row = max(history, key=lambda s:s['revision']) if history else None
        if row is None or row['delivery'] is None or row.get('duration') is None or row.get('cost') is None or not row.get('model_confirmed'):
            pending.append({'task_id': task, 'reason': 'missing result, complete metering or confirmed attribution', 'sample': row})
            continue
        number(row['duration']); number(row['cost'])
        settled.append(row)
    success = sum(s['delivery'] == 1 for s in settled)
    failure = len(settled)-success
    lower = beta_lower(success, failure, alpha=alpha, beta=beta, quantile=quantile)
    t = sum(number(s['duration']) for s in settled)/len(settled) if settled else None
    c = sum(number(s['cost']) for s in settled)/len(settled) if settled else None
    score = utility(lower, t, c, time_reference=time_reference, cost_reference=cost_reference,
                    time_weight=time_weight, cost_weight=cost_weight) if settled else None
    latest = [max((s for (t, _), s in versions.items() if t == task), key=lambda s:s['revision'])
              for task in task_ids if any(t == task for t, _ in versions)]
    business_samples = [s for s in latest if s['business'] is not None and s.get('model_confirmed') and s.get('acceptance_ref')]
    return {'schema_version':'1.0', 'configuration':configuration, 'cohort':list(task_ids),
            'provenance_mode':'UNVERIFIED_INPUT_PROJECTION',
            'settled_task_ids':[s['task_id'] for s in settled], 'pending':pending,
            'successes':success, 'failures':failure, 'p_safe':lower, 'mean_time':t, 'mean_cost':c,
            'posterior_mean':(alpha+success)/(alpha+beta+success+failure), 'q_safe':quantile,
            'n_total':len(task_ids),'n_settled':len(settled),'n_pending':len(pending),
            'references':{'time_reference':time_reference,'cost_reference':cost_reference,'time_weight':time_weight,'cost_weight':cost_weight},
            'utility':score, 'status':'NOT_COMPUTABLE' if not settled else 'PROVISIONAL' if pending else 'COMPUTABLE',
            'meets_reliability': (bool(settled) and lower >= p_required) if p_required is not None else None,
            'first_pass_successes': sum(s.get('first_pass') is True for s in settled),
            'first_pass_unknown': sum(s.get('first_pass') is None for s in settled),
            'business_view': {'kind':'conditional_business_judgments',
                              'task_ids':[s['task_id'] for s in business_samples],
                              'successes':sum(s['business']==1 for s in business_samples),
                              'failures':sum(s['business']==0 for s in business_samples),
                              'excluded_task_ids':[t for t in task_ids if t not in {s['task_id'] for s in business_samples}]},
            'calibration':'PENDING' if not settled else 'CONDITIONAL_ON_SAMPLE_PROTOCOL',
            'prior':{'alpha':alpha,'beta':beta,'quantile':quantile}, 'history':list(versions.values()),
            'authority':'read-only delivery-configuration statistics, never current business acceptance'}


def rank_reports(reports):
    """Stable presentation only; no assignment, exclusion or route mutation."""
    import json
    return sorted(reports, key=lambda r:(r.get('utility') is None, -(r.get('utility') or 0),
                  json.dumps(r['configuration'],sort_keys=True)))

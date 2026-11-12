"""Capture current UI state at the qualified consumer's Review boundary."""
import hashlib
import json
import shutil
import sys
from pathlib import Path
from resume_promotion import P, H, put, sha

root = P / 'promotion/run-05'
expected_hash = sys.argv[1] if len(sys.argv) > 1 else '904f5b7229cc02ee0c35b2b10a11768efbd1848f798f6f5247dee6555d1d07f9'
assert len(expected_hash) == 64 and all(c in '0123456789abcdef' for c in expected_hash)
boundary = sys.argv[2] if len(sys.argv) > 2 else 'Review'
assert boundary in {'Review', 'Approve', 'Publish'}
out = H / ('migration/veriarbor/gui-' + ('visibility' if boundary == 'Review' else boundary.lower()) + '-' + expected_hash[:6])
out.mkdir(exist_ok=False)
original_hash = sha(root / 'candidate/early_main.py')
assert original_hash == expected_hash
shutil.copytree(root / 'candidate', out / 'snapshot')
assert sha(out / 'snapshot/early_main.py') == original_hash
put(out / 'request.json', {'workspace': str(out / 'snapshot'), 'requirements': {'M7': {}}})
checker = root / 'consumer-revisions/gui-locators-v3.py'
source = checker.read_text(encoding='utf8')
prefix = source.split("\nwith tempfile.TemporaryDirectory(prefix='promotion-consumer-'")[0]
assert len(prefix) < len(source)
sys.argv = ['consumer-readonly-diagnostic', '', str(out / 'request.json')]
scope = {'__name__': 'consumer_diagnostic', '__file__': str(checker)}
exec(compile(prefix, str(checker), 'exec'), scope)
scratch = out / 'scratch'; scratch.mkdir()
scope['scratch'] = scratch; scope['data'] = scratch / 'data'
scope['load_modules']()
original_button = scope['workflow_button']
class ObservationComplete(Exception): pass
def observe(page, name):
    if name != boundary: return original_button(page, name)
    page.wait_for_timeout(1500)
    buttons = page.locator('button').evaluate_all("els => els.filter(e => /Review|Approve|Publish/.test(e.textContent)).map(e => ({id:e.id,text:e.textContent,visible:!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length),disabled:e.disabled,section:e.closest('section')?.id,inNav:!!e.closest('nav')}))")
    state = page.evaluate("() => ({storage:{...localStorage},visibleSections:[...document.querySelectorAll('section')].filter(e=>!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length)).map(e=>e.id),alerts:[...document.querySelectorAll('[role=alert]')].map(e=>e.textContent)})")
    storage = state['storage']
    api_observations = {}
    if storage.get('projectId') and storage.get('contentId'):
        for tag, op in [('M5', 'content.get'), ('M6', 'approval.status')]:
            try:
                api_observations[op] = scope['http_action'](page.url.rstrip('/'), tag, op,
                    project_id=storage['projectId'], content_id=storage['contentId'])
            except Exception as error:
                api_observations[op] = {'observation_error':str(error)}
    page.screenshot(path=str(out / ('before-' + boundary.lower() + '.png')), full_page=True)
    put(out / 'observation.json', {'kind':'ReadOnlyGUIBoundaryObservation', 'artifact_sha256':original_hash,
        'checker_sha256':sha(checker), 'buttons':buttons, 'page_state':state,
        'api_observations':api_observations,
        'action_bar_element_count':page.locator('#action-bar').count(),
        'test_boundary':'Immediately before qualified ' + boundary + ' click, after preceding original workflow steps',
        'acceptance_authority':False, 'host_business_patches':0})
    raise ObservationComplete()
scope['workflow_button'] = observe
try:
    scope['browser_probe']('early_main.py', full=False)
except ObservationComplete:
    print(json.dumps(json.loads((out / 'observation.json').read_text()), ensure_ascii=False))
finally:
    put(out / 'source-check.json', {'snapshot_sha256':sha(out / 'snapshot/early_main.py'),
        'live_source_sha256_after':sha(root / 'candidate/early_main.py'), 'original_checker_unchanged':sha(checker)==hashlib.sha256(source.encode()).hexdigest(),
        'scope':'Immutable candidate snapshot; current live edits, if any, require new observation'})

"""Run on the E5; exercises the installed plugin and restores group selection."""
import json
from pathlib import Path
import time
import urllib.error
import urllib.request

BASE = 'http://127.0.0.1:8088/api/plugins/nikki-control'
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
passed = []


class PluginError(Exception):
    def __init__(self, result):
        self.code = result.get('status')
        super().__init__(result.get('error'))


def call(path, data=None):
    body = None if data is None else json.dumps(data).encode()
    request = urllib.request.Request(BASE + path, data=body,
                                     headers={'Content-Type': 'application/json'})
    with OPENER.open(request, timeout=12) as response:
        result = json.load(response)
    if not result.get('ok'):
        raise PluginError(result)
    return result


def job(path, data):
    expected = call(path, data)['job']['id']
    deadline = time.monotonic() + 170
    while time.monotonic() < deadline:
        state = call('/status')
        current = state.get('job')
        assert current and current['id'] == expected, 'Job identity changed'
        if current['phase'] in ('done', 'failed'):
            assert current['phase'] == 'done', current.get('error')
            return state
        time.sleep(1)
    raise AssertionError('Job timeout')


def mark(name):
    passed.append(name)
    print('PASS', name, flush=True)


assert call('/status')['apiReady']
mark('initial-status')
groups = call('/groups')['groups']
group = next(g for g in groups if any(n['type'] == 'URLTest' for n in g['choices']))
original = group['now']
alternative = next(n['name'] for n in group['choices']
                   if n['name'] != original and n['type'] not in ('Direct', 'Reject', 'Selector', 'URLTest'))
try:
    assert call('/select', {'group': group['name'], 'node': alternative})['now'] == alternative
    mark('node-switch-readback')
    try:
        call('/select', {'group': group['name'], 'node': "'; touch /tmp/e5-must-not-exist; '"})
        raise AssertionError('Invalid node accepted')
    except (urllib.error.HTTPError, PluginError) as error:
        assert error.code == 400
    assert not Path('/tmp/e5-must-not-exist').exists()
    mark('invalid-node-rejected')
    state = job('/service', {'action': 'restart'})
    assert state['running'] and state['apiReady']
    actual = next(g for g in call('/groups')['groups'] if g['name'] == group['name'])
    assert actual['now'] == alternative
    mark('node-selection-survives-core-restart')
finally:
    assert call('/select', {'group': group['name'], 'node': original})['now'] == original
    mark('original-node-group-restored')

state = job('/service', {'action': 'stop'})
assert not state['running'] and not state['enabled']
mark('stop-service-keeps-plugin-available')
state = job('/service', {'action': 'start'})
assert state['running'] and state['enabled'] and state['apiReady']
mark('start-service')
result = call('/update', {})
try:
    call('/service', {'action': 'restart'})
    raise AssertionError('Concurrent operation was accepted')
except (urllib.error.HTTPError, PluginError) as error:
    assert error.code == 409
mark('concurrent-request-rejected')
deadline = time.monotonic() + 170
while time.monotonic() < deadline:
    state = call('/status')
    assert state['job']['id'] == result['job']['id']
    if state['job']['phase'] in ('done', 'failed'):
        assert state['job']['phase'] == 'done', state['job'].get('error')
        break
    time.sleep(1)
else:
    raise AssertionError('Subscription job timeout')
assert state['apiReady']
mark('subscription-update-and-reload')
assert next(g for g in call('/groups')['groups'] if g['name'] == group['name'])['now'] == original
mark('selection-preserved-after-subscription-update')
Path('/tmp/nikki-control-e2e-result.json').write_text(json.dumps({'passed': passed}))

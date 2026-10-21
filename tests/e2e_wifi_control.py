"""E5 real-network test; USB SSH must remain connected throughout."""
import json
from pathlib import Path
import time
import urllib.request

BASE = 'http://127.0.0.1:8088/api/plugins/wifi-control'
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
passed = []


def call(path, body=None):
    request = urllib.request.Request(BASE + path,
        data=None if body is None else json.dumps(body).encode(),
        headers={'Content-Type': 'application/json'})
    with OPENER.open(request, timeout=16) as response:
        result = json.load(response)
    assert result.get('ok'), result.get('error')
    assert 'password' not in result
    return result


def job(action, body=None, success=True):
    expected = call('/' + action, body or {})['job']['id']
    deadline = time.monotonic() + 130
    while time.monotonic() < deadline:
        result = call('/status')
        current = result['job']
        assert current['id'] == expected
        assert 'payload' not in current
        if current['phase'] in ('done', 'failed'):
            assert (current['phase'] == 'done') == success, current.get('error')
            if not success:
                assert current.get('rolledBack'), current
            return result
        time.sleep(1)
    raise AssertionError('Network job did not complete')


def wait_connected(ssid):
    for _ in range(45):
        state = call('/status')
        if state['connected'] and state['ssid'] == ssid:
            return state
        time.sleep(1)
    raise AssertionError('Original uplink not restored')


def mark(text):
    passed.append(text)
    print('PASS', text, flush=True)


initial = call('/status')
assert initial['connected']
original = initial['ssid']
assert any(n['ssid'] == original for n in call('/scan')['networks'])
mark('live-scan')
state = job('connect', {'ssid': original, 'useSaved': True})
assert state['connected'] and state['ssid'] == original
mark('saved-profile-reconnect')
state = job('hotspot')
assert state['mode'] == 'hotspot'
mark('hotspot-mode-with-usb-management')
state = job('connect', {'ssid': original, 'useSaved': True})
assert state['connected'] and state['ssid'] == original
mark('wifi-uplink-mode-with-usb-management')
state = job('connect', {'ssid': 'E5-Rollback-Probe-Not-Present', 'band': '5g',
                       'encryption': 'psk2', 'password': 'rollback-test-only'}, success=False)
assert state['job']['rolledBack']
wait_connected(original)
mark('failed-join-automatically-restores-real-uplink')
state = job('restore')
wait_connected(original)
mark('manual-recovery-entry')
Path('/tmp/wifi-control-e2e-result.json').write_text(json.dumps({'passed': passed}))

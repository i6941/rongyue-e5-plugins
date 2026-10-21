import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:  # the device backends use Unix-only fcntl; stub it so the suite runs anywhere
    import fcntl  # noqa: F401
except ImportError:
    import _fcntl_stub
    sys.modules['fcntl'] = _fcntl_stub

SOURCE = Path(__file__).resolve().parents[1] / 'plugins/nikki-control/control.py'
spec = importlib.util.spec_from_file_location('nikki_control', SOURCE)
control = importlib.util.module_from_spec(spec)
spec.loader.exec_module(control)


@unittest.skipIf(os.name == 'nt', 'Uses Linux flock; execute on the E5')
class ControlTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.run_patch = patch.object(control, 'RUN', Path(self.temp.name))
        self.run_patch.start()

    def tearDown(self):
        self.run_patch.stop()
        self.temp.cleanup()

    def test_atomic_job_and_lock_conflict(self):
        control.save_job({'phase': 'done', 'id': 'one'})
        control.save_job({'phase': 'done', 'id': 'two'})
        self.assertEqual(control.read_job()['id'], 'two')
        self.assertEqual(sorted(p.name for p in control.RUN.iterdir()), ['job.json'])
        with control.locked():
            with self.assertRaises(control.ControlError) as error:
                with control.locked():
                    self.fail('Concurrent lock unexpectedly acquired')
            self.assertEqual(error.exception.status, 409)

    def test_group_response_does_not_expose_credentials(self):
        proxies = {'group': {'type': 'Selector', 'all': ['node'], 'now': 'node'},
                   'node': {'type': 'AnyTLS', 'server': 'private.example',
                            'password': 'must-not-leak', 'history': [{'delay': 42}]},
                   'GLOBAL': {'type': 'Selector', 'all': ['node']}}
        with patch.object(control, 'api', return_value={'proxies': proxies}):
            result = control.groups()
        self.assertEqual(len(result['groups']), 1)
        self.assertEqual(result['groups'][0]['choices'][0]['delay'], 42)
        self.assertNotIn('must-not-leak', json.dumps(result))
        self.assertNotIn('private.example', json.dumps(result))

    def test_reject_unlisted_node_before_put(self):
        with patch.object(control, 'api', return_value={'proxies': {
                'group': {'type': 'Selector', 'all': ['allowed'], 'now': 'allowed'}}}) as api:
            with self.assertRaises(control.ControlError):
                control.select({'group': 'group', 'node': "'; touch /tmp/never; '"})
            self.assertEqual(api.call_count, 1)

    def test_selection_readback_and_url_escaping(self):
        name = '节点 / group'
        with patch.object(control, 'api', side_effect=[
            {'proxies': {name: {'type': 'Selector', 'all': ['new'], 'now': 'old'}}},
            {}, {'now': 'new'}]) as api:
            result = control.select({'group': name, 'node': 'new'})
        self.assertEqual(result['now'], 'new')
        self.assertNotIn(' / ', api.call_args_list[1].args[0])
        self.assertIn('%2F', api.call_args_list[1].args[0])

    def test_idempotent_selection(self):
        with patch.object(control, 'api', side_effect=[
            {'proxies': {'g': {'type': 'Selector', 'all': ['same'], 'now': 'same'}}},
            {'now': 'same'}]) as api:
            control.select({'group': 'g', 'node': 'same'})
        self.assertEqual(api.call_count, 2)  # no PUT

    def test_selection_readback_mismatch_is_error(self):
        with patch.object(control, 'api', side_effect=[
            {'proxies': {'g': {'type': 'Selector', 'all': ['new'], 'now': 'old'}}},
            {}, {'now': 'old'}]):
            with self.assertRaises(control.ControlError) as error:
                control.select({'group': 'g', 'node': 'new'})
        self.assertEqual(error.exception.status, 502)

    def test_reject_arbitrary_service_and_bad_request(self):
        for action, body in [('service', {'action': 'stop; reboot'}), ('select', []), ('unknown', {})]:
            with self.assertRaises(control.ControlError):
                control.dispatch(action, body)

    def test_stale_job_is_reported_interrupted(self):
        control.save_job({'phase': 'running', 'id': 'stale', 'started': 0, 'pid': 1})
        with patch.object(control, 'running', return_value=False), patch.object(control, 'uci', return_value='0'), \
                patch.object(control, 'network_status', return_value={'connected': False}):
            result = control.status()
        self.assertEqual(result['job']['phase'], 'failed')

    def test_dashboard_resolves_actual_node_and_delay(self):
        result = control.proxy_summary({
            '🚀 节点选择': {'type': 'Selector', 'now': 'auto'},
            'auto': {'type': 'URLTest', 'now': 'actual'},
            'actual': {'type': 'AnyTLS', 'history': [{'delay': 123}], 'password': 'not-returned'}})
        self.assertEqual(result['node'], 'actual')
        self.assertEqual(result['delay'], 123)
        self.assertNotIn('not-returned', json.dumps(result))

    def test_dashboard_group_cycle_is_bounded(self):
        result = control.proxy_summary({'a': {'type': 'Selector', 'now': 'b'},
                                        'b': {'type': 'Selector', 'now': 'a'}})
        self.assertEqual(len(result['chain']), 2)

    def test_dashboard_offline_is_not_reported_connected(self):
        with patch.object(control, 'command', return_value=(0, b'[]')):
            self.assertFalse(control.network_status()['connected'])

    def test_dashboard_wifi_ssid_and_signal(self):
        with patch.object(control, 'command', side_effect=[
            (0, b'[{"dev":"wlan0","prefsrc":"192.0.2.10","gateway":"192.0.2.1"}]'),
            (0, b'Connected\n\tSSID: test wifi\n\tsignal: -66 dBm\n')]), \
                patch.object(control, 'interface_rates', return_value={'rx': 100, 'tx': 200}):
            result = control.network_status()
        self.assertEqual(result['kind'], 'Wi-Fi')
        self.assertEqual(result['ssid'], 'test wifi')
        self.assertEqual(result['signal'], -66)


if __name__ == '__main__':
    unittest.main()

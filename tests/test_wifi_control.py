import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:  # the device backends use Unix-only fcntl; stub it so the suite runs anywhere
    import fcntl  # noqa: F401
except ImportError:
    import _fcntl_stub
    sys.modules['fcntl'] = _fcntl_stub

SOURCE = Path(__file__).resolve().parents[1] / 'plugins/wifi-control/control.py'
spec = importlib.util.spec_from_file_location('wifi_control', SOURCE)
wifi = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wifi)


class WifiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.patches = [patch.object(wifi, name, self.root / name.lower()) for name in ('RUN', 'SAVED', 'CONFIG')]
        for p in self.patches:
            p.start()
        wifi.CONFIG.mkdir()
        wifi.prepare()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.temp.cleanup()

    def test_public_job_never_contains_password(self):
        result = wifi.public_job({'id': 'job', 'action': 'connect', 'phase': 'done',
                                  'payload': {'ssid': 'test', 'password': 'secret-password'}})
        self.assertNotIn('payload', result)
        self.assertNotIn('secret-password', json.dumps(result))

    def test_reject_invalid_ssid_and_key(self):
        for body in ({'ssid': 'x\ncommit network', 'password': 'long-enough'},
                     {'ssid': '界' * 11, 'password': 'long-enough'},
                     {'ssid': 'test', 'password': 'short'},
                     {'ssid': 'test', 'password': 'valid-length\n'}):
            with self.assertRaises(wifi.WifiError):
                wifi.validate(body)

    def test_saved_password_is_used_only_in_private_payload(self):
        wifi.save_json(wifi.SAVED / 'profiles.json', {'known': {
            'password': 'saved-secret', 'encryption': 'psk2', 'band': '5g'}})
        result = wifi.validate({'ssid': 'known', 'useSaved': True})
        self.assertEqual(result['password'], 'saved-secret')
        with patch.object(wifi, 'uci', return_value=''):
            with self.assertRaises(wifi.WifiError):
                wifi.validate({'ssid': 'missing', 'useSaved': True})

    def test_scanned_metadata_overrides_saved_profile_without_replacing_password(self):
        wifi.save_json(wifi.SAVED / 'profiles.json', {'known': {
            'password': 'saved-secret', 'encryption': 'psk2', 'band': '5g'}})
        result = wifi.validate({'ssid': 'known', 'useSaved': True,
                                'band': '2g', 'encryption': 'sae', 'password': ''})
        self.assertEqual(result, {'ssid': 'known', 'password': 'saved-secret',
                                  'band': '2g', 'encryption': 'sae'})
        with self.assertRaises(wifi.WifiError):
            wifi.validate({'ssid': 'known', 'useSaved': True, 'band': 'invalid'})

    def test_backup_restore_round_trip_and_mode(self):
        for name in wifi.CONFIGS:
            path = wifi.CONFIG / name
            path.write_bytes(('original-' + name).encode())
            path.chmod(0o600)
        with patch.object(wifi, 'checked', return_value=b''), patch.object(wifi, 'command', return_value=(0, b'')), \
                patch.object(wifi, 'reload_network'):
            wifi.backup()
            for name in wifi.CONFIGS:
                (wifi.CONFIG / name).write_text('changed')
            wifi.restore()
        for name in wifi.CONFIGS:
            self.assertEqual((wifi.CONFIG / name).read_text(), 'original-' + name)
            if os.name == 'posix':  # file modes are meaningless on Windows
                self.assertEqual((wifi.CONFIG / name).stat().st_mode & 0o777, 0o600)

    def test_pending_network_changes_prevent_backup(self):
        with patch.object(wifi, 'checked', return_value=b'wireless.radio0.band=2g'):
            with self.assertRaises(wifi.WifiError) as error:
                wifi.backup()
        self.assertEqual(error.exception.status, 409)

    def test_failed_join_restores_and_removes_password(self):
        wifi.save_json(wifi.RUN / 'job.json', {'id': 'test', 'action': 'connect', 'phase': 'queued',
            'started': time.time(), 'pid': 0, 'payload': {'ssid': 'missing', 'password': 'private', 'band': '5g', 'encryption': 'psk2'}})
        with patch.object(wifi, 'backup'), patch.object(wifi, 'batch'), \
                patch.object(wifi, 'wait_for', side_effect=wifi.WifiError('timeout')), patch.object(wifi, 'restore') as restore:
            wifi.worker('test')
        result = wifi.read_json(wifi.RUN / 'job.json')
        self.assertEqual(result['phase'], 'failed')
        self.assertTrue(result['rolledBack'])
        self.assertNotIn('payload', result)
        restore.assert_called_once()

    def test_password_not_in_uci_process_arguments(self):
        password = "private'$(never-run)"
        with patch.object(wifi, 'uci', side_effect=['wan', 'wan wwan']), \
                patch.object(wifi, 'checked', return_value=b'') as checked, \
                patch.object(wifi, 'reload_network'), patch.object(wifi.os, 'chmod'):
            wifi.batch({'wireless.uplink.key': password})
        self.assertEqual(checked.call_args.args[0], ['/sbin/uci', 'batch'])
        self.assertNotIn(password, str(checked.call_args.args[0]))
        self.assertIn(b'private', checked.call_args.args[1])


if __name__ == '__main__':
    unittest.main()

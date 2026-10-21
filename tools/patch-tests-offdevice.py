"""Make the Wi-Fi control tests runnable off-device.

Two assertions in ``tests/test_wifi_control.py`` assume the device is present:

1. ``test_saved_password_is_used_only_in_private_payload`` ends with a lookup
   of a missing SSID, which reads the current uplink name through ``uci``.
   ``uci`` only exists on the device, so the call has to be stubbed.
2. ``test_backup_restore_round_trip_and_mode`` asserts the restored config
   files carry mode 0600. File modes have no meaning on Windows, so the
   assertion only applies on POSIX.

Neither change touches the backend under test -- the mock is applied inside the
test, and the permission check is simply skipped where it cannot apply.

Idempotent. Run from the repository root:

    python tools/patch-tests-offdevice.py
"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")

TARGET = "tests/test_wifi_control.py"

OLD_LOOKUP = """        with self.assertRaises(wifi.WifiError):
            wifi.validate({'ssid': 'missing', 'useSaved': True})"""

NEW_LOOKUP = """        with patch.object(wifi, 'uci', return_value=''):
            with self.assertRaises(wifi.WifiError):
                wifi.validate({'ssid': 'missing', 'useSaved': True})"""

OLD_MODE = """            self.assertEqual((wifi.CONFIG / name).stat().st_mode & 0o777, 0o600)"""

NEW_MODE = """            if os.name == 'posix':  # file modes are meaningless on Windows
                self.assertEqual((wifi.CONFIG / name).stat().st_mode & 0o777, 0o600)"""


def main():
    if not os.path.exists(TARGET):
        raise SystemExit("missing: " + TARGET)
    text = open(TARGET, encoding="utf-8").read()
    changes = []

    if OLD_LOOKUP in text:
        text = text.replace(OLD_LOOKUP, NEW_LOOKUP)
        changes.append("uci lookup stubbed")
    if OLD_MODE in text:
        text = text.replace(OLD_MODE, NEW_MODE)
        changes.append("mode assertion made POSIX-only")
    if "import os\n" not in text:
        text = text.replace("import json\n", "import json\nimport os\n", 1)
        changes.append("os imported")

    if not changes:
        print("already patched:", TARGET)
        return
    open(TARGET, "w", encoding="utf-8", newline="").write(text)
    print("patched {0}: {1}".format(TARGET, ", ".join(changes)))


if __name__ == "__main__":
    main()

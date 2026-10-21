"""Strip the hardcoded device link-local address from the SSH tools.

The address ``fe80::50:ff:fe00:e501%50`` is derived from the device's MAC, so
leaving it in a public repository discloses the hardware identifier. The tools
read it from the ``E5_HOST`` environment variable instead, defaulting to the
USB network interface address.

Idempotent: running it twice changes nothing the second time.

    python tools/patch-tools-device-host.py
"""
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")

TARGETS = (
    "tools/device-proxy.py",
    "tools/preview-infoscreen.py",
    "tools/restore-e5-apps.py",
)

ADDRESS = "fe80::50:ff:fe00:e501%50"

REPLACEMENTS = (
    ('HOST = "fe80::50:ff:fe00:e501%50"',
     "HOST = os.environ.get('E5_HOST', '192.168.9.1')"),
    ("HOST = 'fe80::50:ff:fe00:e501%50'",
     "HOST = os.environ.get('E5_HOST', '192.168.9.1')"),
    ("client.connect('fe80::50:ff:fe00:e501%50', username='root',",
     "client.connect(HOST, username='root',"),
)

# Files that connect to HOST without defining it need the definition inserted.
NEEDS_HOST_DEFINITION = ("tools/preview-infoscreen.py",)


def main():
    for target in TARGETS:
        if not os.path.exists(target):
            print("{0:<12} {1} (missing)".format("skipped", target))
            continue

        text = open(target, encoding="utf-8").read()
        original = text
        changes = []

        for old, new in REPLACEMENTS:
            if old in text:
                text = text.replace(old, new)
                changes.append("host -> E5_HOST")

        # Any remaining mention is prose in a docstring; point it at the env var.
        if ADDRESS in text:
            text = text.replace(ADDRESS, "E5_HOST")
            changes.append("docstring address -> E5_HOST")

        if text != original and "os.environ" in text and not re.search(r"^import os$", text, re.M):
            if "\nimport json\n" in text:
                text = text.replace("\nimport json\n", "\nimport json\nimport os\n", 1)
            else:
                text = text.replace("\nimport ", "\nimport os\nimport ", 1)
            changes.append("os imported")

        # A file that connects to HOST but never defines it needs the
        # definition, otherwise the script raises NameError at connect time.
        if target in NEEDS_HOST_DEFINITION and not re.search(r"^HOST = ", text, re.M):
            anchor = "ROOT = Path(__file__).resolve().parents[1]\n"
            if anchor in text:
                text = text.replace(
                    anchor,
                    anchor + "HOST = os.environ.get('E5_HOST', '192.168.9.1')\n",
                    1,
                )
                changes.append("HOST definition added")
            if "import os\n" not in text:
                text = text.replace("\nimport json\n", "\nimport json\nimport os\n", 1)
                changes.append("os imported")

        if text == original:
            print("{0:<12} {1}".format("already ok", target))
            continue

        open(target, "w", encoding="utf-8", newline="").write(text)
        print("{0:<12} {1}: {2}".format("patched", target, ", ".join(changes)))


if __name__ == "__main__":
    main()

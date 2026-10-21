"""Inject the cross-platform fcntl stub into the test modules.

The device backends import ``fcntl``, which only exists on Unix, so the test
modules cannot even be imported on Windows. Both the working directory and the
published repository keep their own copy of the tests, and a plain file copy
between the two can silently drop the injection -- so it is applied by script
rather than by hand.

Idempotent: running it twice changes nothing the second time.

    python tools/patch-tests-fcntl.py
"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")

TESTS = ("tests/test_wifi_control.py", "tests/test_nikki_control.py")

# Inserted right after the import block, before the backend module is loaded.
MARKER = "# --- fcntl stub (added by tools/patch-tests-fcntl.py) ---"
INJECTION = """
{marker}
import sys as _sys
_sys.path.insert(0, str(Path(__file__).resolve().parent))
try:  # the device backends use Unix-only fcntl; stub it so the suite runs anywhere
    import fcntl  # noqa: F401
except ImportError:
    import _fcntl_stub
    _sys.modules['fcntl'] = _fcntl_stub
""".format(marker=MARKER)


def patch(path):
    if not os.path.exists(path):
        return "missing"
    text = open(path, encoding="utf-8").read()
    if MARKER in text:
        return "already patched"

    lines = text.split("\n")
    # find the end of the leading import block
    insert_at = 0
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(("import ", "from ")) or (stripped and stripped.endswith("(")):
            insert_at = index + 1
        elif stripped and not stripped.startswith("#"):
            break

    block = INJECTION.strip("\n").split("\n")
    lines[insert_at:insert_at] = block
    open(path, "w", encoding="utf-8", newline="").write("\n".join(lines))
    return "patched"


def main():
    for target in TESTS:
        print("{0:<12} {1}".format(patch(target), target))


if __name__ == "__main__":
    main()

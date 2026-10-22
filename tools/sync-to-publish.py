"""Sync code changes from the working directory into the public GitHub repository.

The device work happens in ``D:\\workspace\\Rongyue-E5``; the public repository
lives in ``D:\\workspace\\rongyue-e5-plugins``. This script copies the code
across while protecting the two things that were deliberately changed in the
public copy and must not be reverted by a blind copy:

1. ``plugins/e5-emulator/index.html`` -- the published copy lists the freely
   redistributable homebrew titles. The working copy may still carry the
   commercial ROM list, so the game table is merged rather than overwritten.
2. The SSH tools -- the published copy reads the device address from the
   ``E5_HOST`` environment variable instead of a hardcoded link-local address
   that discloses the device MAC.

Run from either directory:

    python tools/sync-to-publish.py            # preview what would change
    python tools/sync-to-publish.py --apply    # actually copy
"""
import argparse
import filecmp
import os
import re
import shutil
import sys

sys.stdout.reconfigure(encoding="utf-8")

SOURCE = r"D:\workspace\Rongyue-E5"
PUBLISH = r"D:\workspace\rongyue-e5-plugins"

# Directories copied wholesale from the working directory.
SYNC_DIRS = ("plugins", "tools", "tests", "overlays")

# Files at the root of the working directory that belong in the published
# repository too (the one-line installer users pipe into the device).
ROOT_FILES = ("install.sh",)

# Files that exist only in the working directory and are never published.
SKIP_NAMES = {"__pycache__", ".pytest_cache", ".mypy_cache"}
SKIP_SUFFIXES = (".pyc", ".pyo", ".log", ".bak")

# Files that exist only in the published repository and must never be removed
# by a sync -- they are part of the public repo's own tooling and documentation.
PUBLISH_ONLY = {
    "tools/build-rom-docs.py",
    "tools/build-rom-manifest.py",
    "tools/check-doc-links.py",
    "tools/sync-to-publish.py",
    "tests/_fcntl_stub.py",
    "plugins/e5-emulator/games.homebrew.js",
}

# The published index.html keeps its own game table; see merge_game_table().
GAME_TABLE_RE = re.compile(r"var GAMES=\[.*?\n\];", re.S)


def is_skipped(name):
    if name in SKIP_NAMES:
        return True
    return name.endswith(SKIP_SUFFIXES)


def read_text(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def write_text(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


def merge_game_table(source_text, publish_text):
    """Take the working copy, but restore the published homebrew game table.

    The published copy lists the freely redistributable homebrew titles; the
    working copy may still carry the commercial ROM list. Publishing the
    working copy verbatim would put copyrighted ROM names into a public
    repository, so the table is always replaced with the protected copy in
    ``plugins/e5-emulator/games.homebrew.js`` while every other edit -- CSS
    fixes, key logging, fetch error capture -- is carried over.

    Returns ``(text, table_replaced)``.
    """
    source_match = GAME_TABLE_RE.search(source_text)
    protected_path = os.path.join(PUBLISH, "plugins", "e5-emulator", "games.homebrew.js")
    if not source_match or not os.path.exists(protected_path):
        return source_text, False

    protected = read_text(protected_path).strip()
    if source_match.group(0).strip() == protected:
        return source_text, False

    merged = (source_text[:source_match.start()]
              + protected
              + source_text[source_match.end():])
    return merged, True


def sync_file(src, dst, report):
    rel = os.path.relpath(src, SOURCE)
    if not os.path.exists(dst):
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        report.append(("NEW", rel))
        return True

    if filecmp.cmp(src, dst, shallow=False):
        return False

    # Special case: the emulator front end. Take the working copy, then put
    # the protected homebrew game table back in place.
    if rel.replace("\\", "/") == "plugins/e5-emulator/index.html":
        merged, table_replaced = merge_game_table(read_text(src), read_text(dst))
        if merged == read_text(dst):
            return False
        write_text(dst, merged)
        note = "  (homebrew game table restored)" if table_replaced else ""
        report.append(("MERGED", rel + note))
        return True

    shutil.copy2(src, dst)
    report.append(("COPY", rel))
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write the changes (default: dry run)")
    parser.add_argument("--source", default=SOURCE)
    parser.add_argument("--publish", default=PUBLISH)
    args = parser.parse_args()

    source, publish = args.source, args.publish
    if not os.path.isdir(source) or not os.path.isdir(publish):
        raise SystemExit("source or publish directory not found")

    report = []
    for rel in ROOT_FILES:
        src = os.path.join(source, rel)
        if not os.path.isfile(src):
            continue
        dst = os.path.join(publish, rel)
        if sync_file(src, dst, report):
            pass

    for sub in SYNC_DIRS:
        src_dir = os.path.join(source, sub)
        if not os.path.isdir(src_dir):
            continue
        for root, dirs, files in os.walk(src_dir):
            dirs[:] = [d for d in dirs if d not in SKIP_NAMES]
            for name in files:
                if is_skipped(name):
                    continue
                src = os.path.join(root, name)
                rel = os.path.relpath(src, source)
                dst = os.path.join(publish, rel)
                if sync_file(src, dst, report):
                    pass

    # Files removed from the working directory should disappear from the publish copy.
    for sub in SYNC_DIRS:
        src_dir = os.path.join(source, sub)
        dst_dir = os.path.join(publish, sub)
        if not (os.path.isdir(src_dir) and os.path.isdir(dst_dir)):
            continue
        for root, dirs, files in os.walk(dst_dir):
            dirs[:] = [d for d in dirs if d not in SKIP_NAMES]
            for name in files:
                if is_skipped(name):
                    continue
                dst = os.path.join(root, name)
                rel = os.path.relpath(dst, publish)
                if rel.replace("\\", "/") in PUBLISH_ONLY:
                    continue
                src = os.path.join(source, rel)
                if not os.path.exists(src):
                    if not args.apply:
                        report.append(("REMOVE", rel))
                    else:
                        os.remove(dst)
                        report.append(("REMOVED", rel))

    if not report:
        print("in sync - nothing to do")
        return 0

    print("action   path")
    for action, rel in report:
        print("{0:<8} {1}".format(action, rel))
    print()
    if not args.apply:
        print("dry run - re-run with --apply to write these changes")
    else:
        print("applied {0} change(s)".format(len(report)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

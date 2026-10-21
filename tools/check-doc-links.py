"""Validate that paths mentioned in the docs actually exist.

Run from the repository root:  python tools/check-doc-links.py
"""
import glob
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")

# ``path``-style mentions in prose and tables
CODE_MENTION = re.compile(r"`([^`\n]+)`")
# markdown links [text](target)
MD_LINK = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")


# Directories and files that actually live in this repository. A backtick
# mention is only treated as a repository path when it starts with one of
# these -- otherwise it is prose ("application/wasm", "index.html", a URL
# fragment) and checking it would only produce noise.
REPO_ROOTS = (
    "plugins/", "roms/", "docs/", "tools/", "tests/", "overlays/",
    "README.md", "LICENSE", ".gitignore",
)

# Files that belong to upstream projects and are named in the docs but do not
# live in this repository (they travel inside the bundled core archives).
EXTERNAL_FILES = ("LICENSE.txt",)


def looks_like_path(text):
    candidate = text.strip()
    if " " in candidate:
        return False
    if candidate.startswith(("http://", "https://", "#", "mailto:", "/", "...")):
        return False
    if any(ch in candidate for ch in "*?<>|"):
        return False
    if candidate in EXTERNAL_FILES:
        return False
    if not candidate.startswith(REPO_ROOTS):
        return False
    return True


def main():
    missing = []
    checked = 0
    docs = sorted(glob.glob("*.md") + glob.glob("docs/*.md")
                  + glob.glob("plugins/*/README.md") + glob.glob("overlays/*/README.md"))
    for doc in docs:
        base = os.path.dirname(doc)
        text = open(doc, encoding="utf-8").read()

        for _, target in MD_LINK.findall(text):
            if target.startswith(("http://", "https://", "#", "mailto:")):
                continue
            rel = target.split("#")[0]
            if not rel:
                continue
            checked += 1
            # markdown links are relative to the document
            if not os.path.exists(os.path.normpath(os.path.join(base, rel))):
                missing.append((doc, "link", target))

        for mention in CODE_MENTION.findall(text):
            if not looks_like_path(mention):
                continue
            candidate = mention.split()[0].rstrip(".,;:")
            checked += 1
            # inline path mentions are written relative to the repository root
            if os.path.exists(candidate):
                continue
            if os.path.exists(os.path.normpath(os.path.join(base, candidate))):
                continue
            missing.append((doc, "mention", candidate))

    print("documents scanned:", len(docs))
    print("path references checked:", checked)
    print("missing:", len(missing))
    for doc, kind, target in missing:
        print("  {0:<28} {1:<8} {2}".format(doc, kind, target))
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())

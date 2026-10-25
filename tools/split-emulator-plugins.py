"""从 plugins/e5-emulator 派生两个独立插件：e5-dos 与 e5-pal。

拆分理由：DOS（键盘型、DOSBox-Pure 核心）和仙剑重制版（键盘型、SDLPAL 核心）
跟 FC/MD/GBA/街机（手柄型、EmulatorJS 可兜底）的运行方式完全不同。挤在
同一个插件里，任何一处路由/像素格式/启动钩子出错都会互相牵连——之前的
「无法加载运行库」就是这么来的。

派生方式：页面里已经有 SCOPES 这个机种范围开关，这里只替换那一行，
其余代码完全复用，避免三份副本各自漂移。

用法：
    python tools/split-emulator-plugins.py            # 预览
    python tools/split-emulator-plugins.py --apply    # 真正写盘
"""
import argparse
import json
import os
import re
import shutil
import sys

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "plugins", "e5-emulator")
PLUGINS = os.path.join(ROOT, "plugins")

SCOPES_RE = re.compile(r"^var SCOPES=\[[^\]]*\];", re.M)

# 每个派生产物：目录名 -> 配置
TARGETS = {
    "e5-dos": {
        "scope": ["DOS"],
        "manifest": {
            "id": "e5-dos",
            "api_version": 2,
            "version": "1.0.0",
            "name": {"zh": "DOS 游戏", "en": "DOS games"},
            "description": {
                "zh": "DOSBox-Pure 原生核心（仙剑 DOS / 金庸群侠传 / 大航海时代2 / 大富翁3）",
                "en": "DOSBox-Pure native core (DOS classics)",
            },
            "entry": "index.html",
            "order": 7,
        },
        "extra_files": [],
    },
    "e5-pal": {
        "scope": ["PAL"],
        "manifest": {
            "id": "e5-pal",
            "api_version": 2,
            "version": "1.0.0",
            "name": {"zh": "仙剑奇侠传", "en": "Legend of Sword and Fairy"},
            "description": {
                "zh": "SDLPAL 原生重制版引擎",
                "en": "SDLPAL native engine remake",
            },
            "entry": "index.html",
            "order": 8,
        },
        "extra_files": [],
    },
}

# 派生插件不需要网页运行库那套大文件（DOS/仙剑没有 wasm 核心可退回）
SKIP_FROM_SRC = {"ejs", "emulator.min.js", "emulator.min.css", "games.homebrew.js"}


def build_index_html(scope):
    with open(os.path.join(SRC, "index.html"), encoding="utf-8") as fh:
        html = fh.read()
    line = "var SCOPES=%s;" % json.dumps(scope, ensure_ascii=False)
    new, n = SCOPES_RE.subn(line, html, count=1)
    if n != 1:
        raise SystemExit("在 index.html 里没找到 'var SCOPES=[...];'，无法限定机种范围")
    return new


def plan():
    """返回 [(目标目录, 相对路径, 内容或 None=复制源文件)]。"""
    items = []
    for dirname, cfg in TARGETS.items():
        dst = os.path.join(PLUGINS, dirname)
        items.append((dst, "index.html", build_index_html(cfg["scope"])))
        for name, text in (("manifest.json",
                            json.dumps(cfg["manifest"], ensure_ascii=False, indent=2) + "\n"),
                           ("backend.uc", None)):
            items.append((dst, name, text))
        items.append((dst, "README.md", build_readme(dirname, cfg)))
    return items


def build_readme(dirname, cfg):
    name = cfg["manifest"]["name"]["zh"]
    scope = "/".join(cfg["scope"])
    core = {"DOS": "e5emu-dos（DOSBox-Pure）", "PAL": "e5emu-pal（SDLPAL）"}[scope]
    return (
        "# %s\n\n"
        "本插件由 `tools/split-emulator-plugins.py` 从 `plugins/e5-emulator` 派生，"
        "不要手工修改——改源插件后重新生成。\n\n"
        "- 机种范围：`%s`\n"
        "- 原生核心：`/usr/bin/%s`\n"
        "- 只走原生：这个机种没有网页运行库版本可退回，缺少核心时会直接提示路径\n\n"
        "安装：\n\n"
        "```sh\n"
        "python tools/split-emulator-plugins.py --apply\n"
        "python tools/install-plugin.py %s\n"
        "```\n" % (name, scope, core, dirname)
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真正写盘")
    args = ap.parse_args()

    items = plan()
    if not args.apply:
        print("action   path")
        for dst, name, text in items:
            p = os.path.join(dst, name)
            act = "WRITE" if text is not None else "COPY"
            print("%-8s %s" % (act, os.path.relpath(p, ROOT)))
        print("\n预览模式，加 --apply 才会写入")
        return

    for dirname in TARGETS:
        dst = os.path.join(PLUGINS, dirname)
        if os.path.isdir(dst):
            shutil.rmtree(dst)
        os.makedirs(dst, exist_ok=True)

    for dst, name, text in items:
        p = os.path.join(dst, name)
        if text is None:
            shutil.copyfile(os.path.join(SRC, name), p)
            print("COPY  %s" % os.path.relpath(p, ROOT))
        else:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(text)
            print("WRITE %s" % os.path.relpath(p, ROOT))
    print("\n完成。记得到设备上重启信息屏让宿主重新扫描插件。")


if __name__ == "__main__":
    main()

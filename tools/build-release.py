#!/usr/bin/env python3
"""打包对外发布用的东西。

两套分发路径：

1. 商店路径（用户点一下就能装）
   - e5-emulator-<version>.tar.gz   插件包，符合上游商店的规则
     （单个应用 2MB 上限、文件类型白名单、文本文件要 LF、无尾随空格）
   - index.json                     商店索引 = 官方索引 + 我们这条
   - packages/                      放商店包里，供 GitHub Pages 发布

2. 命令行路径（SSH 一条命令）
   - e5emu / e5emu-genesis / e5emu-gba   三个 aarch64 静态核心
   - sha256sums.txt                      校验和

用法：
    python tools/build-release.py [--out dist] [--publish ../rongyue-e5-plugins]
                                  [--store-index <官方 index.json 路径或 URL>]

官方商店索引默认从设备用的那个地址取：
    https://enceka.github.io/infoscreen-plugins/index.json
"""
import argparse
import hashlib
import json
import os
import shutil
import tarfile
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NATIVE = os.path.join(ROOT, "native")
CORES = ("e5emu", "e5emu-genesis", "e5emu-gba")
OFFICIAL_INDEX = "https://enceka.github.io/infoscreen-plugins/index.json"

# 上游商店对单个应用的限制（tools/check.py）
MAX_APP_BYTES = 2 * 1024 * 1024
# 商店只认这些后缀
ALLOWED_EXT = {".html", ".js", ".css", ".json", ".uc", ".svg", ".txt", ".md",
               ".png", ".jpg", ".jpeg", ".webp", ".gif", ".woff2", ".ico"}
# 插件目录里这些是旧的 EmulatorJS 运行库，商店包不带（原生核心用不到，也超 2MB）
SKIP_NAMES = {"ejs", "emulator.min.css", "emulator.min.js"}


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def normalize_text(path):
    """商店要求：UTF-8、LF 行尾、无尾随空格、文件以换行结尾。"""
    with open(path, "rb") as f:
        raw = f.read()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return False
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [ln.rstrip() for ln in text.split("\n")]
    text = "\n".join(lines).rstrip("\n") + "\n"
    with open(path, "wb") as f:
        f.write(text.encode("utf-8"))
    return True


def build_store_package(publish, out_dir):
    """做一个符合商店规则的插件包，返回 (包路径, 清单, 包内总字节)。"""
    src = os.path.join(publish, "plugins", "e5-emulator")
    stage = os.path.join(out_dir, "_stage", "e5-emulator")
    if os.path.isdir(os.path.join(out_dir, "_stage")):
        shutil.rmtree(os.path.join(out_dir, "_stage"))
    os.makedirs(stage)

    total = 0
    for name in sorted(os.listdir(src)):
        if name in SKIP_NAMES:
            continue
        s = os.path.join(src, name)
        d = os.path.join(stage, name)
        if os.path.isdir(s):
            shutil.copytree(s, d)
            for root, _dirs, files in os.walk(d):
                for n in files:
                    p = os.path.join(root, n)
                    ext = os.path.splitext(n)[1].lower()
                    if ext not in ALLOWED_EXT:
                        raise SystemExit("商店不允许的文件类型：%s" % p)
                    normalize_text(p)
                    total += os.path.getsize(p)
        else:
            ext = os.path.splitext(name)[1].lower()
            if ext not in ALLOWED_EXT:
                raise SystemExit("商店不允许的文件类型：%s" % s)
            shutil.copy2(s, d)
            normalize_text(d)
            total += os.path.getsize(d)

    if total > MAX_APP_BYTES:
        raise SystemExit("插件包 %d 字节，超过商店的 %d 字节上限" % (total, MAX_APP_BYTES))

    with open(os.path.join(stage, "manifest.json"), encoding="utf-8") as f:
        manifest = json.load(f)

    pkg = os.path.join(out_dir, "packages", "%s-%s.tar.gz" % (manifest["id"], manifest["version"]))
    os.makedirs(os.path.dirname(pkg), exist_ok=True)
    with tarfile.open(pkg, "w:gz") as tf:
        for name in sorted(os.listdir(stage)):
            tf.add(os.path.join(stage, name), arcname=name)
    return pkg, manifest, total


def build_index(out_dir, pkg, manifest, base_url, official_path=None):
    """商店索引 = 官方索引 + 我们这一条。"""
    plugins = []
    if official_path and os.path.isfile(official_path):
        with open(official_path, encoding="utf-8") as f:
            plugins = json.load(f).get("plugins", [])
    else:
        try:
            with urllib.request.urlopen(OFFICIAL_INDEX, timeout=20) as r:
                plugins = json.load(r).get("plugins", [])
        except Exception as exc:  # noqa: BLE001
            print("警告：取不到官方索引（%s），只放我们这一条" % exc)

    entry = {
        "id": manifest["id"],
        "version": manifest["version"],
        "api_version": manifest["api_version"],
        "name": manifest["name"],
        "description": manifest["description"],
        "order": manifest.get("order", 50),
        "input_method": False,
        "backend": True,
        "size": os.path.getsize(pkg),
        "sha256": sha256(pkg),
        "url": "%s/packages/%s" % (base_url.rstrip("/"), os.path.basename(pkg)),
    }
    plugins = [p for p in plugins if p.get("id") != entry["id"]]
    plugins.append(entry)
    plugins.sort(key=lambda p: p.get("order", 50))

    index = {
        "api_version": 2,
        "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "plugins": plugins,
    }
    path = os.path.join(out_dir, "index.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=1)
    # 另存一份带版本号的：raw.githubusercontent.com 的 CDN 会按路径缓存，
    # 同一路径在推送后几分钟内还可能发旧内容（实测边缘节点发的是旧副本）。
    # 带版本号的路径是新的缓存键，发出去的一定是这一版。
    ver_path = os.path.join(out_dir, "store", "index-v%s.json" % manifest["version"])
    os.makedirs(os.path.dirname(ver_path), exist_ok=True)
    with open(ver_path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=1)
    return path, ver_path, entry


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=os.path.join(ROOT, "dist"))
    ap.add_argument("--publish", default=os.path.join(ROOT, "..", "rongyue-e5-plugins"))
    ap.add_argument("--base-url", default="https://raw.githubusercontent.com/i6941/rongyue-e5-plugins/main/docs",
                    help="商店包对外可访问的基地址")
    ap.add_argument("--official-index", default="", help="官方 index.json 的本地副本（不给就联网取）")
    args = ap.parse_args()

    publish = os.path.abspath(args.publish)
    out = os.path.abspath(args.out)
    if not os.path.isdir(publish):
        print("找不到公开仓库目录：%s" % publish)
        return 1
    os.makedirs(out, exist_ok=True)

    made = []

    # 1) 商店包与索引
    pkg, manifest, total = build_store_package(publish, out)
    made.append(pkg)
    print("商店包：%s（%d 字节，限制 %d）" % (os.path.basename(pkg), total, MAX_APP_BYTES))
    index_path, ver_path, entry = build_index(out, pkg, manifest, args.base_url, args.official_index or None)
    made.append(index_path)
    made.append(ver_path)
    print("商店条目：%s v%s -> %s" % (entry["id"], entry["version"], entry["url"]))
    print("商店索引（带版本）：%s" % os.path.relpath(ver_path, out))

    # 2) 命令行路径用的三个核心
    missing = []
    for core in CORES:
        src = os.path.join(NATIVE, core)
        if not os.path.isfile(src):
            missing.append(core)
            continue
        dst = os.path.join(out, core)
        shutil.copy2(src, dst)
        os.chmod(dst, 0o755)
        made.append(dst)
    if missing:
        print("缺少二进制：%s（先跑 native/build-*.ps1）" % "、".join(missing))
        return 1

    # 3) 校验和
    sums = os.path.join(out, "sha256sums.txt")
    with open(sums, "w", encoding="utf-8") as f:
        for path in made:
            f.write("%s  %s\n" % (sha256(path), os.path.basename(path)))
    made.append(sums)

    shutil.rmtree(os.path.join(out, "_stage"), ignore_errors=True)

    print("产物在 %s" % out)
    for path in made:
        print("  %-28s %8.1f KB" % (os.path.basename(path), os.path.getsize(path) / 1024))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

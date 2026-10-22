#!/usr/bin/env python3
"""打包对外发布用的安装资源。

install.sh 会从 GitHub Release 下载这些文件，所以打包时要保证：
  - 插件取自公开仓库那份（游戏表是自制游戏版，不含商业 ROM）
  - 三个核心二进制是最新编译的 aarch64 静态版
  - 带上 sha256sums.txt，安装脚本会校验

用法：
    python tools/build-release.py [--out dist] [--publish ../rongyue-e5-plugins]

产物：
    e5-emulator.tar.gz    插件目录（不含旧的 EmulatorJS 运行库）
    roms-homebrew.tar.gz  自制游戏（19 个，许可允许再分发）
    e5emu                 FC 核心
    e5emu-genesis         MD 核心
    e5emu-gba             GBA/GB 核心
    sha256sums.txt        校验和
"""
import argparse
import hashlib
import os
import shutil
import tarfile
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NATIVE = os.path.join(ROOT, "native")
CORES = ("e5emu", "e5emu-genesis", "e5emu-gba")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def make_tar(src_dir, arcname, out_path, skip_dirs=()):
    """把目录打成 .tar.gz（arcname 是包内的顶层目录名）。"""
    with tarfile.open(out_path, "w:gz") as tf:
        for name in sorted(os.listdir(src_dir)):
            if name in skip_dirs:
                continue
            tf.add(os.path.join(src_dir, name), arcname=os.path.join(arcname, name))
    return out_path


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=os.path.join(ROOT, "dist"))
    ap.add_argument("--publish", default=os.path.join(ROOT, "..", "rongyue-e5-plugins"))
    args = ap.parse_args()

    publish = os.path.abspath(args.publish)
    out = os.path.abspath(args.out)
    if not os.path.isdir(publish):
        print("找不到公开仓库目录：%s" % publish, file=sys.stderr)
        return 1
    os.makedirs(out, exist_ok=True)

    plugin_src = os.path.join(publish, "plugins", "e5-emulator")
    roms_src = os.path.join(publish, "roms")
    if not os.path.isdir(plugin_src):
        print("公开仓库里没有插件目录：%s" % plugin_src, file=sys.stderr)
        return 1

    made = []

    # 插件：不要 ejs 那套旧的运行库（原生核心用不到，占 12MB）
    stage = os.path.join(out, "_stage", "e5-emulator")
    if os.path.isdir(os.path.join(out, "_stage")):
        shutil.rmtree(os.path.join(out, "_stage"))
    os.makedirs(stage)
    for name in os.listdir(plugin_src):
        if name == "ejs":
            continue
        src = os.path.join(plugin_src, name)
        dst = os.path.join(stage, name)
        if os.path.isdir(src):
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)
    made.append(make_tar(stage, "e5-emulator",
                          os.path.join(out, "e5-emulator.tar.gz")))

    # 自制游戏
    if os.path.isdir(roms_src):
        roms_stage = os.path.join(out, "_stage", "roms")
        shutil.copytree(roms_src, roms_stage)
        made.append(make_tar(roms_stage, "roms",
                              os.path.join(out, "roms-homebrew.tar.gz")))

    # 三个核心二进制
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
        print("缺少二进制：%s（先跑 native/build-*.ps1）" % "、".join(missing), file=sys.stderr)
        return 1

    # 校验和
    sums = os.path.join(out, "sha256sums.txt")
    with open(sums, "w", encoding="utf-8") as f:
        for path in made:
            f.write("%s  %s\n" % (sha256(path), os.path.basename(path)))
    made.append(sums)

    shutil.rmtree(os.path.join(out, "_stage"), ignore_errors=True)

    print("发布资源已生成于 %s" % out)
    for path in made:
        print("  %-24s %8.1f KB" % (os.path.basename(path), os.path.getsize(path) / 1024))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

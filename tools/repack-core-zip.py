#!/usr/bin/env python3
"""把 EJS 核心的 `.data`（7z 包）重打包成不压缩的 zip。

背景：EmulatorJS 按魔数识别 `.data` 的格式，7z 会走
`compression/extract7z.js`，zip 走 `compression/extractzip.js`。在性能弱、
WebAssembly 引擎又不太可靠的设备上，用 JS 解 4.5MB 的 LZMA 既慢（十几秒）
又可能解出错误字节（表现为 wasm 在里面抛 call_indirect 陷阱）。
store 模式的 zip 只做切分、不做解压，最快也最不容易出错。

用法：
    python tools/repack-core-zip.py <输入.data> [输出文件]
    python tools/repack-core-zip.py --dir plugins/e5-emulator/ejs/data/cores
    python tools/repack-core-zip.py --dir <目录> --in-place    # 覆盖原文件

依赖：系统里有 7z（用于解 7z 包）；打包用 Python 自带的 zipfile。
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile


def find_7z() -> str:
    for name in ("7z", "7za", "7zz"):
        path = shutil.which(name)
        if path:
            return path
    for guess in (r"C:\Program Files\7-Zip\7z.exe",
                  os.path.expanduser(r"~\scoop\shims\7z.exe")):
        if os.path.isfile(guess):
            return guess
    raise SystemExit("找不到 7z 可执行文件")


def repack(src: str, dst: str, seven_zip: str) -> tuple[int, int]:
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run([seven_zip, "x", src, f"-o{tmp}", "-y"],
                       check=True, stdout=subprocess.DEVNULL)
        files = []
        for root, _dirs, names in os.walk(tmp):
            for name in names:
                full = os.path.join(root, name)
                files.append((full, os.path.relpath(full, tmp).replace(os.sep, "/")))
        if not files:
            raise SystemExit(f"{src}: 7z 包里没有文件")
        with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            for full, arc in sorted(files):
                zf.write(full, arc)
    return len(files), os.path.getsize(dst)


def main() -> int:
    ap = argparse.ArgumentParser(description="EJS 核心 .data: 7z -> store zip")
    ap.add_argument("src", nargs="?", help="输入 .data 文件")
    ap.add_argument("out", nargs="?", help="输出文件（默认 <src>.zip）")
    ap.add_argument("--dir", help="批量处理目录下所有 *.data")
    ap.add_argument("--in-place", action="store_true", help="直接覆盖原 .data")
    args = ap.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    seven_zip = find_7z()

    targets = []
    if args.dir:
        for name in sorted(os.listdir(args.dir)):
            if name.endswith(".data"):
                targets.append(os.path.join(args.dir, name))
    elif args.src:
        targets.append(args.src)
    else:
        print("给一个 .data 文件，或用 --dir 指定目录", file=sys.stderr)
        return 2

    for src in targets:
        with open(src, "rb") as fh:
            magic = fh.read(6)
        if magic[:2] == b"PK":
            print(f"{os.path.basename(src)}: 已经是 zip，跳过")
            continue
        out = src if args.in_place else (args.out or src + ".zip")
        if not args.dir and args.out:
            out = args.out
        count, size = repack(src, out, seven_zip)
        print(f"{os.path.basename(src)} -> {os.path.basename(out)}: "
              f"{count} 个文件, {size} 字节")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

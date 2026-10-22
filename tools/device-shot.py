#!/usr/bin/env python3
"""从设备抓一屏（/dev/fb0）存成 PNG，方便不在家时看真机界面。

用法：
    python tools/device-shot.py                 # 存到 .notes/shots/shot-时间.png
    python tools/device-shot.py 输出.png          # 指定文件名
    python tools/device-shot.py 输出.png --order rgba   # 通道顺序（默认 bgra）

说明：设备是 320x480、32bpp 的字符设备帧缓冲，一次读满 614400 字节就是一整屏。
PNG 在电脑上编码（zlib），设备上只负责吐原始像素。
"""
from __future__ import annotations

import json
import struct
import sys
import zlib
from datetime import datetime
from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parents[1]
HOST = "fe80::50:ff:fe00:e501%50"
W, H = 320, 480


def connect() -> paramiko.SSHClient:
    auth = json.loads((ROOT / ".secrets/openwrt-access.json").read_text(encoding="utf-8"))
    client = paramiko.SSHClient()
    client.load_host_keys(str(ROOT / ".secrets/openwrt-known-hosts"))
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    client.connect(
        HOST,
        username="root",
        password=auth["adminPassword"],
        look_for_keys=False,
        allow_agent=False,
        timeout=10,
        auth_timeout=10,
        banner_timeout=10,
    )
    return client


def grab(client: paramiko.SSHClient) -> bytes:
    _in, out, err = client.exec_command(f"cat /dev/fb0", timeout=60)
    data = out.read()
    msg = err.read().decode("utf-8", "replace").strip()
    if msg:
        print("[stderr]", msg)
    return data


def to_rgb(raw: bytes, order: str) -> bytearray:
    """帧缓冲是 32bpp，内存里一般是 B,G,R,A（也有机器是 R,G,B,A）。"""
    out = bytearray(W * H * 3)
    n = min(W * H, len(raw) // 4)
    if order == "rgba":
        for i in range(n):
            b, g, r, _a = raw[i * 4], raw[i * 4 + 1], raw[i * 4 + 2], raw[i * 4 + 3]
            j = i * 3
            out[j], out[j + 1], out[j + 2] = r, g, b
    else:
        for i in range(n):
            b, g, r, _a = raw[i * 4], raw[i * 4 + 1], raw[i * 4 + 2], raw[i * 4 + 3]
            j = i * 3
            out[j], out[j + 1], out[j + 2] = b, g, r
    return out


def write_png(path: Path, rgb: bytearray) -> None:
    raw = bytearray()
    stride = W * 3
    for y in range(H):
        raw.append(0)                      # 每行的 filter 类型
        raw += rgb[y * stride:(y + 1) * stride]

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", W, H, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(bytes(raw), 6))
    png += chunk(b"IEND", b"")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    order = "bgra"
    if "--order" in sys.argv:
        order = sys.argv[sys.argv.index("--order") + 1]
    if args:
        out = Path(args[0])
    else:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        out = ROOT / ".notes/shots" / f"shot-{stamp}.png"
    client = connect()
    try:
        raw = grab(client)
    finally:
        client.close()
    if len(raw) < W * H * 4:
        print(f"帧缓冲只有 {len(raw)} 字节，不足一屏（{W * H * 4}）")
        return 1
    write_png(out, to_rgb(raw, order))
    print(f"{out}  ({len(raw)} bytes from /dev/fb0, order={order})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

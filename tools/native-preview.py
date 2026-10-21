#!/usr/bin/env python3
"""在电脑上预览插件页面：假的 e5emu 推帧服务 + 静态文件服务。

用途：设备上装原生引擎之前/之后，先在本机用浏览器看插件页面的画面、顶栏、
HUD 和按键发送是否符合预期，不用每次下发到手机。

    python tools/native-preview.py            # 默认 127.0.0.1:18080
    python tools/native-preview.py 19000      # 指定静态服务端口

它会：
  1. 在 127.0.0.1:9510 起一个 WebSocket 服务，按 e5emu 的协议推 256x240 的
     RGB565 测试图案（8 色彩条 + 一个来回移动的方块，方便确认画面在动）；
  2. 在静态端口上把项目里的 plugins/ 目录按插件页需要的绝对路径暴露出来；
  3. 收到的按键位图和单字节命令打印在终端里。

打开：http://127.0.0.1:<port>/plugins/e5-emulator/index.html?preview=1&auto=0
（页面里 e5 SDK 不存在，所以不会去调用后端的 /emu/start，直接连 9510。）
"""
from __future__ import annotations

import base64
import hashlib
import os
import socket
import struct
import sys
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
W, H, FPS = 256, 240, 60


def rgb565(r: int, g: int, b: int) -> int:
    return ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)


def build_background() -> bytes:
    bars = [
        (255, 255, 255), (255, 255, 0), (0, 255, 255), (0, 255, 0),
        (255, 0, 255), (255, 0, 0), (0, 0, 255), (16, 16, 16),
    ]
    row = bytearray()
    for i in range(W):
        c = bars[min(len(bars) - 1, i * len(bars) // W)]
        row += struct.pack("<H", rgb565(*c))
    return bytes(row) * H


BG = build_background()
WHITE = struct.pack("<H", rgb565(255, 255, 255)) * 24
BLACK = struct.pack("<H", rgb565(0, 0, 0)) * 24
ROW = 24
ROW_BYTES = ROW * 2


def make_frame(index: int, x: int, y: int, last: tuple[int, int] | None) -> bytes:
    buf = bytearray(BG)
    if last:
        lx, ly = last
        for r in range(ROW):
            off = (ly + r) * W * 2 + lx * 2
            buf[off:off + ROW_BYTES] = BLACK
    if 0 <= x <= W - ROW and 0 <= y <= H - ROW:
        for r in range(ROW):
            off = (y + r) * W * 2 + x * 2
            buf[off:off + ROW_BYTES] = WHITE
    return struct.pack("<HH", W, H) + bytes(buf)


def ws_send(sock: socket.socket, payload: bytes) -> None:
    n = len(payload)
    if n < 126:
        head = bytes([0x82, n])
    elif n < 65536:
        head = bytes([0x82, 126]) + struct.pack(">H", n)
    else:
        head = bytes([0x82, 127]) + struct.pack(">Q", n)
    sock.sendall(head + payload)


def ws_read(sock: socket.socket) -> bytes | None:
    h = sock.recv(2)
    if len(h) < 2:
        return None
    n = h[1] & 0x7F
    if n == 126:
        n = struct.unpack(">H", sock.recv(2))[0]
    elif n == 127:
        n = struct.unpack(">Q", sock.recv(8))[0]
    mask = sock.recv(4) if h[1] & 0x80 else b""
    data = b""
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            return None
        data += chunk
    if mask:
        data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
    return data


def serve_ws() -> None:
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 9510))
    srv.listen(8)
    print("fake e5emu on ws://127.0.0.1:9510", flush=True)
    while True:
        conn, _ = srv.accept()
        threading.Thread(target=serve_client, args=(conn,), daemon=True).start()


def serve_client(conn: socket.socket) -> None:
    if True:
        req = b""
        while b"\r\n\r\n" not in req:
            chunk = conn.recv(1024)
            if not chunk:
                break
            req += chunk
        key = ""
        for line in req.decode(errors="replace").split("\r\n"):
            if line.lower().startswith("sec-websocket-key:"):
                key = line.split(":", 1)[1].strip()
        accept = base64.b64encode(hashlib.sha1((key + GUID).encode()).digest()).decode()
        conn.sendall(
            b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
            b"Connection: Upgrade\r\nSec-WebSocket-Accept: " + accept.encode() + b"\r\n\r\n"
        )
        print("page connected", flush=True)
        stop = threading.Event()

        def reader() -> None:
            while not stop.is_set():
                data = ws_read(conn)
                if data is None:
                    stop.set()
                    return
                if len(data) == 4:
                    bits = struct.unpack("<I", data)[0]
                    on = [n for n in range(16) if bits >> n & 1]
                    print("buttons=0x%04x (%s)" % (bits, on), flush=True)
                elif len(data) == 1:
                    print("cmd=%d" % data[0], flush=True)

        threading.Thread(target=reader, daemon=True).start()
        try:
            idx = 0
            last = None
            while not stop.is_set():
                t0 = time.monotonic()
                x = int((W - ROW) / 2 * (1 + math_sin(idx / 30.0)))
                y = 100 + int(30 * math_sin(idx / 17.0))
                ws_send(conn, make_frame(idx, x, y, last))
                last = (x, y)
                idx += 1
                time.sleep(max(0.0, 1.0 / FPS - (time.monotonic() - t0)))
        except OSError:
            pass
        finally:
            stop.set()
            conn.close()
            print("page disconnected", flush=True)


def math_sin(x: float) -> float:
    import math

    return math.sin(x)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(ROOT), **kw)

    def translate_path(self, path: str) -> str:
        # 页面用的是绝对路径：/plugins/... 、/sdk/e5.js 、/roms/...
        clean = path.split("?", 1)[0].split("#", 1)[0]
        if clean.startswith("/plugins/"):
            return str(ROOT / clean.lstrip("/"))
        if clean == "/sdk/e5.js":
            return str(ROOT / "tools" / "native-preview-stub-e5.js")
        return str(ROOT / "tools" / "native-preview-missing")

    def log_message(self, fmt: str, *args) -> None:  # 静态请求太吵，只留错误
        pass


def main() -> int:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 18080
    missing = ROOT / "tools" / "native-preview-missing"
    missing.mkdir(exist_ok=True)
    threading.Thread(target=serve_ws, daemon=True).start()
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print("plugin page: http://127.0.0.1:%d/plugins/e5-emulator/index.html?preview=1&auto=0" % port, flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

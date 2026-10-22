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

# 假核心的 WS 端口。默认 9510（和真核心一样），但这台电脑上 9510 可能被
# WSL 里的 e5emu 占着——WSL2 的 localhost 转发会让 Windows 侧 bind 报
# "地址已在使用"，而 bind 失败后如果不报错，浏览器就会连上那个占位的进程，
# 表现为"连上了但一帧不来"。用 E5_CORE_PORT=9511 之类换个端口即可。
CORE_PORT = int(os.environ.get("E5_CORE_PORT", "9510"))


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
    try:
        srv.bind(("127.0.0.1", CORE_PORT))
    except OSError as exc:
        # 端口被别人占着时必须说出来：SO_REUSEADDR 会让 bind 静默失败或
        # 抢不到连接，浏览器就会连上占位进程，一直等不到帧。
        print("假核心 bind 127.0.0.1:%d 失败：%s（换个端口：E5_CORE_PORT=9511）"
              % (CORE_PORT, exc), flush=True)
        raise
    srv.listen(8)
    print("fake e5emu on ws://127.0.0.1:%d" % CORE_PORT, flush=True)
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
                elif len(data) == 2:
                    # 状态命令：[1,槽]=存 [2,槽]=读（原生核心的即时存档）
                    print("state cmd=%d slot=%d" % (data[0], data[1]), flush=True)
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
        if clean.startswith("/tools/"):
            return str(ROOT / clean.lstrip("/"))
        if clean == "/sdk/e5.js":
            return str(ROOT / "tools" / "native-preview-stub-e5.js")
        return str(ROOT / "tools" / "native-preview-missing")

    def log_message(self, fmt: str, *args) -> None:  # 静态请求太吵，只留错误
        msg = fmt % args
        if "/ws" in msg or "Upgrade" in msg or "101" in msg or "404" in msg:
            print("[preview] " + msg, flush=True)

    def do_GET(self) -> None:
        """同源 WebSocket 中转：/ws -> 127.0.0.1:9510。

        浏览器连 ws://127.0.0.1:9510 会被系统代理（FlClash）拦掉，握手直接 1006；
        但同一个 http://127.0.0.1:18080 的普通请求没问题。所以让页面连同源的
        /ws，由这个服务转发到真正的帧服务，浏览器侧就完全不过代理。
        """
        if self.path.split("?", 1)[0] == "/ws":
            print("[preview] /ws 请求到达 path=%s" % self.path, flush=True)
            self.relay_ws()
            return
        super().do_GET()

    def relay_ws(self) -> None:
        import base64
        import hashlib
        import socket as _socket
        import threading

        # 请求头已经被 BaseHTTPRequestHandler 解析过了，直接取，不要再读一遍（会卡住）
        key = self.headers.get("Sec-WebSocket-Key", "")

        # 先把 101 回给浏览器，再去连上游。上游 e5emu 只有一个客户端位，
        # 它正忙的时候如果先把上游握手做完，浏览器就会一直卡在 CONNECTING。
        accept = base64.b64encode(
            hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()
        ).decode()
        self.wfile.write(
            b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
            b"Connection: Upgrade\r\nSec-WebSocket-Accept: " + accept.encode() + b"\r\n\r\n"
        )
        self.wfile.flush()
        print("[preview] 101 已回浏览器，开始连上游 9510", flush=True)

        try:
            up = _socket.create_connection(("127.0.0.1", CORE_PORT), timeout=5)
        except OSError as exc:
            print("[preview] 连上游失败: %s" % exc, flush=True)
            try:
                self.connection.shutdown(1)
            except OSError:
                pass
            return

        # 用浏览器给的那个 key 向上游做客户端握手：同一把 key 算出来的 accept
        # 两边一致，浏览器那头能通过校验。
        req = (
            "GET / HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nUpgrade: websocket\r\n"
            "Connection: Upgrade\r\nSec-WebSocket-Key: %s\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n" % (CORE_PORT, key)
        )
        up.sendall(req.encode())
        up.settimeout(8)
        resp = b""
        while b"\r\n\r\n" not in resp:
            try:
                chunk = up.recv(4096)
            except OSError:
                break
            if not chunk:
                break
            resp += chunk
        if b"101" not in resp.split(b"\r\n")[0]:
            up.close()
            print("[preview] 上游拒绝握手: %r" % resp[:80], flush=True)
            try:
                self.connection.shutdown(1)
            except OSError:
                pass
            return
        # 握手响应后面可能已经跟着第一帧，一起转给浏览器，别丢掉
        cut = resp.find(b"\r\n\r\n")
        leftover = resp[cut + 4:] if cut >= 0 else b""
        if leftover:
            try:
                self.connection.sendall(leftover)
            except OSError:
                pass
        print("[preview] 上游握手成功，转发帧", flush=True)

        stop = threading.Event()

        def pump(src, dst):
            try:
                while not stop.is_set():
                    data = src.recv(65536)
                    if not data:
                        break
                    dst.sendall(data)
            except OSError:
                pass
            finally:
                stop.set()

        t1 = threading.Thread(target=pump, args=(self.connection, up), daemon=True)
        t2 = threading.Thread(target=pump, args=(up, self.connection), daemon=True)
        t1.start()
        t2.start()
        while not stop.is_set() and (t1.is_alive() or t2.is_alive()):
            stop.wait(0.2)
        stop.set()
        try:
            up.close()
        except OSError:
            pass

    def do_POST(self) -> None:
        """页面把 canvas 的 PNG(base64) 传上来存盘：做本机联调时能拿到真实分辨率的画面。"""
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length).decode("ascii", "replace")
            name = "shot.png"
            if "?" in self.path:
                q = self.path.split("?", 1)[1]
                for kv in q.split("&"):
                    if kv.startswith("name="):
                        name = kv[5:].replace("/", "_")
                        break
            import base64
            data = base64.b64decode(body + "===")
            out = ROOT / ".notes" / "img" / name
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(data)
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(str(out).encode())
        except Exception as exc:  # noqa: BLE001
            self.send_response(500)
            self.end_headers()
            self.wfile.write(str(exc).encode())


def main() -> int:
    argv = sys.argv[1:]
    real = "--real" in argv
    argv = [a for a in argv if not a.startswith("--")]
    port = int(argv[0]) if argv else 18080
    missing = ROOT / "tools" / "native-preview-missing"
    missing.mkdir(exist_ok=True)
    if real:
        # --real：不造假帧服务，端口留给真的 e5emu（本机 x86 版本或设备上的）
        print("using the real frame server on ws://127.0.0.1:%d" % CORE_PORT, flush=True)
    else:
        threading.Thread(target=serve_ws, daemon=True).start()
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    # 页面连同源的 /ws（由这个服务转发到假核心）。浏览器直连 ws://127.0.0.1:<core>
    # 会被系统代理（FlClash）拦掉，握手直接 1006；同源 HTTP 请求不受影响。
    print("plugin page: http://127.0.0.1:%d/plugins/e5-emulator/index.html?preview=1&auto=0&ws=ws://127.0.0.1:%d/ws"
          % (port, port), flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

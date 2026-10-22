"""把设备上只监听回环的 8088 端口（信息屏的 uhttpd）代理到本机 127.0.0.1:18088。

用途：在本机的真实浏览器里打开设备上的页面（插件页/能力探测页），
这样能直接看到控制台错误，不必依赖有人去点设备屏幕。

另外支持 --tcp 把设备的另一个端口（比如原生核心的 9510）做**裸 TCP 隧道**
转发到本机：WebSocket 握手之后就是裸 TCP，所以这样能让本机浏览器里的
插件页连上真机上的核心，跑完整闭环（宿主页面 -> iframe 里的插件 -> 核心）。

用法：
    python tools/device-proxy.py [本机端口]              # 8088 的 HTTP 代理
    python tools/device-proxy.py [本机端口] --tcp 9510   # 9510 的裸 TCP 隧道
    python tools/device-proxy.py [本机端口] --rewrite 8089  # 改写页面里的绝对地址
注意：这是一个临时的调试通道，只在需要时启动；用完 Ctrl+C 结束。
"""
import json
import os
import socket
import socketserver
import sys
import threading
import time
from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parents[1]
# 设备地址不给默认值：它是按 MAC 派生的，属于不能公开的信息。
# 用法：E5_HOST='<设备地址>' python tools/device-proxy.py [本机端口] [...]
HOST = os.environ.get('E5_HOST', '')
if not HOST:
    sys.exit("缺少 E5_HOST 环境变量（设备地址）")
REMOTE = ("127.0.0.1", 8088)
LOCAL_PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 18088
# --tcp <port>：不做 HTTP 解析，原样转发字节（WebSocket / 帧流）
TCP_MODE = '--tcp' in sys.argv
TCP_REMOTE_PORT = 9510
if TCP_MODE:
    i = sys.argv.index('--tcp')
    TCP_REMOTE_PORT = int(sys.argv[i + 1]) if len(sys.argv) > i + 1 else 9510
# --rewrite <port>：把页面里写死的 http://127.0.0.1:<port> 改成本机的 <本机端口>，
# 这样从电脑打开设备页面时，页面里的事件流/RPC 也能回到设备（否则会打到电脑自己）。
REWRITE_PORT = 0
if '--rewrite' in sys.argv:
    i = sys.argv.index('--rewrite')
    REWRITE_PORT = int(sys.argv[i + 1]) if len(sys.argv) > i + 1 else 8089

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
)
if TCP_MODE:
    print(f"已连接设备 {HOST}，把 {TCP_REMOTE_PORT} 隧道到 127.0.0.1:{LOCAL_PORT}", flush=True)
else:
    print(f"已连接设备 {HOST}，把 {REMOTE} 代理到 127.0.0.1:{LOCAL_PORT}", flush=True)


class TcpHandler(socketserver.BaseRequestHandler):
    """裸转发：设备端口 -> 本机端口，两边各一个线程搬字节。"""

    def handle(self):
        try:
            chan = client.get_transport().open_channel(
                "direct-tcpip", ("127.0.0.1", TCP_REMOTE_PORT), self.client_address)
        except Exception as exc:  # noqa: BLE001
            print(f"开通道失败: {exc}", file=sys.stderr)
            return
        chan.settimeout(None)
        self.request.settimeout(None)

        def up():
            try:
                while True:
                    data = self.request.recv(65536)
                    if not data:
                        break
                    chan.sendall(data)
            except Exception:
                pass
            finally:
                try:
                    chan.shutdown_write()
                except Exception:
                    pass

        t = threading.Thread(target=up, daemon=True)
        t.start()
        try:
            while True:
                data = chan.recv(65536)
                if not data:
                    break
                self.request.sendall(data)
        except Exception:
            pass
        finally:
            try:
                chan.close()
            except Exception:
                pass
            try:
                self.request.close()
            except Exception:
                pass


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        # 先读请求头，再按路径决定转发到 8088（信息屏）还是 8089（RPC/事件流）
        try:
            data = b""
            while b"\r\n\r\n" not in data:
                chunk = self.request.recv(4096)
                if not chunk:
                    return
                data += chunk
        except Exception:
            return
        head, rest = data.split(b"\r\n\r\n", 1)
        lines = head.decode("latin-1", "replace").split("\r\n")
        path = lines[0].split(" ")[1] if lines and " " in lines[0] else "/"
        # /events（SSE）和 /rpc（WebSocket）在设备的 8089 上，其余在 8088
        target = 8089 if (path.startswith("/events") or path.startswith("/rpc")) else 8088
        raw_mode = target == 8089   # 这两个是长连接，原样转发，不改头

        try:
            chan = client.get_transport().open_channel(
                "direct-tcpip", ("127.0.0.1", target), self.client_address)
        except Exception as exc:  # noqa: BLE001
            print(f"开通道失败: {exc}", file=sys.stderr)
            return
        try:
            chan.settimeout(120)
            if raw_mode:
                # 长连接：请求头原样发过去，然后把两边的字节搬来搬去
                chan.sendall(data)
                self.pump(chan)
                return

            headers = lines
            length = 0
            for h in headers[1:]:
                if h.lower().startswith("content-length:"):
                    length = int(h.split(":", 1)[1].strip())
            while len(rest) < length:
                chunk = self.request.recv(4096)
                if not chunk:
                    break
                rest += chunk
            # 强制 Connection: close，便于一次请求一次通道
            out = []
            for h in headers:
                if h.lower().startswith("connection:"):
                    continue
                out.append(h)
            out.append("Connection: close")
            chan.sendall(("\r\n".join(out) + "\r\n\r\n").encode("latin-1") + rest)

            if REWRITE_PORT:
                # 改写模式：整份读完再发，替换页面里写死的设备绝对地址
                raw = b""
                while True:
                    chunk = chan.recv(65536)
                    if not chunk:
                        break
                    raw += chunk
                self.send_rewritten(raw)
                return
            while True:
                chunk = chan.recv(65536)
                if not chunk:
                    break
                self.request.sendall(chunk)
        except Exception as exc:  # noqa: BLE001
            print(f"转发出错: {exc}", file=sys.stderr)
        finally:
            try:
                chan.close()
            except Exception:
                pass

    def pump(self, chan):
        """长连接的双向转发：浏览器 -> 设备，设备 -> 浏览器。"""
        def up():
            try:
                while True:
                    chunk = self.request.recv(65536)
                    if not chunk:
                        break
                    chan.sendall(chunk)
            except Exception:
                pass

        t = threading.Thread(target=up, daemon=True)
        t.start()
        try:
            while True:
                chunk = chan.recv(65536)
                if not chunk:
                    break
                self.request.sendall(chunk)
        except Exception:
            pass
        finally:
            try:
                self.request.close()
            except Exception:
                pass

    def send_rewritten(self, raw):
        """把响应里的设备绝对地址改成本机端口，再原样发回浏览器。"""
        split = raw.find(b"\r\n\r\n")
        if split < 0:
            self.request.sendall(raw)
            return
        head, body = raw[:split], raw[split + 4:]
        lines = head.decode("latin-1", "replace").split("\r\n")
        ctype = ""
        for h in lines[1:]:
            if h.lower().startswith("content-type:"):
                ctype = h.split(":", 1)[1].strip().lower()
        if "text" in ctype or "javascript" in ctype or "json" in ctype:
            for scheme in ("http://", "ws://"):
                old = f"{scheme}127.0.0.1:{REWRITE_PORT}".encode()
                new = f"{scheme}127.0.0.1:{LOCAL_PORT}".encode()
                if old in body:
                    body = body.replace(old, new)
        if "html" in ctype:
            # 浏览器会缓存改写前的脚本（里面还是旧地址），给本地脚本加随机尾巴
            import re
            bust = str(int(time.time())).encode()
            def _bust(m):
                url = m.group(2)
                if url.startswith((b"http://", b"https://", b"//", b"/", b"#")):
                    return m.group(0)
                return m.group(1) + url + b"?bust=" + bust + m.group(3)
            body = re.sub(rb'((?:src|href)\s*=\s*")([^"]+\.(?:js|css))(")', _bust, body)
        # 长度变了，Content-Length 要跟着改
        out = []
        for h in lines:
            if h.lower().startswith("content-length:"):
                out.append(f"Content-Length: {len(body)}")
            elif h.lower().startswith("cache-control:"):
                # 改写后的内容不能被浏览器缓存，否则它会一直用旧地址
                out.append("Cache-Control: no-store")
            else:
                out.append(h)
        if not any(h.lower().startswith("cache-control:") for h in out):
            out.append("Cache-Control: no-store")
        self.request.sendall(("\r\n".join(out) + "\r\n\r\n").encode("latin-1") + body)


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    handler = TcpHandler if TCP_MODE else Handler
    with Server(("127.0.0.1", LOCAL_PORT), handler) as srv:
        if TCP_MODE:
            print(f"隧道就绪: 127.0.0.1:{LOCAL_PORT} -> 设备 {TCP_REMOTE_PORT}", flush=True)
        else:
            print(f"代理就绪: http://127.0.0.1:{LOCAL_PORT}/", flush=True)
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            pass
    client.close()

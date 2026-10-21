"""把设备上只监听回环的 8088 端口（信息屏的 uhttpd）代理到本机 127.0.0.1:18088。

用途：在本机的真实浏览器里打开设备上的页面（插件页/能力探测页），
这样能直接看到控制台错误，不必依赖有人去点设备屏幕。

用法：python tools/device-proxy.py [本机端口]
注意：这是一个临时的调试通道，只在需要时启动；用完 Ctrl+C 结束。
"""
import json
import socket
import socketserver
import sys
import threading
from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parents[1]
HOST = "fe80::50:ff:fe00:e501%50"
REMOTE = ("127.0.0.1", 8088)
LOCAL_PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 18088

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
print(f"已连接设备 {HOST}，把 {REMOTE} 代理到 127.0.0.1:{LOCAL_PORT}", flush=True)


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        try:
            chan = client.get_transport().open_channel("direct-tcpip", REMOTE, self.client_address)
        except Exception as exc:  # noqa: BLE001
            print(f"开通道失败: {exc}", file=sys.stderr)
            return
        try:
            chan.settimeout(120)
            # 读到请求头结束；POST 的 body 按 Content-Length 一并读走
            data = b""
            while b"\r\n\r\n" not in data:
                chunk = self.request.recv(4096)
                if not chunk:
                    return
                data += chunk
            head, rest = data.split(b"\r\n\r\n", 1)
            headers = head.decode("latin-1", "replace").split("\r\n")
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


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    with Server(("127.0.0.1", LOCAL_PORT), Handler) as srv:
        print(f"代理就绪: http://127.0.0.1:{LOCAL_PORT}/", flush=True)
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            pass
    client.close()

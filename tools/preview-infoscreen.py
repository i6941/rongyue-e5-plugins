"""Temporary localhost-only SSH tunnel for testing the real E5 screen UI.

Run from this workspace; Ctrl+C closes the listener. Never exposes port8088
on the E5's USB or Wi-Fi interface. Credentials stay in .secrets.
"""
import json
import os
from pathlib import Path
import select
import socketserver
import paramiko

ROOT = Path(__file__).resolve().parents[1]
HOST = os.environ.get('E5_HOST', '192.168.9.1')
auth = json.loads((ROOT / '.secrets/openwrt-access.json').read_text())
client = paramiko.SSHClient()
client.load_host_keys(str(ROOT / '.secrets/openwrt-known-hosts'))
client.connect(HOST, username='root',
               password=auth['adminPassword'], look_for_keys=False,
               allow_agent=False, timeout=8)
client.get_transport().set_keepalive(15)


class Forward(socketserver.BaseRequestHandler):
    def handle(self):
        channel = client.get_transport().open_channel(
            'direct-tcpip', ('127.0.0.1', 8088), self.client_address, timeout=5)
        try:
            while True:
                ready, _, _ = select.select([self.request, channel], [], [], 30)
                if not ready:
                    return
                if self.request in ready:
                    data = self.request.recv(65536)
                    if not data:
                        return
                    channel.sendall(data)
                if channel in ready:
                    data = channel.recv(65536)
                    if not data:
                        return
                    self.request.sendall(data)
        except (ConnectionError, OSError):
            pass
        finally:
            channel.close()


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


try:
    with Server(('127.0.0.1', 18088), Forward) as server:
        print('Temporary screen preview: http://127.0.0.1:18088/', flush=True)
        server.serve_forever()
except KeyboardInterrupt:
    pass
finally:
    client.close()

"""设备更新/重刷之后，把我们加的东西恢复到 E5。

恢复三样：
  1. ROM 集合 -> /etc/e5-infoscreen/roms（更新会被 settings.tar 带走），www/roms 是软链
  2. 两个信息屏应用（复古游戏机、保号·推送）-> 从本项目的 .tgz 安装
  3. 保号设置与 token -> /etc/e5-infoscreen/keepalive

用法：python tools/restore-e5-apps.py
依赖：本机有 paramiko；设备可从 USB 链路地址 E5_HOST 访问。
"""
import io
import json
import os
import tarfile
from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parents[1]
NOTES = ROOT / ".notes" / "game-port"
HOST = os.environ.get('E5_HOST', '192.168.9.1')
ROM_SRC = NOTES / "roms"

PKGS = [
    (NOTES / "e5-emulator.tgz", "/tmp/e5-emulator.tgz"),
    (NOTES / "e5-keepalive.tgz", "/tmp/e5-keepalive.tgz"),
]


def sh(client, cmd, timeout=90):
    _i, out, err = client.exec_command(cmd, timeout=timeout)
    rc = out.channel.recv_exit_status()
    return rc, out.read().decode("utf-8", "replace"), err.read().decode("utf-8", "replace")


def push_bytes(client, data, remote):
    _i, out, _e = client.exec_command("cat > " + remote, timeout=180)
    out.channel.sendall(data)
    out.channel.shutdown_write()
    out.channel.recv_exit_status()


def main() -> int:
    auth = json.loads((ROOT / ".secrets/openwrt-access.json").read_text(encoding="utf-8"))
    client = paramiko.SSHClient()
    client.load_host_keys(str(ROOT / ".secrets/openwrt-known-hosts"))
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    client.connect(HOST, username="root", password=auth["adminPassword"],
                   look_for_keys=False, allow_agent=False, timeout=10)
    print("connected:", HOST)

    if ROM_SRC.is_dir():
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tf:
            for f in sorted(ROM_SRC.iterdir()):
                if f.is_file():
                    tf.add(f, arcname=f.name)
        push_bytes(client, buf.getvalue(), "/tmp/e5-roms.tgz")
        rc, out, err = sh(client, "mkdir -p /etc/e5-infoscreen/roms && "
                                  "tar -xzf /tmp/e5-roms.tgz -C /etc/e5-infoscreen/roms && "
                                  "rm -f /usr/share/e5-infoscreen/www/roms && "
                                  "ln -sfn /etc/e5-infoscreen/roms /usr/share/e5-infoscreen/www/roms && "
                                  "ls /etc/e5-infoscreen/roms | wc -l")
        print("ROMs:", (out.strip() or err.strip()), "-> /etc/e5-infoscreen/roms (www/roms is a symlink)")
    else:
        print("WARNING: no ROM source at", ROM_SRC)

    for local, remote in PKGS:
        if not local.exists():
            print("missing package", local, "- skipped")
            continue
        push_bytes(client, local.read_bytes(), remote)
        rc, out, err = sh(client, "/usr/libexec/e5-infoscreen/plugin install " + remote)
        print("install", local.name, "->", (out.strip() or err.strip()))

    rc, out, err = sh(client, "mkdir -p /etc/e5-infoscreen/keepalive && chmod 700 /etc/e5-infoscreen/keepalive && "
                               "ls -l /etc/e5-infoscreen/keepalive/ | tail -3")
    print("keepalive settings dir:\n" + out.strip())

    # WebKit 会缓存旧页面（uhttpd 不发 Cache-Control），清掉才能立刻用上新版
    rc, out, err = sh(client, "rm -rf /tmp/run/e5-infoscreen/.cache/wpe/WebKitCache "
                             "/tmp/run/e5-infoscreen/.cache/wpe/NetworkCache 2>/dev/null; echo cleared")
    print("webkit cache:", out.strip() or err.strip())

    for path in ["/plugins/e5-emulator/index.html", "/plugins/e5-keepalive/index.html",
                 "/roms/fc-contra.nes"]:
        rc, out, _e = sh(client, "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8088" + path)
        print("check", path, "->", out.strip())
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

import subprocess, os, sys

sys.stdout.reconfigure(encoding='utf-8')

def sh(c, t=60):
    r = subprocess.run(['python', '.notes/game-port/device-ssh.py', c], capture_output=True, text=True, timeout=t)
    return r.stdout.replace('$ ' + c, '').strip()

def put(local, remote):
    r = subprocess.run(['python', '.notes/game-port/device-ssh.py', '--put', local, remote],
                       capture_output=True, text=True, timeout=120)
    print(r.stdout.strip())
    if r.returncode != 0:
        raise RuntimeError(f"Put failed: {local} -> {remote}")

print("=== 1. 部署 e5-emulator ===")
put("plugins/e5-emulator/manifest.json", "/etc/e5-infoscreen/plugins/e5-emulator/manifest.json")
put("plugins/e5-emulator/index.html", "/etc/e5-infoscreen/plugins/e5-emulator/index.html")
put("plugins/e5-emulator/backend.uc", "/etc/e5-infoscreen/plugins/e5-emulator/backend.uc")

print("\n=== 2. 部署 e5-dos ===")
sh("mkdir -p /etc/e5-infoscreen/plugins/e5-dos")
put("plugins/e5-dos/manifest.json", "/etc/e5-infoscreen/plugins/e5-dos/manifest.json")
put("plugins/e5-dos/index.html", "/etc/e5-infoscreen/plugins/e5-dos/index.html")
put("plugins/e5-dos/backend.uc", "/etc/e5-infoscreen/plugins/e5-dos/backend.uc")

print("\n=== 3. 设备端插件目录核对 ===")
print(sh("ls -la /etc/e5-infoscreen/plugins/e5-emulator/"))
print(sh("ls -la /etc/e5-infoscreen/plugins/e5-dos/"))

print("\n=== 4. 重启 e5-infoscreen 服务 ===")
print(sh("/etc/init.d/e5-infoscreen restart"))

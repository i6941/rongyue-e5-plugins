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

print("=== 1. 部署独立仙剑插件 plugins/e5-pal ===")
sh("mkdir -p /etc/e5-infoscreen/plugins/e5-pal")
put("plugins/e5-pal/manifest.json", "/etc/e5-infoscreen/plugins/e5-pal/manifest.json")
put("plugins/e5-pal/index.html", "/etc/e5-infoscreen/plugins/e5-pal/index.html")
put("plugins/e5-pal/backend.uc", "/etc/e5-infoscreen/plugins/e5-pal/backend.uc")

print("\n=== 2. 创建 www 软链接并重启信息屏 ===")
sh("ln -sfn /etc/e5-infoscreen/plugins/e5-pal /usr/share/e5-infoscreen/www/plugins/e5-pal")
sh("/etc/init.d/e5-infoscreen restart")

print("\n=== 3. 检查已挂载插件 ===")
print(sh("ls -l /usr/share/e5-infoscreen/www/plugins/e5-*"))

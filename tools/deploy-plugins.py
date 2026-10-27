"""把本项目所有运行时产物下发到设备（USB 或 Wi-Fi 均可，用 E5_HOST 指定）。

用法：
    $env:E5_HOST='192.168.9.1'        # USB NCM
    $env:E5_HOST='192.168.123.244'    # Wi-Fi
    python tools/deploy-plugins.py            # 插件 + 共享库
    python tools/deploy-plugins.py --host     # 同时下发宿主 app.js（有缓存/竞态修复）

说明：
- 共享库 shared/e5-no-sleep.js 必须下发到 /usr/share/e5-infoscreen/www/shared/，
  否则所有引用它的插件（模拟器/DOS/仙剑/B站）会拿不到 E5NoSleep。
- 插件本体在 /etc/e5-infoscreen/plugins/<id>/，宿主通过链接暴露到 www。
- 下发后始终重启 e5-infoscreen：uhttpd 不发 Cache-Control，WebKit 会缓存旧页面；
  宿主 index.html 打开应用时带 &v=<manifest.version>，升版本即强制取新。
"""
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8")

PLUGINS = ["e5-emulator", "e5-dos", "e5-pal", "bili"]
SHARED = [("shared/e5-no-sleep.js", "/usr/share/e5-infoscreen/www/shared/e5-no-sleep.js")]
HOST_FILES = [("device-source/usr/share/e5-infoscreen/www/app.js",
               "/usr/share/e5-infoscreen/www/app.js")]


def sh(cmd, t=120):
    r = subprocess.run(["python", ".notes/game-port/device-ssh.py", cmd],
                       capture_output=True, text=True, timeout=t)
    return r.stdout.replace("$ " + cmd, "").strip()


def put(local, remote):
    r = subprocess.run(["python", ".notes/game-port/device-ssh.py", "--put", local, remote],
                       capture_output=True, text=True, timeout=180)
    print(r.stdout.strip())
    if r.returncode != 0:
        raise RuntimeError(f"put failed: {local} -> {remote}")


def main():
    with_host = "--host" in sys.argv
    print("=== 1. 共享库 ===")
    sh("mkdir -p /usr/share/e5-infoscreen/www/shared")
    for local, remote in SHARED:
        put(local, remote)

    print("=== 2. 插件 ===")
    for pid in PLUGINS:
        sh(f"mkdir -p /etc/e5-infoscreen/plugins/{pid}")
        for name in ("manifest.json", "index.html", "backend.uc"):
            local = f"plugins/{pid}/{name}"
            try:
                open(local, "rb").close()
            except OSError:
                continue
            put(local, f"/etc/e5-infoscreen/plugins/{pid}/{name}")

    if with_host:
        print("=== 3. 宿主 app.js ===")
        for local, remote in HOST_FILES:
            put(local, remote)
    else:
        print("=== 3. 宿主 app.js 跳过（加 --host 才下发）===")

    print("=== 4. 重启宿主 ===")
    print(sh("/etc/init.d/e5-infoscreen restart; sleep 3; echo restarted"))

    print("=== 5. 自检 ===")
    for pid in PLUGINS:
        print(pid, sh(f"curl -s -o /dev/null -w '%{{http_code}}' "
                      f"http://127.0.0.1:8088/plugins/{pid}/index.html"))
    print("shared", sh("curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8088/shared/e5-no-sleep.js"))


if __name__ == "__main__":
    main()

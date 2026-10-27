"""在设备上采一段时间的功耗数据，用来定位"待机掉电快"的大头。

用法（E5_HOST 指向设备）：
    $env:E5_HOST='192.168.9.1'
    python tools/power-probe.py            # 默认采 30 秒
    python tools/power-probe.py 60         # 采 60 秒
    python tools/power-probe.py 30 --label idle      # 打标签，存 .notes/power/idle-<时间>.json

采什么：
- 电池：/sys/class/power_supply/*/current_now（µA）、voltage_now（µV）、capacity、status
  → 换算成 mA / mW，这是最直接的"掉电速度"
- CPU：/proc/stat 两次差值，算 idle% 与各态占比
- 唤醒源：/sys/kernel/debug/wakeup_sources（需挂 debugfs）、/proc/interrupts 差值 Top
- 进程：top -bn1 前 15 名；cog/WPE/uhttpd/e5emu/hostapd/wpa_supplicant 的实例数与 CPU
- Wi-Fi 省电：iw dev wlan0 get power_save
- 屏幕：背光亮度、是否 blank

判读思路：
1. 先看 current_now：待机低于 ~50mA 算正常，100mA+ 说明有大户；
2. 若 CPU idle < 70%，看 top 里是谁；
3. 若 CPU 很闲但电流高，看 interrupts 与 wakeup_sources（Wi-Fi/Modem 唤醒）；
4. 对比"关屏待机"和"开着我们的插件"两次采样，差值就是插件成本。
"""
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sh(cmd, timeout=30):
    r = subprocess.run(
        ["python", str(ROOT / ".notes/game-port/device-ssh.py"), cmd],
        capture_output=True, text=True, timeout=timeout,
    )
    out = r.stdout
    # device-ssh.py prints "$ cmd" first; drop it
    lines = out.splitlines()
    if lines and lines[0].startswith("$ "):
        lines = lines[1:]
    return "\n".join(lines).strip()


def read_battery():
    data = {}
    ps = sh("ls -d /sys/class/power_supply/* 2>/dev/null") or ""
    for d in ps.split():
        name = d.rsplit("/", 1)[-1]
        val = {}
        for f in ("current_now", "voltage_now", "capacity", "status", "power_now"):
            v = sh(f"cat {d}/{f} 2>/dev/null")
            if v:
                val[f] = v.strip()
        if val:
            data[name] = val
    return data


def cpu_times():
    line = sh("head -1 /proc/stat")
    parts = [int(x) for x in line.split()[1:]]
    idle = parts[3] + (parts[4] if len(parts) > 4 else 0)
    return sum(parts), idle


def interrupts():
    txt = sh("cat /proc/interrupts 2>/dev/null")
    out = {}
    for ln in txt.splitlines():
        cols = ln.split()
        if len(cols) < 3 or not cols[0].rstrip(":").isdigit():
            continue
        irq = cols[0].rstrip(":")
        label = " ".join(cols[-1:])
        nums = [int(c) for c in cols[1:] if c.isdigit()]
        if nums:
            out[f"{irq} {label}"] = sum(nums)
    return out


def main():
    secs = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 30
    label = "sample"
    if "--label" in sys.argv:
        label = sys.argv[sys.argv.index("--label") + 1]

    print(f"采样 {secs}s（label={label}）…")
    bat0 = read_battery()
    c0, i0 = cpu_times()
    irq0 = interrupts()
    ps0 = sh("top -bn1 2>/dev/null | head -20")
    wifi_ps = sh("iw dev wlan0 get power_save 2>/dev/null")
    backlight = sh("cat /sys/class/backlight/*/brightness 2>/dev/null")
    wakeup = sh("cat /sys/kernel/debug/wakeup_sources 2>/dev/null | head -20")
    proc_counts = sh(
        "for n in cog WPEWebProcess uhttpd e5emu hostapd wpa_supplicant zerotier-one; do "
        "printf '%s=%s ' $n $(ps w | grep -c \"[$]n\"); done")

    time.sleep(secs)

    bat1 = read_battery()
    c1, i1 = cpu_times()
    irq1 = interrupts()
    ps1 = sh("top -bn1 2>/dev/null | head -20")
    awake = sh("cat /sys/class/backlight/*/brightness 2>/dev/null")

    total = c1 - c0
    idle = i1 - i0
    idle_pct = (100.0 * idle / total) if total else 0

    top_irqs = []
    for k, v in irq1.items():
        d = v - irq0.get(k, 0)
        if d > 0:
            top_irqs.append((d, k))
    top_irqs.sort(reverse=True)

    result = {
        "label": label,
        "at": datetime.now().isoformat(timespec="seconds"),
        "seconds": secs,
        "battery": {"before": bat0, "after": bat1},
        "cpu": {"total_ticks": total, "idle_ticks": idle, "idle_pct": round(idle_pct, 1)},
        "top_irqs_delta": [{"count": c, "irq": k} for c, k in top_irqs[:12]],
        "wifi_power_save": wifi_ps,
        "backlight_before": backlight,
        "backlight_after": awake,
        "process_counts": proc_counts,
        "wakeup_sources": wakeup.splitlines()[:15],
        "top_before": ps0.splitlines(),
        "top_after": ps1.splitlines(),
    }

    outdir = ROOT / ".notes" / "power"
    outdir.mkdir(parents=True, exist_ok=True)
    out = outdir / f"{label}-{datetime.now():%Y%m%d-%H%M%S}.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\nCPU idle: {idle_pct:.1f}%  (ticks {total})")
    for name, v in bat1.items():
        cur = v.get("current_now")
        volt = v.get("voltage_now")
        if cur and volt:
            try:
                ma = abs(int(cur)) / 1000.0
                mw = ma * (int(volt) / 1e6)
                print(f"电池 {name}: {ma:.0f} mA / {mw:.0f} mW  容量 {v.get('capacity','?')}%  {v.get('status','')}")
            except ValueError:
                print(f"电池 {name}: {v}")
    print("IRQ 增量 Top:", ", ".join(f"{k}+{c}" for c, k in top_irqs[:6]) or "(无)")
    print("Wi-Fi:", wifi_ps or "(无 iw)")
    print("进程:", proc_counts)
    print(f"\n完整结果: {out}")


if __name__ == "__main__":
    main()

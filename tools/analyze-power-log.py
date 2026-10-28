"""分析设备上的 /tmp/power-log.csv（由 .notes/game-port/power-log.sh 每 15 秒采样）。

列：epoch,cap,current_ua,voltage_uv,status,backlight,ap_on

用法：
    python tools/analyze-power-log.py .notes/power/unplug-20261027.csv
    python tools/analyze-power-log.py 日志.csv --json 输出.json

输出：按 status 分段统计放电/充电电流、功率、估算电池容量、
背光与热点开关对电流的影响，以及采样空档（设备重启会让 /tmp 清空）。
"""

import argparse
import csv
import json
import locale
import statistics
import sys
import time
from datetime import datetime


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _scale_current(values):
    """current_now 在不同内核里是 uA 或 mA，按量级判断。返回 (缩放后mA, 是否缩放)。"""
    vals = [abs(v) for v in values if v is not None]
    if not vals:
        return 1.0, False
    med = statistics.median(vals)
    if med > 20000:          # 20000 "单位" 以上只可能是 uA（20mA）
        return 0.001, True
    return 1.0, False


def _scale_voltage(values):
    vals = [v for v in values if v is not None]
    if not vals:
        return 1.0
    med = statistics.median(vals)
    return 0.001 if med > 20000 else 1.0   # uV -> mV


def load(path):
    rows = []
    with open(path, newline="", encoding="utf-8", errors="replace") as fh:
        for rec in csv.DictReader(fh):
            row = {k: (v.strip() if isinstance(v, str) else v) for k, v in rec.items()}
            rows.append({
                "t": _f(row.get("epoch")),
                "cap": _f(row.get("cap")),
                "cur": _f(row.get("current_ua")),
                "vol": _f(row.get("voltage_uv")),
                "status": (row.get("status") or "").strip(),
                "bl": _f(row.get("backlight")),
                "ap": _f(row.get("ap_on")),
            })
    return [r for r in rows if r["t"] is not None]


def summarize(rows):
    cur_scale, cur_scaled = _scale_current([r["cur"] for r in rows])
    vol_scale = _scale_voltage([r["vol"] for r in rows])

    for r in rows:
        r["cur_ma"] = None if r["cur"] is None else r["cur"] * cur_scale
        r["vol_v"] = None if r["vol"] is None else r["vol"] * vol_scale / 1000.0

    out = {
        "samples": len(rows),
        "first": datetime.fromtimestamp(rows[0]["t"]).isoformat(timespec="seconds") if rows else None,
        "last": datetime.fromtimestamp(rows[-1]["t"]).isoformat(timespec="seconds") if rows else None,
        "duration_min": round((rows[-1]["t"] - rows[0]["t"]) / 60.0, 1) if len(rows) > 1 else 0,
        "current_unit_scaled": cur_scaled,
        "gaps": [],
        "by_status": {},
        "capacity": {},
        "by_backlight": {},
        "by_ap": {},
    }

    # 采样空档：间隔明显大于 15 秒就记一笔（设备重启 / 进程被杀）
    for a, b in zip(rows, rows[1:]):
        gap = b["t"] - a["t"]
        if gap > 45:
            out["gaps"].append({
                "from": datetime.fromtimestamp(a["t"]).isoformat(timespec="seconds"),
                "to": datetime.fromtimestamp(b["t"]).isoformat(timespec="seconds"),
                "seconds": int(gap),
            })

    groups = {}
    for r in rows:
        groups.setdefault(r["status"] or "unknown", []).append(r)

    for name, group in groups.items():
        currents = [r["cur_ma"] for r in group if r["cur_ma"] is not None]
        volts = [r["vol_v"] for r in group if r["vol_v"] is not None]
        entry = {"samples": len(group)}
        if currents:
            entry["current_ma"] = {
                "median": round(statistics.median(currents), 1),
                "mean": round(statistics.fmean(currents), 1),
                "min": round(min(currents), 1),
                "max": round(max(currents), 1),
            }
        if volts:
            entry["voltage_v"] = {"median": round(statistics.median(volts), 2)}
        if currents and volts and len(currents) == len(volts):
            watts = [abs(c) / 1000.0 * v for c, v in zip(currents, volts)]
            entry["power_mw"] = {"median": round(statistics.median(watts) * 1000, 1)}
        out["by_status"][name] = entry

    caps = [r["cap"] for r in rows if r["cap"] is not None]
    if len(caps) > 1 and out["duration_min"] > 5:
        delta = caps[-1] - caps[0]
        hours = out["duration_min"] / 60.0
        out["capacity"] = {
            "start_pct": caps[0],
            "end_pct": caps[-1],
            "delta_pct": delta,
            "pct_per_hour": round(delta / hours, 2),
        }
        # 用中位放电电流反推电池标称容量：capacity 百分比变化 <-> 库仑
        dis = [r["cur_ma"] for r in rows if r["cur_ma"] is not None
               and (r["status"] or "").lower().startswith("discharg")]
        if dis and delta < 0:
            med = statistics.median(dis)
            implied_mah = abs(med) * hours / (abs(delta) / 100.0)
            out["capacity"]["implied_battery_mah"] = round(implied_mah)

    if len(rows) > 20:
        for key, label in (("bl", "by_backlight"), ("ap", "by_ap")):
            buckets = {}
            for r in rows:
                if r["cur_ma"] is None or r[key] is None:
                    continue
                if not (r["status"] or "").lower().startswith("discharg"):
                    continue
                buckets.setdefault(int(r[key]), []).append(abs(r["cur_ma"]))
            out[label] = {
                str(k): {"samples": len(v), "median_ma": round(statistics.median(v), 1)}
                for k, v in sorted(buckets.items())
            }

    return out


def summarize_groups(path, column="phase"):
    """按某列分组对比（例如 A/B 实验的 phase），并算 *_ticks 列折成 CPU 百分比。"""
    with open(path, newline="", encoding="utf-8", errors="replace") as fh:
        rows = [r for r in csv.DictReader(fh)]
    if not rows or column not in rows[0]:
        raise SystemExit(f"{path} 里没有 {column} 列")

    groups = {}
    for r in rows:
        groups.setdefault(r[column], []).append(r)

    print(f"按 {column} 分组，共 {len(rows)} 条")
    for name, group in groups.items():
        cur = [float(r["current_ua"]) / 1000.0 for r in group
               if r.get("current_ua") not in (None, "")]
        if not cur:
            cur = [float(r["cur"]) / 1000.0 for r in group
                   if r.get("cur") not in (None, "")]
        t0, t1 = int(group[0]["epoch"]), int(group[-1]["epoch"])
        span = max(t1 - t0, 1)
        line = f"  [{name}] {len(group)} 条，{t1 - t0}s"
        if cur:
            line += (f"，电流 中位 {statistics.median(cur):.1f}mA"
                     f"（{min(cur):.0f}~{max(cur):.0f}）")
        for key in group[0]:
            if not key.endswith("_ticks"):
                continue
            vals = [int(r[key]) for r in group if r.get(key) not in (None, "")]
            if len(vals) > 1:
                # HZ=100 时，每秒 1 tick = 单核 1%
                line += f"，{key[:-6]}={(vals[-1] - vals[0]) / span:.1f}%单核"
        if "backlight" in group[0]:
            line += "，背光=" + ",".join(sorted({r["backlight"] for r in group}))
        print(line)
    return 0


def summarize_autosuspend(path, start_cap=None, end_cap=None, battery_mah=None):
    """分析 e5-autosuspend 的日志：睡眠时长、占空比，并按电量变化反推平均电流。"""
    import re
    from datetime import datetime as _dt

    lines = [l for l in open(path, encoding="utf-8", errors="replace").read().splitlines() if l.strip()]
    susp, resumed, blocked = [], [], []
    for line in lines:
        if len(line) < 19:
            continue
        try:
            ts = _dt.strptime(line[:19], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        if "suspend: arming" in line:
            susp.append(ts)
        elif "resumed after" in line:
            m = re.search(r"after (\d+)s", line)
            if m:
                resumed.append((ts, int(m.group(1))))
        elif "blocked:" in line:
            blocked.append((ts, line.split("blocked:", 1)[1].strip()))

    total_sleep = sum(s for _, s in resumed)
    print(f"日志 {len(lines)} 行：挂起尝试 {len(susp)} 次，成功返回 {len(resumed)} 次")
    if resumed:
        first = susp[0] if susp else resumed[0][0]
        span = (resumed[-1][0] - first).total_seconds()
        if span > 0:
            print(f"覆盖 {span / 3600:.1f} 小时，累计睡眠 {total_sleep / 3600:.1f} 小时"
                  f"（占空比 {100 * total_sleep / span:.0f}%）")
        durations = [s for _, s in resumed]
        short = [s for s in durations if s < 540]
        print(f"单次睡眠：中位 {statistics.median(durations):.0f}s，"
              f"最短 {min(durations)}s，最长 {max(durations)}s，短于 540s 的 {len(short)} 次")
        if blocked:
            counts = {}
            for _, reason in blocked:
                counts[reason] = counts.get(reason, 0) + 1
            top = sorted(counts.items(), key=lambda kv: -kv[1])[:5]
            print("被挡下的原因：" + "，".join(f"{k}×{v}" for k, v in top))

        if start_cap is not None and end_cap is not None and span > 0:
            drop = start_cap - end_cap
            per_hour = drop / (span / 3600)
            print(f"电量 {start_cap}% → {end_cap}%：掉 {drop}%，即 {per_hour:.2f}%/小时")
            if battery_mah:
                avg_ma = per_hour / 100 * battery_mah
                print(f"按 {battery_mah}mAh 电池折算，全程平均 {avg_ma:.0f}mA")
                awake = total_sleep and (span - total_sleep)
                if awake:
                    # 设睡眠电流 x，醒着 86mA：avg = duty*x + (1-duty)*86
                    duty = total_sleep / span
                    x = (avg_ma - (1 - duty) * 86) / duty
                    print(f"推算睡眠电流约 {x:.0f}mA（醒着按 86mA 计，睡眠占空比 {100 * duty:.0f}%）")
    return 0


def _fix_console():
    """终端里用本地代码页（Windows 中文版是 GBK）才不乱码；
    输出被重定向/管道接走时，调用方通常按 UTF-8 解码，就发 UTF-8。"""
    try:
        enc = locale.getpreferredencoding(False) if sys.stdout.isatty() else "utf-8"
        sys.stdout.reconfigure(encoding=enc, errors="replace")
    except Exception:
        pass


def main(argv):
    _fix_console()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv", nargs="?", help="power-log.csv 路径")
    ap.add_argument("--json", help="把结果另存为 JSON")
    ap.add_argument("--group", metavar="列名",
                    help="按这列分组对比（A/B 实验用，例如 --group phase）")
    ap.add_argument("--suspend-log", metavar="文件",
                    help="分析 e5-autosuspend 日志：睡眠时长、占空比、按电量反推平均电流")
    ap.add_argument("--start-cap", type=float, help="配合 --suspend-log：起始电量百分比")
    ap.add_argument("--end-cap", type=float, help="配合 --suspend-log：结束电量百分比")
    ap.add_argument("--battery-mah", type=float, default=3082,
                    help="配合 --suspend-log：电池容量 mAh（默认 3082，本机实测值）")
    args = ap.parse_args(argv)

    if args.suspend_log:
        return summarize_autosuspend(args.suspend_log, args.start_cap, args.end_cap, args.battery_mah)

    if args.group:
        return summarize_groups(args.csv, args.group)

    rows = load(args.csv)
    if not rows:
        print("没有可解析的采样行", file=sys.stderr)
        return 2

    result = summarize(rows)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(result, fh, ensure_ascii=False, indent=2)

    r = result
    print(f"采样 {r['samples']} 条，{r['first']} → {r['last']}（{r['duration_min']} 分钟）")
    if r["current_unit_scaled"]:
        print("电流按 uA 处理（已除以 1000 转 mA）")
    for name, entry in r["by_status"].items():
        line = f"  [{name}] {entry['samples']} 条"
        if "current_ma" in entry:
            c = entry["current_ma"]
            line += f"，电流 中位 {c['median']}mA（{c['min']}~{c['max']}）"
        if "power_mw" in entry:
            line += f"，功率 {entry['power_mw']['median']}mW"
        if "voltage_v" in entry:
            line += f"，电压 {entry['voltage_v']['median']}V"
        print(line)

    if r["capacity"]:
        c = r["capacity"]
        print(f"电量 {c['start_pct']}% → {c['end_pct']}%（{c['pct_per_hour']}%/小时）")
        if "implied_battery_mah" in c:
            print(f"按电流与掉电速率反推电池约 {c['implied_battery_mah']}mAh")
    for label, title in (("by_backlight", "按背光"), ("by_ap", "按热点")):
        if r[label]:
            parts = [f"{k}={v['median_ma']}mA/{v['samples']}条" for k, v in r[label].items()]
            print(f"{title}（放电中位电流）：" + "，".join(parts))
    for gap in r["gaps"]:
        print(f"采样空档 {gap['from']} → {gap['to']}（{gap['seconds']}s，可能是设备重启）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

#!/usr/bin/env python3
"""检查每个插件是否满足与宿主交互的"契约"，防止一边修好一边漏改。

用法：
    python tools/check-plugin-contract.py [插件目录根，默认 plugins]

检查项（对长时间运行、会自己藏宿主 UI 的插件：e5-emulator / e5-dos / e5-pal / bili）：
  1. 有 pagehide/beforeunload 清理（退出时把宿主 UI 还回去）
  2. 有 e5.keepAwake
  3. 有 hostNoSleep（熄屏/锁屏保护）
  4. 电源键是双击确认（出现 lastPowerPressAt）
  5. manifest.json 的 version 与页面里 APP_VER（若有）一致
  6. 页面以 </html> 结束（防止大文件被截断）
  7. 藏宿主 UI 的样式包含 #bar（状态栏），否则顶部 28px 的触摸会落到宿主
退出码非 0 表示有硬性失败。
"""
import json
import re
import sys
from pathlib import Path

LONG_RUNNING = {"e5-emulator", "e5-dos", "e5-pal", "bili"}


def check(plugin_dir: Path):
    problems, warns = [], []
    manifest_p = plugin_dir / "manifest.json"
    index_p = plugin_dir / "index.html"
    if not index_p.exists():
        return problems, warns
    html = index_p.read_text(encoding="utf-8", errors="replace")
    name = plugin_dir.name
    if not html.rstrip().endswith("</html>"):
        problems.append("页面没有以 </html> 结束（可能被截断）")
    if name in LONG_RUNNING:
        if "hostNoSleep" not in html:
            problems.append("缺少 hostNoSleep（宿主熄屏/锁屏保护）")
        if "lastPowerPressAt" not in html:
            problems.append("电源键没有双击确认（缺 lastPowerPressAt）")
        if "keepAwake" not in html:
            problems.append("缺少 e5.keepAwake")
        if not re.search(r"pagehide|beforeunload", html):
            problems.append("缺少 pagehide/beforeunload 清理")
        if "mobile-toolbar" in html and "#bar" not in html:
            problems.append("藏了宿主工具栏但没藏 #bar（顶部触摸会落到宿主）")
    if manifest_p.exists():
        try:
            ver = json.loads(manifest_p.read_text(encoding="utf-8"))["version"]
        except Exception as e:  # noqa: BLE001
            problems.append(f"manifest.json 读取失败: {e}")
            ver = None
        m = re.search(r"APP_VER\s*=\s*['\"]([^'\"]+)['\"]", html)
        if m and ver and m.group(1) != ver:
            problems.append(f"APP_VER={m.group(1)} 与 manifest.version={ver} 不一致")
        if ver and re.search(r'\"version\"\s*:\s*\"0\.0\.0\"', manifest_p.read_text(encoding='utf-8')):
            warns.append("版本号还是 0.0.0")
    return problems, warns


def main():
    root = Path(sys.argv[1] if len(sys.argv) > 1 else "plugins")
    failed = 0
    for d in sorted(p for p in root.iterdir() if p.is_dir()):
        problems, warns = check(d)
        if problems or warns:
            print(f"[{d.name}]")
            for x in problems:
                print(f"  FAIL  {x}")
            for x in warns:
                print(f"  warn  {x}")
            if problems:
                failed += 1
    if failed:
        print(f"\n{failed} 个插件不满足契约")
        return 1
    print("所有插件满足契约")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

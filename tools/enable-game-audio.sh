#!/bin/sh
# 给设备补上浏览器音频输出（gst1-plugins-base 提供 autoaudiosink）。
# 装完 WPE 浏览器才有音频输出；「复古游戏机」里那层静音兜底可以用 ?audio=1 关掉。
# 建议先 apk update 拉索引，再装这两个包：
#   apk update
#   apk add gst1-plugins-base gst1-plugins-good
# 装完需要重启信息屏的浏览器进程才会生效：
#   killall -TERM cog
set -e
echo "=== 更新索引 ==="
apk update
echo "=== 安装 ==="
apk add gst1-plugins-base gst1-plugins-good
echo "=== 确认 autoaudiosink ==="
gst-inspect-1.0 autoaudiosink 2>/dev/null | head -3 || echo "(没有 gst-inspect，看包是否装上)"
apk list --installed 2>/dev/null | grep -E "gst1-plugins-(base|good)"
echo "=== 重启信息屏浏览器 ==="
killall -TERM cog 2>/dev/null || true
echo done

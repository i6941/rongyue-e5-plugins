#!/bin/sh
# 一键安装「复古游戏机」插件到荣月 E5（OpenWrt / 展锐 UMS9621 / 320x480）。
#
# 手机用 USB 连电脑时，设备地址是 192.168.9.1。在电脑上执行：
#
#   ssh root@192.168.9.1 'wget -O- https://raw.githubusercontent.com/i6941/rongyue-e5-plugins/main/install.sh | sh'
#
# 可选参数：
#   --roms        连 19 个自制游戏一起装（许可允许再分发）
#   --no-restart  装完不重启信息屏
#   --remove      卸载：删插件、三个核心二进制和自制游戏
#
# 想装自己的 ROM：把文件放进设备的 /etc/e5-infoscreen/roms/ 即可，
# 扩展名决定用哪个内核：.nes 用 e5emu，.md 用 e5emu-genesis，.gba/.gb 用 e5emu-gba。
# 商业 ROM 请自行保管，不要转发。

set -e

BASE="${E5_BASE:-https://github.com/i6941/rongyue-e5-plugins/releases/latest/download}"
PLUGIN_ID=e5-emulator
PLUGIN_DIR="/etc/e5-infoscreen/plugins/$PLUGIN_ID"
ROM_DIR=/etc/e5-infoscreen/roms
CACHE_DIR=/tmp/run/e5-infoscreen/.cache/wpe/WebKitCache
WORK=/tmp/e5-install
CORES="e5emu e5emu-genesis e5emu-gba"

WITH_ROMS=0
RESTART=1
REMOVE=0

for arg in "$@"; do
    case "$arg" in
        --roms) WITH_ROMS=1 ;;
        --no-restart) RESTART=0 ;;
        --remove) REMOVE=1 ;;
        -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
        *) echo "不认识的参数：$arg（用 --help 看用法）" >&2; exit 1 ;;
    esac
done

say() { echo "== $* =="; }
die() { echo "出错：$*" >&2; exit 1; }

if [ ! -d /etc/e5-infoscreen ]; then
    die "这台机器不像荣月 E5（没有 /etc/e5-infoscreen）"
fi

if [ "$REMOVE" = 1 ]; then
    say "卸载"
    /etc/init.d/e5-infoscreen stop >/dev/null 2>&1 || true
    for c in $CORES; do
        pkill -f "/usr/bin/$c" 2>/dev/null || true
        rm -f "/usr/bin/$c"
    done
    rm -rf "$PLUGIN_DIR"
    rm -rf "$CACHE_DIR"
    say "已卸载，剩下自己的 ROM 保留在 $ROM_DIR"
    exit 0
fi

mkdir -p "$WORK"
cd "$WORK"

fetch() {
    # fetch <url> <输出文件>
    if wget -q -O "$2" "$1"; then
        return 0
    fi
    if command -v curl >/dev/null 2>&1 && curl -fsSL -o "$2" "$1"; then
        return 0
    fi
    return 1
}

say "下载核心与插件"
fetch "$BASE/e5-emulator.tar.gz" plugin.tar.gz || die "下载插件包失败：$BASE/e5-emulator.tar.gz（网络不通？）"
for c in $CORES; do
    fetch "$BASE/$c" "$c" || die "下载 $c 失败"
done
if fetch "$BASE/sha256sums.txt" sha256sums.txt; then
    say "校验完整性"
    if command -v sha256sum >/dev/null 2>&1; then
        for c in $CORES; do
            if grep -q " $c\$" sha256sums.txt; then
                grep " $c\$" sha256sums.txt | sha256sum -c - || die "$c 校验不通过"
            fi
        done
    fi
else
    echo "（没有校验文件，跳过完整性校验）"
fi

say "安装核心"
for c in $CORES; do
    cp -f "$c" "/usr/bin/$c"
    chmod 0755 "/usr/bin/$c"
    echo "  /usr/bin/$c"
done

say "安装插件"
rm -rf "$PLUGIN_DIR"
mkdir -p "$PLUGIN_DIR"
tar -xzf plugin.tar.gz -C "$PLUGIN_DIR"
if [ ! -f "$PLUGIN_DIR/index.html" ]; then
    die "插件包结构不对（缺 index.html）"
fi
echo "  $PLUGIN_DIR"

if [ "$WITH_ROMS" = 1 ]; then
    say "下载自制游戏"
    if fetch "$BASE/roms-homebrew.tar.gz" roms.tar.gz; then
        mkdir -p "$ROM_DIR"
        tar -xzf roms.tar.gz -C "$ROM_DIR"
        echo "  $(ls "$ROM_DIR" | wc -l) 个文件 -> $ROM_DIR"
    else
        echo "（自制游戏包下载失败，跳过）"
    fi
fi

say "清理页面缓存"
rm -rf "$CACHE_DIR"

if [ "$RESTART" = 1 ]; then
    say "重启信息屏"
    /etc/init.d/e5-infoscreen restart >/dev/null 2>&1 || killall -TERM cog >/dev/null 2>&1 || true
    sleep 2
fi

say "自检"
for c in $CORES; do
    if [ -x "/usr/bin/$c" ]; then
        echo "  $c 已安装"
    else
        echo "  $c 缺失"
    fi
done
nes="$(ls "$ROM_DIR"/*.nes 2>/dev/null | head -1)"
if [ -n "$nes" ]; then
    for c in e5emu e5emu-genesis e5emu-gba; do
        [ -x "/usr/bin/$c" ] || continue
        printf "  %s: " "$c"
        "/usr/bin/$c" --selftest "$nes" 60 2>/dev/null | tail -1 || true
    done
else
    echo "  （没找到 .nes 测试文件，跳过核心自检）"
fi

say "完成"
echo "在信息屏里打开「复古游戏机」，选一个游戏就能玩。"
echo "自己的 ROM 放 $ROM_DIR，扩展名决定内核：.nes / .md / .gba"

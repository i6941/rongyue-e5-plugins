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
#   --official    用官方商店索引（https://enceka.github.io/...）而不是我们这份
#
# 想装自己的 ROM：把文件放进设备的 /etc/e5-infoscreen/roms/ 即可，
# 扩展名决定用哪个内核：.nes 用 e5emu，.md 用 e5emu-genesis，.gba/.gb 用 e5emu-gba。
# 商业 ROM 请自行保管，不要转发。

set -e

REPO="${E5_REPO:-i6941/rongyue-e5-plugins}"
RELEASE="${E5_RELEASE:-https://github.com/$REPO/releases/latest/download}"
STORE="${E5_STORE:-https://i6941.github.io/$REPO/index.json}"
OFFICIAL_STORE="https://enceka.github.io/infoscreen-plugins/index.json"
PLUGIN_ID=e5-emulator
PLUGIN_DIR="/etc/e5-infoscreen/plugins/$PLUGIN_ID"
ROM_DIR=/etc/e5-infoscreen/roms
CACHE_DIR=/tmp/run/e5-infoscreen/.cache/wpe/WebKitCache
WORK=/tmp/e5-install
PLUGIN_TOOL=/usr/libexec/e5-infoscreen/plugin
CORES="e5emu e5emu-genesis e5emu-gba"

WITH_ROMS=0
RESTART=1
REMOVE=0
USE_OFFICIAL=0

for arg in "$@"; do
    case "$arg" in
        --roms) WITH_ROMS=1 ;;
        --no-restart) RESTART=0 ;;
        --remove) REMOVE=1 ;;
        --official) USE_OFFICIAL=1 ;;
        -h|--help) sed -n '2,25p' "$0"; exit 0 ;;
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

say "下载核心"
for c in $CORES; do
    fetch "$RELEASE/$c" "$c" || die "下载 $c 失败：$RELEASE/$c（网络不通？）"
done
if fetch "$RELEASE/sha256sums.txt" sha256sums.txt; then
    if command -v sha256sum >/dev/null 2>&1; then
        for c in $CORES; do
            grep " $c\$" sha256sums.txt | sha256sum -c - || die "$c 校验不通过"
        done
    fi
else
    echo "（没有校验文件，跳过完整性校验）"
fi
for c in $CORES; do
    cp -f "$c" "/usr/bin/$c"
    chmod 0755 "/usr/bin/$c"
    echo "  /usr/bin/$c"
done

say "安装插件"
if [ -x "$PLUGIN_TOOL" ]; then
    # 设备自带的应用商店：把商店索引指到我们这份，再用它自己的安装命令
    if [ "$USE_OFFICIAL" = 1 ]; then
        STORE="$OFFICIAL_STORE"
    fi
    if uci -q get e5-infoscreen.main.store_url >/dev/null 2>&1; then
        uci set e5-infoscreen.main.store_url="$STORE"
    else
        uci add_list e5-infoscreen.main.store_url="$STORE" 2>/dev/null ||
            uci set e5-infoscreen.main.store_url="$STORE"
    fi
    uci commit e5-infoscreen
    echo "  商店索引 -> $STORE"
    if "$PLUGIN_TOOL" store >/dev/null 2>&1; then
        "$PLUGIN_TOOL" get "$PLUGIN_ID" || echo "  商店安装失败，改用直接解包"
    fi
fi
if [ ! -f "$PLUGIN_DIR/index.html" ]; then
    # 没有商店工具，或者商店安装失败：直接解包
    fetch "https://raw.githubusercontent.com/$REPO/main/dist/packages/$PLUGIN_ID-1.10.0.tar.gz" plugin.tar.gz ||
        die "下载插件包失败"
    rm -rf "$PLUGIN_DIR"
    mkdir -p "$PLUGIN_DIR"
    tar -xzf plugin.tar.gz -C "$PLUGIN_DIR"
fi
if [ ! -f "$PLUGIN_DIR/index.html" ]; then
    die "插件没装上（缺 index.html）"
fi
echo "  $PLUGIN_DIR"

if [ "$WITH_ROMS" = 1 ]; then
    say "下载自制游戏"
    if fetch "https://codeload.github.com/$REPO/tar.gz/refs/heads/main" repo.tar.gz; then
        tar -xzf repo.tar.gz -C "$WORK" 2>/dev/null || true
        d=$(ls -d "$WORK"/"$REPO"-* 2>/dev/null | head -1)
        if [ -n "$d" ] && [ -d "$d/roms" ]; then
            mkdir -p "$ROM_DIR"
            cp -f "$d"/roms/* "$ROM_DIR"/ 2>/dev/null || true
            echo "  $(ls "$ROM_DIR" | wc -l) 个文件 -> $ROM_DIR"
        fi
    else
        echo "（自制游戏下载失败，跳过）"
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

#!/bin/bash
# 编译《仙剑奇侠传》重制版（SDLPAL 原生引擎）为 E5 上的 e5emu-pal
#
# === 为什么必须锁 SDL 1.2 ===
# SDLPAL 官方在 2025 年把底层升到了 SDL3，但它的 libretro 移植目录仍然
# 保留 SDL 1.2 的私有内部头文件，pal_config.h 里明确写着：
#   #error "this libretro port must build with SDL 1.2, please checkout 3rd/SDL with v1.2.15"
# 所以 3rd/SDL 子模块必须签出到 v1.2.15，否则必编译失败。
#
# === 三个必须的补丁（脚本会自动检查并应用） ===
# 1. main() 改名：SDLPAL 和 e5emu 各有一个 main，静态链接报 duplicate symbol。
# 2. RefreshVideo 取帧源：必须读 gpScreen（8bpp 逻辑画布）并查调色板转 RGB565。
#    用 _surface 或 SDL_GetVideoSurface() 拿到的都不是游戏画面，推出去全黑。
# 3. _surface 惰性创建：PAL_VIDEO_ALLOCATE_SWSURFACE=1 时不走 DUMMY_SetVideoMode，
#    _surface 恒为 NULL，直接解引用会在 aarch64 上 SIGSEGV。
#
# === 前端 (native/e5emu.c) 里配套的两处修复 ===
# - 处理 RETRO_ENVIRONMENT_SET_FRAME_TIME_CALLBACK：SDLPAL 靠这个回调推进
#   虚拟时钟；不实现的话 SDL_GetTicksReal() 恒为 0，游戏时间冻结在首帧。
# - 处理 RETRO_ENVIRONMENT_SET_KEYBOARD_CALLBACK：SDLPAL 只认键盘事件，
#   把手柄位图翻译成 SDLK_* 发过去。
# - ws_recv_exact()：WebSocket 帧必须读满，否则按键会错位断线。
#
# 用法（WSL / Ubuntu）：
#   bash native/build-sdlpal.sh
#
# 产物：native/e5emu-pal（aarch64 全静态）

set -e

BUILD_ROOT="${BUILD_ROOT:-$HOME/e5-kernel-build}"
SRC="$BUILD_ROOT/sdlpal-test"
WORKDIR="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$WORKDIR/native/e5emu-pal"

CC=aarch64-linux-gnu-gcc
CXX=aarch64-linux-gnu-g++
LIBRETRO_INC="${LIBRETRO_INC:-$HOME/build/FBNeo/src/burner/libretro/libretro-common/include}"
MARGS="$WORKDIR/native/libretro-mgba/src/platform/libretro"

if [ ! -d "$SRC" ]; then
    echo "找不到 SDLPAL 源码目录：$SRC" >&2
    echo "请先：" >&2
    echo "  git clone --depth 1 https://github.com/sdlpal/sdlpal.git $SRC" >&2
    echo "  cd $SRC && git submodule update --init 3rd/SDL" >&2
    exit 1
fi
if [ ! -f "$LIBRETRO_INC/libretro.h" ]; then
    echo "找不到 libretro.h：$LIBRETRO_INC（可用 LIBRETRO_INC= 覆盖）" >&2
    exit 1
fi

echo "=== 1. 确保 SDL 子模块在 v1.2.15 ==="
cd "$SRC/3rd/SDL"
git reset --hard -q
git clean -ffdxq
git checkout -f v1.2.15
echo "SDL: $(git log -1 --oneline)"

echo "=== 2. 检查并应用必要补丁 ==="
cd "$SRC"
if ! grep -q 'sdlpal_main_entry' main.c; then
    echo "  [1/3] main -> sdlpal_main_entry"
    python3 - << 'PYEOF'
p = 'main.c'
c = open(p).read()
c = c.replace("""int
main(
   int      argc,
   char    *argv[]
)""", """int
sdlpal_main_entry(
   int      argc,
   char    *argv[]
)""", 1)
open(p, 'w').write(c)
p2 = 'libretro/libretro.c'
c2 = open(p2).read()
c2 = c2.replace("int main(int argc, char *argv[]);", "int sdlpal_main_entry(int argc, char *argv[]);")
c2 = c2.replace("    main(1, argv);", "    sdlpal_main_entry(1, argv);")
open(p2, 'w').write(c2)
PYEOF
fi

python3 - << 'PYEOF'
import re
p = 'libretro/sdl-libretro/video.c'
c = open(p).read()

if 'gpScreen' not in c or 'g_xfer' not in c:
    print("  [2/3] RefreshVideo -> gpScreen + 调色板转 RGB565")
    start = c.index('void SDL_libretro_RefreshVideo(retro_video_refresh_t video_cb)')
    # 找到函数结束（下一个顶层 } 后跟空行或文件尾）
    depth = 0
    i = c.index('{', start)
    j = i
    while True:
        if c[j] == '{': depth += 1
        elif c[j] == '}':
            depth -= 1
            if depth == 0:
                break
        j += 1
    new = '''/* PAL 真正绘制的是 gpScreen（8bpp 逻辑画布），所有绘图都先落在这里；
   gpScreenReal 是 SDL_SetVideoMode 拿到的 8bpp 显示面，只在中转时被写。
   两者都不能直接当 16bpp 推给 libretro：必须查调色板逐像素转 RGB565，
   否则推出去的是索引值，看起来就是全黑。

   曾经的错误做法与后果：
   - 直接解引用 _surface          -> aarch64 上空指针 SIGSEGV
   - 惰性创建 _surface            -> 不崩了，但推的是从未写过的空缓冲（全黑）
   - 用 SDL_GetVideoSurface()     -> 那不是游戏画面（全黑） */
extern SDL_Surface *gpScreen;
extern SDL_Surface *gpScreenReal;

static uint16_t *g_xfer = NULL;
static size_t    g_xfer_cap = 0;

void SDL_libretro_RefreshVideo(retro_video_refresh_t video_cb)
{
	SDL_Surface *surf = (gpScreen && gpScreen->pixels) ? gpScreen
	                  : ((gpScreenReal && gpScreenReal->pixels) ? gpScreenReal : NULL);
	if (surf == NULL || surf->pixels == NULL)
		return;

	const int w = surf->w, h = surf->h;
	if (w <= 0 || h <= 0) return;

	size_t need = (size_t)w * h;
	if (need > g_xfer_cap) {
		uint16_t *p = realloc(g_xfer, need * sizeof(uint16_t));
		if (p == NULL) return;
		g_xfer = p;
		g_xfer_cap = need;
	}

	if (surf->format->BitsPerPixel == 8) {
		SDL_Palette *pal = surf->format->palette;
		if (pal == NULL || pal->colors == NULL) return;
		SDL_Color *colors = pal->colors;
		int ncolors = pal->ncolors;
		for (int y = 0; y < h; y++) {
			const uint8_t *src = (const uint8_t *)surf->pixels + (size_t)y * surf->pitch;
			uint16_t *dst = g_xfer + (size_t)y * w;
			for (int x = 0; x < w; x++) {
				unsigned idx = src[x];
				if ((int)idx >= ncolors) idx = 0;
				dst[x] = (uint16_t)(((colors[idx].r >> 3) << 11) |
				                    ((colors[idx].g >> 2) << 5) |
				                    (colors[idx].b >> 3));
			}
		}
	} else if (surf->format->BitsPerPixel == 32) {
		for (int y = 0; y < h; y++) {
			const uint32_t *src = (const uint32_t *)((const uint8_t *)surf->pixels + (size_t)y * surf->pitch);
			uint16_t *dst = g_xfer + (size_t)y * w;
			for (int x = 0; x < w; x++) {
				uint32_t v = src[x];
				dst[x] = (uint16_t)((((v >> 19) & 0x1f) << 11) |
				                    (((v >> 10) & 0x3f) << 5) |
				                    ((v >> 3) & 0x1f));
			}
		}
	} else if (surf->format->BitsPerPixel == 16) {
		for (int y = 0; y < h; y++) {
			const uint16_t *src = (const uint16_t *)((const uint8_t *)surf->pixels + (size_t)y * surf->pitch);
			memcpy(g_xfer + (size_t)y * w, src, (size_t)w * sizeof(uint16_t));
		}
	} else {
		return;
	}

	video_cb(g_xfer, w, h, (size_t)w * sizeof(uint16_t));
}'''
    c = c[:start] + new + c[j+1:]
    open(p, 'w').write(c)
else:
    print("  [2/3] 已应用，跳过")

# 3. _surface 不再是取帧源，但 DUMMY_UpdateRects 仍会用到它，保持惰性创建兜底
if '_surface == NULL' not in c:
    print("  [3/3] _surface 兜底提示：当前实现已不使用 _surface，无需补丁")
else:
    print("  [3/3] _surface 兜底已存在")
PYEOF

echo "=== 3. 交叉编译 sdlpal_libretro.a ==="
rm -rf build-aarch64
mkdir -p build-aarch64
cd build-aarch64
cmake ../libretro \
  -DCMAKE_SYSTEM_NAME=Linux \
  -DCMAKE_SYSTEM_PROCESSOR=aarch64 \
  -DCMAKE_C_COMPILER="$CC" \
  -DCMAKE_CXX_COMPILER="$CXX" \
  -DLIBRETRO_STATIC=ON > /dev/null
make -j"$(nproc)" 2>&1 | tail -3

echo "=== 4. 链接 e5emu 前端 ==="
# 必须用 GNU sysroot：SDLPAL 是 glibc 编的，和 zig 的 musl libc++ ABI 不兼容
"$CC" -O2 -I "$LIBRETRO_INC" -I "$MARGS" -c "$WORKDIR/native/e5emu.c" -o /tmp/e5emu_pal_main.o
"$CXX" -O2 -static -static-libstdc++ -static-libgcc -o "$OUT" \
  /tmp/e5emu_pal_main.o ./sdlpal_libretro.a -lpthread -lm
aarch64-linux-gnu-strip --strip-all "$OUT"

echo "=== 完成 ==="
ls -lh "$OUT"
file "$OUT"

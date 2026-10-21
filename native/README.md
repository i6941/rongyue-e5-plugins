# Native emulator frontend for the E5

The browser route (EmulatorJS/WASM) hits three hard limits on this phone:
a 16-26 second start while a JavaScript LZMA decoder unpacks a 4.5 MB
WebAssembly core, a WebAssembly trap that kills the frame loop a few
seconds into a game, and a constant fight with the browser's single UI
thread while the game runs. `e5emu` is the native replacement: a small
libretro frontend with the core linked in statically, built for
`aarch64-linux-musl` with Zig.

## Measured on the device

Unisoc UMS9621, OpenWrt 25.12.5, kernel 6.18.54-e5, 320x480 screen.

```
$ /tmp/e5emu --selftest /etc/e5-infoscreen/roms/fc-contra.nes 600
E5EMU core=FCEUmm version=(SVN)
E5EMU geometry=256x240 fps=60.100 sample_rate=48000 pixfmt=2
E5EMU rom=/etc/e5-infoscreen/roms/fc-contra.nes bytes=393232
E5EMU frames=600 elapsed_ms=10088.2 fps=59.48 core_frames=600 size=256x240 checksum=5352
```

600 requested frames, 600 produced by the core, 59.48 FPS sustained.
Starting the binary is immediate; there is no compile or unpack step.
Compare with the browser route on the same device: 16-26 s before the
first frame and a stall 2-3 s into the game.

## Build

Requires Zig (tested with 0.17.0) and a checkout of
[libretro-fceumm](https://github.com/libretro/libretro-fceumm).

```sh
zig cc -target aarch64-linux-musl -O2 -static \
  -D__LIBRETRO__ -DPATH_MAX=1024 -DFCEU_VERSION_NUMERIC=9900 \
  -DFRONTEND_SUPPORTS_RGB565 \
  -Icore/src/drivers/libretro -Icore/src/drivers/libretro/libretro-common/include \
  -Icore/src -Icore/src/input -Icore/src/boards \
  e5emu.c <sources from Makefile.common> -o e5emu
```

`Makefile.common` in the core repository lists the exact source set;
include `src/boards/*.c` and `src/input/*.c` as well. The result is a
single static binary of about 8 MB.

## Status

Stage 1 (done): headless self-test that proves the core runs at full
speed on the device.

Stage 2 (not started): a frame transport so the plugin page can show the
game - a WebSocket server that pushes 256x240 RGB565 frames and accepts
button bitmasks, started on demand when a game is opened and exiting
after a few idle minutes. The plugin then becomes a thin canvas client
and keeps its key configuration, save states and layout.

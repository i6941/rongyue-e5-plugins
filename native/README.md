# Native emulator frontend for the E5

The browser route (EmulatorJS/WASM) hits hard limits on this phone: a
16-26 second start while a JavaScript LZMA decoder unpacks a 4.5 MB
WebAssembly core, a WebAssembly trap that kills the frame loop a few
seconds into a game, and repeated launches exhausting the WebGL2 contexts
of the browser process. `e5emu` is the native replacement: a small
libretro frontend with the core linked in statically, built for
`aarch64-linux-musl` with Zig.

## Measured on the device

Unisoc UMS9621, OpenWrt 25.12.5, kernel 18.54-e5 (5.4?), 320x480 screen.

Headless benchmark:

```
$ /tmp/e5emu --selftest /etc/e5-infoscreen/roms/fc-contra.nes 600
E5EMU geometry=256x240 fps=60.100
E5EMU frames=600 elapsed_ms=10088.2 fps=59.48 core_frames=600
```

WebSocket frame server plus its test client, both on the device:

```
$ /tmp/e5emu --serve /etc/e5-infoscreen/roms/fc-contra.nes 9510 &
E5EMU listening 127.0.0.1:9510
E5EMU geometry=256x240 fps=60.100

$ python3 /tmp/test-ws.py 9510 120
handshake: HTTP/1.1 101 Switching Protocols
frame0: 256x240 pixels=122880 (expected 122880)
received 120 frames in 2.01s -> 59.6 fps
frames after input: 10 -> OK
```

Starting the binary is immediate; there is no unpack or compile step.
Compare with the browser route on the same device: 16-26 s before the
first frame and a stall 2-3 s into the game.

## Protocol

- The server listens on `127.0.0.1:9510` only (never on the LAN address).
- It runs the core only while a client is connected; disconnecting stops
  the loop, so the emulator is on demand rather than resident.
- Each binary WebSocket frame is `width u16le, height u16le` followed by
  `width*height` RGB565 pixels (122880 bytes for 256x240).
- The client sends a 4-byte little-endian button bitmask, using the
  libretro joypad ids (bit 0 = B, 2 = SELECT, 3 = START, 4-7 = d-pad,
  8 = A, 10 = L, 11 = R).

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

`Makefile.common` lists the exact source set; include `src/boards/*.c`
and `src/input/*.c` as well. The result is a single static binary of
about 8 MB.

## Status

- Stage 1 (done): headless self-test, 59.5 FPS sustained on the device.
- Stage 2 (done): WebSocket frame server and input, verified at 59.6 FPS
  with 256x240 RGB565 frames by `native/test-ws-client.py`.
- Stage 3 (next): a canvas client in the plugin that connects to the
  server, draws the RGB565 frames and sends the key bitmask, plus the
  start/stop wiring so the daemon is launched when a game is opened and
  exits after a few idle minutes. The plugin keeps its key
  configuration, save states and layout.

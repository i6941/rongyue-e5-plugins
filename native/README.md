# Native emulator frontend for the E5

The browser route (EmulatorJS/WASM) does not work on this phone: a 16-26
second start while a JavaScript LZMA decoder unpacks a 4.5 MB WebAssembly
core, a WebAssembly trap that kills the frame loop a few seconds into a
game, and repeated launches exhausting the WebGL2 contexts of the browser
process. `e5emu` is the native replacement: a small libretro frontend with
the core linked in statically, built for `aarch64-linux-musl` with Zig.

## Measured on the device

Unisoc UMS9621, OpenWrt 25.12.5, 320x480 screen.

Headless benchmark:

```
$ e5emu --selftest /etc/e5-infoscreen/roms/fc-contra.nes 600
E5EMU geometry=256x240 fps=60.100
E5EMU frames=600 elapsed_ms=10088.2 fps=59.48 core_frames=600
```

Frame server driven by `test-ws-client.py` on the device itself:

```
$ e5emu --serve /etc/e5-infoscreen/roms/fc-contra.nes 9510 --log /tmp/e5emu.log &
E5EMU listening 127.0.0.1:9510
E5EMU geometry=256x240 fps=60.100

$ python3 test-ws-client.py 9510 60
handshake: HTTP/1.1 101 Switching Protocols
frame0: 256x240 pixels=122880 (expected 122880)
received 60 frames in 1.00s -> 60.3 fps
frames after input: 10 -> OK
after save cmd: 10 -> OK

$ tail /tmp/e5emu.log
E5EMU buttons=0x0008
E5EMU state save ok /etc/e5-infoscreen/roms/fc-contra.st0 (13903 bytes)
E5EMU state load ok /etc/e5-infoscreen/roms/fc-contra.st0
E5EMU client disconnected, frames=121
```

Starting the binary is immediate; there is no unpack or compile step.

## Protocol

- Listens on `127.0.0.1:9510` only, never on the LAN address.
- Runs the core only while a client is connected; if nobody reconnects
  within 120 seconds after a client leaves, the process exits, so the
  emulator is on demand rather than resident.
- Each binary frame is `width u16le, height u16le` followed by
  `width*height` RGB565 pixels (122880 bytes for 256x240).
- Client to server, 4 bytes: little-endian libretro button bitmask
  (bit 0 = B, 2 = SELECT, 3 = START, 4-7 = d-pad, 8 = A, 10 = L, 11 = R).
- Client to server, 1 byte: command. 1 = save a state, 2 = load it,
  3 = flush the battery save, 4 = pause or resume.
- Client to server, 2 bytes: command and slot. Slots 1 to 3 are manual;
  slot 0 is the automatic one the emulator writes every 30 seconds, on exit
  and before it suspends, so a manual save is never overwritten.

## Saves

- `<rom>.srm`: the core's battery-backed save RAM, loaded at start and
  written back two seconds after it changes and when the client leaves.
- `<rom>.st0`: a serialized machine state (13 KB for a NES game), written
  by command 1 and read back by command 2.
- Both live next to the ROM, so they survive restarts and follow the ROM
  directory backup.

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

## Building and running it on a computer

The same source builds for the host, which is how the UI is developed
without the phone in hand:

```sh
zig cc -target x86_64-linux-musl -O2 -static ... e5emu.c <sources> -o e5emu-linux-x64
wsl -d Ubuntu -- bash -lc "cd /mnt/d/workspace/Rongyue-E5/native && \
  env -u http_proxy -u https_proxy setsid nohup ./e5emu-linux-x64 \
  --serve /mnt/d/workspace/Rongyue-E5/.notes/game-port/roms/fc-contra.nes 9510 \
  --log /tmp/e5emu-local.log >/dev/null 2>&1 &"
python tools/native-preview.py 18080 --real
```

Then open `http://127.0.0.1:18080/plugins/e5-emulator/index.html?preview=1&auto=0`.
The real core streams through the real page at 60 FPS; WSL2 forwards the
port to the Windows side. For the device itself, `tools/device-shot.py`
pulls /dev/fb0 and writes a PNG, so the phone screen can be looked at from
anywhere.

## Status

- Stage 1 (done): headless self-test, 59.5 FPS sustained.
- Stage 2 (done): WebSocket frame server and input, 60.3 FPS with
  256x240 RGB565 frames.
- Stage 3 (done): the plugin page is the client. `index.html` opens a
  canvas, decodes the frames into RGBA and sends the button bitmask built
  from its existing key map; `backend.uc` starts and stops the daemon
  with `start-stop-daemon` on demand. Verified locally with
  `tools/native-preview.py` (a fake frame server drawing colour bars) and
  on the device through the HTTP API: start, 60.3 FPS, `buttons=0x0008`
  reaching the core, state save and load, stop leaving no process behind.
- Only fceumm (NES) is linked in. MD and GBA games still take the old
  browser path, so linking genesis_plus_gx and mgba is the next step if
  those systems matter.


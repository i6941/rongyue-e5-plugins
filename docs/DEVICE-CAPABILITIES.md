# Device capabilities

What the E5's OpenWrt build actually offers, measured on the device with read-only
commands. This is the reference the plugins were written against.

## Platform

| Item | Measured value |
|---|---|
| SoC | Unisoc UMS9621 |
| Device tree model | `Unisoc UMS9621-base Board` (ubus reports `sprd,ums512-base`; the two disagree) |
| CPU | 8 cores, `CPU part 0xd05` (Cortex-A55), implementer 0x41 |
| CPU frequency | **not exposed** — no `cpd/cpu0/cpufreq`, no MHz line in `dmesg` |
| RAM | `MemTotal` ≈ 1.435 GiB, `MemAvailable` ≈ 931 MiB, no swap |
| Storage | `/dev/mmcblk0p71` 7.8 GB, `/tmp` tmpfs 729.8 MB |
| Kernel | `6.18.54-e5`, SMP |
| Userspace | OpenWrt 25.12.5, `armsr/armv8`, `aarch64_generic` |

## Display and GPU

| Item | Measured value |
|---|---|
| DRM nodes | `card0` (226,0), `card1` (226,1), `renderD128` (226,128) |
| `card0` driver | `sprd-drm-drv` — the display controller |
| `card1` driver | `panfrost` — Mali GPU |
| Panel | `card0-DSI-1`, connected, mode **320x480**, enabled |
| `/dev/fb0` | present, but it is `sprddrmfb` (the DRM fbdev emulation) at 320x480 32bpp — it shares the same DRM card as the compositor, so writing to it is forbidden |
| GL libraries | `libEGL.so`, `libGLESv1_CM.so`, `libGLESv2.so` (no `libGL`) |
| Compositor stack | `seatd` 0.9.1 (two instances: `-g video`, `-g root`) → `cage` 0.2.0 → `cog` 0.18.5 (`libwpewebkit` 2.50.1, `libWPEBackend-fdo` 1.0.1, `libmesa-panfrost` 25.2.4) |

`/dev/fb0` only ever shows the kernel text console. It is not a way to capture the
panel's composited output.

## Audio

- `/proc/asound/cards`: `0 [sprdphonesc2730]` (`sprdphone-sc2730`).
- `aplay -l` lists ten playback devices including `FE_ST_NORMAL_AP01`,
  `FE_ST_FAST`, `FE_ST_VOICE`, `FE_ST_FM`, `FE_ST_LOOP`, `FE_ST_A2DP_PCM`.
- Installed: `alsa-lib` 1.2.11, `alsa-utils`, `alsa-ucm-conf`, `gst1-mod-alsa` 1.26.4, `pactl`.
- **The web panel has no working audio sink** (`autoaudiosink not found`) — see
  `docs/EMULATORJS.md`.

## Input

| event | Device | Notes |
|---|---|---|
| event0 | `gpio-keys` | physical function keys (kbd) |
| event1 | `tlsc6x_touch` | touchscreen, registered as a **kbd** handler |
| event2 | `sc27xx:vibrator` | vibrator |
| event3 | `sprd-keypad` | **physical keypad** (kbd), `/devices/platform/soc/soc:aon/641b0000.keypad` |
| event4 | `sprdphone-sc2730 Headset Jack` | headset detection |
| event5 | `sprdphone-sc2730 Headset Keyboard` | headset inline controls |

There is no `evtest` binary on the device, and `/dev/input/by-path` does not exist.
Testing keyboard blocking/ghosting properly needs the real kernel event stream plus a
human pressing two keys at once — a browser-level test cannot tell you that.

## Packages

Installed and relevant: `cage` 0.2.0 (MIT), `cog` 0.18.5 (BSD-2), `libcogcore`,
`libwpewebkit` 2.50.1, `libmesa-panfrost` 25.2.4 (BSD-3), `libdrm` 2.4.123,
`libseat` 0.9.1, `libwayland` 1.23.0, `wayland-protocols` 1.45, `alsa-lib`,
`alsa-utils`, `alsa-ucm-conf`, `gst1-mod-alsa`, `uhttpd` 2026.06.16 (+ubus/ucode),
`apk-tools` 3.0.5.

**Not available**: `sdl2`, `retroarch`, any libretro core, `/usr/lib/libretro`,
`/usr/lib/libSDL*`. The emulator plugin therefore uses EmulatorJS in the panel's
WebKit view rather than a native RetroArch build.

## Package manager notes

`apk`'s `-X` flag means `--repository REPO`, **not** "exact match". Searching for a
package with `-X` treats the argument as a repository path, which is a silent mistake
worth knowing about.

Sources live in `/etc/apk/repositories.d/distfeeds.list` and `customfeeds.list` —
there is no `/etc/apk/repositories`. Among the eight feeds is
`.../packages/aarch64_generic/video/packages.adb`, which is where `cage`, `cog`,
`mesa` and `wpewebkit` come from.

The package index cache is empty, so `apk search` prints
`opening from cache ... No such file or directory` and returns nothing until `apk
update` has run. That needs network access and writes to the cache, so it is not
something the plugins do on their own.


## Media playback on this device

Measured while building the `bili` plugin.

| Item | Result |
|---|---|
| H.264 hardware decode | **no** — `h264_v4l2m2m` reports "Could not find a valid device", so ffmpeg cannot decode video in hardware. The `bili` plugin ships its own software decoder (`native/e5play.c`, OpenH264) and pushes RGB565 frames over WebSocket |
| 1280×720 software decode | works, ~91 fps on a 400-frame test, so 720P is comfortable |
| AAC decode | ffmpeg has the native `aac` decoder `ffmpeg -i x.mp4 -vn -f s16le -ac 2 -ar 48000 -` |
| Audio output | PulseAudio 35, sink `speaker` (s16le 2ch 48000Hz), `paplay` present; default volume 5/16 (-28.9 dB), change with `/usr/libexec/e5-volume set N` |
| Audio verification | `parec --device=speaker.monitor` records the sink; a normal playback peaks around 900-1000 (s16le full scale 32767) |
| Bilibili 720P | `platform=pc&qn=80&fnval=0&fourk=1` returns `quality: 64` even without login, as a progressive MP4 (`durl`), so no DASH demuxer is needed |
| `qrencode` | installed, but **built without PNG output** ("PNG output is disabled at compile time") and there is no `base64` command; QR codes are drawn in the page with a JS encoder instead |

## WPE runtime capabilities

Probed with the `wpe-capability` plugin and the standalone capability page:

| Capability | Result |
|---|---|
| `WebAssembly.instantiate(bytes)` | available — the `bytes` path works; `instantiateStreaming` does not, because `uhttpd` has no `application/wasm` MIME type |
| WebGL2 | available, renderer `WebGL 2.0 (OpenGL ES 3.0 Chromium)` |
| WebGL1 | available, renderer `WebGL 1.0 (OpenGL ES 2.0 Chromium)` |
| WebAudio `resume` | resolves, but the context stays suspended (no audio sink) |
| `crossOriginIsolated` | `false` — expected, single-threaded build |
| `SharedArrayBuffer` | unavailable — expected, single-threaded build |

WebGL2 and WebGL1 are probed on **separate canvases**: a canvas's context type cannot
be switched after creation, so one canvas cannot stand in for both APIs.

## Still unconfirmed

1. CPU frequency — not exposed by the kernel.
2. Keyboard blocking and ghosting — needs kernel-level events plus a real human.
3. Whether the upstream OpenWrt feed carries `retroarch` or `sdl2` — needs `apk update`
   with network access.

# E5 Infographics Plugins

Plugins for the **Rongyue E5** (`荣悦 E5`) phone running **OpenWrt 25.12.5** on Unisoc
UMS9621 hardware. The device boots a `cage`/`cog` (Wayland + WPE WebKit) compositor that
renders the on-screen information panel; these plugins are loaded by the host
`e5-infoscreen` service from `/etc/e5-infoscreen/plugins/<id>/`.

Everything here is plain HTML + JavaScript for the frontend and
[ucode](https://openwrt.org/docs/guide-user/developer/ucode) for the backend, matching
what the device's runtime actually supports.

## Plugins

| Plugin | What it does |
|---|---|
| `e5-emulator` | Retro game console. Runs NES / Game Boy / GBA titles through EmulatorJS (WebAssembly) inside the panel's WebKit view. |
| `e5-keepalive` | Keeps a giffgaff SIM alive on a schedule and pushes notifications through PushPlus. |
| `nikki-control` | Local-only control panel for the Nikki proxy service: pick a node, watch status. Never returns credentials. |
| `wifi-control` | Scans for Wi-Fi networks and switches the USB tether uplink, with automatic rollback if the join fails. |
| `wpe-capability` | Reports what the device's WPE runtime can actually do (WebAssembly, WebGL1/2, WebAudio). |

## Quick start

```sh
# copy a plugin onto the device (over the USB network interface)
scp -r plugins/e5-emulator root@192.168.9.1:/etc/e5-infoscreen/plugins/

# the panel caches pages aggressively; clear it or you will see the old build
rm -rf /tmp/run/e5-infoscreen/.cache/wpe/WebKitCache
```

Each plugin directory is self-contained: `index.html` (UI), `backend.uc` (ucode API),
`manifest.json` (host plugin descriptor).

## The emulator plugin

The panel's WebKit build has no audio output (`GStreamer element autoaudiosink not
found`), which makes the Emscripten audio context fail with `NotAllowedError` and the
emulator loop stall at frame zero — a grey screen, 0 FPS, unresponsive buttons. The
plugin works around this by replacing `window.AudioContext` with a silent stub. Pass
`?audio=1` to keep real audio if your build has working output.

Other platform quirks this plugin handles, all of them found on this hardware:

- The emulator runtime listens for keys on its own container, so the canvas must be
  focused before input reaches the game.
- The host consumes the arrow keys before the plugin sees them, so menus are driven
  through `e5.onKey` rather than native focus navigation.
- `requestAnimationFrame` does not fire in a hidden page; a `setTimeout` fallback keeps
  the frame counter ticking.
- Frame rate is read from the core's own frame counter (`getFrameNum`), not from the
  browser's animation frame rate.

Measured on the E5 itself: **FC 60 FPS, MD 59 FPS, GBA 60 FPS** (60 is the panel's
refresh cap).

### Games

`roms/` ships with **19 homebrew titles** whose licences explicitly permit
redistribution — GPL-2.0/3.0, MIT, Zlib, CC-BY-4.0, FSFAP and 0BSD. Every file lists
its author, licence, upstream source repository and SHA-256 in
[`roms/manifest.json`](roms/manifest.json), with a per-title breakdown in
[`docs/ROMS-LICENSES.md`](docs/ROMS-LICENSES.md). No commercial ROMs are included.

## Tests

```sh
python -m unittest discover -s tests -p 'test_*.py'
```

The suite stubs the Unix-only `fcntl` module so it runs on any platform. Tests that
need real device behaviour (file locking against a live `uci`, for example) skip
themselves and are meant to run on the E5 itself.

## Tools

| Tool | Purpose |
|---|---|
| `tools/build-rom-manifest.py` | Regenerates `roms/manifest.json` with each ROM's SHA-256. |
| `tools/build-rom-docs.py` | Regenerates `docs/ROMS-LICENSES.md` and `docs/THIRD-PARTY.md`. |
| `tools/enable-game-audio.sh` | Installs the GStreamer packages that give the panel a working audio sink. |
| `tools/device-proxy.py` | Forwards the device's loopback panel port to the desktop for debugging. |
| `tools/preview-infoscreen.py` | SSH tunnel for previewing the real panel UI in a desktop browser. |
| `tools/restore-e5-apps.py` | Restores the installed apps on the device after a firmware change. |

The three SSH-based tools read the device password at runtime from
`.secrets/openwrt-access.json` and the host key from `.secrets/openwrt-known-hosts`.
Neither file is in this repository — create your own before using them:

```json
{ "adminPassword": "the-password-you-set-on-the-device" }
```

The device address defaults to `192.168.9.1` (the USB network interface) and can be
overridden with the `E5_HOST` environment variable. Link-local IPv6 addresses are
derived from the device's MAC address, so they are deliberately not hardcoded here.

## Licence

GPL-3.0-or-later — required because the bundled EmulatorJS runtime and several of its
cores are GPL. See [`LICENSE`](LICENSE) and [`docs/THIRD-PARTY.md`](docs/THIRD-PARTY.md)
for the full attribution list.

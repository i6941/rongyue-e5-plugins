# EmulatorJS on the E5

Notes from running EmulatorJS 4.2.3 inside the E5's WPE WebKit view. Everything here
was measured on the device, not inferred.

## Files and where they come from

| File | Source | Licence |
|---|---|---|
| `ejs/data/loader.js`, `emulator.min.js`, `emulator.min.css` | `cdn.emulatorjs.org/stable/data/` | GPL-3.0 (`@emulatorjs/emulatorjs`) |
| `ejs/data/cores/<core>-wasm.data` | `cdn.emulatorjs.org/stable/data/cores/` | per core — see `docs/THIRD-PARTY.md` |
| `ejs/data/compression/extract7z.js`, `extractzip.js`, `libunrar.js/.wasm` | same `compression/` directory | same runtime |
| `ejs/data/localization/zh-CN.json` | npm `@emulatorjs/emulatorjs` `data/localization/` | same runtime |

The core `.data` files are 7z archives (magic `37 7a bc af`). The runtime unpacks
them in a **Worker** with `compression/extract7z.js`, builds `core.js`, and injects it
into the page as a Blob.

## `EJS_player` is a CSS selector, not an iframe

This is the one detail that blocks a naive integration. The runtime constructor uses
its first argument directly as a selector:

```js
setElements(t) {
    const e = this.createElement("div"),
          i = document.querySelector(t);   // t IS the selector
    i.innerHTML = "";
    ...
}
```

Passing `undefined` gives `querySelector(undefined)` → `null` → `Cannot set
properties of null (setting 'innerHTML')`. The upstream demo does:

```js
window.EJS_player = '#game';
```

## Working configuration

```js
window.EJS_player = '#ejs_game';        // container selector
window.EJS_core = 'fceumm';              // core name
window.EJS_gameUrl = '/roms/fc/croom.nes';
window.EJS_gameName = 'Concentration Room';
window.EJS_pathtodata = BASE + 'ejs/data/';
window.EJS_biosUrl = '';
window.EJS_startOnLoaded = true;
window.EJS_disableDatabases = true;      // IndexedDB is unreliable on the device
window.EJS_threads = false;              // no SharedArrayBuffer on the device
var s = document.createElement('script');
s.src = BASE + 'ejs/data/loader.js';
document.head.appendChild(s);
```

## Reading the frame rate

The runtime does not count frames, but the core does:

```js
em.gameManager.functions.getFrameNum()          // cumulative simulated frames
em.gameManager.functions.getVideoDimensions()   // canvas aspect ratio
em.gameManager.functions.setVsync(false)        // uncapped, for measuring the ceiling
```

Sample `getFrameNum()` once a second and take the difference. The browser's
`requestAnimationFrame` rate is **not** the emulated frame rate and will mislead you.

There is no `start()` method on the runtime — only `play` / `pause` / `togglePlaying`.
Calling `EJS_emulator.start()` throws a `TypeError` and breaks the runtime's own
startup sequence.

## Core selection

The core file is chosen by WebGL capability:

- WebGL2 available → `<core>-wasm.data`
- otherwise → `<core>-legacy-wasm.data`

`webgl2Enabled` defaults to `null`, so the runtime picks the **legacy** core unless
you set it explicitly. The legacy cores are software-rendered and run at about 1 FPS
on the desktop — always set the flag:

```js
// in cores/reports/<core>.json
{ "options": { "defaultWebGL2": true } }
```

A missing `cores/reports/<core>.json` is only a warning; it affects caching, not
execution.

## Keys

EmulatorJS matches input with `controls[player][button].value = keyCode`. The plugin
does not use that path. It intercepts keys in the capture phase and calls the core
directly, so there is only ever one mapping in play:

```js
em.gameManager.simulateInput(0, libretro_button, 1);  // press
em.gameManager.simulateInput(0, libretro_button, 0);  // release
```

libretro button numbers: `0`=B, `2`=SELECT, `3`=START, `4..7`=dpad, `8`=A, `9`=X,
`10`=L, `11`=R.

Keys must **bubble through the runtime's own container** — it listens on
`this.elements.parent`, so the canvas needs focus:

```js
canvas.focus();
```

The key map for the E5 is rewritten every second, because the runtime rebuilds
`controls` after the core loads and a stale map silently stops working:

| Action | Browser key | libretro |
|---|---|---|
| A | 13 | 8 |
| B | 8 | 0 |
| Up / Down / Left / Right | 38 / 40 / 37 / 39 | 4..7 |
| START | 48 | 3 |
| SELECT | 49 | 2 |

Menus cannot rely on native browser focus navigation, because the host consumes the
arrow keys before the plugin sees them. The plugin drives its own menu through
`e5.onKey`.

## Platform quirks on this device

### No audio output

The web process logs `GStreamer element autoaudiosink not found`. The Emscripten
audio initialisation is rejected with `NotAllowedError: Permission was denied`, the
main loop stops after the first few frames, and you get a grey screen with 0 FPS and
dead buttons.

The fix is to replace `window.AudioContext` with a silent stub. The trade-off is
explicit: **the games are silent**. To get sound, install `gst1-plugins-base` on the
device so a real audio sink exists.

### Hidden pages stop the frame counter

`requestAnimationFrame` does not fire in a page that is not visible, so the frame
count freezes when the panel is in the background. A `setTimeout` fallback keeps it
ticking.

### Cores are re-extracted every time

`EJS_disableDatabases = false` caches the *compressed* archive in IndexedDB, but the
*extracted* files are never cached — each launch re-unpacks the 7z core, which costs
one to three seconds.

### The framebuffer is not the panel

`/dev/fb0` is the DRM fbdev emulation and shows the kernel text console. It cannot
capture what the compositor is showing. To capture the panel you have to have the
page export its own canvas and upload it in chunks.

## Measured frame rates

On the E5 itself, with the panel at its native 320x480 and a second `cog` instance
sharing the same Wayland display, reading the core's own frame counter:

| System | Core | FPS |
|---|---|---|
| NES | `fceumm` | 60 |
| Game Boy | `gambatte` | 60 |
| Game Boy Advance | `mgba` | 60 |

60 is the panel's refresh rate cap, not the emulator's ceiling.

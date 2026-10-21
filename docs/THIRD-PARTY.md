# Third-party components

This repository bundles third-party software. Each component keeps its own
licence; the list below is the attribution for what ships inside `plugins/`.

## EmulatorJS

- Version: 4.2.3
- Licence: **GPL-3.0-or-later**
- Upstream: <https://github.com/EmulatorJS/EmulatorJS>
- Files: `plugins/e5-emulator/ejs/data/emulator.min.js`,
  `plugins/e5-emulator/ejs/data/emulator.min.css`,
  `plugins/e5-emulator/ejs/data/loader.js`,
  `plugins/e5-emulator/ejs/data/compression/`
- The emulator runtime itself is why this repository is GPL-3.0-or-later.

## Emulator cores

The cores are 7z-compressed archives shipped as `plugins/e5-emulator/ejs/data/cores/*.data`.
They are unpacked at runtime by the EmulatorJS runtime.

| Core | Licence | Notes |
| --- | --- | --- |
| `fceumm` (NES) | GPL-2.0-or-later | libretro/libretro-fceumm, FCEUmm derived |
| `gambatte` (Game Boy) | GPL-2.0-or-later | libretro/gambatte-libretro, by sinamas |
| `mgba` (Game Boy Advance) | MPL-2.0 | mgba-emu/mgba |
| `genesis_plus_gx` (Mega Drive) | BSD-3-Clause | Charles MacDonald, Eke-Eke |

MPL-2.0 requires that modifications to the covered files are made available under
MPL-2.0. The cores are redistributed here unmodified.

Genesis Plus GX is BSD-3-Clause by default, but its `LICENSE.txt` also carries the
full GPL text because parts of the emulator are GPL-licensed. It is bundled here
unmodified; its `LICENSE.txt` ships with the upstream core archive.

## Host platform

The plugins target the `e5-infoscreen` host service, which is part of the device's
own firmware and is not included in this repository. The plugin API it exposes is
documented in `docs/`.

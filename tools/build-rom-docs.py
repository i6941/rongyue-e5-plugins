"""Generate docs/ROMS-LICENSES.md and docs/THIRD-PARTY.md from roms/manifest.json.

Run from the repository root:  python tools/build-rom-docs.py
"""
import json
import sys

sys.stdout.reconfigure(encoding="utf-8")

SYSTEM_LABEL = {"fc": "NES", "gb": "Game Boy", "gba": "Game Boy Advance"}
CORE_LABEL = {"fceumm": "fceumm", "gambatte": "gambatte", "mgba": "mgba"}


def main():
    with open("roms/manifest.json", encoding="utf-8") as fh:
        entries = json.load(fh)

    lines = [
        "# ROM licences",
        "",
        "Every game bundled in `roms/` is a **homebrew title** whose licence explicitly",
        "allows redistribution. No commercial ROMs are included in this repository.",
        "",
        "The ROMs were obtained from the Homebrew Hub community databases, which record",
        "the licence and upstream source repository for each entry:",
        "",
        "- NES: <https://github.com/nesdev-org/homebrew-db>",
        "- Game Boy: <https://github.com/gbdev/database>",
        "- Game Boy Advance: <https://github.com/gbadev-org/games>",
        "",
        "The machine-readable form of this table is [`roms/manifest.json`](../roms/manifest.json),",
        "including the SHA-256 of each file. Regenerate both with",
        "`python tools/build-rom-manifest.py`.",
        "",
        "## Attribution",
        "",
        "| System | Title | Author | Licence | Source |",
        "| --- | --- | --- | --- | --- |",
    ]
    for e in entries:
        lines.append("| {sys} | {title} | {dev} | `{lic}` | {src} |".format(
            sys=SYSTEM_LABEL.get(e["system"], e["system"]),
            title=e["title"],
            dev=e["developer"],
            lic=e["license"],
            src=e["source"],
        ))

    lines += [
        "",
        "## Licence texts and obligations",
        "",
        "- **GPL-2.0-or-later / GPL-3.0-or-later** — redistribution is permitted provided the",
        "  same terms apply, the copyright notice and licence text are included, and the",
        "  corresponding source is made available. The upstream repositories linked above",
        "  are the corresponding source; each entry also carries its own licence file.",
        "  This repository is distributed under GPL-3.0-or-later for that reason.",
        "- **MIT / Zlib / 0BSD** — redistribution is permitted provided the copyright notice",
        "  and permission notice are retained. The notices are preserved in the upstream",
        "  repositories linked above.",
        "- **CC-BY-4.0** — redistribution is permitted provided attribution is given, a link",
        "  to the licence is supplied, and changes are indicated. Cybercoaster is credited",
        "  to *Fizzer & noby*; no modifications were made to the ROM.",
        "- **FSFAP** (Free Standard Distribution License) — redistribution is permitted with",
        "  the required notices retained. See the upstream repository for the full terms.",
        "",
        "## Adding your own ROMs",
        "",
        "The bundled set is a demo, not a catalogue. The plugin reads whatever is present",
        "in the device's ROM directory, so you can drop in your own legally obtained files.",
        "If you add titles to `roms/`, add them to `tools/build-rom-manifest.py` and",
        "regenerate the manifest so the licence table stays accurate.",
        "",
    ]
    with open("docs/ROMS-LICENSES.md", "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))

    third = [
        "# Third-party components",
        "",
        "This repository bundles third-party software. Each component keeps its own",
        "licence; the list below is the attribution for what ships inside `plugins/`.",
        "",
        "## EmulatorJS",
        "",
        "- Version: 4.2.3",
        "- Licence: **GPL-3.0-or-later**",
        "- Upstream: <https://github.com/EmulatorJS/EmulatorJS>",
        "- Files: `plugins/e5-emulator/ejs/data/emulator.min.js`,",
        "  `plugins/e5-emulator/ejs/data/emulator.min.css`,",
        "  `plugins/e5-emulator/ejs/data/loader.js`,",
        "  `plugins/e5-emulator/ejs/data/compression/`",
        "- The emulator runtime itself is why this repository is GPL-3.0-or-later.",
        "",
        "## Emulator cores",
        "",
        "The cores are 7z-compressed archives shipped as `plugins/e5-emulator/ejs/data/cores/*.data`.",
        "They are unpacked at runtime by the EmulatorJS runtime.",
        "",
        "| Core | Licence | Notes |",
        "| --- | --- | --- |",
        "| `fceumm` (NES) | GPL-2.0-or-later | libretro/libretro-fceumm, FCEUmm derived |",
        "| `gambatte` (Game Boy) | GPL-2.0-or-later | libretro/gambatte-libretro, by sinamas |",
        "| `mgba` (Game Boy Advance) | MPL-2.0 | mgba-emu/mgba |",
        "| `genesis_plus_gx` (Mega Drive) | BSD-3-Clause | Charles MacDonald, Eke-Eke |",
        "",
        "MPL-2.0 requires that modifications to the covered files are made available under",
        "MPL-2.0. The cores are redistributed here unmodified.",
        "",
        "Genesis Plus GX is BSD-3-Clause by default, but its upstream `LICENSE.txt` also",
        "carries the full GPL text because parts of the emulator are GPL-licensed. The",
        "core is bundled here unmodified; that `LICENSE.txt` travels inside the upstream",
        "core archive and is not extracted into this repository.",
        "",
        "## Host platform",
        "",
        "The plugins target the `e5-infoscreen` host service, which is part of the device's",
        "own firmware and is not included in this repository. The plugin API it exposes is",
        "documented in `docs/`.",
        "",
    ]
    with open("docs/THIRD-PARTY.md", "w", encoding="utf-8") as fh:
        fh.write("\n".join(third))

    print("wrote docs/ROMS-LICENSES.md and docs/THIRD-PARTY.md")


if __name__ == "__main__":
    main()

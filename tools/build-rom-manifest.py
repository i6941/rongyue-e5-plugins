"""Rebuild roms/manifest.json with full per-title attribution.

Run from the repository root:  python tools/build-rom-manifest.py
"""
import hashlib
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")

# file -> (title, licence, developer, upstream source, homebrew hub entry)
TITLES = {
    "fc/croom.nes": (
        "Concentration Room", "GPL-3.0-or-later", "Damian Yerrick",
        "https://github.com/pinobatch/croom-nes",
        "https://github.com/nesdev-org/homebrew-db/blob/master/entries/croom/game.json"),
    "fc/cybercoaster.nes": (
        "Cybercoaster", "CC-BY-4.0", "Fizzer & noby",
        "https://github.com/Fizzer/cybercoaster",
        "https://github.com/nesdev-org/homebrew-db/blob/master/entries/cybercoaster/game.json"),
    "fc/nova.nes": (
        "Nova the Squirrel", "GPL-3.0-or-later", "NovaSquirrel",
        "https://github.com/NovaSquirrel/NovaTheSquirrel",
        "https://github.com/nesdev-org/homebrew-db/blob/master/entries/novathesquirrel/game.json"),
    "fc/thwaite.nes": (
        "Thwaite", "GPL-3.0-or-later", "Damian Yerrick",
        "https://github.com/pinobatch/thwaite-nes",
        "https://github.com/nesdev-org/homebrew-db/blob/master/entries/thwaite/game.json"),
    "fc/zap-ruder.nes": (
        "Zap Ruder", "Zlib", "Damian Yerrick",
        "https://github.com/pinobatch/zap-ruder",
        "https://github.com/nesdev-org/homebrew-db/blob/master/entries/zap-ruder/game.json"),
    "fc/rhde.nes": (
        "RHDE: Furniture Fight", "FSFAP", "Damian Yerrick",
        "https://github.com/pinobatch/rhde-nes",
        "https://github.com/nesdev-org/homebrew-db/blob/master/entries/rhde/game.json"),
    "fc/240p-test-suite.nes": (
        "240p Test Suite", "GPL-2.0-or-later", "Damian Yerrick",
        "https://github.com/pinobatch/240p-test-mini",
        "https://github.com/nesdev-org/homebrew-db/blob/master/entries/240p-test-suite/game.json"),
    "gb/airaki.gb": (
        "Airaki", "GPL-3.0-or-later", "furrtek",
        "https://github.com/furrtek/Airaki",
        "https://github.com/gbdev/database/blob/master/entries/airaki/game.json"),
    "gb/2048.gb": (
        "2048gb", "Zlib", "Sanqui",
        "https://github.com/Sanqui/2048-gb",
        "https://github.com/gbdev/database/blob/master/entries/2048gb/game.json"),
    "gb/carazu.gb": (
        "Carazu", "GPL-3.0-or-later", "Martin Holtkamp",
        "https://github.com/mholtkamp/carazu",
        "https://github.com/gbdev/database/blob/master/entries/carazu/game.json"),
    "gb/dusky-dungeon.gb": (
        "Dusky Dungeon", "MIT", "invertedHat",
        "https://github.com/inverted-hat/duskyDungeon",
        "https://github.com/gbdev/database/blob/master/entries/dusky-dungeon/game.json"),
    "gb/gb-corp.gb": (
        "GB Corp.", "MIT", "Dr. Ludos",
        "https://github.com/drludos/GBcorp",
        "https://github.com/gbdev/database/blob/master/entries/gb-corp/game.json"),
    "gb/brekstas-cat.gb": (
        "Breksta's Cat", "MIT", "NotImplementedLife",
        "https://github.com/NotImplementedLife/brekstascat",
        "https://github.com/gbdev/database/blob/master/entries/brekstascat/game.json"),
    "gb/big2small.gb": (
        "Big2Small", "GPL-3.0-or-later", "mdsteele",
        "https://github.com/mdsteele/big2small",
        "https://github.com/gbdev/database/blob/master/entries/big2small/game.json"),
    "gba/gbatris.gba": (
        "GBAtris", "GPL-3.0-or-later", "John Tsiombikas & Greig Stewart",
        "https://github.com/jtsiomb/gbatris",
        "https://github.com/gbadev-org/games/blob/master/entries/gbatris/game.json"),
    "gba/minicraft.gba": (
        "Minicraft for GBA", "GPL-3.0-or-later", "Vulcalien",
        "https://github.com/Vulcalien/minicraft-gba",
        "https://github.com/gbadev-org/games/blob/master/entries/minicraft-gba/game.json"),
    "gba/ucity-advance.gba": (
        "uCity Advance", "GPL-3.0-or-later", "AntonioND",
        "https://github.com/AntonioND/ucity-advance",
        "https://github.com/gbadev-org/games/blob/master/entries/ucity-advance/game.json"),
    "gba/meteorain.gba": (
        "MeteoRain", "MIT", "Dr. Ludos",
        "https://github.com/drludos/meteorain-gba",
        "https://github.com/gbadev-org/games/blob/master/entries/meteorain-gba-jam-2021/game.json"),
    "gba/trogdor-gba.gba": (
        "Trogdor for Game Boy Advance", "MIT", "Jeremy Elkayam",
        "https://github.com/jeremyelkayam/trogba",
        "https://github.com/gbadev-org/games/blob/master/entries/jeremyelkayam_trogba/game.json"),
}

CORE = {"fc": "fceumm", "gb": "gambatte", "gba": "mgba"}


def main():
    entries = []
    for rel, (title, lic, dev, src, hub) in TITLES.items():
        path = os.path.join("roms", rel)
        if not os.path.exists(path):
            raise SystemExit("missing ROM: " + path)
        blob = open(path, "rb").read()
        system = rel.split("/")[0]
        entries.append({
            "system": system,
            "file": rel.split("/")[1],
            "path": rel,
            "title": title,
            "license": lic,
            "core": CORE[system],
            "developer": dev,
            "source": src,
            "homebrew_hub": hub,
            "bytes": len(blob),
            "sha256": hashlib.sha256(blob).hexdigest(),
        })
    entries.sort(key=lambda e: (e["system"], e["file"]))
    with open("roms/manifest.json", "w", encoding="utf-8") as fh:
        json.dump(entries, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    print("manifest entries:", len(entries))
    for e in entries:
        print("  {system:4} {file:24} {title:32} {license:20} {bytes:>9}".format(**e))


if __name__ == "__main__":
    main()

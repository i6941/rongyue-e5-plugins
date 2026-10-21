# ROM licences

Every game bundled in `roms/` is a **homebrew title** whose licence explicitly
allows redistribution. No commercial ROMs are included in this repository.

The ROMs were obtained from the Homebrew Hub community databases, which record
the licence and upstream source repository for each entry:

- NES: <https://github.com/nesdev-org/homebrew-db>
- Game Boy: <https://github.com/gbdev/database>
- Game Boy Advance: <https://github.com/gbadev-org/games>

The machine-readable form of this table is [`roms/manifest.json`](../roms/manifest.json),
including the SHA-256 of each file. Regenerate both with
`python tools/build-rom-manifest.py`.

## Attribution

| System | Title | Author | Licence | Source |
| --- | --- | --- | --- | --- |
| NES | 240p Test Suite | Damian Yerrick | `GPL-2.0-or-later` | https://github.com/pinobatch/240p-test-mini |
| NES | Concentration Room | Damian Yerrick | `GPL-3.0-or-later` | https://github.com/pinobatch/croom-nes |
| NES | Cybercoaster | Fizzer & noby | `CC-BY-4.0` | https://github.com/Fizzer/cybercoaster |
| NES | Nova the Squirrel | NovaSquirrel | `GPL-3.0-or-later` | https://github.com/NovaSquirrel/NovaTheSquirrel |
| NES | RHDE: Furniture Fight | Damian Yerrick | `FSFAP` | https://github.com/pinobatch/rhde-nes |
| NES | Thwaite | Damian Yerrick | `GPL-3.0-or-later` | https://github.com/pinobatch/thwaite-nes |
| NES | Zap Ruder | Damian Yerrick | `Zlib` | https://github.com/pinobatch/zap-ruder |
| Game Boy | 2048gb | Sanqui | `Zlib` | https://github.com/Sanqui/2048-gb |
| Game Boy | Airaki | furrtek | `GPL-3.0-or-later` | https://github.com/furrtek/Airaki |
| Game Boy | Big2Small | mdsteele | `GPL-3.0-or-later` | https://github.com/mdsteele/big2small |
| Game Boy | Breksta's Cat | NotImplementedLife | `MIT` | https://github.com/NotImplementedLife/brekstascat |
| Game Boy | Carazu | Martin Holtkamp | `GPL-3.0-or-later` | https://github.com/mholtkamp/carazu |
| Game Boy | Dusky Dungeon | invertedHat | `MIT` | https://github.com/inverted-hat/duskyDungeon |
| Game Boy | GB Corp. | Dr. Ludos | `MIT` | https://github.com/drludos/GBcorp |
| Game Boy Advance | GBAtris | John Tsiombikas & Greig Stewart | `GPL-3.0-or-later` | https://github.com/jtsiomb/gbatris |
| Game Boy Advance | MeteoRain | Dr. Ludos | `MIT` | https://github.com/drludos/meteorain-gba |
| Game Boy Advance | Minicraft for GBA | Vulcalien | `GPL-3.0-or-later` | https://github.com/Vulcalien/minicraft-gba |
| Game Boy Advance | Trogdor for Game Boy Advance | Jeremy Elkayam | `MIT` | https://github.com/jeremyelkayam/trogba |
| Game Boy Advance | uCity Advance | AntonioND | `GPL-3.0-or-later` | https://github.com/AntonioND/ucity-advance |

## Licence texts and obligations

- **GPL-2.0-or-later / GPL-3.0-or-later** — redistribution is permitted provided the
  same terms apply, the copyright notice and licence text are included, and the
  corresponding source is made available. The upstream repositories linked above
  are the corresponding source; each entry also carries its own licence file.
  This repository is distributed under GPL-3.0-or-later for that reason.
- **MIT / Zlib / 0BSD** — redistribution is permitted provided the copyright notice
  and permission notice are retained. The notices are preserved in the upstream
  repositories linked above.
- **CC-BY-4.0** — redistribution is permitted provided attribution is given, a link
  to the licence is supplied, and changes are indicated. Cybercoaster is credited
  to *Fizzer & noby*; no modifications were made to the ROM.
- **FSFAP** (Free Standard Distribution License) — redistribution is permitted with
  the required notices retained. See the upstream repository for the full terms.

## Adding your own ROMs

The bundled set is a demo, not a catalogue. The plugin reads whatever is present
in the device's ROM directory, so you can drop in your own legally obtained files.
If you add titles to `roms/`, add them to `tools/build-rom-manifest.py` and
regenerate the manifest so the licence table stays accurate.

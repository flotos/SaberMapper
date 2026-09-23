# 06 — 3 BIG SHOTS FROM [KITCHEN GUN]

| | |
|---|---|
| Song | 3 BIG SHOTS FROM [KITCHEN GUN] — Grambam36 (YTPMV; original music Toby Fox) |
| Mapper | Droobix (TheGoodBoi) |
| BeatSaver | [43a4a](https://beatsaver.com/maps/43a4a) · hash `82d8b81f0477d2c51952854f24aa3b34587324e5` |
| BPM / length | 140 · 150 s |
| Environment | BigMirrorEnvironment |
| Schema | Info 2.1.0, difficulties 3.3.0 |
| Requirements | Chroma, Noodle Extensions, Vivify |
| Local | `workspace/corpus/extrasensory/downloads/06-43a4a.zip` · `extracted/06-43a4a/` |
| Public source | [droobix/map-source-files](https://github.com/droobix/map-source-files) |

Map 6 of 10. Droobix's second entry, after `Breezer`.

## Concept

A meme map, and openly so — a YTPMV built on an Undertale theme crossed with a UK advert sketch,
mapped as a full modchart. The description is written in-character in the source meme's voice. Seven
contributors, including Swifter for optimisation, Mawntee as testplayer, Aeroluna for troubleshooting.

Assets are all screens and broadcast: `thetvplane.prefab`, `screen1.prefab`, `screenmat1.mat`,
`screenmat2.mat`, `screenmat3.mat`. Tracks include `boom0`, `boom1`, `screen1`–`screen3`, `alleyFakes`.

## Structure

| Characteristic / Difficulty | Label | Notes | Bombs | Walls | Chains | NPS | NJS |
|---|---|---|---|---|---|---|---|
| Standard / Expert | `an easier way` | 548 | 39 | 24 | 0 | 3.91 | 17 |
| Standard / ExpertPlus | `[[SPARKLE LIKE NEW]]` | 597 | 0 | 29 | 6 | 4.26 | 17 |

343 basic light events, 15 environment enhancements. `_colorLeft`, `_colorRight` and `_obstacleColor`
all overridden per difficulty.

Active NPS across eight windows on Expert+: 3.4 / 5.6 / 6.2 / 2.3 / 2.9 / 5.7 / 5.6 / 2.5. The most
strongly alternating profile in the pack — two dense passages separated by a deep trough, then a
final drop.

Note the bomb inversion: Expert has 39 bombs and Expert+ has none. The downmap is not simply a subset.

## Event program

| Event | Expert | ExpertPlus |
|---|---|---|
| `AnimateTrack` | 398 | 397 |
| `InstantiatePrefab` | 133 | 133 |
| `DestroyObject` | 48 | 48 |
| `SetMaterialProperty` | 47 | 47 |
| `AssignTrackParent` | 47 | 47 |
| `AssignPathAnimation` | 24 | 24 |
| **`Blit`** | **10** | **46** |
| **`CreateScreenTexture`** | **0** | **4** |
| `SetRenderingSettings` | 1 | 1 |
| `CreateCamera` | 1 | 1 |
| **total** | **709** | **748** |

152 tracks, 37–38 assets.

## What is distinctive

**One of only two maps whose show differs between difficulties**, and the difference is specific:
Expert+ adds 36 blits and 4 screen textures that Expert does not have. Everything else matches exactly.
The harder difficulty gets a post-process layer the easier one is spared — a readability decision, not
a reward. That inverts the usual assumption that the harder chart should be busier visually.

**Mixed v2 and v3 Noodle field names in the same file.** 274 notes carry the legacy
`_disableSpawnEffect` and `_disableNoteGravity` while 226 carry the modern `disableNoteGravity` and 405
carry `spawnEffect`. The map was migrated across schema versions and the old fields were left in place.
Worth knowing when parsing EXSII maps: **do not assume a single field convention within one file.**

**The only map using `uninteractable`** (45 notes), alongside `link` (76) and `flip` (148). The
`alleyFakes` track name gives it away — these are notes that exist to be looked at and not swung at.
Fake notes as set dressing is a technique unique to this entry in the pack.

**47 `AssignTrackParent` calls** — by far the most. The scene is assembled as a deep hierarchy of
parented screens and props rather than a flat list, so one animation can move a whole composed group.

**The only map with meaningful walls on both difficulties** (24 and 29), coloured via `_obstacleColor`.
Everywhere else in EXSII walls are absent.

## What to take from it

- **Visual load is a readability variable, and it can go down as difficulty goes up.** This is the
  clearest counterexample in the pack to "harder means more". Our composer should be able to express
  "this section gets less post-processing on the harder chart".
- Fake, `uninteractable` notes are a cheap way to build visual density without touching the swing load.
  They cost nothing in strain and read as part of the scene.
- Deep `AssignTrackParent` hierarchies are the scene-map equivalent of grouped animation: compose once,
  animate the parent.
- Alternating dense/sparse sections (5.6 → 2.3 → 5.7) is the pack's dominant structural rhythm and this
  map is the sharpest example. Density troughs align with the visual set-pieces.
- For our parser: handle both `_disableNoteGravity` and `disableNoteGravity` spellings, in the same
  file, on different notes. This is real data, not a hypothetical.
- A meme concept was given a full modchart treatment and shipped as map 6 of a flagship pack. Tone and
  technical ambition are independent axes.

## How the idea follows from the song

**Song.** Grambam36's YTPMV (2022) cuts the Kitchen Gun advert parody (Peter Serafinowicz, 2007)
against BIG SHOT, Spamton NEO's battle theme from *Deltarune* Chapter 2 by Toby Fox. Manic and comic;
the words are advert samples rather than song lyrics.

**Verified in the files (Expert+).** No `AssignPlayerToTrack`: possession `none`. Beat 0: a TV plane,
screens at 2 and 16.5. Beat 36 (15 s): alley, posters, field. Beat 68.5 (29 s): city, tracks, cars,
`ralsei`, `susie`, left and right wings and eight `string` prefabs. Beat 100 (43 s): `kitchen`; at
101–106 and 117–122 a screen texture is captured and `oldmat.mat` flashes eight times at quarter-beat
spacing. 130.88: `world`, two `chaos` prefabs and a note-wiggle camera Blit. 172: five toilets. 196:
the alley set again. 228 (98 s): papers and 50 screens. 260.5 (112 s): the city, wings and strings
set is rebuilt; freeze-frame bursts return at 277–290, and 28 walls plus a `crouch.mat` Blit sit in
288–303. Note colours: left #fe6fda, right #f1e100.

**Interpretation.** The map cuts between the two source worlds the way the video does: the advert
(TV screens, kitchen, toilets, freeze-frame "shots") and *Deltarune* (alley, Ralsei, Susie, and a
winged figure on strings that reads as Spamton NEO). Pink and yellow notes echo Spamton's colours.
Motifs: TV screens, freeze-frames, the puppet-string set. They develop from single screens to a
full set, then to screens multiplied by fifty. Held for the end is the reprise at 260.5, which
brings back the string set together with the freeze-frames and the map's only wall section.

Sources: [BeatSaver 43a4a](https://beatsaver.com/maps/43a4a) ·
[Grambam36 on Bandcamp](https://grambam36.bandcamp.com/track/3-big-shots-from-kitchen-gun) ·
[Kitchen Gun (Know Your Meme)](https://knowyourmeme.com/memes/kitchen-gun) ·
[BIG SHOT (Deltarune Wiki)](https://deltarune.fandom.com/wiki/BIG_SHOT) ·
[droobix/map-source-files](https://github.com/droobix/map-source-files)

## Required assets

Not in the BeatSaver zip (except where noted) — Vivify fetches these from LunarRepo at play
time, keyed by the checksum in `Info.dat`.

| Platform | `_assetBundle` CRC | Download | Local |
|---|---|---|---|
| windows2019 | `2669732511` | [`2669732511.vivify`](https://cdn.repo.totalbs.dev/2669732511.vivify) | not downloaded |
| windows2021 | `3416881939` | [`3416881939.vivify`](https://cdn.repo.totalbs.dev/3416881939.vivify) | `06-43a4a_bundleWindows2021.vivify` (30.81 MB) |
| android2021 | `223024126` | [`223024126.vivify`](https://cdn.repo.totalbs.dev/223024126.vivify) | not downloaded |

Resolution rule: `https://cdn.repo.totalbs.dev/{crc}.vivify`. The CRC is Unity's AssetBundle
CRC from the build manifest, not a CRC32 of the file — it is a lookup key, not something we can
recompute.

**Published source:** [droobix/map-source-files](https://github.com/droobix/map-source-files) — Unity project + all three built bundles (31 MB each)

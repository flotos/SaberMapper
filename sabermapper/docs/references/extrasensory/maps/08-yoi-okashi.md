# 08 — Yoi Okashi to Warui Okashi

| | |
|---|---|
| Song | Yoi Okashi to Warui Okashi — Asatsumei |
| Mappers | Elecast (mapper, lighter), Fatalution (mapper, downmaps) |
| BeatSaver | [43a4b](https://beatsaver.com/maps/43a4b) · hash `bb8c40d9220ddcc5ec5fe2e015823d9111b21a8b` |
| BPM / length | 175 · **304 s** |
| Environment | BigMirrorEnvironment |
| Schema | Info 2.1.0, difficulties 3.3.0 |
| Requirements | Noodle Extensions, Chroma, Vivify |
| Local | `workspace/corpus/extrasensory/downloads/08-43a4b.zip` · `extracted/08-43a4b/` |

Map 8 of 10. The longest song in the pack by nearly two minutes, and the heaviest map by every
structural measure. Swifter is credited for custom notes and bombs and shader help, Mawntee for shader
debugging.

## Concept

The asset names describe a journey through built and natural scenery: `field.prefab`, `field2.prefab`,
`city.prefab`, `windows.prefab`, `grass_100.mat`, with track families named `ring2`/`ring4`/`ring6`
and `cate`/`cath`/`catm`. Over five minutes the map moves through a sequence of fully instantiated
environments rather than transforming one.

## Structure

| Characteristic / Difficulty | Notes | Bombs | Walls | Arcs | NPS | NJS | Offset |
|---|---|---|---|---|---|---|---|
| Standard / Expert | 1237 | 176 | 249 | 46 | 4.14 | 18 | -0.25 |
| Standard / ExpertPlus | **2475** | 185 | 260 | 25 | **8.28** | **20** | **-0.5** |

**1893 basic light events. 80 environment enhancements. 7 declared materials.** All three are the
highest in the pack.

Active NPS across eight windows on Expert+: 6.1 / 9.0 / 7.9 / 9.0 / **4.4** / 10.2 / 10.6 / 9.2. A
single deliberate trough at the midpoint, otherwise sustained 8–10 NPS.

## Event program

**7785 custom events** — more than the other nine maps combined. Identical between Expert and
ExpertPlus.

| Event | Count |
|---|---|
| **`SetMaterialProperty`** | **4241** |
| **`AnimateTrack`** | **1909** |
| `DestroyObject` | 789 |
| `InstantiatePrefab` | 788 |
| `Blit` | 40 |
| `SetAnimatorProperty` | 6 |
| `AssignObjectPrefab` | 6 |
| `AssignPathAnimation` | 5 |
| `SetRenderSetting` | 1 |

**774 tracks. 101 assets.** Both the highest in the pack.

Prefab spawns by 64-beat window: 4, 0, 8, 9, 3, 2, 1, 2, 5, 61, 10, 59, **518**, 106. More than
two-thirds of all instantiation happens in a single window near the end.

## What is distinctive

**It is the only EXSII map that is also a hard map by conventional standards.** 8.28 NPS, NJS 20, 2475
notes, 260 walls and 185 bombs on Expert+. Every other entry trades density for spectacle; this one
refuses to. It is the closest thing in the pack to a map that would sit in the 6.5–8 star band in
`PLAYER.md` on gameplay merit alone.

**Minimal note customisation despite maximal everything else.** Note `customData` carries *only*
`noteJumpMovementSpeed`, `noteJumpStartBeatOffset` and `track` — on all 2475 notes, with no
`animation`, no `spawnEffect`, no `disableNoteGravity`. The chart is left alone to be a chart. All 774
tracks and 1909 `AnimateTrack` calls are driving *scene* objects, not notes.

This is the decisive structural lesson of the map: **the visual program and the note layer are fully
decoupled.** The scene does everything; the notes do nothing unusual. That is why the chart can be this
dense — it never has to be read through note trickery.

**518 prefab spawns in one window.** The finale instantiates an entire environment at once. Spawn and
destroy remain balanced overall (788 vs 789), so even this burst is cleaned up.

**4241 material-property calls.** Unquestionably generated. `_editors` lists MMA2 and ChroMapper with
no scripting tool named, but 774 tracks and 7785 events did not come from a GUI.

**The highest NJS and the most negative offset in the pack** (20 / -0.5), which is consistent: dense,
conventional charting needs fast, early-spawning notes. Compare `you` at NJS 8.

## What to take from it

- **This is the map to study for combining real difficulty with Vivify.** The rule it demonstrates:
  when the chart is dense, keep note `customData` minimal and put all the ambition in the scene. Note
  choreography and note density compete for the same attention budget; pick one per section.
- A single mid-map density trough (9.0 → 4.4 → 10.2) is enough recovery for a five-minute map at this
  intensity. Our strain model should recognise one deep trough as a valid alternative to frequent
  shallow ones.
- Balanced spawn/destroy holds even at 788 objects. This should be a hard validation rule in our
  compiler, not a guideline.
- 80 environment enhancements plus 1893 basic light events means the *vanilla* environment is still
  being used heavily alongside Vivify. Custom assets did not replace conventional lighting work here;
  they were layered onto it.
- Downmapping halved the note count (2475 → 1237) and dropped NJS 20 → 18, while the show stayed
  byte-identical. Standard EXSII practice, applied at the largest scale in the pack.

## How the idea follows from the song

**Song.** Asatsumei feat. L4hee, a Japanese vocal electronic track at 175 BPM, 304 s. The title reads
as "good sweets and bad sweets". Lyric content is not verified here.

**Verified in the files (Expert+).** No `AssignPlayerToTrack`: possession `none`. Beats 0–62: a field
and three text prefabs. 132: grass; 163–222: a second field with short-lived `fpa` spawns. 236
(81 s): city, windows and stars; 270–273: three `cat` sprites, animated by texture swaps until 663.
495–510 (170–175 s): a `glitcheye` prefab and eleven glitch, VHS and colour Blits over 124 bombs
(492.7–509.75), with no notes between beats 494 and 514.
575–636: corridor sections spawned one per beat. 644–653: the city and a ring tunnel built ring by
ring; the rings flicker through 662–780, with a `cs_fancy_color` Blit on each beat in 766–780. From
790 (271 s): 608 cloud prefabs until the end. Notes stay plain throughout (NJS, offset, track only).

**Interpretation.** A long journey: field, city, a corrupted interlude, a tunnel, open sky. The
glitch section is the one place where the chart turns into bombs only, which reads as the "bad" half
of the title's pair. Motifs: open landscape, the city, rings, glitch; the rings grow from a static
tunnel to a flickering, colour-cycling one. Held for the end is the cloud field from beat 790, the
largest spawn burst in the pack. With an 8 NPS chart, neither the camera nor the notes are touched.

Sources: [BeatSaver 43a4b](https://beatsaver.com/maps/43a4b) ·
[osu! listing (artist, vocalist)](https://osu.ppy.sh/beatmapsets/2319311) ·
[EXSII site](https://exsii.totalbs.dev/)

## Required assets

Not in the BeatSaver zip (except where noted) — Vivify fetches these from LunarRepo at play
time, keyed by the checksum in `Info.dat`.

| Platform | `_assetBundle` CRC | Download | Local |
|---|---|---|---|
| windows2019 | `3360852256` | [`3360852256.vivify`](https://cdn.repo.totalbs.dev/3360852256.vivify) | not downloaded |
| windows2021 | `2608972127` | [`2608972127.vivify`](https://cdn.repo.totalbs.dev/2608972127.vivify) | `08-43a4b_bundleWindows2021.vivify` (2.80 MB) |
| android2021 | — | *not declared* | — |

Resolution rule: `https://cdn.repo.totalbs.dev/{crc}.vivify`. The CRC is Unity's AssetBundle
CRC from the build manifest, not a CRC32 of the file — it is a lookup key, not something we can
recompute.

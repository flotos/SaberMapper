# 03 — Lifelike

| | |
|---|---|
| Song | Lifelike — Porter Robinson |
| Mapper | nasafrasa |
| BeatSaver | [43a25](https://beatsaver.com/maps/43a25) · hash `cb5470be988e526c08e1c7e98f2ba9c26ec6fbd0` |
| BPM / length | 100.72 · 96 s |
| Environment | BillieEnvironment |
| Schema | Info 2.1.0, difficulties 3.2.0 |
| Requirements | Noodle Extensions, Chroma, Vivify |
| Local | `workspace/corpus/extrasensory/downloads/03-43a25.zip` · `extracted/03-43a25/` |

Map 3 of 10. Marked **PC only, not for Quest** — and the Info.dat confirms it: the asset bundle
declares `_windows2019` and `_windows2021` but no `_android2021`.

## Concept

Porter Robinson's *Nurture* material, and the difficulty labels name the album and the track directly:
Easy is `Nurture`, Normal is `Lifelike`. The asset list — `scribble.mat`, `doorleft.prefab`,
`doorright.prefab`, `skyboxblack.prefab`, `camerawarm.mat` — and tracks named `TRoof`, `TRight`,
`TLeft`, `TFloor`, `Intro Scribble`, `Piano` describe a room built out of four planes that the player
is moved through, with a hand-drawn scribble aesthetic over it.

## Structure

| Characteristic / Difficulty | Label | Notes | Arcs | Chains | NPS | NJS |
|---|---|---|---|---|---|---|
| Standard / Easy | `Nurture` | 123 | 39 | 2 | 1.56 | 16 |
| Standard / Normal | `Lifelike` | 145 | 52 | 10 | 1.84 | 16 |

Zero bombs, zero walls on both. 77 basic light events, **16 environment enhancements**, and **2
declared materials** in `customData.materials` — one of only three maps (with `luminescent` and
`Yoi Okashi`) that declares materials at the difficulty level rather than driving bundle materials
directly.

Active NPS across eight windows: 1.7 / 1.6 / 2.6 / 2.0 / 1.9 / 1.6 / 1.6 / 1.5. The flattest profile
in the pack — a single gentle rise at the one-third mark and then a long even plateau.

## Event program

86 custom events, **identical between Easy and Normal**.

| Event | Count |
|---|---|
| `AnimateTrack` | 41 |
| `InstantiatePrefab` | 14 |
| `DestroyObject` | 14 |
| `SetMaterialProperty` | 10 |
| `AssignObjectPrefab` | 2 |
| `Blit` | 1 |
| `SetCameraProperty` | 1 |
| `SetGlobalProperty` | 1 |
| `AssignPlayerToTrack` | 1 |
| `AssignTrackParent` | 1 |

21 tracks, 18 assets.

## What is distinctive

**Arc-forward charting.** 52 arcs against 145 notes on Normal — proportionally the heaviest arc usage
in the pack. Combined with 10 chains and zero bombs or walls, the chart is built almost entirely from
flow objects. For a slow, legato track at 100 BPM this is the musically correct choice, and it is the
one map here whose *note layer* is doing expressive work rather than just staying out of the way.

**Every note carries a Chroma `color`.** All 145 notes set `color` alongside `animation`,
`disableNoteGravity`, per-note NJS, offset and `track`. The notes are recoloured individually rather
than by a difficulty-level palette — the chart participates in the visual scheme instead of sitting on
top of it.

**`InstantiatePrefab` and `DestroyObject` are exactly balanced at 14 each.** The cleanest lifetime
discipline in the pack. Nothing spawned survives the map.

**One blit, one global property, one camera call.** This map is almost pure geometry — it sits at the
opposite end of the technique axis from `luminescent`, by the same mapper. nasafrasa contributed both
the most restrained scene map and one of the heaviest post-process maps to the same pack.

**Difficulty labels replace difficulty names.** Neither label describes hardness; both name songs. The
pack routinely uses `_difficultyLabel` as a titling device rather than a calibration signal — worth
remembering when reading EXSII metadata as difficulty evidence, because it is not.

## What to take from it

- A complete, well-regarded Vivify map needs **86 events**. The pack's median is much higher, but the
  floor is low. Visual ambition does not require event volume; it requires the scene to be built well
  in Unity.
- Arcs and chains are the right density lever for slow tracks — raising note count would have fought
  the music. Our composer should treat arc-forward charting as a distinct mode, not a garnish.
- Per-note `color` is how a chart joins a visual scheme. Cheap to emit, and it is what stops the notes
  looking pasted on.
- The four-plane room (`TRoof` / `TFloor` / `TLeft` / `TRight` on a parent track) is a small, directly
  reusable scene pattern: build a box from planes, parent it, animate the parent.
- Declaring no Android bundle is a legitimate, explicit scoping decision, recorded in Info.dat. If we
  ever emit Vivify maps we should make the platform set explicit rather than implicit.

## Required assets

Not in the BeatSaver zip (except where noted) — Vivify fetches these from LunarRepo at play
time, keyed by the checksum in `Info.dat`.

| Platform | `_assetBundle` CRC | Download | Local |
|---|---|---|---|
| windows2019 | `2049252416` | [`2049252416.vivify`](https://cdn.repo.totalbs.dev/2049252416.vivify) | not downloaded |
| windows2021 | `2874852143` | [`2874852143.vivify`](https://cdn.repo.totalbs.dev/2874852143.vivify) | `03-43a25_bundleWindows2021.vivify` (5.58 MB) |
| android2021 | — | *not declared* | — |

Resolution rule: `https://cdn.repo.totalbs.dev/{crc}.vivify`. The CRC is Unity's AssetBundle
CRC from the build manifest, not a CRC32 of the file — it is a lookup key, not something we can
recompute.

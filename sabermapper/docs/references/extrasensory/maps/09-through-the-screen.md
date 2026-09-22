# 09 — Through The Screen

| | |
|---|---|
| Song | Through The Screen — RXLZQ |
| Mapper | Mawntee (lower difficulty by Fatalution) |
| BeatSaver | [43a5d](https://beatsaver.com/maps/43a5d) · hash `6f3e5a591648dbb927199c6deba7647ac85b341a` |
| BPM / length | 160 · 150 s |
| Environment | WeaveEnvironment |
| Schema | Info 2.1.0, difficulties 3.3.0 |
| Requirements | Chroma, Noodle Extensions, Vivify, **AudioLink** |
| Local | `workspace/corpus/extrasensory/downloads/09-43a5d.zip` · `extracted/09-43a5d/` |

Map 9 of 10. Mawntee maintains [the modchart resource dump](https://github.com/Mawntee/modhcart) and
is credited for shader debugging on two other EXSII entries.

## Concept

Passage through screens. Assets are named for it — `tts_scene1.prefab`, `tts_scene2.prefab`,
`tts_alwaysenabled.prefab`, `tts_saberclone_left.prefab`, `tts_saberclone_right.prefab` — and tracks
run `Screen1` through `Screen4` plus `pogFog` and `noHead?`.

## Structure

| Characteristic / Difficulty | Notes | NPS | NJS |
|---|---|---|---|
| Standard / Normal | 230 | 1.75 | 16 |
| Standard / ExpertPlus | 279 | 2.12 | 16 |

Zero bombs, zero walls, zero arcs, zero chains, zero basic light events. 20 environment enhancements.

Another Normal → ExpertPlus jump with nothing between, and only 49 notes separating them.

Active NPS across eight windows on Expert+: 0.6 / 1.3 / 2.9 / 1.8 / **0.4** / 2.1 / 3.3 / **4.6**. The
strongest late climb in the pack — it finishes at eleven times its opening density, with a near-empty
window at the midpoint.

## Event program

**65 custom events.** The leanest program in EXSII. Identical between Normal and ExpertPlus.

| Event | Count |
|---|---|
| `AnimateTrack` | 20 |
| `InstantiatePrefab` | 12 |
| `DestroyObject` | 12 |
| `SetGlobalProperty` | 7 |
| `SetRenderingSettings` | 4 |
| `Blit` | 3 |
| `AnimateComponent` | 2 |
| `AssignTrackParent` | 2 |
| `SetCameraProperty` | 1 |
| `AssignPlayerToTrack` | 1 |
| `AssignObjectPrefab` | 1 |

16 tracks, 11 assets.

## What is distinctive

**65 events for a headline modchart.** Two orders of magnitude below `Yoi Okashi`. The complexity did
not disappear — it moved into Unity. Twelve prefabs, each presumably carrying its own animators,
timelines and shaders, are spawned and destroyed, and seven `SetGlobalProperty` calls drive the whole
thing. The `.dat` file is a cue sheet; the show is in the bundle.

This is the most important architectural datapoint in the pack. **Event count does not measure visual
ambition.** It measures how much of the show was authored in the beatmap versus in Unity.

**The only mid-map possession in EXSII.** A single `AssignPlayerToTrack` at **beat 194**, target
`Head`, track `noHead?`. Every other possession in the pack fires at beat 0 as setup. Here it is a
timed event — the moment the player goes through the screen — and it lands right after the 0.4 NPS
dead window at the midpoint. The chart empties out so the reveal has the player's full attention, then
climbs continuously to the end.

**Saber clones as prefabs.** `tts_saberclone_left` / `tts_saberclone_right` are instantiated scene
objects rather than `AssignObjectPrefab` saber replacements — duplicate sabers that exist in the world
alongside the real ones.

**`SetGlobalProperty` over `SetMaterialProperty`.** Seven global calls and no per-material calls at
all. One value change propagates to every shader in the bundle at once. Consistent with the
prefab-heavy architecture: the bundle's materials are already wired to global properties.

**Custom tooling.** `_editors` lists MMA2, ChroMapper and `MawnteesStinkyScript` — a personal script,
not a public library.

## What to take from it

- **Push complexity into the asset bundle and keep the event program as a cue sheet.** For a generative
  pipeline this is the most tractable architecture in the pack: 65 cue points are something our
  composer can reason about and place musically. 7785 are not.
- `SetGlobalProperty` plus bundle-side wiring beats per-material calls when everything should change
  together. Fewer events, one source of truth.
- **A timed possession needs an empty bar in front of it.** The 0.4 NPS window immediately before beat
  194 is the technique, not an accident. Any reveal our composer schedules should reserve the
  preceding phrase.
- A monotonic late climb (0.6 → 4.6) is the one place in the pack where density does rise steadily to
  the end, and it works because the visual reveal already happened at the midpoint. Structure the
  density curve around the narrative beat, not the clock.
- Declaring `AudioLink` alongside the usual three is a reminder that the requirements array is an
  open list. Our exporter should carry through whatever the arrangement declares rather than assuming
  a fixed set.

## Required assets

Not in the BeatSaver zip (except where noted) — Vivify fetches these from LunarRepo at play
time, keyed by the checksum in `Info.dat`.

| Platform | `_assetBundle` CRC | Download | Local |
|---|---|---|---|
| windows2019 | `3665654059` | [`3665654059.vivify`](https://cdn.repo.totalbs.dev/3665654059.vivify) | not downloaded |
| windows2021 | `743306464` | [`743306464.vivify`](https://cdn.repo.totalbs.dev/743306464.vivify) | `09-43a5d_bundleWindows2021.vivify` (1.44 MB) |
| android2021 | — | *not declared* | — |

Resolution rule: `https://cdn.repo.totalbs.dev/{crc}.vivify`. The CRC is Unity's AssetBundle
CRC from the build manifest, not a CRC32 of the file — it is a lookup key, not something we can
recompute.

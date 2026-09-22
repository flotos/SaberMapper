# 02 — End Times

| | |
|---|---|
| Song | End Times — Andrew Prahlow (Outer Wilds) |
| Mapper | Chaimzy |
| BeatSaver | [43a24](https://beatsaver.com/maps/43a24) · hash `b4acc042f6541c06e57a384fa9796a10c45ff558` |
| BPM / length | 128 · 157 s |
| Environment | DefaultEnvironment |
| Schema | Info 2.1.0, difficulty 3.2.0 |
| Requirements | Noodle Extensions, Chroma, Vivify |
| Local | `workspace/corpus/extrasensory/downloads/02-43a24.zip` · `extracted/02-43a24/` |

Map 2 of 10.

## Concept

An Outer Wilds piece, built around the game's spacesuit HUD. The asset list is unambiguous about it:
`o2gauge.mat`, `o2arrow.mat`, `fuelarrow.mat`, `healthvignette.mat`, `eyes.mat`. The player is put
inside the suit and the map's interface becomes the instrument panel.

Chaimzy's description is a year-long-project note: the map started as "the sun, stars, and you" and
grew as they learned Unity. Swifter is credited for shader help, Aeroluna for the custom UI,
nasafrasa for cover art. The single difficulty is labelled `There's more to explore here`.

## Structure

| Characteristic / Difficulty | Label | Notes | Bombs | Walls | NPS | NJS |
|---|---|---|---|---|---|---|
| Standard / Hard | `There's more to explore here` | 32 | 8 | 0 | 0.53 | 16 |

One difficulty. **Thirty-two notes across a 157-second song.** Zero basic light events — the entire
lighting is Vivify. Three environment enhancements.

The notes occupy only about 60 seconds of the 157-second runtime, spanning beats 36–164. Active NPS
across eight windows: 0.7 / 0.1 / 0.8 / 0.3 / 0.8 / 0.1 / 0.7 / 0.8 — an alternation between sparse
phrases and effectively nothing.

## Event program

693 custom events against 32 notes — a ratio of roughly 22:1, the most extreme in the pack.

| Event | Count |
|---|---|
| `InstantiatePrefab` | 194 |
| `SetMaterialProperty` | 175 |
| `DestroyObject` | 170 |
| `AnimateTrack` | 129 |
| `Blit` | 13 |
| `CreateScreenTexture` | 7 |
| `AssignObjectPrefab` | 3 |
| `AssignPlayerToTrack` | 2 |

277 tracks. 196 distinct assets — the largest asset vocabulary in the pack, ahead of `Yoi Okashi` at
101, despite having the fewest notes.

Prefab spawns are spread evenly rather than clustered: roughly 57 in the first 64 beats, then 43, 42,
36 and 16 across the following windows. The scene is continuously rebuilt rather than revealed in
bursts.

## What is distinctive

**Both hands are possessed, the head is not.** Two `AssignPlayerToTrack` calls at beat 0, targeting
`LeftHand` and `RightHand` onto tracks of the same names. The sabers become scene objects the map can
drive, while the camera stays with the player. This is the opposite choice from `Breezer` and
`Lifelike`, which move the whole player and leave the hands alone. For a HUD-inside-a-suit concept it
is the right split: the panel moves with your hands, the world does not lurch.

**Diegetic UI via `CreateScreenTexture`.** Seven screen textures plus a `uistuff` track plus the gauge
and arrow materials means the suit readouts are rendered to texture and composited, not faked with
geometry. This is the cleanest example in the pack of Vivify used for *interface* rather than
spectacle.

**Generated track names.** `floatingNote_Z1`, `floatingNote_Z2`, `floatingNote_Z3` and 277 tracks total
against 32 notes. `_editors` lists ChroMapper and **ReMapper** — this was scripted.

**Spawn and destroy are nearly balanced** (194 vs 170). The 24-prefab gap is scene furniture that
persists to the end of the map.

## What to take from it

- The clearest demonstration in the pack that **note count and map quality are unrelated**. At 0.53
  NPS this is by a wide margin the sparsest map in EXSII, and it was the pack's second entry.
- The 22:1 event-to-note ratio is a useful upper bound for what "the scene is the content" looks like.
- Splitting possession by target (`LeftHand` / `RightHand` / `Head` separately) is a real design lever
  with distinct consequences. Our arrangement format should expose the target, not just the track.
- Render-to-texture UI is a discrete, reusable technique: `CreateScreenTexture`, a camera, a set of
  materials on a UI track, then `SetMaterialProperty` to drive the readouts.
- Caution: this map would not suit the player profile in `PLAYER.md` as a gameplay target at all. It is
  a reference for *presentation technique*, and nothing about its density should be copied toward a
  6.5–8 star arrangement.

## Required assets

Not in the BeatSaver zip (except where noted) — Vivify fetches these from LunarRepo at play
time, keyed by the checksum in `Info.dat`.

| Platform | `_assetBundle` CRC | Download | Local |
|---|---|---|---|
| windows2019 | `388412152` | [`388412152.vivify`](https://cdn.repo.totalbs.dev/388412152.vivify) | not downloaded |
| windows2021 | `4245253238` | [`4245253238.vivify`](https://cdn.repo.totalbs.dev/4245253238.vivify) | `02-43a24_bundleWindows2021.vivify` (16.68 MB) |
| android2021 | `268337194` | [`268337194.vivify`](https://cdn.repo.totalbs.dev/268337194.vivify) | not downloaded |

Resolution rule: `https://cdn.repo.totalbs.dev/{crc}.vivify`. The CRC is Unity's AssetBundle
CRC from the build manifest, not a CRC32 of the file — it is a lookup key, not something we can
recompute.

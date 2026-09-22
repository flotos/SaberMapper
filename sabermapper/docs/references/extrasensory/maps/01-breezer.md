# 01 — Breezer

| | |
|---|---|
| Song | Breezer — Jaroslav Beck |
| Credited mapper | Ján Ilavský (uploaded by Droobix) |
| BeatSaver | [43a47](https://beatsaver.com/maps/43a47) · hash `4944e7285d06bd452c0e7089e1e94bdfd807626f` |
| BPM / length | 112.5 · 173 s |
| Environment | TriangleEnvironment |
| Schema | Info 2.1.0, difficulties 3.3.0 |
| Requirements | Noodle Extensions, Vivify, Chroma |
| Local | `workspace/corpus/extrasensory/downloads/01-43a47.zip` · `extracted/01-43a47/` |

Map 1 of 10. The pack's opener.

## Concept

A found-footage bit. Droobix's description frames the map as a recovered build of a very old,
unstable version of Beat Saber — corrupted cover art kept deliberately, a warning that the map "may
break stuff in your game", an invitation to report "anomalies". Breezer and Ján Ilavský's original
chart are the real historical artefacts it is pretending to have excavated. Kane Pixels is credited
for "Sounds, Inspiration", which places the register precisely: analog horror.

Seven credited contributors — the most collaborative entry alongside `3 BIG SHOTS`.

## Structure

| Characteristic / Difficulty | Label | Notes | Bombs | Walls | NPS | NJS |
|---|---|---|---|---|---|---|
| Standard / Normal | `Hard-` | 163 | 36 | 2 | 1.02 | 16 |
| Standard / Hard | — | 190 | 44 | 2 | 1.19 | 16 |
| Lawless / Expert | `Hard+` | 194 | 44 | 2 | 1.22 | 16 |

497 basic light events per difficulty, 3 environment enhancements, no point definitions.

Active-note NPS across eight equal windows: 1.9 / 1.3 / 0.5 / 1.6 / 1.4 / 1.2 / 1.1 / 0.7. The near-
silence at the 25–38% mark is the map's central dropout — the horror beat, not a mapping gap.

## Event program

| | Normal | Hard | Lawless Expert |
|---|---|---|---|
| custom events | 42 | 44 | 39 |
| `AnimateTrack` | 23 | 24 | 23 |
| `Blit` | 6 | 6 | 4 |
| `InstantiatePrefab` | 3 | 3 | 3 |
| `CreateCamera` | 2 | 2 | 1 |
| `AssignTrackParent` | 4 | 4 | 4 |
| `AssignPathAnimation` | 2 | 2 | 2 |
| `AssignPlayerToTrack` | 1 | 1 | 1 |
| `DestroyObject` | 1 | 1 | 1 |

14–15 tracks: `playerTrack`, `corpse0`, `corpse1`, `fall`, `tumble`, `everythingParent`.

Assets: `vhs.mat`, `staticnotebody.mat`, `staticnotearrow.mat`, `br.prefab`, `tumble.prefab`, and on
Lawless only `jaroslav.prefab` and `imagpaste.mat`.

## What is distinctive

**It is the only map in the pack whose show differs per difficulty.** Everywhere else the visual
program is copied verbatim between difficulties; here the Lawless set drops a camera and two blits and
swaps in two assets the Standard set never touches. The Lawless characteristic exists precisely so the
"unstable build" can misbehave differently.

**It is the only map that ships its Vivify bundles inside the BeatSaver zip.** All three —
`bundleWindows2019.vivify`, `bundleWindows2021.vivify`, `bundleAndroid2021.vivify`, roughly 11.5 MB
each — are in the download, which is why this zip is 43.5 MB against a pack median of 7.1 MB. Every
other map fetches its bundles from LunarRepo at play time instead.

That accident makes this map the pack's **integrity reference**: because a known-good bundle ships
here, the LunarRepo copy of the same bundle can be checked against it. It is byte-identical, which is
how the other nine downloads were confirmed authentic. Breezer is also the one map whose
`android2021` bundle 404s on LunarRepo — it exists only in this zip and in droobix's repo.

**Track names carry the narrative.** `corpse0`, `corpse1`, `fall`, `tumble` are not decorative
labels — they are the beats of the story, and `AnimateTrack` (23 of ~42 events) is doing character
animation, not visual flourish.

**Player possession is a single setup call.** One `AssignPlayerToTrack` at beat 0 onto `playerTrack`,
with no target, so the whole player rides the track for the entire map. Combined with
`everythingParent` and four `AssignTrackParent` calls, the map builds one parented hierarchy at the
start and then moves the player through it.

## What to take from it

- A sparse chart (1.0–1.2 NPS) can carry a full-length map when the scene is the content. Note count
  is not the deliverable here.
- The mid-map density dropout to 0.5 NPS is a deliberate narrative device. Our composer should be able
  to schedule a near-empty window when the visual program peaks, without treating it as a defect.
- Per-difficulty show variation is possible but rare and expensive. Default to a shared program.
- 114 of 190 notes carry `animation`, `track`, `spawnEffect` and `disableNoteGravity`; all 190 carry
  per-note NJS and offset. Even in the lightest map in the pack, per-note jump control is universal.
- Diegetic framing ("this is a corrupted old build") lets visual glitching read as intentional. Worth
  noting as a category of concept, but it depends on the player trusting the map — it is not a
  technique to reuse casually.

## Required assets

Not in the BeatSaver zip (except where noted) — Vivify fetches these from LunarRepo at play
time, keyed by the checksum in `Info.dat`.

| Platform | `_assetBundle` CRC | Download | Local |
|---|---|---|---|
| windows2019 | `2529316773` | [`2529316773.vivify`](https://cdn.repo.totalbs.dev/2529316773.vivify) | not downloaded |
| windows2021 | `1614546449` | [`1614546449.vivify`](https://cdn.repo.totalbs.dev/1614546449.vivify) | `01-43a47_bundleWindows2021.vivify` (11.53 MB) |
| android2021 | `3440664542` | [`3440664542.vivify`](https://cdn.repo.totalbs.dev/3440664542.vivify) ⚠️ 404 on LunarRepo; ships in the map zip | not downloaded |

Resolution rule: `https://cdn.repo.totalbs.dev/{crc}.vivify`. The CRC is Unity's AssetBundle
CRC from the build manifest, not a CRC32 of the file — it is a lookup key, not something we can
recompute.

**Published source:** [droobix/map-source-files](https://github.com/droobix/map-source-files) — Unity project + all three built bundles

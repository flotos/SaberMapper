# 07 — luminescent

| | |
|---|---|
| Song | luminescent — sxth sns |
| Mapper | nasafrasa |
| BeatSaver | [43a26](https://beatsaver.com/maps/43a26) · hash `334adfdc5bdf2436e601760ebf53e04560ed71a6` |
| BPM / length | 170 · 167 s |
| Environment | DefaultEnvironment |
| Schema | Info 2.1.0, difficulties 3.2.0 |
| Requirements | Noodle Extensions, Chroma, Vivify |
| Local | `workspace/corpus/extrasensory/downloads/07-43a26.zip` · `extracted/07-43a26/` |

Map 7 of 10. Marked **PC only, not for Quest** (no `_android2021` bundle declared). The mapper's
description carries an explicit photosensitivity warning.

## Concept

Colour as the whole subject. nasafrasa's note amounts to "I like the colours". The asset list is a
numbered skybox series — `skybox1.1.mat` through `skybox1.5.mat` and on — which is the map in
miniature: the sky is swapped and cross-faded as a sequence of materials.

This is nasafrasa's second entry, and it sits at the opposite technical extreme from their other map
`Lifelike` (86 events, almost pure geometry). Same mapper, same pack, two nearly disjoint techniques.

## Structure

| Characteristic / Difficulty | Label | Notes | Arcs | Chains | NPS | NJS |
|---|---|---|---|---|---|---|
| Standard / Hard | `fluorescent` | 551 | 16 | 5 | 3.52 | 16 |
| Standard / ExpertPlus | `luminescent` | 712 | 18 | 6 | 4.54 | 16 |

Zero bombs, zero walls. 66 basic light events, 7 environment enhancements, 1 declared material.

Note the difficulty gap: **Hard to ExpertPlus with nothing between**. The labels again name variations
on the song title rather than describing difficulty.

Active NPS across eight windows on Expert+: 3.0 / 4.9 / 5.7 / **6.8** / 5.2 / **2.3** / 4.1 / 4.3. The
peak lands at 45% through and is followed immediately by the pack's sharpest single drop — 6.8 to 2.3.

## Event program

994 custom events, **identical between Hard and ExpertPlus**.

| Event | Count |
|---|---|
| **`SetMaterialProperty`** | **536** |
| **`Blit`** | **239** |
| `AnimateTrack` | 141 |
| `AnimateComponent` | 44 |
| `InstantiatePrefab` | 17 |
| `DestroyObject` | 17 |

**6 tracks only** — `Buildup1Track`, `Buildup1Left`, `Buildup1Right`, `MainNoteTrack`,
`RM_environmentFog`, `Mirror`. 27 assets.

Blit density by 64-beat window: 0, 35, 38, **88**, 10, 0, 55, 13. The 88-blit window is the map's
centrepiece, and it coincides with the 6.8 NPS peak rather than with the trough.

## What is distinctive

**The purest post-process map in the pack.** 775 of 994 events — 78% — are `SetMaterialProperty` or
`Blit`. Only 17 prefabs, exactly matched by 17 destroys. The spectacle is entirely full-screen shader
work over a fixed scene.

**Six tracks for 712 notes.** The most extreme track economy in EXSII. `MainNoteTrack` carries the
chart; `Buildup1Left` / `Buildup1Right` handle a hand-split section; `Mirror` and `RM_environmentFog`
are scene elements. Note-level `animation` appears on 296 of 712 notes, but the coordination happens on
those few shared tracks.

**`RM_` prefix confirms ReMapper.** `RM_environmentFog` is a generated name; `_editors` lists
ChroMapper and ReMapper. The 536 material-property calls are unmistakably programmatic — nobody hand-
places that many keyframes.

**44 `AnimateComponent` calls** — the heaviest use in the pack, and one of only two maps to use the
event at all. This drives Beat Saber's own components (fog, tube bloom) rather than bundle materials,
so the vanilla environment is being animated in step with the custom shaders.

**Peak density and peak visual intensity are simultaneous, then both collapse.** Unlike `3 BIG SHOTS`,
which alternates them, this map stacks them and then empties out. The 2.3 NPS trough right after the
88-blit window is a recovery bar for the player, not a visual set-piece.

## What to take from it

- **A whole map can be built from two event types.** If the concept is colour, light or texture, the
  scene can stay fixed and `Blit` plus `SetMaterialProperty` will carry it. This is the cheapest
  high-impact Vivify technique to generate programmatically — it is a timeline of property keyframes,
  which is exactly the shape our arrangement format already handles well.
- A numbered material series (`skybox1.1` … `skybox1.5`) cross-faded over time is a directly reusable
  pattern for sectional visual change.
- `AnimateComponent` on vanilla fog and bloom is how custom shader work is kept from looking bolted on.
  Animate the game's own environment in step with the bundle.
- **Stacking peak density with peak visuals is viable if a real recovery follows.** The 6.8 → 2.3 drop
  is the price of the 88-blit window. Our strain model should treat a visual peak as *additive* load
  and require the trough afterwards.
- Six tracks is enough. Track proliferation in other maps is a consequence of per-note choreography,
  not a requirement of ambitious visuals.
- At 4.54 NPS on Expert+ this is mid-range for the pack and still well under the player's historical
  band in `PLAYER.md` — another reminder that EXSII is a presentation reference, not a difficulty one.

## How the idea follows from the song

**Song.** sxth sns' luminescent (Rushdown, 2021) is melodic dubstep; streaming listings place it on
the *watercolours* EP. Lyric content is not verified here. The mapper's note is that they like the
colours.

**Verified in the files (Expert+).** No `AssignPlayerToTrack`: possession `none`. Skies are swapped
as whole prefabs: galaxy and stars at beat 0; fractal `sky2` at 104 (36.7 s); speckles `sky3` at 168;
fractal again at 200; galaxy at 262, then nebula, water, mountains, stars and streaks at 265
(93.5 s); galaxy at 360; `sky6` ("Swirl") at 392 (138.4 s) to the end at 472. Blits: none before 96;
12–25 per 16 beats in 96–159 and 192–255; none in 272–351; 7–16 per 16 beats from 384. `sky2.mat`
cycles through #007fff, #ff00ff, #7f00ff and #00ffff over 115 keyframes. Notes per 16 beats fall from
43–48 in 192–255 to 7–18 in 272–351.

**Interpretation.** Colour is the subject, and the song's form decides when it changes: quiet space
for the intro, a saturated fractal with glitch and scanlines for the drops, a still landscape for the
break, and one new sky kept for the last drop. Motifs: sky swaps, colour cycling, glitch pulses.
Held for the end is the swirl sky at 392, the only sky not seen earlier. The camera stays put; the
full-screen effects do the moving.

Sources: [BeatSaver 43a26](https://beatsaver.com/maps/43a26) ·
[luminescent (Rushdown, SoundCloud)](https://soundcloud.com/rushdownrecs/sxth-sns-luminescent) ·
[luminescent (Beatport)](https://www.beatport.com/track/luminescent/15499983) ·
[luminescent (Spotify)](https://open.spotify.com/track/3i1oRRhb4k2kQ8Ys3YOuZj)

## Required assets

Not in the BeatSaver zip (except where noted) — Vivify fetches these from LunarRepo at play
time, keyed by the checksum in `Info.dat`.

| Platform | `_assetBundle` CRC | Download | Local |
|---|---|---|---|
| windows2019 | `2125274369` | [`2125274369.vivify`](https://cdn.repo.totalbs.dev/2125274369.vivify) | not downloaded |
| windows2021 | `3576816246` | [`3576816246.vivify`](https://cdn.repo.totalbs.dev/3576816246.vivify) | `07-43a26_bundleWindows2021.vivify` (6.52 MB) |
| android2021 | — | *not declared* | — |

Resolution rule: `https://cdn.repo.totalbs.dev/{crc}.vivify`. The CRC is Unity's AssetBundle
CRC from the build manifest, not a CRC32 of the file — it is a lookup key, not something we can
recompute.

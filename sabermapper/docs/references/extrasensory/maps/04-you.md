# 04 — you

| | |
|---|---|
| Song | you — Simplifi |
| Mapper | Swifter |
| BeatSaver | [43a1f](https://beatsaver.com/maps/43a1f) · hash `d265d40935983502ad6f05ddeb5417f3e37c2290` |
| BPM / length | 70 · 157 s |
| Environment | BillieEnvironment |
| Schema | Info 2.1.0, difficulties 3.2.0 |
| Requirements | Chroma, Noodle Extensions, Vivify |
| Local | `workspace/corpus/extrasensory/downloads/04-43a1f.zip` · `extracted/04-43a1f/` |
| Public source | **[github.com/Swifter1243/you_map](https://github.com/Swifter1243/you_map)** |

Map 4 of 10. The single most valuable map in the pack for our purposes, because the full authoring
project is public.

## Concept

Swifter states that everything in the map was created from scratch by them, and that the map marks the
end of one chapter and the start of another — they had wanted to release a Vivify map for as long as
they had been a Beat Saber creative. Swifter is also the author of **VivifyTemplate**, the Unity
project scaffold the official documentation recommends, and appears in the credits of four other EXSII
maps for shader and optimisation help.

The asset list reads as a glass-and-light piece: `glassnote.mat`, `glassarrow.mat`,
`glassnote_debris.mat`, `saberguide.mat`, `introskybox.mat`, `prefab_ambientflare`.

## Structure

| Characteristic / Difficulty | Notes | Chains | NPS | NJS | Offset |
|---|---|---|---|---|---|
| Standard / Normal | 160 | 5 | 1.11 | **8** | **-0.25** |
| Standard / Hard | 160 | 5 | 1.11 | **8** | **-0.25** |

Zero bombs, zero walls, zero arcs. Zero basic light events. One environment enhancement. Both
difficulties have the same note count — they differ only in chart content, not volume.

`_colorLeft` and `_colorRight` are overridden at the difficulty level.

Active NPS across eight windows: 1.0 / 1.1 / 1.4 / 1.8 / 0.8 / 1.4 / 1.0 / 0.4.

## Event program

1247 custom events, **identical between Normal and Hard**.

| Event | Count |
|---|---|
| **`AssignPathAnimation`** | **826** |
| `SetMaterialProperty` | 340 |
| `AnimateTrack` | 40 |
| `InstantiatePrefab` | 15 |
| `AssignObjectPrefab` | 10 |
| `DestroyObject` | 6 |
| `Blit` | 4 |
| `AssignPlayerToTrack` | 3 |
| `SetCameraProperty` | 1 |
| `SetRenderingSettings` | 1 |
| `AssignTrackParent` | 1 |

99 tracks, 44 assets.

## What is distinctive

**NJS 8 with a -0.25 offset — the slowest note approach in the pack** by a factor of two. Every other
EXSII map sits at 16–20. At 70 BPM with 160 notes, the notes drift in. This is a deliberate pairing:
the visual program needs the player looking at the scene, so the chart gives them time.

**`AssignPathAnimation` dominates: 826 of 1247 events, two thirds of the program.** No other map in
the pack is remotely path-driven like this (`42-flux` is second at 378). Track names such as
`dropPath2_143`, `dropPath2_144`, `dropPath2_145` are a generated sequence — one path per note or per
small group, each individually animated along its approach. This is what NJS 8 buys: with a slow
approach there is room to choreograph the entire flight path of every note.

**Three-way possession.** `player` (no target), `head` → `Head`, and `rightHand` → `RightHand`, all at
beat 0. The most granular possession setup in the pack. The right hand is tracked and the left is not,
which is an asymmetric, deliberate choice.

**101 of 160 notes carry `worldRotation`.** Only map in the pack to use the field at scale. Combined
with the path animation, notes arrive from rotated world frames rather than the standard lane.

**Ten `AssignObjectPrefab` calls** — custom note bodies, arrows, debris and a saber guide. The glass
note model is the map's signature and it is swapped in per section rather than once.

## What to take from it

- **Read the published source.** It is a Deno + TypeScript (ReMapper) project with a `you_unity/`
  folder beside the `.dat` files: `script.ts`, `deno.json`, `scripts.json`. This is the reference
  architecture for a programmatic Vivify pipeline, and it is the closest public analogue to what
  SaberMapper is trying to be. Swifter published it explicitly so others could study how it works, and
  asks for transformative use rather than copying — which is exactly our intended use.
- **Low NJS is a legitimate tool, not a beginner setting.** If a section's visual program needs
  attention, drop the approach speed and choreograph the note paths. Our composer currently has no
  reason to ever emit NJS 8; this map is the argument for it.
- Path animation per note is expensive to hand-author and trivial to generate. It is the single
  highest-leverage generated feature in the pack for a programmatic mapper.
- Both difficulties having identical note counts is a reminder that "downmap" can mean *simpler
  patterns at the same density*, not *fewer notes*.
- `worldRotation` plus path animation plus a slow NJS is a coherent, reusable bundle. The three
  reinforce each other; using `worldRotation` at NJS 16+ would be much harder to read.

## How the idea follows from the song

**Song.** "you" by Simplifi (Scan Records, 2022), a slow electronic track at 70 BPM; lyric content is
not verified here. Swifter frames the map as the end of one chapter and the start of another, and
hands it to the player to keep.

**Verified in the files and the public script.** The script names the sections: intro 0, ambient
34, ambient rise 70, buildup 98, drop 112.5, outro 140.75, text 172.75. Three `AssignPlayerToTrack`
at beat 0: `player` (no target), `Head`, `RightHand`. At beat 70 (60 s) the `head` track moves 0.8
up and 4 m back over 28 beats and returns, while a saber-guide material fades in to show where the
sabers are; the script calls this an out-of-body experience. Beats 98–111.25 spawn a flower,
explosions, a build-up panel, particles and a sphere. At 112.5 (96.4 s) two drop Blit passes and
`dropscene` start, and 742 of the 826 `AssignPathAnimation` events fall in beats 112–143. At 140.75
the ending scene replaces the drop; at 172.75 outro text appears, the head is sent 10 km away and
the right hand hidden.

**Interpretation.** The title and the description point at the player, and the map makes that
literal: once, the view leaves the body and looks back at the player, and every note is choreographed
around them. Motifs: glass notes, a skybox that changes per section, light flares. Key moments: the
out-of-body rise at 70, the drop at 112.5, which is held for the end as the biggest scene change, and
the closing text. Possession is `head` in effect, with the whole player and the right hand also
tracked.

Sources: [BeatSaver 43a1f](https://beatsaver.com/maps/43a1f) ·
[Swifter1243/you_map](https://github.com/Swifter1243/you_map) ·
[you_map script.ts](https://raw.githubusercontent.com/Swifter1243/you_map/main/script.ts) ·
[Simplifi — you (Scan Records)](https://soundcloud.com/scanrecs/simplifi-you)

## Required assets

Not in the BeatSaver zip (except where noted) — Vivify fetches these from LunarRepo at play
time, keyed by the checksum in `Info.dat`.

| Platform | `_assetBundle` CRC | Download | Local |
|---|---|---|---|
| windows2019 | `2512046672` | [`2512046672.vivify`](https://cdn.repo.totalbs.dev/2512046672.vivify) | not downloaded |
| windows2021 | `439194816` | [`439194816.vivify`](https://cdn.repo.totalbs.dev/439194816.vivify) | `04-43a1f_bundleWindows2021.vivify` (1.52 MB) |
| android2021 | `1563550775` | [`1563550775.vivify`](https://cdn.repo.totalbs.dev/1563550775.vivify) | not downloaded |

Resolution rule: `https://cdn.repo.totalbs.dev/{crc}.vivify`. The CRC is Unity's AssetBundle
CRC from the build manifest, not a CRC32 of the file — it is a lookup key, not something we can
recompute.

**Published source:** [Swifter1243/you_map](https://github.com/Swifter1243/you_map) — Unity project + ReMapper script, **no built bundle**

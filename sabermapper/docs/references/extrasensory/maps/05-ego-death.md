# 05 — Ego Death

| | |
|---|---|
| Song | Ego Death — Xtrullor |
| Mapper | Sands |
| BeatSaver | [43a2e](https://beatsaver.com/maps/43a2e) · hash `80fd2689ce77bdee4b31d61debf4dc9de764c1aa` |
| BPM / length | 180 · 126 s |
| Environment | RocketEnvironment |
| Schema | Info 2.1.0, difficulties 3.3.0 |
| Requirements | Chroma, Noodle Extensions, Vivify |
| Local | `workspace/corpus/extrasensory/downloads/05-43a2e.zip` · `extracted/05-43a2e/` |

Map 5 of 10. The smallest download in the pack at 1.5 MB.

## Concept

A malware bit. The difficulty labels are the joke: Expert is `Install BS Antivirus`, Expert+ is
`Install Vivify.dll`, and the description warns the map "may be a little dangerous" and suggests
bringing an antivirus along. Assets — `boss.prefab`, `electricfuzz.prefab`, `rain.prefab`,
`platform.prefab`, `introanim.prefab` — point at a boss-fight framing over a corrupted-system look.

Like `Breezer`, it plays at being something that has gone wrong with the game. Unlike `Breezer`, it
does it with post-processing rather than narrative.

## Structure

| Characteristic / Difficulty | Label | Notes | NPS | NJS |
|---|---|---|---|---|
| Standard / Expert | `Install BS Antivirus` | 181 | 2.15 | 16 |
| Standard / ExpertPlus | `Install Vivify.dll` | 318 | 3.79 | 16 |

Zero bombs, zero walls, zero arcs, zero chains, zero basic light events. 14 environment enhancements.

Active NPS across eight windows on Expert+: 2.9 / 3.6 / 4.1 / 3.4 / 4.3 / 3.7 / 3.9 / 4.4. **The
flattest and most monotonic profile in the pack** — it starts near its ceiling and stays there. Where
most EXSII maps carve out density troughs for the visuals, this one does not.

## Event program

507 custom events, **identical between Expert and Expert+**.

| Event | Count |
|---|---|
| `AnimateTrack` | 213 |
| `Blit` | 149 |
| `SetMaterialProperty` | 125 |
| `InstantiatePrefab` | 12 |
| `DestroyObject` | 7 |
| `AssignPathAnimation` | 1 |

**12 tracks** — `endNotes`, `ScaleNotes`, `intronotes`, `introanim`, `platTrack`, `wow`. 14 assets.

Blit density by 64-beat window: 0, 39, 35, 48, 26, 1. A steady post-process pressure through the body
of the map rather than a reveal structure.

## What is distinctive

**Shared tracks instead of per-note tracks.** Only 12 tracks for 318 notes, and the note `customData`
carries *no* `animation` field at all — just `track`, per-note NJS, offset, and
`disableBadCutSaberType` on every note. Notes are animated in groups (`intronotes`, `endNotes`,
`ScaleNotes`) via 213 `AnimateTrack` calls on those shared tracks.

This is the clean counterexample to `you` and `42-flux`, which animate notes individually. Grouped
track animation gets you coordinated mass movement — whole phrases scaling or sweeping together — at a
fraction of the event cost. 507 events do the work that `you` spends 1247 on.

**`disableBadCutSaberType` on all 318 notes.** The most systematic use of the field in the pack. With
notes being scaled and moved as groups, the map removes a whole class of unfair bad cuts rather than
hoping the movement stays legible.

**Post-process heavy, geometry light.** 274 of 507 events are `Blit` or `SetMaterialProperty`, against
12 prefabs. Together with `luminescent` and `42-flux` this is one of the pack's three post-process
maps.

**The only map whose density does not dip.** At 180 BPM with a flat ~4 NPS ceiling, this is among the
closest EXSII entries to a conventionally-charted map. It is also the only one where the visual
program and the note stream run at full intensity simultaneously for the whole runtime.

## What to take from it

- **Grouped track animation is the cost-efficient technique.** If a section wants coordinated note
  movement rather than individual choreography, assign a shared track and animate it. Reserve per-note
  paths for moments that need them. This is a direct, implementable rule for our composer.
- `disableBadCutSaberType` should be emitted automatically on any note whose position or scale is being
  animated. This map treats it as mandatory, and that is the right default.
- A flat density profile is viable when the visual technique is post-processing rather than scene
  reveals. Full-screen shader work does not compete for the player's attention the way a spawning
  scene does — the player keeps looking at the same place.
- 12 tracks and 14 assets is a very small vocabulary for a headline map. Constraint is not a
  limitation here; it is what makes 507 events enough.
- Both difficulties sharing one show while differing by 137 notes (181 vs 318) is the pack's standard
  downmapping model, and the cleanest example of it.

## How the idea follows from the song

**Song.** Xtrullor's Ego Death (2019, album *1st Era*) is harsh, orchestral-leaning dubstep with no
lyrics. The original runs 3:56; the map's audio is 126 s. The title names the dissolution of the
self; Sands frames the map as malware (labels install "BS Antivirus" and "Vivify.dll").

**Verified in the files (Expert+).** No `AssignPlayerToTrack`: possession `none`. Beat 0: a
platform; beat 6: `introanim` with id `download`. Notes run 35–287. Beat 57.5 (19 s): `boss.prefab`,
never destroyed. Blits start at 65 and hold at 4–14 per 16 beats until 287; `warp.mat` and `umm.mat`
appear only in 65–191, `brightness.mat` from 128, `kick.mat` throughout. Beats 172–180 (57–60 s): the
platform scales, rain and four `electricfuzz` prefabs spawn, the platform is destroyed, and note
animation moves from the `ScaleNotes` group (63–171) to `endNotes` (175–286). At 287 (95.7 s) the fuzz
is removed and a second platform spawns; beats 288–342 have no notes and no events. At 342.8
(114.3 s) `reddeath.prefab`, a `hit` prefab and a final kick Blit fire and the rain is removed.

**Interpretation.** The show reads as an infection: a download installs itself, a boss takes the
scene, the second half turns to storm. Motifs: a kick-locked post-process pulse, notes that scale
and dissolve as groups, the platform under the player (built, destroyed, rebuilt). Held for the end
is the red "death" after a long empty stretch: the title's event arrives as one image once the chart
has stopped. The flat density profile follows a track that stays near full intensity.

Sources: [BeatSaver 43a2e](https://beatsaver.com/maps/43a2e) ·
[Ego Death on Bandcamp](https://xtrullor.bandcamp.com/track/ego-death) ·
[Ego Death on Apple Music](https://music.apple.com/us/song/ego-death/1482323593)

## Required assets

Not in the BeatSaver zip (except where noted) — Vivify fetches these from LunarRepo at play
time, keyed by the checksum in `Info.dat`.

| Platform | `_assetBundle` CRC | Download | Local |
|---|---|---|---|
| windows2019 | `377480426` | [`377480426.vivify`](https://cdn.repo.totalbs.dev/377480426.vivify) | not downloaded |
| windows2021 | `2195937566` | [`2195937566.vivify`](https://cdn.repo.totalbs.dev/2195937566.vivify) | `05-43a2e_bundleWindows2021.vivify` (4.24 MB) |
| android2021 | `3817251849` | [`3817251849.vivify`](https://cdn.repo.totalbs.dev/3817251849.vivify) | not downloaded |

Resolution rule: `https://cdn.repo.totalbs.dev/{crc}.vivify`. The CRC is Unity's AssetBundle
CRC from the build manifest, not a CRC32 of the file — it is a lookup key, not something we can
recompute.

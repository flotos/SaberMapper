# Extra Sensory II — the Vivify reference pack

Retrieved 2026-09-22 for local study. Ten maps, all downloaded and extracted under
`sabermapper/workspace/corpus/extrasensory/` (git-ignored; treat as user data).
Machine-readable facts for every map and difficulty are in [map-index.json](map-index.json).
Per-map write-ups are in [maps/](maps/).

## What "Extra Sensory" is

Extra Sensory is a showcase event run by the TotalBS team. The first edition (2020) released five
maps built on Noodle Extensions and Chroma. **Extra Sensory II (EXSII)**, released 2025-01-26, is the
edition that matters here: it was built to launch **Vivify**, and all ten of its maps require it.
EXSII is the pack people mean by "the Vivify maps".

EXSII was not only a map drop. It ran as a live sight-read elimination tournament through the
**Synapse** mod — roughly 900 players in the first run, about 1900 in the second. That framing
explains much of the design: every map had to land on first sight, across a wide range of skill
levels, with no prior practice. Nothing in the pack rewards memorisation.

There is **no Extra Sensory III** as of this retrieval.

## What Vivify actually adds

Vivify lets a mapper compile a Unity **AssetBundle** and then load, instantiate and drive its contents
from beatmap events. The bundle can hold shaders, post-process materials, 3D models, animators,
textures and audio. Before Vivify, a mapper could move and recolour the objects the game already had;
with Vivify they ship their own scene.

Hard constraints, confirmed against the pack:

- **v3 beatmaps only.** Every EXSII difficulty is schema 3.2.0 or 3.3.0 (one Info.dat is 2.0.0, but
  its difficulty files are v3).
- The bundle sits beside the map as `bundleWindows2019.vivify`, `bundleWindows2021.vivify`,
  `bundleAndroid2021.vivify`, and `Info.dat` carries an `_assetBundle` block per platform. All ten maps
  declare that block. Nine of the ten do **not** ship the `.vivify` files inside the BeatSaver zip;
  they are fetched at play time from LunarRepo — see [The asset bundles](#the-asset-bundles).
- `"Vivify"` must be listed in the difficulty's `_requirements`.
- Asset paths inside events are lowercase.
- Unity 2019.4.28f1 targets game 1.29.1; 2021.3.16f1 targets 1.30.0+. Single-pass stereo rendering.

**Vivify does not replace Noodle Extensions or Chroma — it sits on top of them.** All ten maps require
all three. Vivify owns the scene; Noodle owns where the notes are and how they move; Chroma owns
colour. Two maps also list AudioLink.

### The event vocabulary

| Event | What it does |
|---|---|
| `InstantiatePrefab` / `DestroyObject` | spawn and tear down bundle content, bound to an id and a track |
| `SetMaterialProperty` | animate a named material's float/colour/vector/texture/keyword over a duration |
| `SetGlobalProperty` | same, but global to every shader |
| `Blit` | run a material as a full-screen post-process pass |
| `CreateScreenTexture` / `CreateCamera` / `SetCameraProperty` | render-to-texture, secondary cameras, depth modes, clear flags, culling |
| `AssignObjectPrefab` | replace notes, bombs, arcs or sabers with custom models |
| `SetAnimatorProperty` | drive Unity Animator parameters |
| `SetRenderingSettings` | change Unity render/quality/XR settings mid-map |

Heck's own events do the motion work alongside these: `AnimateTrack`, `AssignPathAnimation`,
`AssignTrackParent`, `AssignPlayerToTrack`, `AnimateComponent`.

## The asset bundles

**BeatSaver does not package `.vivify` files with map uploads.** This is the missing piece that makes
the pack look incomplete on first download: nine of the ten zips contain only audio, cover art,
`Info.dat` and the difficulty files. Only `Breezer` ships its bundles inside the zip.

The bundles are hosted separately on **LunarRepo** (<https://repo.totalbs.dev/>), Aeroluna's asset
repository, and **Vivify's auto-downloader fetches them at play time**, verifying each against the
checksum in `Info.dat`. Maps stay on BeatSaver; assets come from LunarRepo.

The resolution rule is simple and fully deterministic:

```
https://cdn.repo.totalbs.dev/{crc}.vivify
   where {crc} = Info.dat -> _customData._assetBundle.<platform>
```

So `Breezer`'s `_windows2021: 1614546449` resolves to
`https://cdn.repo.totalbs.dev/1614546449.vivify`. A listing API exists at
`https://repo.totalbs.dev/api/v1/maps`, which returns each map's versions with a `bundles` block per
platform, but it is not needed — the checksum in `Info.dat` is the lookup key.

**The `_assetBundle` value is Unity's AssetBundle CRC from the build manifest, not a CRC32 of the
`.vivify` file.** It cannot be recomputed outside Unity; treat it as a lookup key and as Vivify's own
integrity check, not as something our tooling can independently verify.

### Local status

All 26 declared bundles resolve on LunarRepo except `Breezer`'s `android2021`, which 404s there but
ships inside the map zip. The `windows2021` bundle for all ten maps is downloaded to
`workspace/corpus/extrasensory/bundles/` (87.1 MB); `windows2019` and `android2021` resolve at the same
URL pattern and were not fetched. Full detail, including sizes and SHA-256s, is in
`workspace/corpus/extrasensory/bundle-manifest.json`.

Authenticity was confirmed two independent ways rather than assumed:

- `Breezer`'s `windows2021` from LunarRepo is **byte-identical** to the bundle shipped inside
  `Breezer`'s own BeatSaver zip.
- `3 BIG SHOTS`'s `windows2021` from LunarRepo is **byte-identical** to the copy published in
  `droobix/map-source-files`.
- All ten downloaded files carry the `UnityFS` magic header.

### Published sources

Three of the ten maps have public authoring projects, which are worth more than the compiled bundles:

| Map | Source | Contains |
|---|---|---|
| `you` | [Swifter1243/you_map](https://github.com/Swifter1243/you_map) | Deno + ReMapper `script.ts`, full Unity project. **No built bundle** — it is built from the project. |
| `Breezer` | [droobix/map-source-files](https://github.com/droobix/map-source-files) | Unity project, all three built `.vivify` bundles, `bundleinfo.json` |
| `3 BIG SHOTS` | [droobix/map-source-files](https://github.com/droobix/map-source-files) | Unity project, all three built `.vivify` bundles (31 MB each), ReMapper `but.ts` |

Both Unity projects are built on **[VivifyTemplate](https://github.com/Swifter1243/VivifyTemplate)**,
Swifter's scaffold — the same one the official docs recommend — and both vendor AudioLink.

`bundleinfo.json` is the most directly useful artefact for us: it is a machine-readable index of every
material in the bundle with its asset path and its typed, defaulted shader properties
(`{"_Amount": {"Float": "1"}}`). That is exactly the schema a composer needs in order to emit valid
`SetMaterialProperty` events without guessing property names or types. **If we ever generate Vivify
output, we should emit and consume a `bundleinfo.json` of our own.**

## What the pack teaches — findings from the files

These are the patterns that hold across all ten maps, measured rather than assumed.

### 1. The visual budget is enormous; the note budget is small

| | notes | active NPS | bombs | walls |
|---|---|---|---|---|
| median EXSII top difficulty | 299 | 3.0 | 0 | 0 |
| busiest (Yoi Okashi, E+) | 2475 | 8.3 | 185 | 260 |
| sparsest (End Times, Hard) | 32 | 0.5 | 8 | 0 |

Seven of the ten top difficulties have **zero walls**. Six have **zero bombs**. Meanwhile custom-event
counts run from 39 to 7785. The pack spends its complexity on the scene, not on the note stream.

This is the single most important calibration point: **a Vivify-quality map is a presentation target,
not a difficulty target.** Most of EXSII sits well below the 6.5–8 star band in `PLAYER.md`. Raising
note density to meet the player's skill and raising visual load are independent decisions, and EXSII
deliberately trades one against the other.

### 2. The show is authored once; only the note layer is downmapped

In six of the ten maps (`Lifelike`, `you`, `Ego Death`, `luminescent`, `Yoi Okashi`, `Through The
Screen`) the custom-event array is **identical across difficulties** — same count, same tracks, same
assets. The easier difficulty is the same film with a different note chart over it.

`3 BIG SHOTS` and `42-flux` diverge only slightly (709 vs 748, and 1485 vs 1602 events); the extra
events are note-track animations that exist only because the harder chart has more notes to animate.
Only `Breezer` genuinely varies its show per difficulty, and it is the one map with a Lawless set.

**Implication for our pipeline:** the visual program should be a separate, difficulty-independent
document that the compiler merges into every difficulty. Track names referenced by note-level
animation are the only coupling point.

### 3. Per-note NJS override is the default, not an exception

Nine of ten top difficulties set `noteJumpMovementSpeed` and `noteJumpStartBeatOffset` **on every
single note** — 2475 of 2475 in Yoi Okashi, 712 of 712 in luminescent. The Info.dat NJS is nearly
always a flat 16 and is effectively a placeholder.

This is how the pack gets away with moving notes into strange places: a note that spawns from an
unusual position or along a path gets its own jump speed and offset so it still arrives readable at
the swing point. Reaction time is tuned per note rather than per difficulty.

Companion fields, in rough frequency order across the pack: `track`, `spawnEffect` (usually disabled),
`disableNoteGravity`, `animation`, `disableBadCutSaberType`, `link`, `coordinates`, `worldRotation`,
`uninteractable`, `flip`.

### 4. Two distinct techniques, and they barely overlap

Clustering the maps by what dominates their event array gives two families:

- **Post-process maps** — the spectacle is full-screen shader work. `luminescent` (239 `Blit`, 536
  `SetMaterialProperty`), `Ego Death` (149 `Blit`), `42-flux` (67 `Blit` plus 14 screen textures and
  4 extra cameras). Few prefabs, heavy material animation.
- **Scene maps** — the spectacle is instantiated geometry. `Yoi Okashi` (788 prefabs), `End Times`
  (194 prefabs, 170 destroys), `3 BIG SHOTS` (133 prefabs). Few blits, heavy spawn/destroy churn.

`InstantiatePrefab` and `DestroyObject` counts track each other almost exactly in the scene maps
(194/170, 788/789, 14/14, 17/17, 12/12) — **everything spawned is explicitly destroyed.** Lifetime
management is manual and disciplined. Nothing is left to leak.

### 5. Camera and player possession are used sparingly and deliberately

`AssignPlayerToTrack` appears in six maps, at most three times each, and almost always at beat 0:

- `Breezer`, `Lifelike` — whole player on one track (the camera is moved through the scene).
- `End Times`, `42-flux` — left and right hand tracked separately (the sabers become scene objects).
- `you` — player, head and right hand on three separate tracks.
- `Through The Screen` — a single mid-map possession at beat 194, target `Head`, on a track named
  `noHead?`. The one case where the effect is a timed reveal rather than a setup.

Moving the player is a once-per-map structural decision, not a recurring effect.

### 6. Track counts reveal the authoring method

Track counts split cleanly: 6–21 tracks (`luminescent`, `Ego Death`, `Through The Screen`, `Lifelike`,
`Breezer`) versus 99–774 tracks (`you`, `3 BIG SHOTS`, `42-flux`, `End Times`, `Yoi Okashi`).

The high-count maps have generated track names — `dropPath2_143` through `dropPath2_147`, `lane-8`,
`lane-17`, `floatingNote_Z1`. These were not hand-placed. They came out of **ReMapper**, a TypeScript
library run under Deno that emits the `.dat` files. Five of the ten maps list ReMapper or a custom
script in `_editors`; Swifter published [the full source of `you`](https://github.com/Swifter1243/you_map)
as a Deno project with a Unity folder beside it, explicitly so others can study it.

**This is the workflow to copy.** The map file is a build artifact. A program places the notes and
writes the events; ChroMapper is used for the hand-authored parts and for review. That is close to the
shape SaberMapper already has, which makes EXSII a realistic target rather than an aspirational one.

### 7. Structure follows a reveal, not a difficulty curve

Bucketing the heavy Vivify events by beat shows the same shape repeatedly: a setup burst at beat 0
(cameras, render textures, rendering settings, the initial scene), then discrete spikes at section
boundaries, then a dense final section. `Yoi Okashi` puts 518 of its 788 prefab spawns in a single
64-beat window near the end. `42-flux` front-loads camera and texture declarations, then escalates
blit density to the finish.

NPS profiles do **not** climb monotonically. `luminescent` peaks at 6.8 NPS at 45% through and drops to
2.3 at 62% before recovering. `3 BIG SHOTS` alternates 3.4 / 5.6 / 6.2 / 2.3 / 2.9 / 5.7 / 5.6 / 2.5.
The drops are where the visual is doing the work. Density is a dial the mapper turns down to make room
for spectacle, then back up.

## How to use this for authoring

Concrete rules to carry into SaberMapper composition:

1. Author the visual program as its own difficulty-independent document; merge at compile time.
2. Budget note density *against* visual load per section, not monotonically upward.
3. Emit per-note `noteJumpMovementSpeed` / `noteJumpStartBeatOffset` whenever a note is displaced,
   pathed or parented — do not rely on the difficulty-level NJS.
4. Pair every `InstantiatePrefab` with a `DestroyObject` on the same id. Validate this.
5. Pick one family — post-process or scene — per section. The pack does not blend them.
6. Treat `AssignPlayerToTrack` as a structural, once-per-map decision.
7. Declare `Vivify`, `Chroma` and `Noodle Extensions` together in `_requirements`, and keep asset paths
   lowercase.
8. Remember the pack was built for sight-reading. If a section is only fair once you know it is
   coming, it is not EXSII-quality.

## Rights and completeness

These maps were downloaded from BeatSaver for **local study only**. No redistribution, and no copying
of note arrays or bundle assets into our output. Swifter's public source states the intent plainly:
study and transformative use, not direct copying. Treat that as the standard for the whole pack.

The bundles were fetched from LunarRepo, the official public repository, by the same URL pattern
Vivify's own auto-downloader uses. They are third-party creative assets: study them, do not
redistribute them, and do not copy their contents into our output. Swifter's published source states
the intent for `you` explicitly — study and transformative use, not direct copying — and that is the
right standard for the whole pack.

One gap remains, and it is not closeable:

- **Nothing here is a playtest.** These are structural statistics from the files plus the mappers' own
  published descriptions. No claim about how any of these maps feels in VR is made in these documents.

Two things that are now resolved and were open in the first draft of this document: the asset bundles
*are* obtainable (see [The asset bundles](#the-asset-bundles)), and their absence from the BeatSaver
zips is by design rather than an upload problem.

## Sources

- [Extra Sensory II official site](https://exsii.totalbs.dev/)
- [EXSII BeatSaver playlist](https://beatsaver.com/playlists/797071)
- [Vivify — Getting Started](https://heck.aeroluna.dev/vivify/getting-started-with-vivify/)
- [Vivify — Events reference](https://heck.aeroluna.dev/vivify/events/)
- [Swifter1243/you_map — published map source](https://github.com/Swifter1243/you_map)
- [droobix/map-source-files — published sources for Breezer and 3 BIG SHOTS](https://github.com/droobix/map-source-files)
- [Mawntee/modhcart — modchart resource dump](https://github.com/Mawntee/modhcart)
- [Synapse / Aeroluna](https://aeroluna.dev/synapse)

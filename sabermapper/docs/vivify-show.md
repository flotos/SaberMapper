# Vivify show: schema, compiler, checks and export

Status: Phase A of [vivify-approach.md](vivify-approach.md) as amended by ticket M3 in
`tickets/vivify/base-ticket.md` (2026-09-23). The game is the renderer, so there is no show sheet or
WebGL preview. Every generated visual event records the audio evidence, lyric word, moment or section
boundary it came from (ticket principle 6).

Code: `sabermapper/show.py` (schema, spans, presentation, evidence, storage), `show_compile.py`
(primitive expansion), `show_validation.py` (semantic checks), `vivify.py` (event vocabulary,
requirements, bundle reader, stripping), `vivify_export.py` (ZIP entries), `show_cli.py` (CLI).
Tests: `tests/test_vivify_show.py` with hand-written fixtures in `tests/vivify_fixtures.py`.

## Arrangement 0.2: `presentation`

Arrangement `schema_version` `"0.2"` allows optional `presentation` blocks. Otherwise it is identical to
0.1, and 0.1 stays valid and exports byte-identically (the golden digests are in
`tests/fixtures/vivify/plain-0.1-export-golden.json`). In a 0.1 arrangement, `presentation` is still
an `unsupported_field` error, and unknown keys inside a presentation block are errors in both versions.
Presentation blocks sit in the arrangement, so they follow the section locks and revisions.

Map level (every key optional):

```json
"presentation": {"concept": "glass corridor; the pad swells open the walls",
                 "palette": ["#1a2b3c", [1, 0.5, 0]], "possession": "none"}
```

- `palette`: 1 to 12 colors, each written as `#rrggbb[aa]` or `[r, g, b(, a)]` in 0..1.
- `possession`: one of `none` (the default), `player`, `head`, `hands` or `right_hand`. It is a
  once-per-map decision (see below).
- `note_colors`: `{"left": colour, "right": colour}` (same colour formats). Export writes it as the map's
  colour scheme in Info.dat (`_colorSchemes`, `useOverride: true`; the vanilla twin keeps it) and as
  `_colorLeft`/`_colorRight` in each difficulty's `_customData` for Chroma/SongCore, so notes, arcs and
  sabers match the concept palette. Keep the two hands clearly distinct from each other and from the scene.

Per section (`family` is required, the other keys are optional):

```json
"presentation": {"concept": "grey glass", "family": "post_process",
                 "attention": {"notes": 0.7, "scene": 0.3}, "reveal": false, "note_style": "plain"}
```

- `family`: `post_process`, `scene` or `none`.
- `attention`: `notes` and `scene` each 0..1, summing to at most 1.
- `note_style`: `plain` or `choreographed`. Choreographed sections need per-note NJS and offset.

The compiled beatmap does not depend on presentation. Presentation drives the checks below and
decides whether an export is vivified.

## Show 0.1 (`<project>/show.json`)

The show is project-level and independent of difficulty: one show compiles into every difficulty.
Its revision is the canonical SHA-256 of its JSON, computed the same way as an arrangement revision.
The revision of a project without a show is the string `none`.

```json
{"schema_version": "0.1", "description": "optional", "primitives": [ ... ]}
```

Every primitive has a `kind` and may have an `id` (unique, `[a-z0-9_-]{1,48}`, used to derive stable
track and object names), a `note` (free text) and an `anchor` (see Provenance). Beats are absolute
arrangement beats, written as numbers or rational strings such as `"1/2"`. A primitive usually names
a `section`; its span defaults to that section. `until_section` extends the span to the end of a later
section. `start_beat` and `end_beat` narrow it, but the span must start inside `section`.
Sub-objects that map one to one onto a Vivify, Heck or Chroma structure use the mod's own camelCase
field names, for example `xRatio`, `colorNotes`, `anyDirectionAsset` and `offsetPosition`.

| Primitive | Fields | Expands to |
|---|---|---|
| `setup` | `screen_textures[]` (CreateScreenTexture fields), `cameras[]` (CreateCamera fields), `camera_properties`, `rendering` (`renderSettings`/`qualitySettings`/`xrSettings`), `player_tracks` {Root/Head/LeftHand/RightHand: track} | `CreateScreenTexture`, `CreateCamera`, `SetCameraProperty`, `SetRenderingSettings`, `AssignPlayerToTrack` at beat 0 (one per map) |
| `look` | `section`, `material`, optional `priority`, `pass`, `order`, `source`, `destination`, `easing`, `properties[{id, value, type?}]`, `keyframes[]` | `Blit` over the span, then one `SetMaterialProperty` per keyframe |
| `scene` | `section`, `prefab`, optional `object_id`, `track`, `position`/`localPosition`/`rotation`/`localRotation`/`scale`, `persist`, `animate[]`, `keyframes[]` (with `material`), `animator[]` | `InstantiatePrefab`, `AnimateTrack` per `animate` entry, `SetMaterialProperty` per keyframe, `SetAnimatorProperty` per `animator` entry, `DestroyObject` at span end unless `persist: true` |
| `skin` | `section`, optional `track`, `load_mode`, and `colorNotes`/`bombNotes`/`burstSliders`/`burstSliderElements`/`saber` blocks | `AssignObjectPrefab` at span start. Notes, bombs and chains in the span get the skin track |
| `pulse` | `section`, `property`, `driver`, one target (`material`, `global: true` with `type`, or `track`), optional `type`, `envelope`, `min_gap_beats` (default 1/4), `max_events` | One keyframe burst per evidence item: `SetMaterialProperty`, `SetGlobalProperty` or `AnimateTrack` |
| `possess` | `target` (Root/Head/LeftHand/RightHand), `track`, optional `section`/`beat`, `animate[]` | `AssignPlayerToTrack` plus `AnimateTrack` on that track |
| `env` | optional `section`/`beat`, `environment[]` (Chroma entries), `materials{}` (Chroma materials), `animate[{beat, track, component, fields}]` | `customData.environment`, `customData.materials`, `AnimateComponent` (BloomFogEnvironment, TubeBloomPrePassLight) |
| `path` | `section`, `njs`, `offset`, optional `track`, `colors`, `animation` (per-note), `world_rotation`, `keyframes[]` | `AssignPathAnimation` per keyframe. Notes in the span get `track`, `noteJumpMovementSpeed`, `noteJumpStartBeatOffset`, and `animation`/`worldRotation` where declared |
| `raw` | `event {b, t, d}`, optional `section`, `persist` | The literal event, checked against the event vocabulary and the bundle |

Keyframes on material properties are written as `{beat, property, value | points, duration_beats?,
easing?, type?, anchor?}`. With `value` and a duration, the compiler writes the point definition
`[[previous, 0], [value, 1, easing]]`, where `previous` is the last value it set or the bundle default.
With `points`, the point definition is passed through unchanged. Track, path and component animations
take the Heck property names directly (`offsetPosition`, `dissolve`, `scale`, ...) as point definitions.

Auto-generated names: `sm_scene_<id>` for scene object ids and tracks, `sm_skin_<id>` and
`sm_path_<id>` for tracks. When a primitive has no `id`, its index is used instead.

### Drivers (pulse)

```json
{"source": "onsets", "layer": "drums", "detector": "spectral_flux", "min_strength": 0.6, "run": "RUN_ID?"}
{"source": "sustains", "layer": "vocals", "min_strength": 0.3, "min_seconds": 0.5, "shapes": ["rise"]}
{"source": "moments", "kinds": ["drop"], "min_strength": 0.5}
{"source": "lyrics", "words": ["light"]}
```

- `onsets` and `sustains` come from the project's newest musical evidence run for its current audio,
  or from `run`. `detector` is any event `method` of the layer, such as `spectral_flux`,
  `energy_rise`, `pitch_change` or `chord_change`.
- `moments` and `lyrics` are read from `report[source]`, then `musical/<run>/<source>.json`, then
  `<project>/<source>.json`. The container is a list, or an object holding `items`, `<source>` or
  `words`. Each item has `id?`, a time in `seconds`, `start_seconds`, `start` or `time`, an optional
  end in `end_seconds` or `end`, a `strength` or `confidence`, and a label in `kind`, `type`, `word`
  or `text`. `kinds` filters moments by label. `words` matches lyric labels case-insensitively,
  ignoring punctuation. This is the contract for the moments and lyrics analysis added under M5.
- When a source is absent, the pulse fails with the error `driver_source_unavailable`, which blocks
  export but not save. When no run exists at all, it fails with `evidence_missing`. An unknown layer
  fails with `unknown_layer`.
- `envelope`: `peak` and `base` (a number, or a list for colors and vectors; defaults 1 and 0),
  `attack_beats` (default 0), `decay_beats` (default 1/2, for point events), `release_beats`
  (default 1/2, for events with an end), `easing` (default `easeOutQuad`) and `scale_by_strength`
  (default true: the peak scales with the evidence strength). Items closer together than
  `min_gap_beats` keep the stronger one. Items with an end, such as sustains, hold the peak until
  they end.

## Provenance sidecar

Every compiled custom event gets one provenance row, at the same index as
`customData.customEvents`. Rows never go into the beatmap. Export writes them to
`<zip>.show.json`, and `show compile` prints them:

```json
{"event_index": 3, "type": "SetMaterialProperty", "beat": 112.5, "seconds": 54.48, "primitive": 1,
 "primitive_id": "kick", "kind": "pulse", "section": "s03-drive", "role": "pulse",
 "evidence": {"source": "onsets", "id": "drums:spectral_flux:5461", "seconds": 54.48, "strength": 0.9,
              "label": "spectral_flux", "run": "0f31..."}}
```

The compiler fills `evidence` from the first of these that applies:

1. A driver item (for pulses).
2. An explicit `anchor` on the keyframe or primitive: `{"source": "onsets"|"sustains", "id": ...}`,
   `{"source": "moments", "id": ...}`, `{"source": "lyrics", "id"|"word": ...}` or
   `{"source": "section", "id": SECTION}`. The named item must exist.
3. `{"source": "setup"}` for setup, or `{"source": "lifetime", "of_event": N}` for a destroy.
4. The strongest onset (`spectral_flux` or `energy_rise`, strength of at least 0.3) within 1/8 beat,
   recorded with `"auto": true`.
5. A section boundary at that exact beat.

An event that matches none of these produces the warning `visual_without_evidence`, which lists its
beats.

## Validation

`show save` checks the show's structure and references. `show validate` and export compile the show
into every difficulty and run every check. Errors block export. Warnings never block.

| Code | Severity | Rule |
|---|---|---|
| `invalid_show`, `schema_version`, `missing_field`, `unsupported_field`, `unknown_primitive`, `duplicate_id`, `invalid_beat`, `invalid_value`, `invalid_points`, `invalid_driver`, `invalid_anchor`, `raw_unknown_event`, `raw_invalid_field` | error (blocks save) | Show structure and the event vocabulary |
| `unknown_section`, `outside_section`, `keyframe_outside_span` | error (blocks save) | Section references and spans hold in every difficulty |
| `bundle_missing` | error | Events reference bundle assets, but `<project>/assets/bundleinfo.json` is absent |
| `unknown_material`, `unknown_prefab`, `unknown_asset_kind` | error | The asset path is not in `bundleinfo.json`, or is not a `.mat` or `.prefab` path |
| `asset_path_case` | error | Asset paths must be lowercase |
| `unknown_material_property`, `property_type_mismatch`, `property_type_unknown`, `property_value_shape` | error | Property names, types (Float, Color, Vector, Texture; Keyword is not typed) and value dimensions match the bundle |
| `prefab_not_destroyed`, `prefab_without_id`, `duplicate_object_id` | error | Every `InstantiatePrefab` id is destroyed later, or its primitive sets `persist: true` |
| `destroy_unknown_object` | warning | A `DestroyObject` names an object that is not alive |
| `multiple_setup` | error | At most one setup primitive |
| `possession_not_allowed` | error | `AssignPlayerToTrack` targets must match `presentation.possession`: player→Root, head→Head, hands→LeftHand+RightHand, right_hand→RightHand, none→nothing |
| `possession_unused` | warning | Possession is declared, but no event assigns the player to a track |
| `flash_rate_exceeded` | error | More than 3 full-screen flashes per second (WCAG 2.3.1) |
| `flash_rate_high` | warning | More than 2 full-screen flashes per second |
| `attention_over_budget` | warning | The section runs at least 4 notes/s and declares scene attention of at least 0.5 |
| `choreographed_density` | warning | A choreographed section runs more than 3 notes/s (the EXSII median active NPS) |
| `choreographed_note_jump_missing` | error | A note in a choreographed section has no per-note NJS and offset |
| `choreographed_njs_high` | warning | A choreographed section uses NJS above 12 |
| `path_requires_choreographed` | error | A path primitive targets a section that is not choreographed |
| `family_mismatch` | warning | A look runs in a scene section, a scene runs in a post_process section, or any visual primitive runs in a `none` section |
| `outside_exsii_envelope` | warning | Total custom events, events per second or spawns per second exceed the EXSII maximum |
| `visual_without_evidence` | warning | Grounding, see Provenance |
| `pulse_without_events` | warning | A driver matches no evidence in its span |
| `driver_source_unavailable`, `evidence_missing`, `evidence_run_missing`, `unknown_layer` | error | Driver evidence cannot be resolved |
| `note_path_conflict`, `duplicate_material` | error | Two paths give one note different jump settings, or one Chroma material is declared twice |
| `presentation_mismatch` | warning | Difficulties declare different map-level presentation |

The photosensitivity check is a static upper bound computed from the events alone. It counts these
full-screen transitions:

- Blit start and end.
- A pulse or instant change on a material that some Blit uses.
- A `SetGlobalProperty` change.

Transitions within the same 1/50 s count once. Two transitions make one flash. The check counts the
most flashes in any one-second window and lists the offending beats. Frame-luminance checks from
game captures belong to M2.

The EXSII envelope is stored in `sabermapper/resources/vivify-envelope.json`, with provenance.
`scripts/vivify_envelope.py` measures it from the local extracted EXSII difficulties (20
difficulties; maxima: 7781 events, 472 events/s, 51 spawns/s). The resource holds counts only.

## Bundle layout

A project's Vivify bundle set lives in `<project>/assets/`:

```
assets/bundleinfo.json          VivifyTemplate shape: materials {name: {path, properties {prop: {type: {Float: null}, value}}}},
                                prefabs {name: path}, bundleFiles [...], bundleCRCs {"_windows2021": crc, ...}, isCompressed
assets/bundleWindows2021.vivify (and optionally bundleWindows2019.vivify, bundleAndroid2021.vivify)
```

The reader also accepts the older property shape `{"_Amount": {"Float": "1"}}` and lowercases every
path. The M4 asset forge (`sabermapper assets build`) is expected to write this directory. The CRCs are
Unity's AssetBundle build CRCs. The exporter copies them from `bundleCRCs` and never computes them.
`show bundle ID` lists the bundle's contents.

## Export outputs

`project export ID` works as it always has for plain projects: one ZIP with the same bytes as before.
When the project has a `show.json`, or any difficulty has a presentation block, the export is
vivified:

- `map-<rev>-<id>.zip` contains:
  - the difficulty `.dat` files with the merged `customData` (`customEvents`, `environment`,
    `materials`) and per-object `customData`;
  - `Info.dat` with per-difficulty `_customData._requirements`, derived from the events actually
    used (see below);
  - Info-level `_customData._assetBundle` holding only the platforms whose bundle file ships;
  - the shipped `bundle*.vivify` files.
- `map-<rev>-<id>-vanilla.zip` is the same map with every `customData`, requirement and bundle
  removed. ArcViewer uses it.
- `map-<rev>-<id>.zip.show.json` is the provenance sidecar.

The export result reports `vanilla_twin` and `provenance_file`. The report's `vivify` block holds the
requirements, the `_assetBundle` value, the bundle files and the warnings.

Requirements are derived from the events used:

- `Vivify`: any Vivify event.
- `Noodle Extensions`: `AssignPathAnimation`, `AssignTrackParent` or `AssignPlayerToTrack`; an
  `AnimateTrack` with transform or Noodle properties; per-note NJS, offset, animation or world
  rotation.
- `Chroma`: `AnimateComponent`, `environment`, `materials`, or `color` animations.

## CLI

```
sabermapper show get ID --workspace W
sabermapper show save ID --workspace W --show show.json --revision CURRENT|none
sabermapper show validate ID --workspace W [--show FILE] [--difficulty D]
sabermapper show compile ID --workspace W [--show FILE] [--difficulty D] [--output FILE]
sabermapper show bundle ID --workspace W
sabermapper show envelope
```

`project get` also returns `show` (document, revision, `written_against`, `stale_difficulties`, bundle
summary and structural diagnostics). `show save` refuses the following:

- A stale revision (`ConflictError`).
- Structural errors (`show_invalid`).
- An edit whose primitives touch a locked section's time span in any difficulty. A primitive's span
  is its section span. Map-global `env` edits touch every section.

Typed errors print `{"error": {"code", "message"}}` on stderr.

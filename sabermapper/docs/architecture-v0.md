# Milestone 0 architecture and contracts

Status: disposable experiment contract, schema `0.1`. This document does not record a real song test.

## Decision

Use Python local commands and JSON arrangements edited by a user-invoked assistant. Compile deterministically to Beat Saber v3 Standard two-saber notes, package an OGG Vorbis track and cover, and inspect playback in ArcViewer before testing the ZIP on the user's SteamVR installation. A static HTML review timeline may follow; it is not required for this slice. The exact Beat Saber build, installed mods, and export compatibility remain to be measured. This chooses a narrow, inspectable workflow at the cost of manual timing, song structure, and phrase preparation. Variable tempo, corpus retrieval, learned ranking, richer lighting, a custom viewer, and automatic assistant integration are deferred.

```text
User -> independently invoked Codex -> arrangement.json
  |                                  -> local Python validate / compile / export
  |                                  -> diagnostics, v3 ZIP -> ArcViewer -> Beat Saber
  +-> checked timing/report/phrases --------------------^          |
  <----------------------- human feedback and section revision ---+
```

The local application never calls a provider API, assistant CLI or SDK, and never launches assistant background jobs. The user may independently invoke the assistant and may obtain track and reference data outside the application. This v0 path requires no network operation by the application. Any future downloader needs an explicit source, consent, rate limit, and recorded provenance. The assistant cannot be assumed to hear audio or see a running 3D scene; it consumes the checked report and saved review artifacts.

## Versioned payloads

The arrangement and illustrative report use `schema_version: "0.1"`. Other rows below describe proposed later contracts unless marked implemented; the disposable CLI does not yet wrap every artifact in a common schema. Beat positions are musical beats (quarter-note beats at the declared BPM), zero at the checked downbeat; audio time is seconds, with `audio_offset_seconds` describing the time of beat zero in the audio file. A number or rational string such as `"3/4"` is accepted for beat subdivisions. Avoid floating-point rounding as a source of IDs. Durations and offsets use explicit `_beats` or `_seconds` suffixes. Unresolved timing must be recorded as unresolved and reviewed by a human before export.

| Artifact | Current slice and proposed contract | Provenance and next stage |
| --- | --- | --- |
| Track report | `schema_version`, `song`, `audio_sha256`, checked BPM/offset, section starts/lengths and accent beats; `timing_reviewed` | Hash exact audio; record human or local estimator and date. Authoring input, never proof of audio inference. |
| Pattern record | stable `id`, local note beats, entry/exit intent, source and rights/review status | Synthetic examples are illustrative. Real phrases require exact source map/version and human inspection. |
| Arrangement | `schema_version`, `song`, `difficulty`, `motifs`, `sections` | Main editable contract; see below and the synthetic example. |
| Compiled map | Currently raw Beat Saber v3.3 JSON with `version` and `colorNotes`; it has no wrapper, schema version, lineage IDs, or source hash. A future map IR may carry those fields. | Deterministically derived; no source score ID is invented. |
| Diagnostics | Currently `validate` prints one raw JSON object per issue, with severity/code/message and optional location. It emits no JSON when clean. A future envelope may add schema and source hash. | Hard structural errors block export. Warnings need review; a clean structural check does not prove playability. |
| Feedback | `schema_version`, map artifact hash, reviewer, playtest date/build, section ID, observation and requested change | Review tied to the exact compiled map and playtest context. |
| Player preference | `schema_version`, player ID, target difficulty and named liked/disliked examples with reasons | One player's qualitative evidence; never a population quality label. |

For this experiment, `song` has `title`, `artist`, `bpm`, and `audio_offset_seconds`. `difficulty` has `name`, `rank`, `njs`, and `spawn_offset_beats`. `motifs` maps stable IDs to arrays of notes. A note has `id`, local `beat`, `x` (0–3), `y` (0–2), `color` (0 red or 1 blue), and `direction` (0–8, where 8 is any). Each section has `id`, absolute `start_beat`, `length_beats`, `intent`, `locked`, `resolved`, literal `notes`, and `patterns` containing `{id, motif, start_beat}`. A section note's beat and a pattern's start beat are relative to the section; a motif note's beat is relative to the pattern start. Expanded notes must lie within their section. IDs stay stable across edits. `locked: true` forbids an assistant section revision. `resolved: false` records a drafting gap and blocks compilation/export.

The `0.1` arrangement schema is intentionally provisional. Change it after observed authoring failures, with an explicit migration that names old/new versions and preserves IDs, locks, intent, beat meaning, and provenance. Reject unknown future arrangement versions rather than silently guessing. The scoped revision helper compares a canonical arrangement SHA-256 and replaces one unlocked section only; a stale hash or ID change is an error. A caller should present that error for reconciliation, not overwrite the file.

## Implemented pilot limits

The validator currently accepts only Standard Expert (rank 7), zero audio offset, and color notes. BPM and NJS must be positive finite numbers. IDs cannot contain `/`. No walls, bombs, arcs, chains, tempo changes, or full swing-state model are implemented. Align the audio before authoring if beat zero is not already time zero, record that transformation, and review the resulting exact audio. The static timeline and feedback UI remain deferred.

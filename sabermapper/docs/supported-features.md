# Supported features and limits

| Area | Available local behavior | Limit or required review |
|---|---|---|
| Audio | WAV, FLAC, OGG, MP3 decode; exact source SHA-256, waveform, peak, duration; OGG Vorbis preparation; original 48-second demo. | File and decode limits apply. Tags are not resolved into trusted song identity. Check conversion alignment by ear. |
| Timing | Constant BPM, phase hypothesis, half/double alternatives, editable beat/time grid; optional arrangement tempo events compile to v3. | Confidence is relative agreement. Downbeat/meter and section boundaries require review. Automated variable-tempo tracking is absent. |
| Structure | Onset accents, per-beat energy, rest and repeated-window candidates. | Anonymous windows and similarity do not prove verse/chorus. No stems or source separation. |
| Authoring | JSON schema 0.1 with stable sections, locks, motifs, literal notes, mirror, bombs, obstacles, arcs, chains and tempo events. | Validation catches scoped structural faults, not complete gameplay ergonomics. |
| Export | One Standard difficulty per arrangement in v3.3 beatmap ZIP, v2.1 Info.dat, decoded Vorbis, PNG/JPEG cover, minimal lighting, hash/compatibility report. | Multiple difficulties require separate authored arrangements and mapsets. No game/editor compatibility or playability claim without testing. |
| Review | Local 2D timeline, project revisions, feedback tied to artifacts, structural and movement diagnostics. | No 3D VR simulation or automatic enjoyment judgment. |
| Corpus | Safe local Beat Saber ZIP import, exact-version BeatSaver fetch, parser, phrase grouping and retrieval, split and label records. | Online fetch is an explicit operation. Source rights, audio alignment, duplicates and player taste require review. |
| Ranking | Optional small local preference model from recorded comparisons with family split evaluation. | An unpromoted or sparse model must not be presented as player preference knowledge. |

Research and demo assets may be shared freely only when their source permits it. Exporting a local map is distinct from publishing to BeatSaver or redistributing someone else's audio.

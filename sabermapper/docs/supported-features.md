# Supported features and limits

| Area | Available local behavior | Limit or required review |
|---|---|---|
| Audio | WAV, FLAC, OGG, MP3 decode; exact source SHA-256, waveform, peak, duration; OGG Vorbis preparation; original 48-second demo. | File and decode limits apply. Tags are not resolved into trusted song identity. Check conversion alignment by ear. |
| Timing | Constant BPM, phase hypothesis, half/double alternatives, editable beat/time grid; optional arrangement tempo events compile to v3. | Confidence is relative agreement. Downbeat/meter and section boundaries require review. Automated variable-tempo tracking is absent. |
| Structure | Onset accents, per-beat energy, rest and repeated-window candidates. | Anonymous windows and similarity do not prove verse/chorus. No stems or source separation. |
| Authoring | JSON schema 0.1 with stable sections, locks, motifs, literal notes, mirror, bombs, obstacles, arcs, chains and tempo events. | Validation catches scoped structural faults, not complete gameplay ergonomics. |
| Lighting | Audio-driven basic-event lightshow generated automatically on save (drums, lead, bass, chords and section energy to back/ring/side lasers/center, laser speed, ring spin/zoom, color boost), agent overrides and cues, strobe blocking and coverage/grounding/blackout/density checks, classic v2 environments. | No v3 group lighting, Chroma or custom color schemes. Visual quality needs the user's review in ArcViewer or in game. |
| Export | One Standard difficulty per arrangement in v3.3 beatmap ZIP, v2.1 Info.dat with the lightshow environment, decoded Vorbis, PNG/JPEG cover, lightshow events (section pulses as a fallback), hash/compatibility report. | Multiple difficulties require separate authored arrangements and mapsets. No game/editor compatibility or playability claim without testing. |
| Review | Local 2D timeline, project revisions, feedback tied to artifacts, structural and movement diagnostics. | No 3D VR simulation or automatic enjoyment judgment. |
| Corpus | Safe local Beat Saber ZIP import, exact-version BeatSaver fetch, parser, phrase grouping and retrieval, split and label records. | Online fetch is an explicit operation. Source rights, audio alignment, duplicates and player taste require review. |
| Ranking | Optional small local preference model from recorded comparisons with family split evaluation. | An unpromoted or sparse model must not be presented as player preference knowledge. |

Research and demo assets may be shared freely only when their source permits it. Exporting a local map is distinct from publishing to BeatSaver or redistributing someone else's audio.

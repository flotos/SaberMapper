# Listen and concept (Vivify ticket M5)

The listen step describes the song for the visual concept: its sections, moments, mood and
lyrics. The concept step is where the agent writes three candidate treatments that follow from
that evidence, scores them and selects one. The app measures, validates and stores. The agent
writes every creative field, and nothing here places notes or visual events.

```
music analyze ID --backend ensemble   ->  musical/<run>/report.json + stems   (existing)
music listen ID                        ->  musical/<run>/listen.json + moments.json
music lyrics ID                        ->  musical/<run>/lyrics.json
concept template ID                    ->  skeleton pre-filled with that evidence
concept validate --project ID --file F ->  structure, references, rubric totals
concept save ID --file F --revision R  ->  <project>/concept.json (+ concept-history/)
```

Every derived file lives inside the evidence run it was measured from. Each file records the
run's `source_sha256`, so it is reproducible and never outlives the audio it describes. Beats are
computed against the map grid, and readers refresh them when the grid changes; times in seconds
never change.

## `music listen`

`music listen ID [--run RUN] [--force] [--full] [--mood-backend heuristic|external]`

The command measures the project audio and every separated stem of the run: RMS, spectral
centroid, flatness, band shares, flux, 12-bin chroma, and a harmonic/percussive share on 96 log
bands. From these it derives three things.

**Sections.** Beat-synchronous features: stem chroma (drums excluded), level, centroid, flux,
harmonic share and per-stem balance. A checkerboard novelty kernel spans about 8 s, sections are
at least 10 s long, and boundaries snap to the bar phase the map's sections start on. Each section
gets:

- a repetition `group` letter: sections whose chord sequences match once the song's mean chroma is
  removed, with a ±2-beat lag search and transposition allowed and penalised;
- a Krumhansl–Kessler `key` with `major_minus_minor`;
- `level_db`;
- the overlapping `map_sections`.

**Moments.** Each moment is `{id, kind, time, beat, strength 0-1, duration?, section_id,
evidence}`. The `evidence` field records the rule, the thresholds and the measurements that fired.

| kind | rule (constants in `moments.py`) |
|---|---|
| `silence` | mix level (0.2 s) 35 dB below the song's loud level (95th percentile) for ≥ 0.3 s; song edges excluded |
| `break` | drums stem inactive (< its 90th percentile −18 dB) ≥ 2 s after being active, then back; or mix ≥ 9 dB under its previous 8 s for ≥ 1.5 s, then back |
| `build` | the 4–16 s before a drop or a louder section: level +4 dB, centroid +0.5 octave or onset density +2/s, each with a linear fit r² ≥ 0.5, and the level never falls more than 1 dB |
| `drop` | level after ≥ loud −8 dB, and either mix +6 dB with low end (drums+bass) +4 dB, or mix not quieter with low end +12 dB (3 s before vs 2.5 s after); spaced ≥ 8 s apart; not in the first 3 s of sound; snaps to the strongest onset within 0.5 s of a section boundary; boosted when a build, break or silence resolves into it |
| `key_change` | the best diatonic collection of sections of ≥ 8 s changes, each side fits its own collection ≥ 0.04 better, and the new region lasts ≥ 16 s (or ends the song) without returning within 30 s; or a transposed repeat. Relative major/minor never counts |
| `tempo_shift` | arrangement tempo events, or section onset-autocorrelation tempi differing ≥ 8% (not a simple ratio) with clarity ≥ 2.5 |
| `energy_shift` | consecutive sections differing ≥ 5 dB that no drop, break, silence or build already explains |
| `final_chorus` | last occurrence of the most repeated group whose mean level is at or above the median section level; otherwise the loudest section of the last 40%, flagged `fallback` |
| `vocal_entry`, `vocal_return` | the first vocals `layer_entries` entry; later ones after ≥ 8 s of silence |
| `layer_entry` | other stems entering after ≥ 8 s of silence at ≥ −12 dB against the mix |
| `big_hit` | mix spectral-flux onsets ≥ 0.5 standing out from the onsets within 4 s; at most duration/25 (3–12), ≥ 6 s apart |
| `ending` | the last strong onset before the sound ends, or the last 10 s when it fades out (`fade_out`) |

IDs are `<kind>-<n>`, numbered in time order within each kind. They are stable for the same audio
and algorithm version. The `schema_version` changes when the rules change.

**Mood per section.** Valence and arousal run from 0 to 1, plus timbre tags with confidences.
The default backend, `heuristic`, is a formula over measured features. It is not a trained model
and not a human judgement.

- **Arousal**: 0.2 tempo (60–180 BPM), 0.3 loudness (−30…−8 dBFS), 0.2 strong-onset density
  (0–6/s), 0.15 brightness (centroid 700–4000 Hz, log), 0.15 percussive share.
- **Valence**: 0.5, plus 0.2 × mode, plus 0.1 × tempo, 0.1 × brightness and 0.05 × harmonic share,
  minus 0.1 × spectral noisiness; clipped to 0–1. The mode term is the major-minus-minor profile
  fit, half from the section and half from the whole song, because relative keys flip easily.
- **Tags**, each with the feature it came from (`because`):
  - stem tags: `vocal_led`, `drum_heavy`, `bass_heavy`, `distorted_guitar` (1–6 kHz flatness of
    the guitar stem), `clean_guitar`, `piano`, `sustained_pad` (a steady "other" stem, meaning a
    synth pad or strings, which it cannot tell apart), `dense`, `sparse`;
  - mix tags: `bright`, `dark`, `airy`, `noisy`.

The direction of each term follows the music-emotion literature (Gabrielsson & Lindström 2010;
Eerola & Vuoskoski 2013). The weights are hand-set. Every section stores its `features` and
`components`, so the agent can weigh them itself.

`--mood-backend external --mood-python P --mood-module M` is the hook for a local model, for
example one running in `.venv-separation` on the RTX 5070 Ti. The user decided that heavier models
run locally, not on RunPod. The module gets `{sections, features, audio, stems}` as JSON on stdin
and prints `{"model": {...}, "sections": {id: {valence, arousal, tags}}}`. Its values replace the
heuristic ones, and the heuristic ones are kept under `heuristic`. If the module is missing, the
command returns the structured error `mood_model_missing`. No model is installed.

The command prints a summary: sections with key, valence, arousal and tags at confidence ≥ 0.5,
the moment list, and the song's mood. `--full` prints the whole `listen.json`.

**Files.** The command writes `listen.json` (the full document) and `moments.json` (driver-shaped:
`{"moments": [{id, kind, seconds, end_seconds?, strength, beat, section_id}]}`). The show
compiler's `{"source": "moments", "kinds": [...]}` pulses read `moments.json`; see
[vivify-show.md](vivify-show.md).

## `music lyrics`

`music lyrics ID [--run RUN] [--python PATH] [--model large-v3] [--device auto|cuda|cpu]
[--language CODE] [--input vocals|mix] [--from-file F]`

**Whisper.** The command runs a separate interpreter, `.venv-separation` by default like Demucs,
with faster-whisper (preferred) or openai-whisper. It uses the vocal stem, resampled to 16 kHz,
with word timestamps on, VAD, beam 5 and `condition_on_previous_text=False`. On CUDA it uses
float16; on CPU, int8. On Windows the runner adds torch's `lib` directory and any `nvidia-*` wheel
`bin` directories to the DLL search path, so CTranslate2 can find cuBLAS and cuDNN. `lyrics.json`
holds:

- `backend`, `model`, `language`, `language_probability`, `device`, `compute_type`;
- `precision` and `precision_note`;
- `segments`: `{id: "lyr-001", start, end, start_beat, end_beat, text, words: [{word, start, end,
  probability, beat}]}`;
- a flattened `words` list (`{id: "lyr-001/0", segment_id, word, start, end, confidence, beat}`),
  which is what the show's `{"source": "lyrics", "words": [...]}` pulses read;
- `provenance`.

**Status on this machine (2026-09-23).** Neither package is installed. The permission system
blocked the install, so the command returns this structured error:

```json
{"error": {"code": "whisper_missing",
  "message": "Neither faster-whisper nor openai-whisper is importable in ...\\.venv-separation\\Scripts\\python.exe",
  "fix": "...python.exe -m pip install faster-whisper   (needs the user's approval; ...)",
  "install_command": "C:/Users/floto/Documents/SaberMapper/sabermapper/.venv-separation/Scripts/python.exe -m pip install faster-whisper"}}
```

The exit code is 2. To enable Whisper, the user runs or approves:

```
C:/Users/floto/Documents/SaberMapper/sabermapper/.venv-separation/Scripts/python.exe -m pip install faster-whisper
```

That environment already has torch 2.8.0+cu128 with CUDA available. If CTranslate2 still cannot
load cuDNN, add `nvidia-cublas-cu12 nvidia-cudnn-cu12`. Alternatively, `openai-whisper` reuses
that torch directly.

Model weights are downloaded on first use:

- faster-whisper: the Hugging Face hub cache, `%USERPROFILE%\.cache\huggingface\hub`
  (`models--Systran--faster-whisper-large-v3`, about 3 GB);
- openai-whisper: `%USERPROFILE%\.cache\whisper`.

Word-timestamp quality on real songs has **not been observed** yet, because no model has run. The
stored note describes Whisper's known behaviour: usually within a few tenths of a second, worse on
melisma, held notes, backing vocals and ad-libs, and words can be misheard.

**Lyric sheets without a model (`--from-file`).**

- **LRC** keeps its `[mm:ss.xx]` line times (`precision: lrc_line`). It keeps word times too when
  the file is enhanced LRC with `<mm:ss.xx>` tags (`precision: lrc_word`). Otherwise word times
  are spread by syllable count inside the line and snapped to vocal onsets within 0.15 s.
- **Plain text** skips `[Chorus]`- and `(x2)`-style headers. A monotone dynamic program aligns each
  line to a run of vocal phrases. The phrases are vocal-stem energy runs, merged over gaps under
  0.35 s. The cost is the log ratio of the phrase span to the line's syllable-count duration, and
  unused phrases (ad-libs) pay a penalty. Word times are interpolated and snapped. The result is
  labelled `precision: rough`: a line can land a phrase early or late. Use it for section-level
  cues, not word-exact effects.

Structured errors: `whisper_missing`, `whisper_failed` (with the `lyrics.log` path),
`vocal_stem_missing`, `lyrics_empty`, `vocal_phrases_missing`, `lyrics_file_missing`,
`evidence_missing`, `run_unknown`, `run_stale`.

## Integration: `latest_listen(project_dir)`

`sabermapper.listen.latest_listen`, also exported from `sabermapper.moments`, returns:

```
{run_id, available, moments: [...], mood: {...}, sections: [...], lyrics: {...}|None, path,
 schema_version, stale, hint?}
```

It covers the newest run of the project's current audio. `available` stays false, with empty
lists, until `music listen` has run. `lyrics` stays None until `music lyrics` has run. Beats follow
the current arrangement grid. The show compiler and the capture time-set generator call it. The
compiler also reads `moments.json` and `lyrics.json` directly through its own driver contract.

## Concept

`<project>/concept.json` is revision-aware. The first save passes `--revision none`, and each
later save passes the current revision; anything else is refused with `revision_conflict`. The
revision is the SHA-256 of the canonical document. Every saved version is kept in
`concept-history/<revision>.json`, with one log entry per save in `concept-history/log/`.

The document the agent writes:

```json
{"schema_version": "1.0", "listen_run": "RUN",
 "steering": [{"text": "user's words", "source": "user", "applied": "how it changed the candidates"}],
 "candidates": [{
   "id": "ring", "title": "...", "central_idea": "...",
   "grounding": {"moments": ["drop-2"], "mood": ["sec-05"], "lyrics": ["lyr-004"], "notes": "how it follows"},
   "palette": ["#1b0f2e", "#f2c14e"],
   "motifs": [{"name": "...", "description": "...", "development": {"sec-02": "...", "sec-12": "..."}}],
   "key_moments": [{"moment_id": "final_chorus-1", "treatment": "...", "held_for_end": true}],
   "possession": "none|player|head|hands|right_hand",
   "buildability": {"tiers": [1, 2], "notes": "which assets each tier provides"},
   "rubric": {"grounded": {"score": 4, "why": "one line"}, "one_idea": {...}, "develops": {...},
              "readable": {...}, "buildable": {...}}}, ...],
 "selected": "ring", "selection_reason": "needed when it is not the top total"}
```

Validation checks the following:

- exactly three candidates with unique slug ids;
- grounding that cites at least one moment or section mood, plus `notes`;
- every moment, section and lyric id exists in the latest listen evidence (lyric ids need
  `lyrics.json`);
- 2–8 `#rrggbb` palette colours;
- 2–4 motifs, each developing across ≥ 2 listen or map section ids;
- 1–3 key moments with exactly one `held_for_end` (a warning when it is not the latest);
- the possession enum;
- asset tiers from 1–3, with notes;
- rubric scores as integers 1–5 with a one-line `why`.

Totals (out of 25) and a ranking are computed.

Document-level errors block a save. A candidate with errors can stay in a draft, but it cannot be
`selected`; that save is refused with `concept_invalid`. Selecting a candidate that is not the
top total requires `selection_reason`.

On save, the selected treatment's `palette`, `possession` and key `moments` (with seconds) are
mirrored at the top level of `concept.json`. The frame metrics (`frames metrics`) read them from
there for palette drift and moment alignment.

The other commands:

- `concept template ID` returns the skeleton with the evidence: song mood; sections with key,
  valence, arousal and tags; the moment list; lyric lines; `held_for_end_suggestions`; the rubric,
  tiers and rules.
- `concept get ID` returns the stored document, the computed totals, a fresh validation against the
  current listen evidence (stale references show up after a re-listen), and the history.
- `concept corpus [--id ID]` lists the ten EXSII reference treatments in
  [references/extrasensory/concept-corpus.json](references/extrasensory/concept-corpus.json). Each
  map write-up also has a "How the idea follows from the song" section.

## Trial on real projects (2026-09-23)

Three projects were copied into a temporary workspace (hard-linked audio and stems, copied
reports), so no file in the real workspace was written: The Spell (205 s), Fireflies (184 s) and
Living a Lie (297 s). `music listen` took about 5 s per song, of which measuring took about 3.4 s.

- **Sections** fell mostly on the map's own section starts, within a beat. On The Spell,
  boundaries fell at beats 24, 48, 68, 100, 120, 144, 164…, against map sections at 24, 68, 100,
  144 and 168. The first version snapped to the wrong bar phase, one beat early; boundaries now use
  the arrangement's section phase.
- **Drops** landed on onsets stronger than the song median (mean onset strength 0.57 against a
  median of 0.49 on The Spell, and 0.77 against 0.43 on Living a Lie). On Living a Lie, both drops
  (28.3 s and 179.8 s) coincide with the drums and bass re-entering after long absences (layer
  entries), which is the expected shape. On Fireflies, one drop first came from a section boundary
  with a weak onset (0.20); boundary candidates now snap to the strongest onset within 0.5 s.
- **Big hits** sat on the strongest onsets, by construction: 0.86–0.93 against medians of
  0.43–0.57.
- **Final chorus** picked the last member of a three-times-repeated loud group in every song. On
  The Spell that group is the one the map labels verse/outro, not the map's "chorus". Repetition
  groups are harmonic similarity, not a verse/chorus labeller.
- **Key changes** were over-reported by the first, profile-correlation version: seven on Living a
  Lie. With diatonic-collection regions they dropped to three there, two on The Spell and none on
  Fireflies. They remain the least certain kind; check `margins` in the evidence.
- **Mood**: the spectral-flatness overflow on near-silent stems (values over 1) was found and
  fixed. Distortion now uses the guitar stem's 1–6 kHz flatness. The median across songs ranged
  from 0.05 to 0.31, with the two highest on End of You and Borrowed Waters.

None of this was checked by ear. Listening review and playtests remain the ground truth.

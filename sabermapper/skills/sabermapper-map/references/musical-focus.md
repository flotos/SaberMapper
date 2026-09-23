# Instrument-aware, agent-authored mapping

SaberMapper extracts evidence; the independently invoked Codex or Claude Code
agent authors the musical focus, note rhythms, rests and saber movements. It does
not call an LLM, choose a lead instrument, or turn weighted peaks into notes.

## Gather complementary evidence

Run commands from the application directory with its Python environment:

```text
python -m sabermapper music backends
python -m sabermapper music analyze ID --workspace workspace --backend bands --preset metal
python -m sabermapper music analyze ID --workspace workspace --backend hpss --preset electronic
python -m sabermapper music analyze ID --workspace workspace --backend demucs --model htdemucs --python PATH_TO_SEPARATION_PYTHON
python -m sabermapper music analyze ID --workspace workspace --backend import --manifest stems.json
python -m sabermapper music list ID --workspace workspace
python -m sabermapper music inspect ID --workspace workspace --run RUN_ID --start 64 --end 80
python -m sabermapper music rhythm ID --workspace workspace --start 64 --end 96 [--layers guitar,drums] [--division 3]
python -m sabermapper music analyze ID --workspace workspace --from-run RUN_ID
```

`--from-run` (backend `rerun`) re-analyzes the stems an earlier run already
separated with the current detectors, without separating again. Use it when a
project's newest run predates schema 1.2 (no `chord_change` events).

Each analysis creates an immutable `musical/RUN_ID/report.json` beside the project
arrangement. `music inspect` returns only the selected absolute beat range, with
the current revision, mapped notes, events, energy contours and existing focus
annotations. Its beat conversion uses
the current arrangement's offset and tempo events; raw evidence stays in audio
seconds. Inspect short passages to avoid flooding the context. A saved run also
appears under **Music layers** in the studio after **Refresh**. This is
an optional agent-operated inspection surface. Complete analysis, authoring and
saving through the CLI without requiring the user to operate the studio.

- `bands`: full mix and low/mid/high spectral evidence. Useful for bass pulses,
  bright attacks and ensemble accents; bands are not instrument isolation.
- `hpss`: harmonic/percussive median-mask separation, with soloable mono audio.
  Useful when a sustained layer masks percussion; neither layer is an instrument.
- `demucs`: optional local neural separation in a separate Python environment.
  Four-source models expose vocals/drums/bass/other. `htdemucs_6s` also estimates
  guitar/piano; inspect bleed and artifacts before trusting these labels.
- `import`: aligned outputs from BS-RoFormer, Mel-Band RoFormer, UVR or another
  locally run separator. This is an import adapter, not an installed RoFormer
  inference engine. Select the external model/checkpoint based on the passage.

Presets `balanced`, `metal`, `electronic`, and `vocal` adjust peak spacing and
prominence only. They are starting hypotheses, not genre classification or
difficulty. Analyze vocal passages with a different preset/run if useful.

Every audio layer includes two independent candidate detectors: spectral flux
and energy rise. Strength is normalized per layer and detector; it is not a
probability, and quiet bleed can still have a strong normalized peak. Use energy
contours, full-mix context and listening to distinguish attacks, sustained notes,
breaths, gaps and separator artifacts. Vocal onsets are not syllable transcription.

## Author focus and rhythm before movement

Annotate phrases inside each section with optional `musical_focus`. Beats are
relative to that section. Phrases must be ordered, nonoverlapping and within its
length. Gaps mean no declared focus; do not silently infer a lead from loudness.

```json
"musical_focus": [
  {
    "id": "vocal-line", "start_beat": 0, "end_beat": 8,
    "lead": "vocals", "weights": {"vocals": 0.8, "drums": 0.1, "mix": 0.1},
    "intent": "Follow the vocal attacks and breath; sparse backbeat support.",
    "evidence": ["RUN_ID/vocals:spectral_flux:125"]
  },
  {
    "id": "riff-answer", "start_beat": 8, "end_beat": 12,
    "lead": "guitar", "weights": {"guitar": 0.8, "mix": 0.2},
    "intent": "Hand focus to the answering riff at the phrase boundary."
  },
  {
    "id": "ensemble-hit", "start_beat": 12, "end_beat": 16,
    "lead": "mix", "weights": {"mix": 0.7, "drums": 0.3},
    "intent": "Emphasize the shared ensemble accents, preserving the final rest."
  }
]
```

Weights are finite 0..1 values summing to 1. They describe the agent's musical
priorities, not audio volume or a note-density multiplier. `lead` must name a
positively weighted layer; `mix` means whole-ensemble emphasis. An agent may use
several analysis runs for one phrase; evidence references should name exact run
and event IDs or a precise listened passage. Never invent an evidence reference.
`music inspect` reports focus layers unavailable in the selected run. Gather
another run or explain the inference instead of silently substituting the mix.

Choose a phrase's attacks, syncopation, accents and rests from its musical layer,
then author literal notes or a motif with that specific rhythm. Reuse a motif when
the musical phrase recurs; do not lay an evenly spaced stock motif over a vocal
line merely because its density matches. Preserve recognizable movements when a
riff returns and adapt its ending when the music changes. Select ensemble accents
deliberately; two detectors or several stems observing one hit do not require
several notes. Check handoff setup, parity, recovery and overall player calibration.

Save through the existing revision-aware project command. Focus metadata participates
in revisions and section locks, and does not alter compilation or gameplay by itself.
Validate and compare the actual authored rhythms, not just the annotations. Keep
musical interpretation, automated evidence and human listening/playtest status distinct.

## Sustains, pitch changes and quiet passages

Report schema 1.1 adds evidence for held material and low-intensity writing.

Each layer carries a `sustains` array; items have `id` (`LAYER:sustain:FRAME`),
`start_seconds`, `end_seconds`, `start_hz`, `end_hz`, `median_hz`,
`semitone_delta` (signed, from a robust slope over the octave-folded pitch
track), `pitch_shape` (`rise`, `fall`, `flat`, `unstable`), `confidence` (0..1)
and `strength` (0..1, relative loudness). `music inspect` adds `start_beat` and
`end_beat`. Held vocals are authored as arcs; see
[held notes](held-notes.md).

Schema 1.2 adds `method: "chord_change"` events on every separated layer except
drums and percussive (and on the mix). They mark where the pitch-class content
changes: strummed chord changes and riff note changes that the monophonic
`pitch_change` tracker cannot follow on polyphonic guitar, keys or pads. Each
carries `novelty` (0..1, raw), `from_pitch_classes` and `to_pitch_classes` (the
three strongest classes, not chord names) and sits on the layer's own attack when
one is within 80 ms. Use them as placement triggers and as cues for a direction
or position change: a new chord is a natural point to change the hand's figure.

Every layer except drums and percussive (and the mix) also emits
`method: "melody_change"` events. They follow the predominant pitch: each frame
scores every semitone from MIDI 60 to 88 by its summed harmonics over a 0.19 s
window, so one line resolves through a held chord, a choir or layered voices,
where `pitch_change` flips octaves and `chord_change` misses a single-voice step.
An event marks the line settling on a new note held at least 0.15 s; it carries
`from_midi`, `to_midi`, `semitone_delta` and `hold_seconds`, and sits on the
layer's own attack when one is 120 ms before to 50 ms after it. Lower voices show
through their harmonics, so read the steps, not the octave. On a dense mix the
line jumps between instruments; trust it where one pitched part leads.

Each layer also emits events with `method: "pitch_change"` carrying `from_midi`,
`to_midi` and `semitone_delta`, where the smoothed pitch moves at least 0.8
semitone and holds the new value for at least 100 ms. A layer's `attack_profile`
reports `sustained_fraction` (0..1) and `sustained_layer` (bool); when
`sustained_layer` is true, `energy_rise` events on that layer are envelope wobble
on held material, not attacks, and must not be used as placement triggers.

The report-level `passages` array holds fixed 2-second windows with
`start_seconds`, `end_seconds`, `drum_onset_density` (strong percussive events
per second), `energy_ratio` (window mix energy over the song median),
`support_score` and `low_intensity` (bool); the cutoffs are published under
`passage_thresholds`. `music inspect` returns the passages overlapping the slice
with beats, and `music inspect --layer NAME` scopes the slice to one stem.

Quiet-passage policy, a standing user rule (2026-09-22: "For passages with low
musical intensity and rhythm, place notes mostly on note change"): inside windows
where `low_intensity` is true, place mostly on `melody_change` and `pitch_change` events and genuine
attacks (`spectral_flux` on layers that are not `sustained_layer`); never place
from `energy_rise` on a `sustained_layer`; select the lead by rhythmic salience,
such as a grid-locked piano, rather than loudness; quantize to 1/2 or whole
beats and never stream quarters, but let a single note take the quarter beat where
the sound itself lands there (a legato pitch change arriving just after the beat,
Living a Lie 2026-09-23); check section seams so a strong accent on a seam still gets a
note; and keep density well below the body of the song.

A passage is quiet only where the evidence says so (`low_intensity` true, mix
energy clearly below the song median). Position does not make a passage quiet:
an intro with a drum groove, riff or bass line is a mapped passage, however
early it comes. Quiet passages still follow every audible layer. Use drums,
guitar, bass and synth attacks when no voice or melody is present. Never limit a
quiet passage to vocal or melodic pitch changes. Lullaby (2026-09-22) went 45 s
with one note because an instrumental intro was labelled "quiet" and then
searched only for vocal and melodic changes. Borrowed Waters' intro had the same
defect. `audio_unmapped` now blocks that on save.

## Follow the melody

Standing user rule (2026-09-23, Living a Lie): "the notes aren't really matching
the pitch change of the sound." When no voice, drum pattern or declared
instrument lead carries a bar (a pad, choir or synth intro, an ambient bridge),
the pitched line is what the player hears, and its pitch changes are the rhythm.
`melody_unmapped` flags those bars when most strong mix `melody_change` events
(0.3 or more, strongest per half-beat) have no note within a quarter beat.

- List the changes with `music inspect ID --workspace workspace --run RUN --start A --end B --layer mix`
  (method `melody_change`, with `from_midi`/`to_midi`), and `music rhythm --layers mix`.
- Put a note on each change, within 0.13 beat of it: the whole or half beat when
  the change is on it, else the nearest quarter. A legato pad or voice reaches its
  new pitch just after the beat; a note on the beat before it misses the sound.
  Keep the line's own spacing; never an even grid that ignores it.
- Let the row follow the contour: the highest notes of the phrase on the top
  row, the lowest on the bottom, and a step up or down moves the next note the
  same way. Cut direction keeps the flow rules; the row carries the pitch.
- A note held a beat or more is an arc, not a stream. The other hand takes the
  next change.
- Do not fill between changes. A line that changes pitch once per beat maps once
  per beat.

## Rhythm, not a metronome

Standing user rule (2026-09-22, `rhythm_not_metronome` in `player-profile.json`):
The Spell was rejected as "extremely monotonous and easy", and The Revival's
intro as "regularly spaced notes that just do the beat". Both maps put most
notes on an even half-beat grid (about 2.8 NPS) and ignored syncopated drum,
bass and synth figures that were plainly present in the stems.

- Before authoring, run `music rhythm ID --start A --end B` for the passage.
  It prints, per 4-beat bar, each layer's attacks on a sixteenth grid (digits
  1-9, normalized within the requested range so quiet intros still show their
  figure) beside the mapped notes, the bar's lead, and pattern letters that show
  where a riff repeats. `grid_fit` says whether a layer sits on sixteenths or
  triplets; use `--division 3` or `6` for a triplet feel. Then place notes on
  the strongest actual attacks, including off-beat sixteenths such as dotted
  3-3-2 kick/snare placements and bass or synth pickups.
- Break long runs of identical gaps. Six or more equal gaps in a row need a
  musical reason, such as a real straight hi-hat or a sung eighth-note line.
  Otherwise, rest or move to the nearest off-grid attack.
- In quiet intros, follow whatever rhythmic figure exists: a synth arpeggio,
  vocal chops or bass notes. A non-sung attack with clear grid alignment may sit
  on a sixteenth position while keeping at least 1/2 beat between notes. The
  1/2-beat quantization above still applies to sung note changes.
- Calibrate body density to the player's 6.5–8 star band, not an easy baseline.
  At ~105 BPM that means roughly 4.5–5.5 NPS in choruses and drives, with
  sixteenth bursts where the music rolls and doubles on the heaviest accents.
  Quiet passages and breaks stay clearly lower, for contrast and recovery.
- Keep flow strict while adding intensity. Each hand alternates forehand and
  backhand, deviating at most 45° from exact reversal. Allow at least 1/2 beat
  between same-hand cuts. Do not cross hands. Doubles need matching parity.
  Carry hand state across section seams and check the first notes of the next
  section.

## Follow the lead instrument's rhythm

Standing user rule (2026-09-23, `lead_rhythm` in `player-profile.json`), from
Fireflies feedback: "should map way more to the rhythm of the guitar being
played; the pacing is very regular". The drive sections declared the guitar as
lead, but notes filled every eighth: the guitar's offbeat figure was merged with
the kick into an even stream, so its syncopation disappeared. It also missed the
guitar's sixteenth runs at 0:33-0:39.

- The bar's lead is the voice in a singing bar. Otherwise it is the
  `musical_focus` lead when that lead is an analyzed stem other than `mix`.
  Declare an instrument lead wherever a riff carries the rhythm. `mix` and gaps
  declare no lead, so nothing checks the rhythm there. Declare the stem that
  actually plays: check `music rhythm` before calling a stretch "drums" or "mix".
- Put the notes on the lead's attacks and keep its rests and syncopation. Add
  another layer's hits only where the lead is silent for about a beat or more.
  A lead playing every beat leaves no room for filler; its figure *is* the map.
- Follow the lead's density changes. A riff that moves from offbeat eighths to
  sixteenth runs should read that way. Short sixteenth bursts are within the
  player's band; flow rules still apply.
- Intensity sets the density; the lead sets the placement. In a thin, soft
  passage (`density_exceeds_audio` territory), take the lead's strongest attack
  per beat rather than every attack. `lead_rhythm_unmapped` does not fire there.
- `critique` checks this. `lead_rhythm_unmapped`: fewer than 60% of an
  instrument lead's strongest attacks per half-beat carry a note.
  `lead_rhythm_diluted`: fewer than 75% of a bar's note times sit on a lead
  attack, in a lead gap, or under a held arc. Its `object_ids` name the filler
  notes. `metrics.lead_rhythm.bars` lists each bar's lead and counts.
- `project repair-audio` rebuilds each diluted bar. It clears the bar's free
  notes and places flow-safe notes on the lead's strongest attack per half-beat
  and on strong sixteenth attacks, filling the lead's silent beats from other
  stems. It keeps arcs, chains, locked sections and motif notes, and restores
  any bar it cannot rebuild safely. It also fills `lead_rhythm_unmapped` onsets.
  Its placements are mechanical: review hand positions for variety afterwards,
  and re-author any bar it reports as unresolved.
- `grid_drift` warns when a 32-beat window's percussive onsets sit more than
  30 ms from the song-wide grid offset (`metrics.grid_alignment`). Fix the BPM,
  offset or tempo events before placing notes there.

## Salience: who leads, bar by bar

Standing user rule (2026-09-22, `salience_lead` in `player-profile.json`), from
Borrowed Waters feedback. The "drive" sections followed guitar and drums while
the singing was the focal point. At 1:38 the voice held one note while the drums
played a strong pattern, and the notes sat between the drum hits.

- Choose the lead per 4-beat bar, not per section label. **Articulated singing
  leads**: vocal sustains cover at least a quarter of the bar and at least two
  vocal `spectral_flux` onsets start in it. Place notes on those vocal onsets.
  Add only strong drum accents where the voice leaves a gap of a beat or more.
- **When the voice holds or rests, the drums lead**, unless a `musical_focus`
  phrase declares another instrument stem as lead (see above). Put the notes on
  the drum pattern and carry the held vocal as an arc on the other hand
  ([held notes](held-notes.md)).
- A busy riff or loud guitar never outranks singing. "Drive" or "chorus" labels
  do not change the lead.
- `focus_on_quiet_stem` checks every focus phrase's weighted stems against their
  own usual level; `repair-audio` drops absent stems from the weights.
- Separator bleed can put vocal or drum events into intros and instrumental
  passages. Confirm with the stem energy before trusting a quiet passage's
  "vocal" onsets. Demucs `htdemucs_6s` often routes a soft solo piano to `other`
  and leaves the `piano` stem nearly silent.
- `python -m sabermapper critique ARRANGEMENT.json --report musical/RUN/report.json`
  checks this. `vocal_line_unmapped` means fewer than half the vocal onsets in a
  singing bar carry a note. `drum_rhythm_unmapped` means fewer than 60% of a
  strong drum pattern's hits carry a note while the voice holds or rests and no
  other instrument lead is declared. Only
  the strongest hit per half-beat counts, so dense sixteenth hats never demand
  a stream.
  `metrics.salience.bars` lists each bar's salient layer. Both are warnings:
  fast melismas thinned for flow or real bleed can explain a flag. Resolve or
  justify every flagged range before saving.
- When repairing flagged bars, re-author only those bars. Keep every existing
  arc and its head and tail notes, keep a rewritten bar at no fewer than
  min(4, its old note count) notes, and fit each seam to the neighbouring notes
  under the blocking flow rule.

## Import manifest and separation environment

Separate the exact project `song.ogg`, keeping zero time and the entire duration.
The manifest references stem files relative to itself (absolute paths also work):

```json
{
  "source_sha256": "SHA256_OF_PROJECT_SONG_OGG",
  "producer": "BS-RoFormer / exact model and checkpoint identifier",
  "stems": {"vocals": "vocals.wav", "drums": "drums.wav", "bass": "bass.wav", "other": "other.wav"}
}
```

Use a producer identifier with the model/checkpoint version. Import records its
manifest hash and each stem's hash. A duration difference above 50 ms is rejected;
matching duration does not prove internal alignment. Check the beginning, middle
and end for separation delay. No stem is silently shifted or normalized. The
original audio and arrangement remain intact.

Demucs is optional and is not bundled with the base NumPy/SciPy application. Use a
compatible separate Python environment (`python -m pip install demucs`) and pass
its executable with `--python`; choose `--device cpu` or a supported CUDA device.
The first run may download model weights. A failed run has a separation log but
no published report. Retry into a new run; do not treat missing model output as
successful separation. For RoFormer, run its own inference tool/environment, then
import the resulting stems with the manifest above.

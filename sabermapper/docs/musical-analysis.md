# Musical analysis and agent composition

SaberMapper provides local evidence; Codex or Claude Code authors the map. The
studio does not call an LLM or turn analysis peaks into note patterns.

The agent starts with `python -m sabermapper music backends`, chooses techniques,
runs `music analyze ID`, then inspects short beat ranges with `music inspect ID
--run RUN_ID --start BEAT --end BEAT`. Inspection returns the current revision,
grid, mapped notes, musical events, energy contours and focus together. The agent
saves its authored notes and focus through the existing revision-aware `project
save` command. The user gives requests and feedback in Codex or Claude Code and
reviews the resulting map in ArcViewer; no studio operation is required.

As an optional agent-operated inspection surface, the **Music layers** panel runs frequency-band analysis or harmonic/percussive
separation with a balanced, metal, electronic or vocal preset. Select a
run to compare its attacks with mapped notes in the selected beat range.
Lines show spectral-flux candidates, dots show energy-rise candidates. Click a
candidate to seek. Use **Listen** to solo an available stem at the same playhead,
or return to the full mix. **Mute** silences preview audio. The main waveform
continues to show the full mix. Analysis never changes the saved arrangement.

For individual instruments, the agent runs the `ensemble` backend: Demucs
`htdemucs_ft` (vocals, drums, bass) with its remainder split into guitar, piano
and other by `htdemucs_6s` masks, in the separate `.venv-separation` environment
on the GPU when one is available. It can also run a single Demucs model, or
import aligned outputs from other tools such as BS-RoFormer or Mel-Band RoFormer.
Every separated stem is bleed-gated: its events are dropped where it sits 30 dB
or more below the mix. Each run records `layer_entries` (a stem becoming audible
after silence) and writes `overview.png`, a spectrogram of the mix and every
stem; `music spectrogram` draws any beat range with the current notes, so the
agent can see the song it cannot hear.
All completed runs are retained; **Refresh** discovers new agent runs.
Model environments are separate from the studio's base Python dependencies.

The agent records phrase-specific musical priorities using `musical_focus` inside
the arrangement's sections. A phrase may follow vocals, the next a riff, and the
next the full ensemble (`mix`). Weights guide the agent's selection of musical
events; they are not audio volumes or note-density controls. At the playhead the
studio shows the saved focus and weights. The agent can also use the existing
section or arrangement JSON editor to inspect and save them.

The complete CLI, optional model setup, stem manifest, focus schema and authoring
workflow are in the portable [agent reference](../skills/sabermapper-map/references/musical-focus.md).

Evidence includes exact source identity, settings, timestamps and stem provenance.
Source seconds are converted to beats using the current grid, including tempo
changes. Strength is relative within each detector/layer, not confidence or
comparable loudness. Frequency bands and harmonic/percussive components are not
isolated instruments. Vocal attack candidates are not syllable transcriptions.
Matching stem durations cannot rule out internal delay; inspect alignment and
separation artifacts. Validation cannot establish musical quality or VR comfort.

## Sustained pitch, pitch changes, attack profile and passages

Report schema `1.1` adds four estimates. They are evidence for the agent, never
notes: nothing here selects a rhythm, a lane, or a difficulty.

Per layer:

- `sustains` — contiguous voiced runs of a monophonic f0 track (70–1100 Hz,
  same 9.98 ms hop, 46 ms comparison window, octave-continuity across frames,
  7-frame median smoothing). A run allows 50 ms unvoiced gaps and at most a
  2-semitone frame-to-frame move; an exact octave slip is folded rather than
  broken. Runs shorter than 0.35 s are dropped. Each entry carries
  `id`, `start_seconds`, `end_seconds`, `start_hz`, `end_hz`, `median_hz`,
  `semitone_delta`, `pitch_shape`, `confidence` and `strength`.
  `semitone_delta` is the signed drift implied by a robust trend (least squares
  after discarding points more than 3 semitones from a running median) times the
  segment duration, not head minus tail. `pitch_shape` is `rise` at
  `semitone_delta` ≥ +0.8, `fall` at ≤ −0.8, `flat` between, and `unstable` when
  the residual spread around the trend exceeds 3 semitones or mean voiced
  confidence is low. `confidence` is mean voiced confidence times the voiced
  fraction inside the segment; `strength` is the segment's mean frame RMS
  normalized within the layer, like event strength.
- `pitch_change` events, inside the layer's ordinary `events` list with
  `"method": "pitch_change"`. They mark a settled step: the smoothed pitch moves
  at least 0.8 semitones within about 30 ms and then holds the new value within
  ±0.6 semitones for at least 100 ms. A glide or a ±0.5-semitone vibrato at
  5–7 Hz does not qualify. Besides the usual `id`, `seconds`, `method` and
  `strength` (`min(1, |semitone_delta|/12)`, a size, not a confidence) they carry
  `from_midi`, `to_midi` and a signed `semitone_delta`.
- `chord_change` events (schema 1.2), on the mix and every separated layer except
  `drums` and `percussive`. A 12-class chroma is built from linear STFT
  magnitudes between 65 and 2100 Hz, minus each frame's weakest class. Novelty is
  1 − cosine similarity between the mean chroma of the 0.2 s before and after a
  frame; both sides must be above 10% of the layer's peak power. Peaks of at
  least 0.2 novelty, 0.15 s apart, become events, moved onto the layer's own
  `spectral_flux` attack when one is within 80 ms. They carry `novelty` (raw),
  `strength` (normalized within the layer) and the three strongest
  `from_pitch_classes` / `to_pitch_classes`. They follow strummed chords and
  polyphonic riffs that the monophonic f0 track cannot; they are not chord names.
- `attack_profile` — `{"sustained_fraction", "sustained_layer"}`. Over frames
  above 10% of the layer's peak power, `sustained_fraction` is the share still
  within 6 dB of their maximum power over the preceding 250 ms, i.e. holding
  rather than decaying after an attack. `sustained_layer` is true at ≥ 0.6. On a
  sustained layer, `energy_rise` peaks are envelope wobble, not attacks.

At report level, `passages` is an array of fixed, non-overlapping 2.0-second
windows in audio seconds: `drum_onset_density` (strong `spectral_flux` events
per second on the first available `drums`, `percussive`, `low` or `mix` layer),
`energy_ratio` (window median of the `mix` energy contour over the song-wide
median), `support_score` and `low_intensity`. `passage_thresholds` publishes
every constant and the layer actually used, so any classification is auditable.
Windows are clock time, not musical phrases.

`music inspect` returns sustains and passages with `start_beat`/`end_beat` added
on the current grid, plus `attack_profile` and `passage_thresholds`. Use
`--layer NAME` to restrict the excerpt to a single analyzed layer. Reports
written by schema 1.0 runs still slice; the new fields are simply absent.
`music analyze ID --from-run RUN_ID` (backend `rerun`) re-analyzes the stems an
earlier run separated, so a new detector reaches old projects without another
separation; the report records `producer.rerun_of`.

`music rhythm ID --start BEAT --end BEAT [--layers a,b] [--division 4]` renders
each 4-beat bar as one string per layer (`.` or a 1-9 strength digit per cell,
normalized within the range) beside the mapped notes (`x`), with the bar's lead
and pattern letters for repeated figures. `grid_fit` gives each layer's share of
strong attacks on the sixteenth and triplet grids.

Limitations: the f0 track is monophonic. Layered, choral or chordal material
gives `unstable` shapes and low confidence, and the estimate follows whichever
partial dominates. Frequency-band layers share the mix time signal, so sustains
and `pitch_change` are published on the `mix` layer only; band layers still carry
their own `attack_profile`. None of this is a transcription, and none of it
establishes musical quality or VR playability.

Technique references: [Demucs](https://github.com/facebookresearch/demucs),
[Music Source Separation Training / RoFormer inference](https://github.com/ZFTurbo/Music-Source-Separation-Training),
and [harmonic/percussive separation](https://librosa.org/doc/main/auto_tutorials/03-advanced/plot_hprss.html).

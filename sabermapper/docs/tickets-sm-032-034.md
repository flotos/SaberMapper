# SM-032 – SM-035: vocal expression, held notes, quiet-passage placement and repetition guards

Status: implemented 2026-09-22 (see "Outcome" at the end). Raised from user review of project `d002569949ef`
("Living a Lie - The Embrace That Smothers, Pt. 8") on 2026-09-22.

## Driving rule (user, 2026-09-22)

> Held singing notes, or intense singing, should always be the focus of the track.
> Use held notes (added relatively recently in Beat Saber) for these, bottom-to-top
> or top-to-bottom to match the pitch change if there is one.
> For example Living a Lie at 4:24, then 4:28, 4:30.

This is a standing authoring rule, not a one-off edit request. It is not yet
expressible in the pipeline: see SM-032.

## Second driving rule (user, 2026-09-22)

> For passages with low musical intensity and rhythm, I'd like the notes to play
> mostly on note change — for example around 2:55 for Living a Lie, or the intro.

Also standing, and also inexpressible today: the report has no notion of a note
change, and no notion of a passage lacking percussive support. See SM-035.

## Measured evidence from the current head

Head arrangement is revision `4fddf04c9de9c90d6fd00514565c90217f8544faf7d3f89e5d09926b1844faad`
(1099 notes), which is what the most recent exports were built from.

- **Zero arcs and zero chains in the entire map.** Every object is a plain colour note.
- At the three moments the user named as held/intense vocals — 4:24, 4:28, 4:30
  (absolute beats 536.19, 544.32, 548.39, section `final-drive`) — the map plays the
  same repeating cell cycle at roughly 4 nps.
- **12 distinct (lane, row, hand, cut-direction) placements across 1099 notes.**
  Eight of them repeat as a strict cycle covering **86.7%** of the map.
- Lane histogram: 442/441 notes in the two middle columns, 108/108 on the outer two.
  Row histogram: 550 bottom, 532 middle, **17 top** in the whole map.
- Pre-peak density collapse at 3:28–3:32 (section `return`, focus window `focus-424`):
  13 notes in 4 s (3.25 nps), of which beats 425–429 are five notes exactly one beat
  apart — 2.0 nps single-stream — immediately before the `peak` section.
  The same 4.1 s of audio carries 48 mix, 43 guitar, 27 drums and 22 vocal onsets.

### Low-intensity passages (second driving rule)

- Two passages have **zero strong drum onsets** and mix energy at roughly half the song
  median (0.007 vs 0.015): the intro, 0:00–0:28 (beats 0–57), and the quiet breakdown,
  2:38–2:58 (beats 321–362). The breakdown is the moment the user named as "2:55".
- Both run at exactly **2.0 nps** — the same floor as the 3:28–3:32 collapse above,
  reached regardless of what the music underneath is doing.
- In the intro the lead layers (`vocals`, `other`) fire **~6 events/s** — about 3 per beat
  at 122 BPM — and **63% are `energy_rise`**, against ~50% in the body. On held pad and
  voice that detector tracks envelope wobble, not attacks: the vocal "onsets" at 2.085,
  2.265 and 2.554 s are one sustained note breathing. The placed notes sit a median
  **36 ms** from a detected event, so they are faithful to the evidence — the evidence is
  what is wrong, not the placement.
- **22 of 57 intro notes sit on 1/4 or 3/4 of a beat**, 16th positions in a passage with
  no percussion to justify them. Three are far from any detected event at all: beat 5.75
  is 576 ms out, beats 25.5 and 27.25 are 427 and 434 ms out — 1/4-beat snapping pushed
  a smeared time into a gap.
- The intro's `piano` stem has clean attacks landing within ~20 ms of the grid (beats
  29.00, 29.51, 30.04, 32.03, 32.51, 33.02, 34.02, 35.03, 37.04), yet piano is **never**
  selected as lead for any intro focus window. The louder sustained pad wins on energy.
- The strongest attack in the intro (piano, beat 32.03, normalized strength 1.00) falls
  exactly on the `opening`/`build` seam and carries **no note**: `opening` ends at 31.5,
  `build` begins at 32.5.
- **The grid is not at fault.** 122 BPM at offset 0.302 s tracks 940 strong drum onsets to
  a **7.7 ms median** (6.8 ms before 90 s, 12.0 ms after 200 s). The intro's out-of-sync
  feel is placement, not tempo, despite `timing_reviewed: false` on the project.

## Root causes

1. `sabermapper/musical.py` emits attack events only (`spectral_flux`, `energy_rise`)
   plus a coarse RMS `energy_contour`. There is **no pitch track and no per-note
   sustain segmentation**, so "held vocal note, pitch rising" cannot be stated in the
   evidence the authoring agent reads.
2. The map skill documents arcs and chains in one sentence
   (`skills/sabermapper-map/references/arrangement.md:7`) as "advanced objects" whose
   "unsupported fields fail closed", and gives no field reference or usage policy.
   The authoring agent therefore never used them.
3. `sabermapper/validation.py` is structural only. Nothing measures density continuity
   or placement repetition, so a map that is 87% one eight-note loop validates clean.
4. `sabermapper/movement.py:148` lists `arcs` and `chains` under `unsupported_motion`,
   so difficulty proxies would ignore held notes even once they are authored.
5. `musical.py` applies both detectors uniformly to every layer and every passage.
   Nothing marks a passage as lacking percussive support and nothing downgrades
   `energy_rise` on sustained material, so a pad's envelope noise enters the evidence
   with the same standing as a snare.
6. Lead selection follows layer energy. Where a sustained pad is loud and a quiet piano
   carries the pulse, the pad wins and the rhythm-bearing layer is never consulted.

**Not** a cause: the export path. Arcs and chains are already supported end to end —
`sabermapper/arrangement.py:73-84` compiles them to v3.3.0 `sliders` and `burstSliders`,
and `sabermapper/validation.py:121-170` already enforces their field schema. Nothing in
the engine's output stage needs to change for the driving rule.

---

## SM-032 — Sustained-pitch evidence for melodic layers

**Problem.** The authoring agent cannot see held notes or pitch direction.

**Change.** Extend the musical evidence report with a `sustains` array per melodic
layer (`vocals`, `guitar`, `bass`, `piano`, `other`), alongside the existing `events`:

```json
{"id": "vocals:sustain:26415", "start_seconds": 264.15, "end_seconds": 265.02,
 "start_hz": 329.6, "end_hz": 392.0, "median_hz": 359.1,
 "semitone_delta": 3.2, "confidence": 0.81, "strength": 0.74}
```

`semitone_delta` is head-to-tail and signed; its sign is what the arc direction rule
in SM-033 consumes.

**Method.** No `librosa` in this environment — deps are numpy/scipy/soundfile only
(`pyproject.toml:10`), and `musical.py` is already hand-rolled over its own framing.
Implement a YIN-style autocorrelation f0 estimator on the existing analysis hop
(9.98 ms), gate on a voiced-frame confidence threshold, merge contiguous voiced frames
into segments with a minimum duration (~0.35 s) and a maximum within-segment jump,
then report head/tail/median pitch per segment. Budget the work assuming the estimator
is written and tested in-repo, not imported. **Octave continuity is required, not
optional** — prefer the candidate nearest the previous voiced frame. A probe of a
harmonic-product-spectrum tracker on this project's `vocals` stem produced frequent
flips of exactly ±12 semitones that immediately reverse; see SM-035's probe note.

**Surface.** `music inspect` returns sustains for the requested beat slice. Add
`--layer` to scope the slice to one stem.

**Boundary.** Evidence only. `musical_cli.py` must continue to compose nothing.

**Acceptance.**
- Unit test: synthetic 1 s tone gliding a known interval yields one sustain with
  `semitone_delta` within tolerance of the true interval, and a flat tone yields ~0.
- Unit test: a sequence of short staccato attacks yields no sustain segments.
- On `d002569949ef`, `music inspect` over the beat range covering 4:24, 4:28 and 4:30
  returns at least one vocal sustain of ≥0.35 s at each of the three moments, with a
  non-zero `semitone_delta` wherever the pitch moves.

---

## SM-033 — Author arcs and chains for held and intense vocals

**Depends on SM-032** (arc direction needs the pitch sign).

**Problem.** The driving rule has no home in the skill, and the one existing mention of
arcs and chains discourages their use.

**Change.**

1. New reference page `skills/sabermapper-map/references/held-notes.md` giving the exact
   `arcs` and `chains` object fields as `validation.py` enforces them — including which
   are optional (`head_multiplier`, `tail_multiplier`, `mid_anchor`, `squish`) and the
   tail constraint that `tail_beat` must fall inside the same section.
2. New authoring policy in `skills/sabermapper-map/SKILL.md`:
   - A vocal sustain above the duration threshold takes **focus priority** over backing
     percussion for its window. Do not thin it into stock onset notes.
   - Sustain with rising pitch → arc from a low row to a high row (`y` 0 → 2);
     falling pitch → `y` 2 → 0; flat → lateral movement across lanes at constant row.
   - Intense or belted vocal runs (dense attacks inside one vocal phrase) → chain
     (burst slider) across the run rather than a repeated alternation cell.
   - State the sustain evidence IDs that justified each arc in the section `intent`.
3. Update `skills/sabermapper-map/references/musical-focus.md` so a `lead: vocals`
   window that contains sustains selects arcs and chains, instead of falling through to
   the gap-preserving onset policy that produced the 3:28–3:32 collapse.
4. Rewrite the discouraging sentence at `references/arrangement.md:7` to point at the
   new reference page.

**Acceptance.**
- A revision of `d002569949ef` places arcs at 4:24, 4:28 and 4:30 whose `tail_y` differs
  from `y` in the direction matching the measured `semitone_delta` sign from SM-032.
- `python -m sabermapper validate` reports no errors on that revision.
- Export compiles to v3.3.0 with non-empty `sliders` and opens in local ArcViewer.
- Arcs and chains appear in more than one section, not only the three named moments.

---

## SM-034 — Density and repetition critique

**Problem.** A map that is 87% one eight-note loop, with 17 top-row notes in 1099 and a
2.0 nps hole before its peak, passes validation clean.

**Change.** Add a non-blocking critique report — either a new `arrangement critique`
subcommand or an `analysis` block on `validate`, emitting `warning` severity only and
never blocking compilation:

- Rolling nps per 4 s window and per section, with each section's density compared
  against the role implied by its `intent`.
- **Density-collapse flag**: a sustained drop below a fraction of the local median
  immediately preceding a section whose role is peak or drive.
- **Repetition flag**: distinct-placement count and placement entropy over a rolling
  window, plus detection of a repeating n-gram cycle above a coverage threshold.
  The current head must trip this at 86.7% coverage of one 8-cell cycle.
- Lane and row histograms, flagging an unused or near-unused top row.
- **Boundary-accent flag**: a strong evidence accent falling within a small window of a
  section seam with no note on either side of it. The current head must trip this at
  the beat 32.03 piano hit on the `opening`/`build` seam.

Also extend `sabermapper/movement.py` so arcs and chains contribute to the swing model
and are removed from `unsupported_motion` (`movement.py:148`); once SM-033 lands, a map's
difficulty proxies would otherwise ignore its held notes entirely.

**Acceptance.**
- Run against the current head: flags the 3:28–3:32 collapse, the 8-cycle repetition,
  the top-row starvation and the beat 32.03 boundary accent, and reports zero errors.
- Run against a fixture with hand-varied placement and continuous density: clean.
- Unit test asserting the critique never emits `error` severity.

---

## SM-035 — Note-change placement in low-intensity passages

**Depends on SM-032** for the f0 track. Adds a passage classifier and a second
change detector on top of it.

**Problem.** Where a passage has no percussion, the report still contains thousands of
`energy_rise` peaks, and the pipeline places notes from them. The intro and breakdown
measurements above are the result: notes faithful to a detector that is measuring a held
note's envelope rather than any musical event.

**Change.**

1. **Passage classifier.** Per focus window, score rhythmic support from three measured
   terms — strong drum-onset density, mix energy relative to the song median, and how
   tightly the lead layer's events concentrate on grid subdivisions. Publish the score
   and all three inputs in the report so a classification is auditable rather than a
   threshold buried in code. Both Living a Lie passages score zero on the drum term and
   about half the median on energy; the rest of the song scores high on both, so the
   separation does not rest on a finely tuned cutoff.

2. **`pitch_change` events**, from the SM-032 f0 track: emit where smoothed pitch moves
   ≥ ~0.8 semitone and **holds** the new value for ≥ ~100 ms. The hold requirement is what
   separates a note change from vibrato. Carry `from_midi`, `to_midi` and a signed
   `semitone_delta`. These are the SM-032 sustain boundaries expressed as placement
   triggers — one implementation, two surfaces.

3. **`harmonic_change` events** for polyphonic sustained layers, where no single f0
   exists. Fold the existing STFT magnitude into 12 pitch classes, smooth over ~300 ms,
   and emit on peaks of the frame-to-frame chroma distance. This catches chord changes
   under a held vocal. numpy/scipy only, over the framing `musical.py` already computes.

4. **Authoring policy** in `skills/sabermapper-map/SKILL.md` and `musical-focus.md`,
   scoped to classified low-intensity windows:
   - Place mostly on `pitch_change` and `harmonic_change`, not on every amplitude peak.
   - Do **not** place from `energy_rise` on a sustained lead in these windows.
   - Keep genuine attacks. The intro piano is real, grid-locked and currently ignored.
   - Select the lead by rhythmic salience, not energy.
   - Quantize to 1/2 or whole beat. Sung note changes do not land on 16ths.

**Interaction with SM-033.** The same pitch movement, two uses: SM-033 reads its sign to
aim an arc, SM-035 reads its timing to decide a note exists at all. On a held vocal in a
quiet passage both apply — one pitch move places the arc and sets its direction. SM-033's
policy takes precedence where a sustain is present; SM-035 governs the gaps between them.

**Probe note (read before implementing SM-032).** A hand-rolled harmonic-product-spectrum
f0 track over this project's `vocals` stem gave 1.6 events/s in the intro and 2.1/s in the
breakdown, against 6.0/s from `energy_rise` — the right order of magnitude, with the
detected pitches forming a coherent line. Two defects appeared, and both constrain SM-032:
**octave flips** (jumps of exactly ±12 semitones that immediately reverse) and **vibrato
doubles** on Epica's sustained operatic notes. Octave continuity and a minimum note
duration are mandatory. Raw timing residuals reached ±120 ms — a quarter beat at 122 BPM —
which is the concrete reason quantization in these passages must be coarse. The probe was
throwaway and is not in the repo; it establishes feasibility and the tuning burden, not a
working detector.

**Boundary.** Evidence and policy only. `musical_cli.py` must continue to compose nothing.

**Acceptance.**
- Unit test: a synthetic two-note phrase at constant amplitude yields one `pitch_change`
  at the join; a vibrato-modulated single tone yields none.
- Unit test: a four-chord pad at constant amplitude yields three `harmonic_change` events;
  a single sustained chord yields none.
- Unit test: the classifier marks a synthetic drumless quiet window as low-intensity and a
  dense percussive window as not.
- On `d002569949ef`, the classifier flags beats 0–57 and 321–362 and nothing in the
  surrounding sections.
- After re-authoring those two windows: no intro note sits on a 1/4 or 3/4 subdivision, the
  beat 32.03 piano accent carries a note, and sections outside the classified windows are
  untouched by this pass.

---

## Path

Ordered, with the reason each step gates the next.

1. **SM-032 first.** Evidence before authoring — an arc whose direction should track
   pitch cannot be placed while the report has no pitch. Land the f0 estimator with its
   unit tests, then re-run `music analyze` on `d002569949ef` so the sustains exist for
   steps 3 and 5. The existing `59325c64…` run stays valid; this adds a new run.
2. **SM-034's critique report second, before any re-authoring.** It is cheap, it does not
   depend on SM-032, and running it against the current head first gives an objective
   before/after for the rewrite instead of a subjective one. Record the baseline numbers.
   Include the boundary-accent flag so the beat 32.03 miss is in the baseline.
3. **SM-035's classifier and change detectors third.** The classifier does not depend on
   SM-032 and can land alongside step 2; `pitch_change` reuses the step 1 f0 track, so it
   follows it. Run the classifier over `d002569949ef` and confirm it selects only the two
   measured windows before any policy is written against it.
4. **SM-033 and SM-035 skill and reference updates fourth.** Both write policy into the
   same two files, so write them together to avoid a conflicting half-state: held-note
   priority and arc direction from SM-033, quiet-passage placement from SM-035. Then
   refresh both agent copies with
   `.venv/Scripts/python scripts/install_skills.py --update`.
5. **Re-author Living a Lie against the new rules.** Held notes at 4:24, 4:28, 4:30 first
   so the user can check the direction of travel on the specific moments they named; then
   the intro and the 2:38–2:58 breakdown, the two moments behind the second rule; then
   the 3:28–3:32 pre-peak build; then the placement-vocabulary pass across the whole map.
   Save through `project save` against the current revision SHA. Re-run the step 2
   critique and compare against the baseline.
6. **Persist both rules.** Record them in `workspace/player-profile.json` under
   `overrides` so they apply to every future project, and file a feedback record
   against `d002569949ef` capturing them as the source of the revision.
7. **Export and review.** Open the saved revision in local ArcViewer at the named
   timestamps — 4:24/4:28/4:30 for the held notes, the intro and 2:55 for the quiet
   passages. VR playtest verdict remains the user's; do not record one from preview.

Register SM-032, SM-033, SM-034 and SM-035 in `docs/ticket-coverage.json` when each
lands, with evidence paths, following the existing entry format.


---

## Outcome (2026-09-22)

All four tickets landed the same day, in a different order than the path above
(see "Review of the path" for why). Evidence:

- **Validator connection rule (added to SM-033).** An arc needs an authored colour note at its
  head and tail, a chain at its head, with matching cut direction; `validation.py` now errors
  otherwise (`arc_head_without_note`, `arc_tail_without_note`, `chain_head_without_note`,
  `*_direction_mismatch`). Basis: the BSMG format page ("if the head of a chain matches a note's
  time and position, then the chain will connect with the note") and the local corpus, where
  98.7% of arc heads and 97.2% of arc tails coincide with a note. The original ticket's claim
  that the export path needed no change was wrong: a dangling arc validated clean and exported
  as a cosmetic curve.
- **SM-032.** `musical.py` schema 1.1: per-layer `sustains` (YIN-style f0, octave continuity,
  robust-slope `semitone_delta`, `pitch_shape` rise/fall/flat/unstable), `pitch_change` events,
  `attack_profile.sustained_layer`; report-level `passages` with published thresholds;
  `music inspect --layer`. 16 s for a 5-minute song. On `d002569949ef` run `82ddaae3…` the vocal
  layer carries 127 sustains (54 of at least 0.7 s), and the classifier flags exactly beats
  0-48, 321-361 and the silent tail.
- **SM-033.** `references/held-notes.md`, skill policy, `arrangement.md` pointer. Chains are
  not used: zero of the 128 reference-band v3 difficulties contain one.
- **SM-034.** `critique.py` and `critique` / `project critique`. The density-collapse metric was
  redefined during implementation: the sparsest 2 s window inside the section's last 8 s, because
  a 4 s average hid the 425-429 hole (0.72 of median, above the 0.6 threshold). Baseline on the
  old head trips all four flags; see `workspace/projects/d002569949ef/critique/`.
- **SM-035.** Classifier, `pitch_change` and `attack_profile` as above; `harmonic_change` was
  deferred, since both named passages track as a single voice.

**Re-authored revision `a25b11c7…`** (feedback record `02d2c46a9fa2`):

| Metric | Old head `4fddf04c…` | New `a25b11c7…` |
|---|---|---|
| Notes / arcs | 1099 / 0 | 961 / 37 |
| Distinct placements | 12 | 64 |
| Cycle coverage (best k) | 0.849 (k=16) | 0.177 (k=8) |
| Top-row share | 0.016 | 0.157 |
| Critique warnings | 4 | 1 (breakdown rest before `return`, musical) |

Named held notes: 4:24 rises bottom to top over beats 535.5-538.5, 4:28 falls top to bottom over
543.5-546.5, 4:30 falls over 547-548.5. The intro carries six notes on the pad chord changes,
the soft entry and the piano attacks; the breakdown carries 17 notes plus three arcs on pitch
and chord changes at half beats.

**Decisions the implementation added to the tickets.**
- Merging: consecutive sustains join into one phrase only across gaps under 0.35 s with pitch
  continuity within 4 semitones; a user-named timestamp anchors a phrase that may join across
  0.6 s consonant gaps up to 3 s but never into another named time. Without this the
  estimator's segment boundaries, not the sung phrase, chose the arcs.
- Arc travel: one row by default, two rows for sustains of at least 1.5 s and for user-named
  climax notes. Head cut points along the arc, tail cut opposite (corpus: 1544 opposite,
  4 same).
- Vocal-stem pitch below 110 Hz is bleed, not voice, and is ignored for arcs.
- Support under an arc: the arc hand is cleared for the arc's span plus half a beat; the other
  hand keeps its pulse except within a quarter beat of the head and tail.

Not done: no VR playtest, `timing_reviewed` and `playtested` remain false.

# SM-036: Build maps correct by construction; replace the repair commands with one validator

Status: Proposed · not implemented.
Phase: Productize.
Size: L; v0 slice: M (see backlog size legend).
Dependencies: SM-017 (arrangement format), SM-018 (compiler), SM-019 (validation), SM-030 (movement model), SM-034 (critique).
Raised: 2026-09-23, from the user's request: "I'd prefer a pattern where initial build avoid all these issues, or to have only one 'repair' tool but that should be more a 'validator' than repair."

## Problem

The agent writes every field of every note by hand: time, hand, cut direction and grid cell. The rules are checked only after that, and three commands then rework the saved map:

| Command | Module (lines on `main`, 2026-09-23) | What it reworks |
| --- | --- | --- |
| `project repair-swings` | `swing_repair.py` (417) | `fast_direction_break`, `flow_parity_break`, `arc_note_conflict`, `chain_note_conflict` |
| `project repair-visibility` | `visibility_repair.py` (208) | `hidden_note` |
| `project repair-audio` | `audio_repair.py` (1143, 7 passes) | Unsupported notes, `density_exceeds_audio`, eight "unmapped" fill codes, `lead_rhythm_diluted`/`_unmapped`, `intensity_underplayed`, `difficulty_exceeds_intensity`, `one_hand_burst`, `focus_on_quiet_stem` |

Consequences:

- **The pipeline repairs instead of preventing.** Each new rule so far has come with a new repair pass: 10 of the 58 commits on `main` (2026-09-23) name a repair, and `one_hand_burst` added another pass that day. The repairs must run in a fixed order (visibility, then swings, then audio), and `repair-audio` refuses to run while any blocking finding remains.
- **Musical decisions happen after the agent has finished.** `repair-audio` rebuilds whole bars, adds notes, removes notes and moves notes to other hands. The agent never planned these changes and only learns of them from a change log.
- **The repair code is already the builder.** `workspace/authoring/fireflies/hand_bars.py` builds bars by importing `insert_note` from `audio_repair.py`, and `swing_repair.py` imports it too. Placement logic that can't break flow exists, but only as a side door of a repair.
- **Checks and fixes can drift.** Each repair keeps its own copy of the rule it fixes. Examples: the reach limit is a bare `12` in `movement.py` and is redefined as `REACH_SPEED = 12` in both `audio_repair.py` and `visibility_repair.py`, and each of those modules has its own `_cells` search.

## Outcome

The agent authors the **musical** layer: which sounds to map, plus optional pins. A deterministic **placer** decides the **mechanical** layer, so every blocking movement rule holds by construction. Audio rhythm is drafted from the same rules the critique checks. One read-only **`project check`** reports everything, with suggested fixes, and never edits the map. The three `repair-*` commands are deleted.

## Design

### 1. Rhythm authored by the agent, placement by the tool

- A note in an arrangement section needs only `id` and `beat`. `color`, `direction`, `x` and `y` become optional **pins**. A fully specified note is valid input, and existing arrangements stay valid unchanged.
- Arcs and chains stay agent-authored. They reserve their saber from head to tail, and the placer treats that as a constraint.
- At compile and save time, the placer walks the timeline once in time order. It keeps per-hand state: effective last direction, parity, position, and held-until.
  - For each unplaced note, it chooses hand, direction and cell satisfying `movement.flow_break`, `hidden_note`, held-saber conflicts, reach (`reach_proxy`), hand crossing and `one_hand_burst`.
  - Pinned fields are hard constraints.
- It is deterministic: the same input always gives the same output. It does not search randomly.
- Among valid options it prefers **variety**, as the player profile asks for technical variety. The score should use the SM-034 repetition metrics (distinct placements, strict cycle share) as well as flow comfort, so the placer doesn't settle into one cycle.
- **Infeasible input is an error, not a repair.** For example, three same-hand sounds under 0.2 s apart when the other hand is held, or a pinned direction that breaks flow. The error names the beat, the notes and the reason, and it lists the feasible alternatives: other hands, directions or cells, and dropping one of the times. The agent resolves it musically.
- Locked sections, and notes the agent pinned, are fixed context. The placer never changes them. Motif and pattern notes are placed once per motif, with its entry state checked at each use; an entry state the motif can't accept is an infeasibility error.
- Saved arrangements store the placed values together with a record of which fields were pinned. That way a later rhythm edit re-places only the tool-chosen fields and keeps the agent's choices. The exact representation is settled in v0.
- Code origin: `audio_repair.insert_note`, `_effective`, `_reach_ok`; `swing_repair._hand_swings`, `_count_breaks`; `visibility_repair._cells`. These move into one module (`placement.py`) that imports named constants from the movement model (the reach limit becomes one) rather than copying them.

### 2. Rhythm drafts that follow the critique's rules

- `music rhythm` gains a proposal mode, for example `--propose`, returning suggested note times per bar together with the evidence behind each one. The proposal uses the functions the critique itself uses (`lead_onsets`, `strongest_per_slot`, `quiet_bar`, `quiet_windows`, `intensity_bars`, `salient_onsets`), scaled to the difficulty's `target_tier`:
  - the declared lead's strongest attack per half-beat;
  - fills where the lead is silent;
  - thinned note times in quiet windows;
  - heavier bars up to the soft passages' peak demand;
  - vocal, drum, melody and accent onsets the salience checks count.
- The agent edits the proposal. It is a starting point, not the map.
- Everything musical in `repair-audio`'s passes moves here, before authoring rather than after: grounding, thinning, lead rebuilds, fills, harden and ease, and burst splitting. A proposal that the agent leaves unedited must produce no `note_without_audio`, `density_exceeds_audio`, `lead_rhythm_*`, intensity or `one_hand_burst` finding (acceptance criterion).
- Focus reweighting (`reweight_focus`) becomes a check finding with the proposed weights as its suggestion.

### 3. One validator that never edits

- New command `project check ID [--difficulty NAME] [--run RUN]` merges structural validation, the movement model, `audio_grounding` findings and the critique into one report. Each finding has `code`, `severity`, `blocking`, `beats`, `object_ids`, `message` and `suggestions`.
- `suggestions` are concrete edits the agent can apply: `{"op": "move", "object_id": ..., "to": {"x": 3, "y": 1}}`, `{"op": "retime", "to_beat": "65/2"}`, `{"op": "remove", ...}`, `{"op": "set_weights", ...}`. They come from the same candidate generators the placer uses. The check never writes anything.
- `project save` refuses exactly the findings `project check` marks `blocking`. The gate and the report share one code path: today `check_save` calls `validate_arrangement` and `project_audio_findings` separately.
- `project critique` and top-level `validate`/`critique` become thin aliases of the same report for one release, then are removed or kept as documented aliases. That decision is part of this ticket.

### 4. Delete the repair commands

- Remove `project repair-swings`, `repair-visibility` and `repair-audio`, their modules and their CLI entry points. The reusable parts live on in `placement.py` and the rhythm proposal.
- **New rules go into the placer's constraints plus a `project check` finding, never into a new post-hoc repair.** Update the "Systematic fixes" section of `AGENTS.md`: its "automated correction" level means a build-time placement rule or safer default, not a command that rewrites saved maps.

## Minimal v0 slice

1. `placement.py` with the blocking movement constraints and the variety preference. It places notes whose `color`/`direction`/`x`/`y` are missing and returns structured infeasibility errors.
2. Compile and `project save` accept partially specified notes, place them and record pins. Fully specified input compiles byte-identically to today.
3. `project check` combining validate, movement, audio grounding and critique, with suggestions for the movement codes.
4. Regression tests. For each blocking movement code: an unpinned rhythm that would violate it under a naive placement is placed cleanly, and a pinned note that violates it produces the infeasibility error with alternatives.

The repair commands stay available during v0.

## Expansion

1. The `music rhythm --propose` rhythm draft, with the "unedited proposal produces no audio finding" tests.
2. Suggestions for the audio and critique codes.
3. **Comparison across the workspace.** For every project and difficulty from `project list`, re-place the current revision with its placement fields unpinned. Compare `project check` output against the stored revision: blocking findings, audio findings, SM-034 repetition and variety metrics, and swing demand per intensity bar. Save the comparison under `workspace/authoring/sm-036/`. Save a re-placed revision only when it is no worse on every measure. Otherwise keep the current revision and record why.
4. Delete the repair modules and commands. Update `skills/sabermapper-map`, `skills/sabermapper-review`, `docs/user-guide.md`, `docs/movement-model.md` and `docs/critique.md`, then run `scripts/install_skills.py --update`.

## Decisions and pitfalls

- **Variety versus comfort.** A placer that optimizes only for flow produces the monotonous cycles SM-034 measured: 12 distinct placements, with one cycle covering 86.7% of a map. Variety must be part of the scoring and measured in the comparison, not assumed.
- **The agent keeps control.** Pins are the escape hatch for any deliberate pattern. The placer must never override a pin, and infeasibility must be reported, never silently resolved.
- **Determinism.** Placement must be reproducible from the arrangement alone, with no dependence on evidence-run order, dictionary order or wall-clock time. Revision hashes depend on it.
- **Locality.** Editing one bar's rhythm must not reshuffle placements in unrelated sections. The placer re-places only unpinned fields and carries boundary state across sections. Test that the rest of the map is unchanged after a local edit.
- **Locks.** Locked sections are fixed context, as they are today. If a locked section makes the next unlocked note infeasible, report it; don't unlock anything.
- **No new repairs in the meantime.** Until this lands, a new rule should add a check and a placer constraint (or at least a `insert_note` constraint), not another `repair-audio` pass.
- Structural validity still says nothing about musical quality or VR playability; see the backlog's evidence rules.

## Acceptance criteria

- [ ] An arrangement with only `id`/`beat` notes (plus arcs and chains) compiles and saves with zero blocking findings, or fails with an infeasibility error that names the beat, the notes, the violated rule and at least one feasible alternative.
- [ ] Fully specified arrangements from every existing project compile byte-identically before and after the change.
- [ ] Pinned fields are never changed by placement, and a local rhythm edit leaves every note outside the edited bar unchanged.
- [ ] `project check` is read-only (it writes nothing to the project directory), and `project save` blocks exactly the findings it marks `blocking`.
- [ ] Every blocking movement finding in `project check` carries at least one concrete suggestion that clears it.
- [ ] An unedited `music rhythm --propose` draft, once placed, produces no `note_without_audio`, `density_exceeds_audio`, `lead_rhythm_diluted`, `lead_rhythm_unmapped`, `intensity_underplayed`, `difficulty_exceeds_intensity` or `one_hand_burst` finding, in tests and on every workspace project with an evidence run.
- [ ] The comparison in Expansion step 3 is recorded for every project and difficulty, and each is either saved as a revision that is no worse on every measure or kept with a stated reason.
- [ ] The `repair-swings`, `repair-visibility` and `repair-audio` commands and modules are removed. No skill, doc or test references them, and the "Systematic fixes" guidance in `AGENTS.md` names build-time placement and `project check` as the automated levels.

## Musical rules the rhythm draft and placer follow

These come from authoring Living a Lie from its ensemble stems and spectrograms on 2026-09-23 (Expert revision `73b10992`, ExpertPlus `9e348b1d`: every note time on a sound, no critique warning except `tier_below_target`). Each rule describes a first draft, for every song:

- **Each bar has one role, read from the evidence: soft, riff or sung.** A bar is soft when it is quiet or the drums rest. It is a riff when drums and guitar play and the voice is absent or not articulated. Otherwise it is sung. Loudness relative to the song's loud bars (75th percentile of passage `energy_ratio`) and the `target_tier` set how many note times a bar may carry. Heavy riff bars carry the most.
- **Riff bars follow the riff, not the kick alone.** Candidates are the union of guitar and kick attacks on a sixteenth grid. The guitar's strongest attack per half beat always carries a note (`lead_rhythm_unmapped`). A kick that falls between two guitar chugs stays unmapped, so the riff's rests survive (`lead_rhythm_diluted`). Such a kick has no guitar attack within 0.13 beat, and has one within 0.75 beat. The bar keeps its heaviest ensemble accent away from the guitar.
- **Sung bars follow the syllables first.** Vocal onsets outrank every band hit, and a bar maps at least 60% of its syllables that no arc holds (`vocal_line_unmapped`). Band attacks fill the voice's gaps of 0.75 beat or more, and play on the free hand under a held arc: the kick or snare, a guitar chug or a bass attack, taking the strongest per half beat with a mix attack under it. Outside gaps and holds, band attacks take at most 24% of the bar's note times, below the 25% limit of `lead_rhythm_diluted`.
- **Held and intense singing becomes an arc.** A vocal sustain becomes an arc when it lasts at least 0.7 s and 1.25 beats. Intense singing (sustain strength 0.45 or more) needs 0.62 s and 1.2 beats. A held note the user named (`held_vocals` in `player-profile.json`) needs 0.9 beat, with its sustain starting within 1.5 beats of the named time. The ensemble separator splits Living a Lie's hold at 4:24 into a 0.698 s sustain. Arc heads and tails take priority over every other time in their bar, and an arc ends inside its own section.
- **Soft bars map changes at half-beat spacing.** Notes sit on melody and chord changes (mix melody, vocal melody, other-stem chords) and on genuine attacks, at least half a beat apart. In a sung soft bar they sit on the voice or in its gaps.
- **Doubles mark the heaviest accents, and both hands reach them on the same parity.** A loud bar carries up to two. In a riff bar they go on kick or crash hits of strength 0.8 or more with a mix attack. In a sung bar they go on the heaviest ensemble accent and the snare backbeat. The sixteenth before a double stays empty, unless it carries the guitar's strongest attack of that half beat. The last single note before a double goes to the hand that leaves both hands on the same parity.

## References to check

- `sabermapper/placement.py` (the placer: `place_arrangement`, `pin_edits`, `rule_violations`), `sabermapper/check.py` (`project check`, the save gate, movement suggestions)
- `sabermapper/rhythm_proposal.py` (`music rhythm --propose`, the audio and critique suggestions)
- `sabermapper/movement.py` (`flow_break`, `is_rest`, `hidden_note`, `hidden_window`, `one_hand_bursts`, `REACH_SPEED`)
- `sabermapper/projects.py` (`prepare_save`, `check`, `lock_conflicts`)
- `workspace/authoring/sm-036/compare_placement.py` and `comparison.json` (Expansion step 3)
- [SM-030](SM-030-movement-and-strain-model.md), [SM-034](../../docs/tickets-sm-032-034.md)

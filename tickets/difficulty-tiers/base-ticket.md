# Harder difficulties that scale NJS and movement, and a real challenge-tier Living a Lie

Status: open, 2026-09-23. Blocked until the spectrogram-reading work (another agent) is merged into
`main`; start only after that lands, then rerun the song analysis. Follows the multi-difficulty and
star-tier work merged on 2026-09-23 (`Merge multi-difficulty`, `Merge repair-tier-noise`).

## Request (user, 2026-09-23)

- Living a Lie's map was "quite easy"; the user wants harder star levels supported.
- "Harder isn't always more notes, but usually yes it is. Also note jump speed should follow, as you
  can see in the maps to analyze."
- "Map more than the lyrics if needed, but avoid adding filler notes."

## Current state

- A project holds one arrangement per difficulty: `arrangement.json` is the primary one, and the
  others live in `difficulties/NAME.json`. Every project command takes `--difficulty NAME`.
  `project add-difficulty` adds a difficulty and `project export` writes all of them to one ZIP.
  See `sabermapper/skills/sabermapper-map/references/difficulties.md`.
- Player star tiers live in `sabermapper/sabermapper/star_tiers.py`: below_band <6.5, band 6.5–8,
  challenge 8–9, stretch 9–9.5 (9.5 is the hardest recorded pass, 9.47, rounded up), beyond.
  `corpus analyze` tags every phrase with its source chart's `stars`/`star_tier`. It also writes
  `workspace/corpus/tier-reference.json` and `tier-pattern-shortlist.json`. `corpus tiers` and
  `corpus retrieve --tier` read them. All 27 usable charts the player has passed at 8+ stars are in
  the corpus.
- `difficulty.target_tier` declares a difficulty's aim. `sabermapper/sabermapper/tier_fit.py`
  compares 4-beat windows of the map with each tier's reference windows. It uses only four
  **density** features: median and p90 window NPS, median swings/s, and median peak swings in 1 s.
  It emits `tier_below_target` / `tier_above_target`. NJS is not checked at all.
- Living a Lie (`d002569949ef`):
  - Expert (primary): the old map, revision `22085a31…`, 1,026 notes, target `below_band`, NJS 18.
  - ExpertPlus: revision `bb699e90…`, 1,458 notes, NJS 19, target `band`. It still reads closest
    to `below_band`: median window 5.08 nps against 6.75 for band.
  - Where ExpertPlus falls short: its loud guitar/drum sections are dense (first-drive 7.6, peak
    8.1, return 6.9 nps). The vocal-led sections (response, sustained, last-response, about 4.6
    nps) follow only the sung syllables, and held-vocal arcs occupy one hand.
  - It was built by `workspace/authoring/living-a-lie/expertplus_challenge.py` (a bar rebuild through
    `audio_repair.insert_note`) and `expertplus_variety.py` (breaks placement loops), then
    repair-visibility, repair-swings and repair-audio.

Measured on the corpus (medians of 4-beat windows, `tier-reference.json`, 79,373 windows):

| Tier | Window NPS | Swings/s | Peak swings/1 s | Longest ¼-s burst | Crossovers/window | Max grid speed | Chart NJS |
|---|---:|---:|---:|---:|---:|---:|---:|
| below_band | 4.16 | 4.27 | 5 | 3 | 1 | 6.6 | 15 |
| band | 6.75 | 6.89 | 8 | 5 | 2 | 13.0 | 18 |
| challenge | 7.67 | 7.68 | 9 | 6 | 3 | 16.0 | 19 |
| stretch | 9.0 | 8.73 | 10 | 7 | 3 | 17.1 | 20.25 |
| beyond | 9.75 | 9.70 | 10 | 6 | 3 | 20.1 | 20 |

Mean angular change and mean grid distance barely differ between tiers, so they do not separate them.

## Changes

### 1. NJS follows the tier

- `tier-reference.json` already holds `chart_njs` per tier. Add NJS stats per tier and BPM band
  (NJS and BPM interact through jump distance). If jump distance separates tiers better than raw
  NJS, report it too; `movement._reaction_proxy` already computes the half jump duration.
- `project add-difficulty --target-tier T` without `--njs` sets NJS from the tier's reference (median,
  adjusted for the song's BPM if the data supports it) and reports the value it chose.
- Critique (`tier_fit`): add a warning, e.g. `njs_outside_tier`, when `difficulty.njs` falls outside
  the target tier's p10–p90 chart NJS. Blocking is not wanted: the player may ask for a slower NJS.
- Skill: `references/difficulties.md` states that NJS rises with the tier and names the command.

### 2. Harder is not only more notes: tier_fit also measures movement

- Add movement features that separate tiers in the table above: longest quarter-second burst,
  crossovers per window and max grid speed. Also consider the p90 of swings/s. Weight them so that a
  map with equal density but more movement reads as a harder tier.
- Keep the method descriptive (closest tier, per-section breakdown). Report the per-feature gap so an
  agent knows which lever to pull (density, bursts, crossovers, NJS).
- Validate on the corpus: the closest tier of each source chart's own windows should match its
  real tier more often than with density alone. Report that confusion matrix in the PR.
- Report notes per beat beside notes per second, per section, so an agent can tell a slow song
  from an under-mapped one. The tier references come mostly from charts faster than 122 BPM
  (`chart_notes_per_beat` median 2.34 for challenge). Living a Lie ExpertPlus (2026-09-23, revision
  `9e348b1d`) reaches 2.5 notes per beat, above the challenge median of 2.25 per window, with every
  note on a sound. Its median window is still 5.08 nps, so it reads `below_band`.
- Update tests in `sabermapper/tests/test_difficulties.py` and the `tier_fit` definitions.

### 3. Map more than the lyrics, never filler (rule change, user decision)

The user decided that harder difficulties may map layers beside the lead. Filler stays forbidden.
Define the terms so a check can enforce them:

- **Filler**: a note time with no attack of strength ≥ 0.3 (on the new spectrogram-backed evidence)
  within 0.13 beat in any stem that carries rhythm in that bar. The candidate stems are drums, bass,
  guitar and the lead. An even stream that ignores rests is filler even when detectors fire on it.
- **Secondary layer**: in a bar led by vocals, the other hand may follow a rhythm-carrying stem's
  real attacks (for example the kick and snare, or a guitar riff) while the vocal onsets keep their
  notes. This must not create `lead_rhythm_diluted` false positives. Adjust that check so a note on
  a strong attack of a rhythm-carrying secondary stem counts as following the music, not as
  dilution. Keep flagging notes that sit on no strong attack.
- Encode it as a verifier change in `critique.py` (and `audio_repair.follow_lead`/`fill_findings`
  where they rebuild bars), with regression tests. Rerun across every project; this changes what is
  flagged on existing maps. Record the preference in `workspace/player-profile.json` overrides
  (`profile feedback`), because it is reusable.

### 4. A reusable raise-tier tool (agent-first)

Promote the Living a Lie scripts into a CLI command, e.g.
`project raise-tier ID --difficulty NAME --target-tier T --revision REV [--dry-run]`. It rebuilds
loud, non-quiet bars from real attacks: lead first, then secondary rhythm layers (per change 3).
Density scales with bar loudness (`intensity_bars`), and quiet bars stay light. It adds doubles on
strong accents and crossovers where flow allows. It varies placements (no `repetitive_cycle` or
`low_placement_variety`) and sets NJS per change 1. Then it runs repair-visibility, repair-swings and
repair-audio and reports `tier_fit` before and after. Existing helpers to reuse:
`audio_repair.insert_note` (flow-safe placement, but no doubles and no crossovers: `LANES` pins each
hand to its half), the double placer and the placement-variety pass in the two authoring scripts.
The tool needs structured JSON output and actionable `unresolved` reasons (for example "hand held
by an arc", "no attack").

### 5. Re-author Living a Lie ExpertPlus

After the spectrogram work lands: run `music analyze d002569949ef` so a new evidence run uses it.
Then rebuild ExpertPlus with the raise-tier tool at `target_tier: challenge` (the user asked for
harder; band is the fallback if challenge cannot be reached without filler). Keep Expert unchanged.
Then:

- Resolve or justify every critique warning. Expect no blocking errors, no `repetitive_cycle`, and
  no `note_without_audio` or `low_audio_support`.
- Keep held-vocal arcs per `references/held-notes.md`, and put the other layers on the free hand.
- Save through `project save --difficulty ExpertPlus`, then run `project export`.
- Report the closest tier, the per-section breakdown, NJS and the unresolved items.

## Acceptance

- `project add-difficulty --target-tier challenge` picks an NJS from the reference and reports it.
- `project critique --difficulty X` reports NJS against the tier and movement features in `tier_fit`.
  A dense but static map and a sparse but wide map are both placed sensibly (tests).
- The filler and secondary-layer definitions are implemented as checks with tests. They have been
  rerun on all projects, and the changes are reported per project.
- Living a Lie ExpertPlus reads closest to its target tier, or the report explains exactly which
  rule-bound sections keep it below, with numbers. Expert is untouched. Both are exported in one ZIP.
- Full test suite passes. Every code change is made in a worktree, then committed and merged into
  `main`, following `CLAUDE.md`.

## Constraints

- Follow `AGENTS.md` / `CLAUDE.md`: audio first, systematic fixes, agent-first tools, worktrees for
  code, and `sabermapper/workspace/` edited only through project commands.
- Never open ArcViewer, the studio or a browser preview. Never claim a playtest or a star rating.
- Other agents merge into `main` often: merge `main` into your branch and rerun tests before merging
  back. The corpus pattern cache is keyed to source fingerprints: after a merge that changes
  `mapio`, `corpus`, `patterns` or `movement`, rerun `corpus process --max-maps 400` before
  `corpus analyze`.

# Difficulties and star tiers

A project holds one arrangement per Beat Saber difficulty (Easy, Normal, Hard,
Expert, ExpertPlus). `arrangement.json` is the primary one; the others live in
`difficulties/NAME.json`. Every difficulty maps the same audio, so all audio-first
rules apply to each one independently.

## Commands

- `project get ID --difficulty NAME` reads one difficulty. Without `--difficulty`
  it reads the primary one. `difficulties` in the output lists every difficulty
  with its revision, note count, NPS and `target_tier`.
- `project add-difficulty ID --name ExpertPlus [--from Expert] [--njs 19] [--target-tier challenge]`
  copies an existing difficulty (default: primary) and clears its section locks.
  Then rewrite the copy at its own level. Never leave it as a relabelled clone.
- `project save`, `restore`, `check`, `critique`, `review`,
  `feedback`, `music rhythm` and `music inspect` all take `--difficulty NAME`.
  Revisions are per difficulty, so pass the revision of the one you edit.
- Saving another `difficulty.name` renames that difficulty, unless the name is already
  taken. For example, save the primary as Expert before adding a harder ExpertPlus.
- `project remove-difficulty ID --difficulty NAME --revision REV` deletes a
  non-primary difficulty. Its content stays in history.
- `project export ID` writes every difficulty into one ZIP. All difficulties must
  share `song.bpm`, `audio_offset_seconds` and `tempo_events`: `difficulty_timing_mismatch`
  warns in `project get`, and export refuses a mismatch.

## Star tiers

Tiers are player-relative ScoreSaber star bands taken from `player-profile.json`
(`corpus tiers` prints them with reference metrics):

| Tier | Stars | Use |
|---|---|---|
| `below_band` | < 6.5 | Warm-up, recovery, easier contrast |
| `band` | 6.5–8 | Default sustained intensity (PLAYER.md) |
| `challenge` | 8–9 | Whole-map target only when the user asks for a harder map |
| `stretch` | 9 to the hardest recorded pass (9.5) | Peaks; a whole-map target only on request |
| `beyond` | above every recorded pass | Study only |

Set `difficulty.target_tier` on every difficulty you author. The Beat Saber label
does not set the tier. When the user asks for a harder difficulty, move one tier up
from the one they found easy. Say in the delivery message which tier you aimed for
and why.

## Authoring to a tier

1. Read the tier's reference: `corpus tiers --tier challenge` gives the median
   and p90 4-beat window NPS, swings per second, peak swings within one second,
   burst length, crossovers and grid speed, measured on real charts of that tier.
2. Retrieve examples from that tier: `corpus retrieve --tier challenge --bpm BPM --nps NPS`.
   `workspace/corpus/tier-pattern-shortlist.json` holds a diverse, reviewed-for-shape
   shortlist per tier. Every phrase in `pattern-list.json` carries its source chart's
   `stars` and `star_tier`. A chart rating describes the whole chart, not the phrase.
   Study rhythm, movement and transitions; never copy note arrays.
3. Raise intensity only where the audio carries it. Put more of the lead's attacks
   on notes (sixteenth runs where the lead or the kick plays them). Split both hands
   across layers, for example vocal on one hand and drums on the other. Add doubles
   on accents, crossovers and wider placement. Quiet passages stay light at every tier.
   `density_exceeds_audio` still applies, and so do the flow rules.
4. Check with `project check ID --difficulty NAME --metrics`. `metrics.tier_fit` compares the
   map's 4-beat windows with each tier's reference windows and names the closest
   tier. `tier_below_target` or `tier_above_target` warns when that is not the
   target, and `tier_fit.sections` shows which sections sit below the tier's floor.
   A matching tier is a descriptive comparison with real charts, not a star rating.

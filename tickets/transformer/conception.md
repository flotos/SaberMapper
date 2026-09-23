# Transformer map generator — conception

Status: design, not started. Origin: [base-ticket.md](base-ticket.md).

## Goal

Train a sequence model that turns song audio into a Beat Saber note draft. It becomes one more agent-facing tool in SaberMapper. The agent still owns musical judgment, locks, player calibration and `project save`. The model supplies what LLM-authored maps do worst: dense, correctly timed, flowing note-level placement.

Success means that on songs the model never saw, generated drafts:

1. place notes on audible sounds at least as well as the current `audio_grounding` heuristics (measured onset F1);
2. pass the blocking validators with no manual repair (after constrained decoding);
3. are preferred by the user over the current agent-authored drafts in blind A/B at the 6.5–8★ calibration from [PLAYER.md](../../PLAYER.md).

## Non-goals (v1)

- Lighting events, walls, arcs, chains and rotation or 90/360 modes. Walls and arcs come after the note model works (see P5).
- Modded maps (Noodle Extensions, Mapping Extensions, Chroma).
- A predicted official star rating for generated maps (PLAYER.md forbids it).
- Redistributing training audio, the dataset or model weights. The model is for local use only (see Rights).
- Replacing the agent. The model drafts, and the agent reviews, edits and saves.

## Constraints from the repo contract

- **Agent-first.** Every step (data fetch, preprocessing, training, evaluation, generation) is a CLI command with JSON output, actionable errors and resumable state. The user never runs a command.
- **Audio first.** Generated notes still go through `audio_grounding`; `project save` still blocks `audio_unmapped`. The model does not bypass any check.
- **Systematic fixes.** Defects found in generated maps become validator or critique checks or decoding constraints, never per-song patches.
- **Worktrees.** All code is written in worktrees branched from `main`, tested there, then merged.
- **User data.** Datasets, features and checkpoints live under `sabermapper/workspace/` (git-ignored) or on an external volume, never in git.
- **Optional dependency.** PyTorch is a separate extra (`pip install -e .[model]`). The base app, its tests and the CLI keep working without it; model commands fail with an actionable "install the model extra" error.

## Prior art to borrow from

- **Dance Dance Convolution (2017):** splits generation into *when* (onset placement) and *what* (note content).
- **osuT5 / Mapperatorinator (osu!):** Whisper-style encoder–decoder. Log-mel spectrogram window → event tokens, with previously generated events carried as decoder context. This is the main architecture template.
- **Beat Sage, DeepSaber, InfernoSaber:** Beat Saber generators. They show the failure mode to avoid: bland output that averages all mappers' styles, with weak flow and parity.

Verify these references during P0; the summary above is from memory.

## System overview

```
BeatSaver / ranked lists ─► acquire ─► parse (mapio) ─► filter ─► tokenize ─┐
                                   └─► audio ─► log-mel + beat phase ───────┴─► shards
shards ─► train (curriculum A→B→C) ─► checkpoint ─► evaluate (held-out song families)
project audio + tempo ─► windowed generation (constrained decode, best-of-N rerank)
                     ─► arrangement JSON ─► agent review ─► project save
```

## 1. Data

### Sources

| Tier | Source | Use |
|---|---|---|
| Gold | ScoreSaber and BeatLeader ranked maps (Standard, vanilla) | Quality fine-tuning; star-band conditioning |
| Silver | BeatSaver curated maps, and maps with rating ≥ 0.80 and ≥ 50 votes | Main pretraining corpus |
| Excluded | Auto-generated maps (BeatSaver `automapper` flag), modded maps, rating < 0.6, non-Standard characteristics | — |

- **Target size:** 15–40k difficulties from 8–15k unique songs. Record the actual count in the data manifest.
- **Reuse existing code:** `corpus.py` already has BeatSaver discovery, safe ZIP extraction and hashing, and `CorpusStore`. Extend it to bulk acquisition rather than writing a new downloader. Keep the existing 110-archive corpus as a smoke-test set.
- **Etiquette:** throttle requests, identify with a User-Agent, cache by map hash, and resume after interruption.

### Filtering and normalization

- Parse with `mapio.parse_map`, which supports v2 and v3. Add v4 support if the ranked set needs it.
- Resolve the beat grid from `bpmEvents` (v3) or `_BPMChanges` (v2 customData) plus the Info file BPM. Drop maps with unresolvable tempo.
- **Timing audit:** compute an onset-alignment score between human notes and audio onsets, and drop maps whose best global offset is > 30 ms or whose alignment is poor. Bad offsets would teach the model wrong timing, and this audit is the most important data-quality gate.
- Deduplicate songs across mappers with an audio fingerprint (reuse `_archive_audio_hash` where possible) to build **song families**.
- **Split by song family, never by map,** using the existing `splits` command: 90% train, 5% validation, 5% test. The test families are frozen before any training.

### Rights

- Audio comes from community map archives of commercial songs.
- **Allowed:** local, personal, non-commercial training and use.
- **Not allowed:** redistributing the audio, spectrograms, dataset or weights.
- The manifest records the BeatSaver map hash, mapper, URL and license status of every item, following the provenance conventions of the existing corpus.

## 2. Representation

### Audio features

- Mono audio at 22 050 Hz → 80-bin log-mel, hop 10 ms (100 frames/s), stored as float16 (about 2.9 MB per 3-minute song).
- Each frame also gets **beat-phase features** from the grid: sin/cos of the position within the beat and within the bar, and a downbeat flag.
  - Training uses the map's own grid.
  - Inference uses the project's tempo analysis (`audio.analyze_audio` / project timing).
- These features let the decoder emit grid-relative time without learning tempo from scratch.

### Event tokens

Time is **beat-relative**, not milliseconds, because human maps snap to a grid.

- **Resolution:** 48 ticks per beat, which covers 1/16 and 1/12 snaps. Off-grid source notes are snapped to the nearest tick, and the snap error is logged. Maps with a large share of off-grid notes are dropped.
- **Window:** 16 beats (4 bars) in stages B–C, 4 beats in stage A. The window is in beats, not seconds, so it adapts to tempo.

Vocabulary (about 1.3k tokens):

| Token family | Count | Meaning |
|---|---|---|
| `POS_t` | 768 | Absolute tick within a 16-beat window; marks the time of the following objects |
| `NOTE_c_x_y_d` | 2×4×3×9 = 216 | Color, column, row, cut direction (including dot) |
| `ANG_k` | 5 | Optional angle-offset bucket (−45, −15, 0, +15, +45) |
| `BOMB_x_y` | 12 | Bomb |
| `DIFF_*`, `STAR_*`, `NJS_*`, `ERA_*` | ~40 | Conditioning prefix: difficulty label; star bucket in 0.5★ steps with `STAR_UNK` for unranked; NJS bucket; map year, because mapping style changed across eras |
| `CTX_BEGIN`, `CTX_END`, `BOS`, `EOS`, `PAD`, `SEP` | 6 | Structure |

- **Objects:** within one `POS`, objects are sorted canonically (left before right, then row, then column), so the target sequence is deterministic.
- **Context segment:** the decoder input is `[conditioning] CTX_BEGIN <previous window's last 8 beats of events, with negative POS> CTX_END BOS <target events> EOS`. Loss is computed only on target tokens.
- **Round trip:** tokenize → detokenize must reproduce the parsed map exactly, up to tick snapping and dropped v1 non-goals. This is a unit-tested invariant.
- **Output format:** detokenization produces a SaberMapper arrangement (the same schema `project save` accepts). Notes carry provenance `model:<checkpoint-sha>`.

## 3. Model

- **Architecture:** encoder–decoder transformer.
  - **Encoder:** 2 strided conv layers (stride 2, so 50 frames/s) followed by N transformer layers over mel + beat-phase features.
  - **Decoder:** causal transformer with cross-attention.
  - **Positions:** rotary or learned positional embeddings.
- **Sizes:**

  | Stage | d_model | Layers | Heads | Parameters |
  |---|---|---|---|---|
  | P1 prototype | 256 | 4 + 4 | 4 | ~10–15M |
  | P2 main | 512 | 8 + 8 | 8 | ~80–100M |

  Scale up only if validation loss keeps improving and data allows.
- **Loss:** cross-entropy on target tokens. Onset tokens (`POS_*`) may get extra weight early in training.
- **Framework:** PyTorch with bf16 mixed precision and a single GPU. No distributed training in v1.

## 4. Training curriculum

This follows the base ticket's short → long → full-song idea, adapted so full songs never need full-song attention:

| Stage | Window | Context | Purpose |
|---|---|---|---|
| **A** | 4 beats (≈1.5–3 s) | none | Learn local timing from audio and note grammar; converges fast |
| **B** | 16 beats | previous 8 beats of **ground-truth** events | Learn flow, parity and pattern continuity across windows |
| **C** | Full song, window-by-window rollout | previous 8 beats of the **model's own** generated events (scheduled sampling ramping 0 → 50%) | Fix exposure bias, so errors don't compound over a 3-minute song |
| **D** | 16 beats + context | ground truth | Fine-tune on the gold tier, conditioned on star bucket; optional player-band fine-tune at 6.5–8★ |

- **Song-level consistency:** for a chorus that should reuse its pattern, add an optional retrieval context in stage C+. The encoder also receives the mel of the most similar earlier window, found with the recurrence analysis `analyze_audio` already produces, and the decoder receives that window's generated events. This is v1.1; skip it if the time budget is short.
- **Data augmentation:** mirror (swap colors and flip columns and directions); audio gain and EQ; pitch-preserving time-stretch of ±5% with a matching grid stretch.

## 5. Inference

1. **Inputs:** project audio, a tempo/beat grid (project timing), conditioning (difficulty label, target star bucket, NJS from the player profile) and optional section ranges. When sections are locked, regenerate only unlocked ranges and use the locked notes as context.
2. **Windowed decoding:** step 16-beat windows with 8 beats of generated context. Stitch at window boundaries, and generate a boundary overlap twice to keep the better candidate.
3. **Constrained decoding (hard rules):** an incremental validator state masks logits before sampling.
   - **Grammar:** `POS` values increase; each object token follows a `POS`.
   - **No overlapping cells** at the same tick (`overlapping_cell`).
   - **Same-tick direction conflicts** are removed (`simultaneous_direction_conflict`).
   - **Per-hand parity:** directions that `movement.flow_parity_break` or `fast_direction_break` would reject, given the gap since that hand's last swing, are masked.

   This needs a small incremental API that exposes the existing movement rules per step without duplicating them. Refactor `movement.py` so the batch checks and the incremental mask share one implementation. A regression test asserts they agree on every corpus map.
4. **Best-of-N reranking (soft rules):**
   - Sample N candidates per window (N = 4–8, temperature ~0.9, nucleus 0.95).
   - Score each candidate with `audio_grounding` support, `critique` metrics (repetition, density contour vs section energy, placement entropy) and the model log-likelihood, and keep the best.
   - The weights live in one config file with a documented rationale.
5. **Output:** a candidate arrangement JSON plus a JSON report (checkpoint sha, seeds, per-window scores, masked-token counts and rejected candidates). The agent then reviews it and saves through `project save`.

## 6. Preference optimization (after P3)

- **Goal:** optimize directly for maps the user prefers.
- **Data:** pairs of generated drafts for the same window, ranked by
  1. the user's actual feedback (`labels` / `learning.py`, origin `human`), and
  2. critique + audio-grounding scores (origin `synthetic`).
- **Method:** start with **DPO** against the stage-D model as the reference. Try GRPO with reward = critique + grounding only if DPO plateaus. Keep a KL/reference constraint.
- **Reward-hacking guard:** after every run, report distribution metrics against held-out human maps (placement histogram, direction transitions, NPS contour). Reject a run that improves the reward but drifts from the human distributions; for example, entropy gamed by random placement.
- **Never** fabricate human labels, and never count `assistant_proposed` or `synthetic` labels as human preference.

## 7. Evaluation

All numbers are measured on the frozen test song families:

| Metric | Definition | Gate |
|---|---|---|
| Onset F1 | Predicted note times vs human note times, ±1 tick at 1/16 snap and ±25 ms | P1: beats the heuristic onset-picking baseline by a clear margin |
| Note accuracy | Given the true onsets (teacher-forced `POS`), accuracy of color, column, row and direction | Report only |
| Validator pass | Share of generated windows with zero blocking findings, **before** masking | Report; masking makes the after-masking rate 100% by construction |
| Parity breaks /100 notes | Measured by `movement.py` | ≤ the median of human test maps in the same star band |
| Audio support | `note_without_audio`, `low_audio_support` rates | ≤ human test maps |
| Distribution distance | Jensen–Shannon distance to human maps in the same star band: placement, direction bigrams, NPS | Report and track over time |
| Blind preference | The user compares model drafts with agent drafts on 3–5 songs | Final go/no-go; human feedback only |

The evaluation harness is a CLI command (`model evaluate`) that writes a JSON report. Checkpoints are compared from those reports, never from single anecdotes.

## 8. Code layout and CLI

```
sabermapper/sabermapper/model/
  __init__.py        # imports torch lazily; actionable error if the extra is missing
  dataset.py         # acquisition manifest, filtering, timing audit, song-family split
  tokens.py          # vocabulary, tokenize/detokenize, round trip (no torch)
  features.py        # log-mel + beat phase (numpy; no torch)
  shards.py          # writes and reads training shards
  net.py             # encoder–decoder
  train.py           # curriculum stages, checkpoints, resume
  decode.py          # windowed generation, constraint masks, reranking
  evaluate.py        # metrics above
  cli.py             # `sabermapper model ...`
sabermapper/tests/test_model_*.py   # tokens, features, masks, a tiny overfit smoke test (skipped without torch)
```

Commands, all with JSON output, `--workspace` and resumable state:

- `model data acquire --tier silver --max N`
- `model data build` (parse, filter, audit, split, shard)
- `model data report`
- `model train --stage A|B|C|D --config FILE [--resume]`
- `model evaluate --checkpoint ID`
- `model generate PROJECT_ID [--sections ...] [--star 7.5] [--candidates 8] --out DRAFT.json`
- `project generate` is a later convenience alias that writes a draft only and never saves automatically.

Storage:

| Path (under `sabermapper/workspace/`) | Contents | Approximate size |
|---|---|---|
| `models/data/` | Shards | ~40–80 GB for 15k songs, float16 mel + tokens |
| `models/checkpoints/` | Checkpoints | — |
| `models/runs/` | Evaluation reports | — |

Raw archives can be deleted once shards are built; the manifest keeps the hashes needed to re-download.

## 9. Compute

- **Local:** P0–P1 and every unit test must run on the local machine (CPU acceptable for tests; a local GPU, if present, for P1).
- **Stages B–D:** need a ≥ 24 GB GPU. Estimate: an ~100M-parameter model on ~30k difficulties, 1–3 days on one H100/A100.
- **Rented compute:** likely RunPod (about $2–3/h for an H100; confirm live pricing before creating anything), so roughly $150–600 for a first full training run, plus data preparation on a network volume.
- **Approval:** billable resources are created only after the user approves a concrete price and plan.
- Checkpoints are copied back to `workspace/models/checkpoints/` and inference runs locally.

## 10. Phases and go/no-go

| Phase | Deliverable | Acceptance |
|---|---|---|
| **P0 Data** | Acquisition + parse + timing audit + song-family split + shards; data report | ≥ 5k clean difficulties from the silver tier; ≥ 95% of kept maps pass the timing audit; token round-trip tests pass; test split frozen |
| **P1 Onsets** | Stage A model, trained locally or on a small GPU, with the onset-F1 harness | Onset F1 clearly beats the heuristic baseline on test families. **If it does not, stop and reassess** before spending on B–D |
| **P2 Full tokens** | Stages B + C at full data scale | Before masking: validator pass rate and parity breaks within human range; distribution distances reported |
| **P3 Integration** | Constrained decoding, reranking, `model generate`, draft → arrangement | Generated drafts pass `project save` checks on all workspace projects without hand edits; agent workflow documented in the skills |
| **P4 Preference** | Stage D gold/star fine-tune, then DPO | Blind user preference over agent-authored drafts; no distribution drift |
| **P5 Extensions** | Walls, arcs, chains, retrieval context for repeated sections | Each with its own ticket |

## 11. Subagent work packages

The orchestrating agent splits the work into packages. Each runs in its own worktree branch, and the orchestrator merges them one at a time with the full test suite green.

| WP | Content | Depends on | Can run in parallel with |
|---|---|---|---|
| WP1 | Data acquisition (extend `corpus.py`), manifest, rights metadata, throttling/resume | — | WP2, WP3 |
| WP2 | `tokens.py`: vocabulary, tokenize/detokenize, round trip, conversion to arrangements | this ticket's token spec | WP1, WP3 |
| WP3 | `features.py`: log-mel + beat phase, grid resolution from v2/v3 BPM events | — | WP1, WP2 |
| WP4 | Filtering, timing audit, song-family split (`splits`), shard writer; `model data build/report` | WP1–3 | WP5 |
| WP5 | `net.py` + `train.py`, stage A, tiny-overfit smoke test | WP2, WP3 | WP4 |
| WP6 | Incremental movement-rule API refactor + constraint masks with agreement test | WP2 | WP4, WP5 |
| WP7 | `decode.py`, reranking, `model generate`, arrangement output | WP5, WP6 | WP8 |
| WP8 | `evaluate.py` metrics + baseline onset heuristic | WP2, WP3 | WP7 |
| WP9 | Skill and doc updates (`sabermapper-map` gets the draft-from-model step), user guide | WP7 | — |

Each work package ends with:

- tests passing inside its worktree;
- a short report listing the files changed, the commands run and any open issues;
- no edits to `workspace/` project arrangements. Only the orchestrator saves projects, and only in P3.

## 12. Risks

| Risk | Mitigation |
|---|---|
| Community map quality | Tiering, rating and vote thresholds, star conditioning, gold fine-tune |
| Bad offsets / variable BPM | Timing audit gate; drop maps whose grid can't be resolved |
| Bland "average mapper" output | Era and star conditioning, best-of-N reranking, DPO on the user's preference |
| Exposure bias over long songs | Stage C self-conditioning rollout |
| Reward hacking in P4 | Reference constraint plus distribution-drift checks |
| Inference tempo errors on new songs | Use project timing (already verified by the agent); report when the grid confidence is low |
| Disk and compute cost | Delete raw archives after sharding; P1 gate before any rented compute |
| Rights | Local, personal use only; no redistribution |

## 13. Open decisions for the user

1. **Compute:** local GPU only, or approve a RunPod budget for P2+? What is the cap?
2. **Dataset scale** for P0: start at ~5k difficulties or go straight to ~30k?
3. **Disk location** for shards if `sabermapper/workspace/` doesn't have ~80 GB free.
4. **Tracking:** should `tickets/` be tracked in git?

# SaberMapper planning backlog

Created 2026-09-22. **Implementation expanded across all 31 tickets at the user's explicit request.** That instruction supersedes the original milestone expansion gates below. The local studio, tools and evidence records are implemented; physical playtests, subjective calibration and human labels remain explicit external acceptance work. See [software coverage](../docs/ticket-coverage.json) and [the user guide](../docs/user-guide.md). Historical stage ordering is retained as research context, not an instruction to stop implementation.

Read the [review decisions](research/review-response.md) for what changed and which review claims required qualification.

## Product agreement and working defaults

Build varied, musically expressive technical maps using local tools and an independently invoked assistant. The long-term research program still includes mapping guides, large-scale pattern discovery, repetition/variation analysis, and learning from feedback. First test whether the assistant can compose a map the user wants to replay.

- Confirmed platform: latest SteamVR Beat Saber installation, currently being downloaded. Record the exact build and mods when available. Target that installation first; rollback is only a verified fallback if needed and supported.
- Working implementation default: Python tools plus no-build static HTML/JavaScript for a 2D review timeline; ArcViewer remains a separate playback tool.
- Proposed first export: one Standard two-saber difficulty, v3, OGG Vorbis audio, and minimal visible lighting, subject to a real import/playtest on the installed game.
- Primary assistant for this implementation: user-invoked Codex. Test one host first, with one shared SKILL.md directory. Secondary-host compatibility is a later increment.
- The application makes no LLM calls and never launches an assistant for the user. Local DSP and non-generative beat/ranking models are separate proposed tools; learned embeddings are undecided and unnecessary initially.
- Use ranked status, curation, and mapper catalogs as sampling evidence, not automatic quality labels. Technical and ranked are compatible; useful musical repetition is different from monotonous reuse.

## Milestone 0: test the premise first

Start with [SM-029](tickets/SM-029-first-playable-experiment.md). Its disposable slice needs one checked steady-tempo song, 15-20 selected phrases, a plain-text arrangement, a prototype mapping skill, minimal compilation/checking, ArcViewer playback, and an in-game playtest. Request one revision and judge whether the result is worth replaying.

The proposed timebox is the first 1-2 working weeks, conditional on actual capacity; it is not a calendar commitment. The experiment produces a **go / revise hypothesis / stop** decision. Larger infrastructure and collection wait for that evidence. The spike owns the disposable integration; it does not require the production tickets to be complete.

The primary risk is the assistant's musical composition from structured evidence. A spike with supplied timing does not prove automatic audio analysis. Keep the target human note arrangement out of assistant inputs, and document single-rater limitations.

## Revised execution order

| Stage | Tickets | Exit evidence |
| --- | --- | --- |
| 0. One playable experiment | [SM-029](tickets/SM-029-first-playable-experiment.md); first slices of [SM-001](tickets/SM-001-architecture-and-contracts.md), [SM-017](tickets/SM-017-arrangement-authoring-format.md), [SM-022](tickets/SM-022-mapping-skill.md), [SM-025](tickets/SM-025-lighting-export-and-compatibility.md) | Assistant-authored track, one revision, real playtest, explicit decision |
| 1. Productize the successful slice | [SM-005](tickets/SM-005-local-cli-foundation.md), [SM-007](tickets/SM-007-map-parser-and-ir.md), [SM-014](tickets/SM-014-audio-ingest-and-metadata.md), [SM-015](tickets/SM-015-beat-grid-and-tempo.md), [SM-017](tickets/SM-017-arrangement-authoring-format.md), [SM-018](tickets/SM-018-deterministic-map-compiler.md), [SM-019](tickets/SM-019-contextual-validation.md), [SM-020](tickets/SM-020-local-map-visualizer.md), [SM-021](tickets/SM-021-visual-feedback-and-revisions.md), [SM-022](tickets/SM-022-mapping-skill.md), [SM-025](tickets/SM-025-lighting-export-and-compatibility.md), [SM-030](tickets/SM-030-movement-and-strain-model.md) | Reusable local tools, shared movement inference, 2D feedback, reliable export |
| 2. Budget and curate the research program | [SM-002](tickets/SM-002-player-calibration.md), [SM-003](tickets/SM-003-mapping-knowledge-research.md), [SM-004](tickets/SM-004-corpus-design.md), [SM-028](tickets/SM-028-benchmark-and-data-splits.md), [SM-031](tickets/SM-031-external-reference-audit.md) | Taste anchors, sources, capacity budget, curated manifest, frozen split rules, external audit |
| 3. Research patterns at increasing scale | [SM-006](tickets/SM-006-beatsaver-ingestion.md), [SM-008](tickets/SM-008-large-corpus-processing.md), [SM-009](tickets/SM-009-pattern-extraction.md), [SM-010](tickets/SM-010-motif-grouping-and-repetition.md), [SM-011](tickets/SM-011-quality-and-preference-labels.md), [SM-013](tickets/SM-013-contextual-pattern-retrieval.md), [SM-016](tickets/SM-016-musical-structure-and-recurrence.md) | Audited corpus, motif atlas, contextual retrieval, musical reports and budgeted labels |
| 4. Prove value and package | [SM-024](tickets/SM-024-map-review-skill.md), [SM-026](tickets/SM-026-end-to-end-quality-evaluation.md), [SM-027](tickets/SM-027-local-release-and-onboarding.md) | Qualitative comparisons, regression checks, documented local workflow |
| Optional increments | [SM-012](tickets/SM-012-learned-quality-and-preference-ranking.md), [SM-023](tickets/SM-023-corpus-research-skill.md); expanded skills/viewer/audio scopes | Evidence justifies learned ranking, research skill, second host, variable tempo, or more advanced tooling |

Rows are outcome groups, not a waterfall. Small calibration, source reading, and movement surveys can support the spike immediately. Each ticket names its minimal v0 slice and later expansion separately. Dependencies identify required artifacts/interfaces; a ticket's entire expanded wishlist need not finish first. SM-029 owns its disposable prototypes explicitly, so production dependencies do not block the experiment.

[SM-009](tickets/SM-009-pattern-extraction.md) no longer waits for the whole corpus/research protocol. [SM-020](tickets/SM-020-local-map-visualizer.md) no longer waits for diagnostics. [SM-022](tickets/SM-022-mapping-skill.md) starts with the arrangement format. [SM-026](tickets/SM-026-end-to-end-quality-evaluation.md), [SM-027](tickets/SM-027-local-release-and-onboarding.md) do not require the learned ranker, broad corpus completion, or every auxiliary skill.

## Human review budget

The user has not yet supplied weekly capacity. These are proposed caps to measure, not commitments or assumptions of free labor.

| Work | First allocation | Expansion rule |
| --- | --- | --- |
| Spike: verify timing, inspect selected phrases, playtest and revise | 2-4 user hours total | Stop and reassess if the chosen track cannot fit; shorten/reselect the experiment rather than hide extra work |
| Pairwise quality/preference labels | 20-40 judgments, 1-2 hours | Log minutes per judgment and uncertainty; 200 labels are not a requirement or assumed adequate training data |
| Timing references | Three tracks, sampled start/middle/end and bar anchors, 1-2 hours | Reuse exact-audio mapper timing as provisional labels; annotate densely only where a failure demands it |
| Qualitative map comparisons | 3-5 songs, 1-2 hours initially | Record that one rater and familiarity limit conclusions; do not claim population statistics |
| Guide synthesis and pattern checks | Five targeted notes and the same pilot phrase pool | Reuse inspected development examples across tasks; separately identify every held-out sample |

These allocations are estimates and may overlap; track actual time once per activity. Do not independently demand 20 guide entries, 30 phrases, 200 pairs, and 20 fully annotated songs from one person. [SM-012](tickets/SM-012-learned-quality-and-preference-ranking.md) is explicitly a stretch experiment with a no-go outcome allowed.

## Corpus and evaluation policy

Positive reference pools lead: spot-checked technical maps from ScoreSaber/BeatLeader ranked pools, BeastSaber curation, and named mappers, with style/era/difficulty diversity. Keep a small random/negative/contrast cohort. Rank/curation are weak priors rather than zero-error labels.

Use a 100-map pilot to measure cost and coverage; expand toward 1,000 or more when useful. The user's larger research pass remains planned, but 10,000 maps is neither a default download quota nor a first-release gate. Decide archive/audio retention per map before collection. Retain exact audio for timing/representation exemplars; only discard transient files after feature extraction succeeds under the configured policy.

Freeze **split rules** before tuning, apply them as families arrive, and freeze concrete manifests for evaluated releases. Raw title/artist hashing alone is insufficient: resolve versions, aliases, duplicate audio, and family merges. Spike and reviewed pilot material remain development data.

## Sizes and ticket index

Sizes describe rough implementation/research complexity, not promised elapsed time: S = narrow task; M = several connected pieces; L = substantial work or algorithm uncertainty; XL = staged program that must be capped and measured. Each ticket also identifies a smaller v0 slice. User labeling/playtest hours are budgeted separately above.

| ID | Ticket | Size / v0 | Dependencies |
| --- | --- | --- | --- |
| [SM-001](tickets/SM-001-architecture-and-contracts.md) | Define architecture, boundaries, and versioned contracts | S / S | None |
| [SM-002](tickets/SM-002-player-calibration.md) | Calibrate player difficulty and technical preferences | S / S | None |
| [SM-003](tickets/SM-003-mapping-knowledge-research.md) | Research mapping guides and build an evidence-based knowledge base | L / S–M | None |
| [SM-004](tickets/SM-004-corpus-design.md) | Design a diverse corpus and exact-version reference manifest | M / S–M | SM-002, SM-003 |
| [SM-005](tickets/SM-005-local-cli-foundation.md) | Grow a minimal local CLI from the playable slice | M / S | SM-001 |
| [SM-006](tickets/SM-006-beatsaver-ingestion.md) | Implement bounded BeatSaver discovery and downloads | M / S–M | SM-004, SM-005 |
| [SM-007](tickets/SM-007-map-parser-and-ir.md) | Parse map versions into a loss-aware internal representation | L / S–M | SM-001, SM-005 |
| [SM-008](tickets/SM-008-large-corpus-processing.md) | Run and audit the large corpus research pipeline | XL / S–M | SM-006, SM-007, SM-028, SM-029 |
| [SM-009](tickets/SM-009-pattern-extraction.md) | Extract contextual patterns and movement features | L / S–M | SM-007, SM-030 |
| [SM-010](tickets/SM-010-motif-grouping-and-repetition.md) | Group motif families and measure repetition versus variation | L / S–M | SM-009 |
| [SM-011](tickets/SM-011-quality-and-preference-labels.md) | Create mapping-quality labels and personal preference examples | L / S–M | SM-002, SM-003, SM-009, SM-028 |
| [SM-012](tickets/SM-012-learned-quality-and-preference-ranking.md) | Optional stretch: test a local quality and preference ranker | L / S–M | SM-010, SM-011, SM-028 |
| [SM-013](tickets/SM-013-contextual-pattern-retrieval.md) | Retrieve compatible, diverse patterns with evidence | M / S–M | SM-002, SM-009 |
| [SM-014](tickets/SM-014-audio-ingest-and-metadata.md) | Import audio and establish reliable metadata provenance | M / S–M | SM-005, SM-001 |
| [SM-015](tickets/SM-015-beat-grid-and-tempo.md) | Build a correctable beat, downbeat, and tempo pipeline | L / S–M | SM-014 |
| [SM-016](tickets/SM-016-musical-structure-and-recurrence.md) | Analyze onsets, musical sections, energy, and recurring phrases | L / S–M | SM-015 |
| [SM-017](tickets/SM-017-arrangement-authoring-format.md) | Co-design the plain-text arrangement with the mapping skill | M / S–M | SM-001 |
| [SM-018](tickets/SM-018-deterministic-map-compiler.md) | Compile arrangements into reproducible map objects | M / S–M | SM-017, SM-007 |
| [SM-019](tickets/SM-019-contextual-validation.md) | Validate correctness and diagnose mapping problems without flattening tech | L / S–M | SM-007, SM-030 |
| [SM-020](tickets/SM-020-local-map-visualizer.md) | Use ArcViewer playback and build a 2D review timeline | M / S–M | SM-001, SM-007, SM-014 |
| [SM-021](tickets/SM-021-visual-feedback-and-revisions.md) | Connect visual feedback to scoped assistant revisions | S / S | SM-017, SM-018, SM-020 |
| [SM-022](tickets/SM-022-mapping-skill.md) | Create the mapping skill for Codex and Claude Code | M / S | SM-017 |
| [SM-023](tickets/SM-023-corpus-research-skill.md) | Create the corpus and mapping-research skill | M / S–M | SM-003, SM-006, SM-009 |
| [SM-024](tickets/SM-024-map-review-skill.md) | Create a critique and revision skill for finished drafts | M / S–M | SM-019, SM-020, SM-021 |
| [SM-025](tickets/SM-025-lighting-export-and-compatibility.md) | Add basic lighting and reliable Beat Saber export | M / S–M | SM-001, SM-014, SM-018, SM-019 |
| [SM-026](tickets/SM-026-end-to-end-quality-evaluation.md) | Evaluate generated maps and close the playtest feedback loop | M / S–M | SM-021, SM-022, SM-025, SM-028 |
| [SM-027](tickets/SM-027-local-release-and-onboarding.md) | Package the local toolkit and document the complete workflow | M / S–M | SM-022, SM-025, SM-026 |
| [SM-028](tickets/SM-028-benchmark-and-data-splits.md) | Freeze family-split rules and a budgeted evaluation protocol | M / S | SM-001, SM-002 |
| [SM-029](tickets/SM-029-first-playable-experiment.md) | Milestone 0: test assistant-authored mapping on one track | M / M | None |
| [SM-030](tickets/SM-030-movement-and-strain-model.md) | Own shared swing inference, transitions, and difficulty proxies | L / M | SM-007 |
| [SM-031](tickets/SM-031-external-reference-audit.md) | Audit external BeatForge code as a read-only reference and baseline candidate | S / S | None |

Unchecked checkboxes are outstanding completion evidence; implemented prototype slices do not imply full-ticket completion. References are starting points to verify during implementation, and quantitative targets remain proposals until the corresponding capacity/benchmark decision. This shared rule replaces the repeated disclaimer previously appended to every ticket.

## Research evidence

- [Player profile analysis](research/player-profile.md): ScoreSaber filters and candidate purposes.
- [ScoreSaber snapshot](research/scoresaber-snapshot.json): 383 saved score entries.
- [BeatLeader snapshot](research/beatleader-snapshot.json): 48 returned score records, component ratings where available, replay links, and source/count caveats.
- [Reference candidates](research/reference-candidates.json): 12 exact-version metadata matches; the two Noodle Hard maps are excluded from the core gameplay cohort.
- [Source catalog](research/sources.md): primary references and questions.
- [Review decisions](research/review-response.md): changes, verified corrections, and remaining choices.

The nine later unmodified ranked ScoreSaber results average 7.43 stars and 80.50% accuracy, but eight are clustered in late January 2025. BeatLeader adds useful evidence, not newer activity: its latest returned result is also 2025-03-20. Named references and measured movement features should drive calibration, with 6.5-8 ScoreSaber stars only an initial search band.

## Remaining choices

The primary host/preview preference and human/hardware budgets have been asked and remain pending. Exact installed game build and mods are also pending. During calibration, collect loved/disliked sections, target music, why existing maps do not meet the need, and whether one personal difficulty is the long-term product. Variable tempo, stems, learned embeddings, modcharts, rich lightshows, public publishing, and a custom 3D renderer are deferred unless a concrete need changes their priority.

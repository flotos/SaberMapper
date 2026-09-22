# Review response and revised decisions

Revised 2026-09-22. This records planning decisions, not completed implementation. The user confirms the latest SteamVR game is being installed, with rollback only if necessary and supported.

## Accepted changes

| Concern | Revision |
| --- | --- |
| Core hypothesis tested too late | SM-029: Milestone 0, one checked track, 15-20 phrases, prototype skill/arrangement, minimal tools, ArcViewer, one revision, playtest, and go/revise/stop |
| Unbudgeted human effort | Small time-boxed batches and shared review-time budget; no mandatory 200 labels or 20 fully annotated songs |
| Learned ranker too central | SM-012 is an optional stretch experiment, removed from evaluation/release prerequisites |
| BeatLeader missing | Added official sources, live profile cross-check, snapshot, and component-rating considerations |
| Corpus sampling too broad | Curated technical positives lead; keep contrast/diversity cohorts and choose per-map audio retention before downloading |
| Exploration blocked by full research | Pilot extraction/retrieval can start early; viewing does not require diagnostics; skill and arrangement co-evolve |
| Viewer too large | Separate ArcViewer playback plus a static 2D review timeline; custom 3D deferred |
| No movement-model owner | SM-030 owns shared swing/parity/transition inference and difficulty/strain proxies |
| External code unused | SM-031 plans a read-only audit and a controlled-baseline recommendation |
| Overbuilt arrangement/feedback infrastructure | Direct YAML/JSON edits and one feedback JSON file; defer queues and generalized infrastructure |
| Audio and compatibility underspecified | Current SteamVR first; test v3 export, OGG Vorbis, timeline transforms, and explicit NJS/jump choices |
| Ticket size/minimum slice missing | All 31 tickets now have sizes, v0 slices, and expansion gates; repeated disclaimers moved to the backlog |

## Qualifications and verified corrections

**Cheap reference labels are useful, but not guaranteed truth.** Exact-audio mapper timing and spot-checked ranked tech reduce effort. They still need alignment/version checks, and rank is not a zero-parity-error certificate. Preserve intentional exceptions and uncertain cases. [Timing preparation](https://bsmg.wiki/mapping/basic-audio.html), [technical mapping](https://bsmg.wiki/mapping/intermediate-mapping.html).

**The median is exactly 7.075.** Its two middle observations are 7.02 and 7.13. The report now shows the exact value; replacing 7.08 with 7.07 would merely choose another rounding result.

**BeatLeader adds detail, not newer activity for this player.** The latest result is also 2025-03-20. Its score list returns 48 records, while the profile aggregate says 27; contexts/count semantics remain explicit rather than combined. Rating components and replay links are available where present; no replay download occurred. [Saved snapshot](beatleader-snapshot.json), [API](https://api.beatleader.xyz/swagger/index.html).

**Checked licenses differ from the review's assumption.** ArcViewer's default branch is GPL-3.0; ChroMapper's is GPL-2.0. JoshaParity and its refactor report MIT. These are source observations, not a blanket reuse decision. [ArcViewer license](https://github.com/AllPoland/ArcViewer/blob/main/LICENSE), [ChroMapper license](https://github.com/Caeden117/ChroMapper/blob/master/LICENSE), [JoshaParity](https://github.com/Joshabi/JoshaParity).

**README-upstream.md belongs to a dependency.** It describes wasm-media-encoders. Its MIT notice does not establish the license for all BeatForge code; SM-031 must separate first-party and vendored provenance.

**Split rules need more than title hashing.** Freeze assignment rules, resolve aliases/versions/audio duplicates and family merges, and then freeze actual manifests for evaluated releases. Retire contaminated evaluations instead of silently moving their examples.

**Constant tempo is a scope choice.** It is not a verified property of all desired music. Start there and defer stems/full variable tempo, while identifying unsupported input. Beat timestamps alone do not establish a downbeat/bar anchor.

**One rater yields qualitative feedback.** Order balancing can reduce some bias but cannot turn a few personal playtests into population statistics. Record user time, enjoyment, discomfort, and replay preference honestly.

## Open choices and implementation boundary

Primary host/preview preference and weekly review time/hardware have been asked and remain pending. Exact installed build and mods still need checking. Working defaults remain proposals where no answer was given.

During SM-002 collect loved/disliked sections, intended music, unmet needs in existing maps, and the long-term audience. The eleven review questions do not all need answers before the planning documents can be completed.

All skills, scripts, downloads, audits, models, and viewers remain future ticketed work. This revision edits documentation and reads public metadata only.


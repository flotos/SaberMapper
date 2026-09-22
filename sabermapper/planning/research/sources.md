# Research sources and follow-up questions

Checked 2026-09-22. These are primary community documentation, official product/library documentation, or project-author repositories. Links are research starting points; proposed architecture and numeric acceptance targets are SaberMapper design judgments, not claims that the sources endorse them.

## Sources

- **SS: [ScoreSaber API](https://scoresaber.com/api/docs)** — Check current pagination, response fields, score/modifier semantics, and available rate-limit guidance. The documentation shell opened; live field behavior was verified through API responses.
- **PROFILE: [Player profile](https://scoresaber.com/u/76561198016617991)** — Player evidence only. The web reader failed; public API access succeeded. Do not infer preferences from play history alone.
- **BS: [BeatSaver API](https://api.beatsaver.com/docs/)** — Check discovery/filtering, hash lookup, versions, difficulty identity, tags, and download rules. Swagger is dynamic; exact-hash metadata lookup was exercised successfully.
- **DISCOVERY: [BeastSaber discovery and curation](https://bsaber.com/getting-started/custom-songs)** — Understand curation and where map discovery leads; use direct BeatSaver data access for ingestion.
- **BASIC: [BSMG basic mapping](https://bsmg.wiki/mapping/basic-mapping.html)** — Review fundamentals and worked examples. Convert applicable advice into contextual heuristics with known exceptions.
- **INTER: [BSMG intermediate mapping](https://bsmg.wiki/mapping/intermediate-mapping.html)** — Study gameplay versus musical representation, technical movement, deliberate exceptions, and player taste. Follow links to original authors and examples during the full research ticket.
- **GLOSS: [BSMG mapping glossary](https://bsmg.wiki/mapping/glossary.html)** — Align vocabulary for pattern families and annotations; preserve ambiguity where community terms differ.
- **FORMAT: [BSMG map format](https://bsmg.wiki/mapping/map-format.html)** — Verify supported file schemas, timing, object semantics, and compatibility before implementing import/export. Pin the version target.
- **AUDIO: [BSMG audio preparation](https://bsmg.wiki/mapping/basic-audio.html)** — Review audio preparation and offset checks before selecting pipeline conventions.
- **TEMPO: [BSMG variable-tempo audio](https://bsmg.wiki/mapping/advanced-audio.html#variable-bpm)** — Investigate variable-tempo handling and correction workflows rather than relying on one global BPM.
- **LIGHT: [BSMG basic lighting](https://bsmg.wiki/mapping/basic-lighting.html)** — Define the smallest useful lighting scope and how events follow musical decisions.
- **RANK: [ScoreSaber ranking criteria](https://wiki.scoresaber.com/ranking/criteria)** — Use ranking requirements as one reference class, not as the definition of enjoyable technical mapping. Follow the current detailed criteria links.
- **ARC: [ArcViewer source and capabilities](https://github.com/AllPoland/ArcViewer)** — Assess viewer capabilities and implementation tradeoffs. Inspect actual license and source compatibility before choosing reuse; do not assume easy embedding.
- **CHRO: [ChroMapper source and editor](https://github.com/Caeden117/ChroMapper)** — Cross-check editor behavior, format handling, and interoperability. Review current license before any code reuse.
- **PROBE: [FFprobe documentation](https://ffmpeg.org/ffprobe.html)** — Evaluate container/tag probing and timestamp/encoding behavior for local ingest.
- **BEAT: [Beat This! implementation and models](https://github.com/CPJKU/beat_this)** — Evaluate a local beat/downbeat model, weight/code licenses, CPU/GPU behavior, and benchmark methodology. No model has been installed.
- **LIBBEAT: [librosa beat tracking](https://librosa.org/doc/0.11.0/generated/librosa.beat.beat_track.html)** — Evaluate a conventional beat-tracking baseline. This is a pinned 0.11.0 documentation link; verify the implementation version selected later.
- **RECUR: [librosa recurrence matrices](https://librosa.org/doc/0.11.0/generated/librosa.segment.recurrence_matrix.html)** — Research recurrence and similarity representations for musical sections; a similarity matrix alone does not label structure.
- **ESS: [Essentia audio analysis](https://essentia.upf.edu/documentation.html)** — Consider alternate local audio features and models; evaluate Windows support and licensing as part of dependency selection.
- **CLUSTER: [scikit-learn clustering](https://scikit-learn.org/stable/modules/clustering.html)** — Compare clustering methods, distance assumptions, outliers, and evaluation; human interpretation remains necessary.
- **CV: [scikit-learn grouped evaluation](https://scikit-learn.org/stable/modules/cross_validation.html)** — Design grouped evaluation to prevent leakage between song versions and overlapping phrases.
- **WEB: [Web Audio specification](https://www.w3.org/TR/webaudio/)** — Check playback clock/scheduling behavior and synchronization when designing the local previewer.
- **CODEX: [OpenAI skills documentation](https://learn.chatgpt.com/docs/build-skills)** — Verify skill packaging, discovery, progressive context loading, and supporting scripts during SM-022/023/024.
- **CLAUDE: [Claude Code skills documentation](https://code.claude.com/docs/en/skills)** — Verify current skill discovery, invocation, script/reference support, and host-specific behavior rather than assuming identical installation to Codex.

## Reading strategy for SM-003

Build topic notes with citations and concrete map sections. Cover technical motion, timing/representation, motif development, and intentional rule exceptions before compressing guidance into skill references. The initial browsing in this planning pass is not the requested full research program.

Keep dates and contradictions visible. Community advice changes with tools, game formats, and mapping style. Do not copy entire guides into a prompt or infer author consent to republish their material.

## Evidence boundaries

- The player analysis uses live public API responses saved locally, not search snippets.
- BeatSaver candidate selection checked metadata, exact hashes, and difficulty matching. Map geometry, music, and actual playability have not yet been reviewed.
- Dynamic API documentation pages may need an interactive viewer or OpenAPI schema during implementation. No undocumented rate-limit number is assumed here.
- No library, model, viewer, skill, or external codebase has been adopted by this plan.
- The larger map/guide pass, learning experiments, and all implementation are explicitly ticketed future work.



## Added after plan review

- **[BeatLeader API](https://api.beatleader.xyz/swagger/index.html)** — Verify score contexts, exact hash/difficulty joins, modifiers, replay availability, and null ratings. Public profile and score reads succeeded and are saved in beatleader-snapshot.json.
- **[BeatLeader RatingAPI](https://github.com/BeatLeader/RatingAPI)** and **[rating models](https://github.com/BeatLeader/beatsaber-replays-ai-2)** — Check definitions/versioning of pass, accuracy, and tech components. Do not assume all ratings are purely geometric or directly comparable across providers.
- **[JoshaParity](https://github.com/Joshabi/JoshaParity)** and **[refactor](https://github.com/Joshabi/JoshaParity-Refactor)** — Survey shared swing inference for SM-030. Both currently report MIT; pin commits and inspect dependencies before reuse.
- **[ArcViewer license](https://github.com/AllPoland/ArcViewer/blob/main/LICENSE)** — Checked default branch is GPL-3.0. Use the separate viewer initially rather than choosing source integration.
- **[ChroMapper license](https://github.com/Caeden117/ChroMapper/blob/master/LICENSE)** — Checked default-branch file is GPL version 2, not the GPL-3 claim in the review. Recheck exact commits and dependencies for future reuse decisions.
- **[BeatForge-AI](https://github.com/dinoboy6611/BeatForge-AI)** — SM-031 owns the read-only audit. The local README-upstream.md describes wasm-media-encoders; its MIT notice does not establish a whole-repository license.

## Inexpensive reference labels

Mapper BPM/offset and exact archive audio can seed timing checks cheaply. Spot-check start/middle/end and bar anchors; inspect trimming, variable tempo, and custom-data semantics before accepting reference labels. They are not universally free ground truth.

Ranked/curated technical maps seed likely-good mechanical fixtures and style strata. Treat them as weak evidence with exact version and review-era context, not a guarantee of zero parity errors or universal comfort. Personal taste still needs direct feedback.

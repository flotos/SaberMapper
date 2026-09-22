# Player profile and reference candidates

Research date: 2026-09-22. Player: **Flotos**, ScoreSaber ID `76561198016617991`.

## Evidence and method

The web reader could not load the profile, but direct read-only HTTPS requests to the public ScoreSaber API succeeded. The analysis retrieved the full player summary and all four score pages using `limit=100&sort=top`. The snapshot contains 383 distinct score IDs, matching the API's reported total.

Sources: [public profile](https://scoresaber.com/u/76561198016617991), [player summary API](https://scoresaber.com/api/player/76561198016617991/full), [score API, first page](https://scoresaber.com/api/player/76561198016617991/scores?limit=100&sort=top&page=1). The other pages use page=2, 3, and 4. The [local snapshot](scoresaber-snapshot.json) records retrieval time and flattened score evidence.

Calculated accuracy is `100 * baseScore / leaderboard.maxScore`, with nonpositive denominators excluded. Values below summarize stored leaderboard results, not a complete history of attempts, failures, or time spent playing.

For the main level estimate, include only currently ranked results with positive stars, mode `SoloStandard`, and an empty modifier field. No Fail and all other modifiers are excluded from this baseline, not silently treated as equivalent passes. Stars are the current ScoreSaber response values for old score entries; they need not be the rating at the time of play.

## Results

| Cohort | Count | Mean stars | Median stars | Mean calculated accuracy |
| --- | ---: | ---: | ---: | ---: |
| All saved score entries | 383 | Not meaningful across unranked entries | — | Not used |
| Ranked entries, including modifiers | 101 | Not used | — | API summary reports 79.54% |
| Ranked Standard, no modifiers | 90 | 6.98 | 7.075 | 81.31% |
| Same filter, timeSet on/after 2024-01-01 | 9 | 7.43 | 7.54 | 80.50% |
| Top 20 by returned PP order within the no-modifier cohort | 20 | 8.47 | Not calculated | 81.38% |

The nine later ranked results span December 2024 through January 2025, with stars from 6.17 to 9.04. Eight cluster in late January 2025 and may reflect a ranked session rather than representative play. The exact 90-result median is (7.02 + 7.13) / 2 = 7.075; it is shown unrounded to avoid floating-point rounding ambiguity. The latest saved score anywhere in the snapshot is dated **2025-03-20**, on an unranked map. Top PP results are largely from 2020.

The API reports 6,458.63 total PP, global rank 5,939, and France rank 152 at retrieval. These are useful context but are not used as a direct mapping-difficulty target.

The API's average ranked accuracy and the filtered calculation are different cohorts/definitions; their difference is not a data error.

## Interpretation: provisional, not a current skill assessment

Start calibration near **6.5-8 ScoreSaber stars**, with references near **8-9 stars** for challenge and difficult transitions. Keep a few easier reference sections for warmup, recovery, and comparison.

This is a proposal based mainly on nine later unmodified ranked results. It is not a statistically established comfort band. The profile is old relative to this planning date, saved best-score timestamps do not capture all later play, and the data does not identify the user's current fatigue or reading tolerance. Refresh through direct playtests in SM-002.

The confirmed taste is **technical variety rather than monotonous repetition**. Do not infer liking from a pass, low accuracy, PP, artist, or mapper. Ranked status does not identify repetitive mapping: the user's history includes maps which are both ranked and tagged tech. Unranked star values of zero mean unrated, not zero difficulty.

Do not advertise a generated map as having an official predicted ScoreSaber rating. Use named references and measurable movement/rhythm features until independently calibrated.

## Download/reference shortlist for the future ingestion ticket

Each candidate was joined through its exact ScoreSaber song hash to BeatSaver and matched to Standard plus the exact scored difficulty. The [candidate snapshot](reference-candidates.json) stores hashes, source endpoints, version-specific download URLs, metadata, flags, and results. **Only metadata was fetched; no ZIP or audio was downloaded.**

The purpose column is a planning recommendation, not a user-confirmed endorsement or a completed manual map review.

| Map and mapper | Exact difficulty | SS stars | Accuracy | Proposed purpose |
| --- | --- | ---: | ---: | --- |
| [The 89's Momentum — yabje](https://beatsaver.com/maps/2f386) | ExpertPlus | 8.15 | 81.91% | Primary tech calibration candidate; BeatSaver tag: tech; Jan 2025 result |
| [Time Leaper — epicmoo34](https://beatsaver.com/maps/20bd1) | ExpertPlus | 7.70 | 81.38% | Level calibration and rhythm contrast; style needs review |
| [Get Get Down — ItsVasili](https://beatsaver.com/maps/195a5) | ExpertPlus | 7.43 | 80.75% | Level calibration; style needs review |
| [eden — slamsyk](https://beatsaver.com/maps/1aaee) | Expert | 6.89 | 84.14% | Lower reference and density contrast; balanced tag |
| [Barbecue — Schwank & Jabob](https://beatsaver.com/maps/1a593) | Expert | 6.17 | 89.55% | Easier control reference |
| [Crimson Night — GalaxyMaster, Mr. Mrow & 3Stans](https://beatsaver.com/maps/1b984) | ExpertPlus | 9.04 | 71.31% | Harder tech reference; inspect transitions and fatigue |
| [Figue Folle — Vilawes](https://beatsaver.com/maps/9afa) | ExpertPlus | 8.68 | 85.04% | Historical tech/balanced reference; score from 2020 |
| [WAKE UP — Khenab](https://beatsaver.com/maps/cbcf) | ExpertPlus | 7.20 | 90.35% | Historical higher-accuracy comparison; style needs review |
| [Party Like It's 1920 — Nixie.Korten](https://beatsaver.com/maps/1a0b8) | ExpertPlus | Unranked | 89.48% | Dance/movement contrast; not automatically a tech exemplar |
| [you — Swifter](https://beatsaver.com/maps/43a1f) | Hard | Unranked | 77.34% | Excluded from core gameplay corpus; optional modchart research only |
| [End Times — Chaimzy](https://beatsaver.com/maps/43a24) | Hard | Unranked | 73.47% | Excluded from core gameplay corpus; optional modchart research only |
| [Very Noise — Checkthepan](https://beatsaver.com/maps/10cf1) | ExpertPlus | 9.60 | 51.78%, NF | Latest saved result is modifier-confounded; exploratory only |

For Very Noise, the shortlist selects the newest stored score rather than the top-PP entry; the snapshot contains another result with a different base-score ratio. Preserve distinct score IDs instead of collapsing them by song title.

BeatSaver flags Noodle Extensions on both `you` and `End Times`; they should not enter a vanilla gameplay-pattern cohort without explicit handling. Crimson Night is flagged Chroma, requiring a check of its visual dependencies. These flags are metadata observations, not a full archive audit.

The exact selected versions of all 12 candidates were found. BeatSaver's displayed star fields can differ from ScoreSaber: for example, Figue Folle returned 8.57 in BeatSaver metadata and 8.68 in ScoreSaber. The table consistently uses ScoreSaber stars.

## Follow-up work

- SM-002: confirm current level and obtain explicit favorite/disliked sections.
- SM-004/006: select and download exact-version references within the corpus plan.
- SM-003/011: inspect the examples and label contextual mapping quality and taste.
- Add newer unranked/curated technical maps and other mappers so historical scored maps do not define the entire corpus.
- Reassess the proposed band after playtesting; avoid treating low accuracy as a quality label or excluding technical motifs merely because they are hard.



## BeatLeader cross-check after review

A public lookup using the same player ID succeeded. The [BeatLeader snapshot](beatleader-snapshot.json) contains all 48 records returned by the score endpoint (metadata total 48), with provider-specific pass/accuracy/tech ratings where non-null and replay links. No replays were downloaded.

Sources: [player API](https://api.beatleader.xyz/player/76561198016617991), [scores sorted by date](https://api.beatleader.xyz/player/76561198016617991/scores?sortBy=date&order=desc&page=1&count=100), [API documentation](https://api.beatleader.xyz/swagger/index.html).

The latest returned result is **2025-03-20 20:13:04 UTC**, so this does not extend known activity beyond ScoreSaber. The profile aggregate reports 27 plays while the list returns 48 score records; contexts/count semantics need reconciliation before combining totals or treating them as complete attempt history.

Rating components are candidate stratification proxies, not enjoyment labels or replacements for ScoreSaber stars. Get Get Down, for example, returns BeatLeader stars 8.383857, passRating 6.12702, accRating 9.7393265, and techRating 5.0450363, while the selected ScoreSaber reference is 7.43 stars. Keep provider, version/date, map hash, characteristic, difficulty, and modifiers explicit. Null ratings remain unknown.

Historical telemetry mentions a Steam game build, but it does not establish the current installation. The user now confirms the latest SteamVR version is being installed, with rollback only if necessary and supported. Validate compatibility on that actual installation first.

SM-002 should combine explicit loved/disliked sections with swing rate, burst/sustained NPS, NJS, jump distance, recovery, and pattern classes. The January 2025 ranked session cannot establish current taste.

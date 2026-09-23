# Default player: Flotos

User-confirmed ScoreSaber profile: https://scoresaber.com/u/76561198016617991 (ID `76561198016617991`). Use this player when authoring maps in this workspace unless the request names someone else.

## Recorded skill evidence

The local snapshot was retrieved on 2026-09-22; these are historical scores, not a fresh assessment of current ability:

- 90 ranked Standard results without modifiers: mean 6.98 ScoreSaber stars and 81.31% base-score accuracy.
- Nine such results since 2024: mean 7.43 stars, median 7.54, and mean 80.50% accuracy. Their dates span December 2024 through January 2025; eight cluster in January 2025.
- Latest score anywhere in the snapshot: 2025-03-20, on an unranked map.

Evidence and exact map references: [player analysis](sabermapper/planning/research/player-profile.md), [raw snapshot](sabermapper/planning/research/scoresaber-snapshot.json), and [reference candidates](sabermapper/planning/research/reference-candidates.json). Current local calibration and explicit feedback live in `sabermapper/workspace/player-profile.json`.

## Default mapping interpretation

Use roughly **6.5–8 ScoreSaber-star reference maps** as the provisional comparison band. References around 8–9 stars are challenge examples, not a default sustained intensity or a measured comfort band. Compare rhythm, movement, transitions and recovery with the exact reference difficulty; do not copy source note arrays.

The planning record states a preference for **technical variety rather than monotonous repetition**. It does not establish specific favorite maps or a current stamina limit. A recorded pass is skill evidence, not an endorsement of the map.

Player star tiers tag the reference corpus and name each difficulty's target (`difficulty.target_tier`): `below_band` <6.5, `band` 6.5–8, `challenge` 8–9, `stretch` 9–9.5 (9.5 is the hardest recorded unmodified pass, 9.47, rounded up), `beyond` above that. The player has 28 recorded unmodified passes at 8+ stars; 27 are in the local corpus as phrase references (Night sky is an unsupported format). `challenge` is the target when the user asks for a harder map than the band, and `stretch` is for peaks only unless the user asks for more.

Treat **Expert / ExpertPlus as export labels**, not player calibration. If asked for “Expert,” still author for this player's evidence unless the user explicitly requests an easier or harder target. Do not assign an official predicted star rating to a generated map. Briefly state which references and difficulty assumptions guided the arrangement.

Read the local profile's `overrides`, `liked`, and `disliked` fields and the project's latest actual playtest feedback before composing. New explicit instructions and feedback take priority over these historical estimates. Proceed with the provisional baseline when current feedback is absent; do not invent preferences, current scores, or VR playtest results.

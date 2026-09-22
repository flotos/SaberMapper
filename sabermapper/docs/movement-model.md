# Movement model 1.1 and implementation survey

The shared `analyze_movement(notes, bpm, njs=..., spawn_offset_beats=...)` result contains versioned swings,
aggregate proxies, review warnings, and an explicit unsupported-motion list.
Validation calls this function; it does not maintain a second parity rule.
This implementation groups same-hand notes within 1/16 beat when their cut
directions agree, treats a long timing gap as a possible reset, and flags a rapid
same-hand cut in a broadly similar direction as a review question. Ordinary
directions suggest a medium-confidence forehand/backhand posture; dot notes and
angle offsets retain ambiguous parity. Native `seconds` fields, when present on
every note, determine swing rates and recovery; otherwise the model states its
constant-BPM assumption. Grid distance, angle change, one-second burst count,
crossover count, reaction-time estimate from NJS/spawn offset, and recovery
time are descriptive proxies, not comfort, injury, ranked difficulty, or star
ratings. Walls, bombs, arcs, chains and complex rotations are not inferred.

The following primary repositories were inspected on 2026-09-22:

| Implementation | Pinned HEAD | License and capabilities | Reuse decision |
| --- | --- | --- | --- |
| [JoshaParity](https://github.com/Joshabi/JoshaParity) | `775b0c36d1549852bdcfb8ce2cb99a4dc6b6b298` | MIT; C# configurable parity and swing/statistics model. Its README reports bomb reset uncertainty and planned multi-path inference. | Useful comparison oracle, but direct C# dependency would add runtime and mapping assumptions. |
| [JoshaParity Refactor](https://github.com/Joshabi/JoshaParity-Refactor) | `ce97ddddecfb8f418903f9322c03530062589651` | MIT; C# v2/v3/v4 parsing, swing generation, statistics, caching; JoshaParser submodule. | Promising future oracle; exact parser/version behavior and fixtures need review before integration. |
| [ChroMapper](https://github.com/Caeden117/ChroMapper) | `0d67a67d9b6ee750c412660a43ce34aa889378ae` | GPL-2.0 license; Unity editor with parity-related editing code. | Reference behavior only; no code copied. |

The [BSMG beatmap format](https://bsmg.wiki/mapping/map-format/beatmap.html)
defines the parsed note directions and native BPM events. The 1.1 model was
written independently for Python to keep interpretation visible and
deterministic. A calibrated production parity model still needs technical
reference phrases, ambiguity branches, cross-hand transitions, and measured
false-positive review. Current warnings should be checked by a player.

# Movement model 1.4 and implementation survey

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

Model 1.3 has two blocking flow rules, both defined once in `movement.flow_break`.
They apply to consecutive same-hand swings without a reset (a reset is a gap of a
full beat or more):

- `fast_direction_break`: a cut less than 0.3 s (`FAST_BREAK_SECONDS`) after the
  previous swing must turn at least 135 degrees (`REVERSAL_DEGREES`). A 90-degree
  turn this fast forces a wrist reset.
- `flow_parity_break`: at any non-reset gap, the swings must turn at least 90
  degrees (`MIN_TURN_DEGREES`), and they must not stay on the same
  forehand/backhand unless they turn 135 degrees or more.

A dot counts as the reversal of the swing before it, so down-dot-down is still
caught. Simultaneous notes are exempt. Findings have severity `error`, so
project save and export refuse them. When every involved note is in a locked
section, the finding is downgraded to a warning.

History: model 1.2 blocked only cuts under 0.2 s, after a playtest report of an
unhittable 16th up-cut followed by a left-cut. Model 1.3 followed two player
reports. The Revival 1:03 had an arc tail cutting right into the top-right
corner and then a down-cut from the same cell 0.24 s later. Living a Lie 1:38
had a down-right cut followed by a right cut, 45 degrees apart. The player asked
for a systematic fix, with half-beat 90-degree turns at 0.3 s or less blocked
everywhere.

Model 1.4 adds the review warning `one_hand_burst`: three or more consecutive
same-hand swings (`BURST_SWINGS`), each less than 0.2 s (`BURST_SECONDS`) after
the previous one, while the other hand has no swing between the first and the
last. One hand then streams a figure that alternating hands would carry. It
followed a report on End of You at 0:02.5: three right-hand eighths at 190 BPM
over a spoken line while the left hand held an arc, only one of them on a
syllable. The finding is a warning; `project repair-audio` removes the burst
notes that sit on none of the bar's lead attacks, then hands the weakest inner
note to the idle hand (or removes it), reverting any split that adds a blocking
diagnostic. Notes added by repair-audio never create a burst.

`sabermapper.swing_repair.repair_fast_breaks` and `project repair-swings` fix
findings deterministically. They drop a 16th pickup under 0.2 s that sits on a
weaker metric position. Otherwise they re-angle whichever cut of the pair leaves
the fewest breaks nearby, preferring the smallest turn from the authored
direction. Arc heads and tails are re-angled together with their note. A pattern
instance involved in a break is inlined as literal notes first; the compiled
output stays the same. Chain anchors and locked sections are never changed.

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

# Movement model 1.6 and implementation survey

The shared `analyze_movement(notes, bpm, njs=..., spawn_offset_beats=...)` result contains versioned swings,
aggregate proxies, review warnings, and an explicit unsupported-motion list.
Validation calls this function; it does not maintain a second parity rule.
This implementation groups same-hand notes within 1/16 beat when their cut
directions agree, treats a rest of 2 s or more as a reset, and flags a rapid
same-hand cut in a broadly similar direction as a review question. Ordinary
directions suggest a medium-confidence forehand/backhand posture; dot notes and
angle offsets retain ambiguous parity. Native `seconds` fields, when present on
every note, determine swing rates and recovery; otherwise the model states its
constant-BPM assumption. Grid distance, angle change, one-second burst count,
crossover count, reaction-time estimate from NJS/spawn offset, and recovery
time are descriptive proxies, not comfort, injury, ranked difficulty, or star
ratings. Walls, bombs, arcs, chains and complex rotations are not inferred.

Model 1.6 has two blocking flow rules, both defined once in `movement.flow_break`.
They apply to consecutive same-hand swings unless the hand rested: every cut must
start where the previous one left the saber. A rest (`movement.is_rest`) is an idle
gap of `REST_SECONDS` (2 s) or more on that hand, measured in seconds and never in
beats:

- `fast_direction_break`: a cut less than 0.3 s (`FAST_BREAK_SECONDS`) after the
  previous swing must turn at least 135 degrees (`REVERSAL_DEGREES`). A 90-degree
  turn this fast forces a wrist reset.
- `flow_parity_break`: at any gap short of a rest, the swings must turn at least 90
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
everywhere. Model 1.6 (2026-09-23) followed a report on Borrowed Waters: many
cuts repeated the direction of the same hand's previous cut. Model 1.5 excused any
pair a full beat apart as a reset, which is 0.33 s at 180 BPM and too short for the
player to raise the saber without swinging. The player asked that notes always start
from the position the previous note left. Only a 2 s rest now resets a hand.

The placer (see Placement below) keeps these rules for every cut it chooses. A rhythm edit that
adds or removes a time inside a phrase changes the parity of the hand's later cuts, so placement re-chooses
those placed cuts up to the hand's next rest. `project check` suggests a cut, hand or removal for a pinned
pair that breaks the rule.

Model 1.4 adds a blocking sight-line rule, `hidden_note`. It is defined once in
`movement.hidden_note` and `movement.hidden_window`. Notes of either hand are
checked in time order. A note arriving in the same cell as the note just in front
of it is hidden until that note is cut, and its arrow reads late. It must trail
that note by 0.35 s (`SIGHTLINE_HIDDEN_SECONDS`) in the four centre cells of the
middle and top rows (x 1-2, y 1-2), which sit on the player's line of sight. Elsewhere
it must trail by 0.2 s (`HIDDEN_SECONDS`). The window is in seconds rather than
beats, because the time the back note is visible before its hit does not depend on
NJS: a faster jump spreads the two notes further apart but brings them in faster.
The rule followed a player report at End of You 0:24: three blue notes in cell
(2,1) at 190 BPM, 0.158 s apart, cut right-left-right, where the front note hid the
ones behind it. Like the flow rules, a finding is an error unless every note
involved is in a locked section.

The placer never puts a note in a cell whose front note is inside that window, and
it keeps a later pinned note in the cell visible too. For a pinned pair, `project
check` suggests the free cells that clear it.

Model 1.5 adds the review warning `one_hand_burst`: three or more consecutive
same-hand swings (`BURST_SWINGS`), each less than 0.2 s (`BURST_SECONDS`) after
the previous one, while the other hand has no swing between the first and the
last. One hand then streams a figure that alternating hands would carry. It
followed a report on End of You at 0:02.5: three right-hand eighths at 190 BPM
over a spoken line while the left hand held an arc, only one of them on a
syllable. The placer never creates a burst. When the other hand is held, such a
rhythm cannot be placed: the infeasibility error names the notes and the times
to drop.

An arc or chain occupies its saber from head to tail. The validator blocks a
same-color note strictly inside it (`arc_note_conflict`, `chain_note_conflict`;
a warning when locked). This followed a 2026-09-23 player report at End of You
0:42. The placer gives every unpinned note inside a hold to the free hand, and the
hold's head and tail notes take the arc's hand, cut and cell.

## Placement (SM-036)

Maps are built correct by construction. A note needs only `id` and `beat`.
`color`, `direction`, `x` and `y` are optional pins, and the placer
(`sabermapper.placement`) fills the rest when the map compiles or saves. A beam
search over the timeline chooses each swing's hand and cut under the flow rules,
the held sabers, `one_hand_burst` and the reach limit (`REACH_SPEED`, the one
constant `reach_proxy` also reads). Two same-hand swings closer than
1/`REACH_SPEED` s are impossible, because the second one needs its own cell. A
greedy pass then chooses each note's cut and cell together, among the cuts that
keep the flow from the hand's actual previous swing and into its next pinned one.
It prefers short hand travel and placements the recent notes have not used, the
SM-034 repetition metrics: distinct placements and strict cycles. The result is
checked with `analyze_movement` itself. A broken rule that involves a
placer-chosen field raises a `placement_infeasible` error. The error names the
beat, the notes, the rule and the alternatives verified to clear it: unpin a
field, or remove a note. A conflict between fully pinned notes is left to
validation.

The fields the placer chose are listed in the note's `placed` array. They are
kept while valid and re-chosen only when a rhythm edit makes them break a rule,
so an edit in one bar leaves the rest of the map alone. Editing a placed value
pins it. Deleting a field asks for a fresh choice. Locked sections are fixed
context. Placement is deterministic, and a fully specified arrangement with no
`placed` record compiles byte for byte as written.

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

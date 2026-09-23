# Lightshow

Every project gets an audio-driven lightshow automatically. `project save` builds one when the
arrangement has none and rebuilds it whenever its inputs change. Export writes it into the difficulty file as v3 `basicBeatmapEvents` and
`colorBoostBeatmapEvents` and sets `Info.dat` `_environmentName`. Your job is to review it and improve
it where the music asks for more than the generator can see. Lights follow the same rule as notes:
every pulse sits on a sound, and no stretch of playing music keeps the lights frozen.

## What the generator does

`lighting.generate_lightshow` reads the newest musical evidence run and, per 4-beat bar:

| Sound | Lights |
|---|---|
| Kick-position drum hits (even beats of the bar) | back lasers + center, primary color |
| Back-beat hits (odd beats) | ring lights (secondary color), ring spin |
| Off-beat hits (hats, ghosts) | soft alternating rings / back lasers |
| Bar's lead: articulated singing, else the declared `musical_focus` lead, else the busiest pitched stem | side lasers with a laser-speed event per onset; rising pitch goes right, falling goes left; peak mirrors both sides; held notes (sustains ≥ 1 beat) switch on and fade at their end |
| Accompanying pitched stem | soft rings / back lasers |
| Bass | center (rings in calm passages, where the center is a steady dim base) |
| Strong chord change at a bar start | primary/secondary colors swap (at most every 8 beats) |
| Section entry | rise: all groups + ring zoom + spin + laser speed; fall: soft fade to the calm base; silent section: all off |

Section **mood** comes from per-bar mix energy, drum density and within-song rank: `off` (no active
audio), `calm`, `groove`, `peak`. It sets the density target, derived from the reference corpus (calm 10, groove 18,
peak 26 light events/s, scaled by bar level), laser speeds (1-2 / 2-4 / 4-7), brightness, ring
motion and color boost (on in peak). Palette `cool_to_warm` (default) lights calm blue and peak red.
Density comes from what the stems play. A sparse passage stays sparse, and the generator never adds pulses without a sound.
Full-field pulses (4+ groups at once) are capped at 4 per second.

## Inspect before changing anything

```
python -m sabermapper project lights-inspect ID --workspace workspace --start 64 --end 80
```

This prints section moods, primary color, leads and density, your cues in range, and a timeline of every event
moment with the sounds under it (`layer:method:strength`). `project critique` / `project get` report
the lighting checks below.

## How to change the lights

Edit `arrangement.lightshow` and save with `project save` as usual. Only change the inputs and cues.
`generated` is rebuilt from them and is never edited by hand.

```json
"lightshow": {
  "environment": "BigMirrorEnvironment",
  "auto": true,
  "style": {"intensity": 1.0, "palette": "cool_to_warm", "white_accents": false, "boost": true},
  "sections": {"s05-chorus": {"mood": "peak", "primary": "red", "boost": true, "white_accents": true, "intensity": 1.3}},
  "cues": [
    {"beat": 128, "action": "zoom", "note": "drop after the build"},
    {"beat": 128, "action": "pulse", "groups": ["back", "center"], "color": "white", "style": "fade", "brightness": 1.2},
    {"beat": 190, "action": "clear", "end_beat": 194, "targets": ["back", "ring", "center"]},
    {"beat": 190, "action": "off", "groups": ["back", "ring", "center"], "note": "a cappella break"},
    {"beat": 194, "action": "laser_speed", "side": "both", "speed": 8},
    {"beat": 194, "action": "boost", "on": true},
    {"beat": 200, "action": "event", "type": 1, "value": 7, "brightness": 0.8}
  ],
  "generated": {"...": "rebuilt automatically"}
}
```

- `environment`: one of the classic basic-lighting environments (`DefaultEnvironment`,
  `BigMirrorEnvironment` default, `NiceEnvironment`, `TriangleEnvironment`, `OriginsEnvironment`,
  `KDAEnvironment`, `MonstercatEnvironment`, `CrabRaveEnvironment`, `DragonsEnvironment`,
  `PanicEnvironment`, `RocketEnvironment`, `GreenDayEnvironment`, `GreenDayGrenadeEnvironment`,
  `TimbalandEnvironment`, `FitBeatEnvironment`). ArcViewer previews lights in its own environment.
- `style` (song-wide) and `sections[ID]` (per section) are generator inputs. Changing them regenerates
  on save. `mood` is `auto|off|calm|groove|peak`, `primary` is `red|blue`, `intensity` is 0.25-2 (density
  and brightness), `palette` is `cool_to_warm|warm_to_cool|red|blue`.
- `cues` are yours and survive every regeneration. Actions: `pulse` (groups, color red/blue/white, style
  on/flash/fade/transition/off, brightness 0-2), `off` (groups), `spin`, `zoom`, `laser_speed` (side
  left/right/both, speed 0-20), `boost` (on), `event` (raw `type`/`value`/`brightness`), and `clear`
  (removes generated events in `[beat, end_beat)` for `targets`: groups, `spin`, `zoom`,
  `left_speed`, `right_speed`, `boost`). Clears apply first, then additions. Give cues a `note`
  naming the sound they answer. Groups: `back`, `ring`, `left`, `right`, `center`.
- `auto: false` freezes `generated`. Saves keep it even when inputs change, and critique reports
  `lightshow_stale`. `project lights ID --workspace workspace --revision REV` rebuilds on demand.
- Each difficulty carries its own lightshow. `add-difficulty` copies it, and every difficulty generates the same show from the same sections. Repeat a cue in each difficulty that should have it, and pass `--difficulty NAME` to `project lights` / `lights-inspect`. Export lists each difficulty's environment in Info.dat.
- An arrangement saved without a `lightshow` key keeps the stored one, cues included. Locked sections
  keep their lights through regeneration. A cue that changes a locked section's lights is refused.

Prefer the most general lever: a section override for a whole passage, a cue for one moment, and
`style` only when the user's taste applies to the whole song. Put a reusable taste ("less red",
"calmer verses") in the player profile, not only in one song's style.

## Checks

Blocking (`validate`/`save`): `light_strobe`, meaning more than 8 full-field pulses (4+ groups) in any
1 s, or more than 3 white pulses on 3+ groups. Also `invalid_lightshow`/`unsupported_field` for schema errors.

Warnings (`project get`, `project save`, `project critique`):
- `lightshow_missing`: no lights while evidence exists. Run `project lights`.
- `lightshow_stale`: `auto: false` and the inputs changed.
- `light_unmapped`: 4 s+ of active, articulated audio with no light change.
- `light_without_audio`: 8+ consecutive pulses with no sound under them, usually from cues.
- `light_density`: a section above 50.8 events/s, or below 4.3 while the stems play 4.3+ strong onsets/s.
- `light_flash_heavy`: 4 s+ of more than 4 full-field pulses per second.
- `light_blackout_notes`: all lights dark for 2+ beats while notes are played.

The checks cover coverage, grounding and safety only. Whether a show looks good is the user's call in ArcViewer or in the game.

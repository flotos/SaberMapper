# What the Extra Sensory II shaders do, how, and why

A measured study of the ten EXSII bundles (274 shaders, 300 custom render passes, 623 materials, the
Vivify events of each map's hardest difficulty), plus the published sources of `you`, Aether (Swifter's
later map), Breezer and 3 BIG SHOTS. Use it to choose techniques and to calibrate how much to do; the
rules that follow from it are in [shader-craft.md](shader-craft.md). Study only: never copy an EXSII
shader, material or event array into a SaberMapper bundle. Re-derive the technique. Claims read from
compiled code rather than source are inferences.

## The numbers that set expectations

| Measure | Value |
|---|---|
| Custom shaders per map | 8 to 76, most written for that map |
| Passes built for single-pass instanced stereo | 298 of 300 |
| Screen-effect passes reading the eye's own slice of the frame | 71 of 74 (the rest never read the screen) |
| Median size of a screen-effect shader | 20 instructions; the heavy shaders (300-800) are skies, screens, water, area lights |
| Blit duration | median 0.5 beat; most common 0.5, 0.25, 2, 0.2, 1, 0.125 beats |
| Blit start times | on integer or half beats almost everywhere |
| Screen effects layered at once | 1 to 3 (deeper stacks only in hand-built bloom chains) |
| Blits in the whole pack | 566, of which 20 run before the game's bloom |
| Passes writing alpha 0 | 64, including all nine procedural skies |
| Shaders exposing `_Glow` | 38 |
| Noise or ramp textures in the whole pack | about 13; nearly all noise is computed in the shader |
| Most-used keyframe easing | `easeStep` (345), then `easeOutSine`, `easeInCirc`, `easeInCubic`, `easeOutExpo` |

Two families: **post-process maps** (luminescent: 239 short blits of four effects; Ego Death: four tiny
screen shaders fired 149 times) and **scene maps** (Yoi Okashi, End Times, 3 BIG SHOTS). The screen effects
are tiny: complexity comes from timing and the number of hits, not from shader size.

## Cross-map lessons

1. **Stereo is universal.** Every screen, grab and depth read goes through the per-eye slice. Some maps use
   the eye index on purpose: 3 BIG SHOTS offsets flat overlay cards per eye to give them a chosen depth,
   42-flux shows some notes to one eye only, and End Times gives each eye its own memory snapshot.
2. **Alpha is the glow switch.** Skies, planets, lit scenery and note bodies write 0. Glow comes from an
   explicit `_Glow`, `_Bloom` or luminance term on small parts. Ego Death's scene flashes animate only
   `_Glow` (125 events), never colour. `you`'s cut edges write alpha 20 for a hard flash. 42-flux's fog
   fades alpha with distance so far objects stop glowing. Water clears the glow under it.
3. **Screen effects share one recipe:** no depth test, no depth write, no culling, no blending, one or
   several samples of the eye's frame, and a single amount property the events key (`_Intensity`, `_amp`,
   `_Strength`, `_Juice`, `_Transition`, `_Blend`). One-shot effects expose `_Progress` or `_Distance` and
   play their whole animation over three to six beats.
4. **Variety without new shaders:** step a seed. luminescent sets a new random static `_amp` before each of
   its 159 glitch hits, so every hit looks different. `you`'s intro sky gets a new `_ID` every 1/16 beat
   (156 events) while `_Zoom` sweeps inside each step, which makes a stuttering tunnel.
5. **Hits are envelopes; stutters are steps.** Hit-and-decay uses out-curves (Ego Death's kick tear:
   `_Intensity` 0.3 → 0 over about 2 beats, 72 times). Glitches and YTPMV-style edits use `easeStep` point
   trains (3 BIG SHOTS is almost all steps).
6. **Long blits are lenses.** A single section-long blit sets a mood: Breezer's 213-beat VHS "found
   footage" lens after the noclip, Lifelike's 160-beat warm grade eased in over 28 beats when the day sky
   appears, Through The Screen's three long acid passes.
7. **Keep the palette in one place.** Yoi Okashi broadcasts every palette change to about 60 materials
   (4241 events) because its shaders share no global. 42-flux sets one global fog colour and distance that
   about 20 shaders read. A shared global (`SetGlobalProperty`) is the cleaner design.
8. **Live game values as inputs.** End Times and Through The Screen bind shader values to Heck base
   providers (energy, score, combo, head rotation, saber colours), so HUDs and sabers react with no
   per-frame events. In our show this needs a `raw` event whose value is the provider name; it is
   untested here.
9. **The depth texture is opt-in.** Four maps enable it with `SetCameraProperty` at beat 0, for water
   thickness, soft particles, wisps drawn only over the far sky, volumetric fog and focus.
10. **AudioLink is not in the base game.** Two maps read an audio texture and list AudioLink as a
    requirement; without that mod those terms read zero. SaberMapper drives shaders from its own audio
    evidence at compile time instead.

## Techniques by family

### Screen effects (53 shaders)

- **Glitch and tear:** the screen is cut into horizontal bands. Each band gets a hashed phase, and the
  colour channels shift by slightly different phases, which builds in a colour split. Row and column tears
  choose their axis per hit and ease to zero within half a beat.
- **Tape (VHS):** independent terms (seeded vertical jitter, pixel flooring, a red-blue split, contrast
  mute, bars, block noise, scanlines), each scaled by its own property, so a transition can jump between
  states with `easeStep`.
- **Warps and zooms:** ripple and shear distortions keyed with easeOutSine; tiling zooms stepped with
  `easeStep`; a per-channel zoom split held under a final chorus.
- **Colour:** warm grades, inversions, a brightness punch (0.2-beat blits up to 3×), per-beat chromatic
  pulses in a final chorus.
- **Stylisation:** pixelation, ordered dithering, an ASCII mosaic (block brightness picks a glyph from a
  sprite sheet), hashed boxes recoloured in steps, film grain.
- **Blur and warp shocks** (`you`'s drop): a blur pass and a noise-warp pass stacked for the whole drop and
  re-keyed together on every 1.75-beat hit.
- **Periphery glow** (`you`): the centre's colours are smeared only into the left and right edges.
- **Overlay cards:** an eyelid blink built from radial falloffs, a death whiteout, bullet holes and
  letterbox bars, a "crouch now" card placed at a stereo depth.
- **Note-only effects:** a whitelist camera renders one note track into a texture, and the blit uses it as a
  mask: static on notes (Breezer), a heat-haze wiggle on notes (3 BIG SHOTS), and notes removed from the main
  camera and composited back with a per-row jitter (42-flux).

### Render textures and feedback (11 shaders)

- **Hand-built bloom:** four downsamples and three upsamples between declared screen textures, ordered by
  `source`, `destination` and `priority`, then a composite with an animated `_Intensity`. End Times ramps
  it 0 → 10 over its 10-beat death.
- **Screen memory:** a zero-duration Blit with no material copies the frame into a screen texture. 3 BIG SHOTS
  stores four frames and replays mixes of them in 32 blits of 1/8 beat as freeze-frame gun shots. 42-flux
  snapshots the frame 0.05 beat before each scene swap and dissolves the frozen old scene into the new one.
- **Feedback loops:** a pass cannot read and write the same texture, so 42-flux writes a buffer and copies
  it back with a material-less Blit each frame: rainbow zoom trails, note afterimages, and a sky that samples
  the previous frame zoomed for an endless tunnel.
- **Cameras as content:** End Times places 157 camera prefabs that snapshot the player's stereo view every
  1.5 beats, then plays them back in reverse as Outer Wilds' memory rewind.

### Skies (18 shaders)

- luminescent draws six skies, swapped per section. Among them: a galaxy from fbm and a spiral rotation, a
  10-step raymarched kaleidoscope tunnel, a domain-warped nebula and a polar spiral. All write alpha 0, and
  the events animate their brightness, swap two colours every half beat, or jump their exposed time offset.
- `you`'s four skies share one kit of hashes, gradient noise, cosine palettes and thin lines made with
  pow. The intro tunnel is built around the view axis; the drop is a kaleidoscope whose mirror count (3-7)
  changes on each hit, with a hue rotation, a time-offset lurch and a bloom strobe that decays after the hit.
- Through The Screen raymarches a void on a flat quad rotated by the real head rotation, so it parallaxes.
- Why: skies are the largest surfaces. A procedural sky gives each section a new set at no texture cost,
  and its few semantic knobs (seed, brightness, time offset, symmetry) are what the events hit.

### Surfaces (68 shaders)

- **Fake lights:** a light direction or position uniform with simple diffuse and specular. Events re-aim it
  (Lifelike moves its light at sunset) or animate its strength (Aether turns the terrain lights on as the
  music enters).
- **Cel shading and ink:** quantised lighting. Lifelike's ink notes use an inverted-hull outline (a
  front-culled copy scaled up) in black or white per hand.
- **Fog:** one formula shared through globals (42-flux) or a keyword block per shader. Distance and height
  fog are combined as `1 - (1-a)(1-b)`.
- **Area lights** (Through The Screen, a VRChat import): screens light the room with what they show, and
  one global relights the whole room.
- **Displaced shapes:** End Times' sun uses three octaves of vertex noise; one `_Collapse` value both spikes
  and shrinks it.
- **Grass:** tessellation plus geometry shaders that emit blades. Only the tips write a little glow.
- **Glass and lensing** (GrabPass, 15 shaders): black holes pull the grabbed screen towards their projected
  centre by fresnel and go black at the core (End Times puts one inside every note). 608 outro clouds share
  one named grab. Water offsets the grab with scrolling normals and fades by depth.

### Notes and sabers (35 shaders)

- The contract everyone follows: noise dissolve against `_Cutout`, debris cut against `_CutPlane`, a bright
  edge band (`_CutoutEdgeWidth`) that flashes the bloom.
- `you`'s showpieces:
  - glass notes refract the realtime reflection probe with a per-channel split;
  - chrome notes blur a cubemap reflection;
  - portal notes are windows onto a far starfield, with a `VOID` keyword switched at the drop.

  The map enables realtime reflection probes and spawns probe prefabs, so the notes reflect the animated
  skies without extra events.
- Aether's outline note keeps the stock silhouette by shrinking the core before pushing the hull out. Its
  gem note refracts into a virtual interior evaluated with 3D Voronoi, with no loop. The note looks swap
  per section by reassigning prefabs.
- Yoi Okashi's toon note uses a four-band cubemap and the world's fog colour, so notes emerge from the same
  haze as the scene.
- Sabers: a Bézier guide beam built in the vertex shader from the hilt back towards a moved viewpoint
  (`you`); trails from noise masks that read the player's colour scheme; `ColorMask RGB` so a trail never
  adds glow.

### Particles, stencil, volumetrics

- Particles are textureless sprites: four-point crosses, hot cores, a hash flicker, cosine palettes.
  Stencil masks keep them out of a black hole regardless of draw order.
- Volumetric fog (42-flux: 32 steps with a blue-noise start offset and a spotlight cone; Aether: 16
  jittered steps through baked noise) stops at scene depth and runs before the bloom when it should glow.

## What each map teaches

| Map | Lesson |
|---|---|
| Breezer | One strong lens (a 213-beat VHS) carries the whole story; never more than one blit at a time. |
| End Times | Object shaders carry the scene; screen work is concentrated at three moments (a blink, a death with a hand-built bloom, a rewind). |
| Lifelike | A scene map needs almost no screen effects (one warm grade, 10 material events); ink notes match the paper world. |
| you | 39 procedural shaders on four small textures; semantic floats on strict grids (1/16 beat intro, 1.75-beat drop) strike every layer together. |
| Ego Death | Four tiny screen shaders fired 149 times: timing, not shader complexity. |
| 3 BIG SHOTS | Ten one-off set-piece effects cut with `easeStep` like a video edit; screen memory for freeze frames. |
| luminescent | Six swapped skies and 239 short blits; a new random amount on every glitch hit. |
| Yoi Okashi | Lit, fogged toon world recoloured by palette events; screen effects held back for the finale. |
| Through The Screen | Imported VRChat techniques (area lights, Droste, particle screens) bound to live head and colour values. |
| 42-flux | A full pipeline: bloom chain, snapshot-and-wipe transitions, feedback loops, note-only cameras, one global fog. |

## What none of them do

- No map raymarches solid SDF shapes. The raymarching there is volumetric fog, a sky tunnel and a
  head-rotated void. A raymarched set-piece is a look of its own if kept small and bright.
- None samples live audio without an extra mod. All music sync is authored keyframes on the beat grid.
- Almost none uses textures for noise.

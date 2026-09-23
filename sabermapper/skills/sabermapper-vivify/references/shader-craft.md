# Shader craft for vivified maps

Read this before you write or restyle a tier-2 shader, and when you design a section's look. It explains
what makes Vivify visuals look good in the headset and why, the rules that follow from how Beat Saber
renders, and the techniques with the handles the show animates. The ten Extra Sensory II maps teach the
same lessons from real bundles in [exsii-shaders.md](exsii-shaders.md). Ready-made functions are in
[shader-cookbook.md](shader-cookbook.md), and compile-checked starting shaders are in `templates/`.

Sources: a study of the ten EXSII bundles and their events, the published source of `you`, Aether,
Breezer and 3 BIG SHOTS, the Vivify docs and source, VivifyTemplate, Inigo Quilez's articles, Valve's
VR rendering talks, the Unity 2021.3 manual and WCAG 2.3.1. Findings from our own in-game captures are
dated. Anything marked *unverified* has not yet been confirmed in a capture.

## 1. The shader is where the spectacle lives

In EXSII, every bundle carries between 8 and 76 shaders, most of them written for that map, while the
meshes are mostly primitives: planes, cubes, spheres, cylinders and a few scenery sets. A plane is a
canvas for a sky, a flare or a screen effect, and real models are always restyled by a shader (cel
shading, fog, glitch) so they never look like stock assets. The look comes from the shader and the way
the show animates its properties, not from polygon counts.

So design a map's visuals shader first:

1. **One idea per map, one family per section.** Pick the image the song suggests (the concept) and the
   one or two shaders that carry it. EXSII maps are either post-process maps (the spectacle is full-screen
   shader work: luminescent, Ego Death, 42-flux) or scene maps (instantiated geometry with custom
   surfaces: Yoi Okashi, End Times, 3 BIG SHOTS). A section uses one family.
2. **Everything is a function of a few semantic drivers.** Each shader exposes one to three 0..1 handles
   named after what they do on screen (`_Progress`, `_Reveal`, `_Pulse`, `_Warp`, `_Phase`), and the
   shader derives its whole shape from them. The show animates those numbers; the shader owns the look.
3. **Cheap analytic pieces beat heavy geometry.** Cosine palettes, polar coordinates, rings drawn as
   `pow(1 - |r - R|, n)`, four-point flare crosses on quads, noise on the view direction for skies. Swifter's
   maps contain almost no textures.
4. **The music moves the numbers, not `_Time`.** `_Time` is seconds since the level loaded. It is fine
   for idle shimmer and drift, but every accent comes from a show `pulse` driven by audio evidence or a
   keyframe anchored to a sound.

## 2. Platform rules (how Beat Saber renders)

These hold for every shader. `assets lint` enforces the stereo macros. The rest are yours to follow.

### 2.1 Stereo: every shader, every pass

- Single-pass instanced stereo: without `UNITY_VERTEX_INPUT_INSTANCE_ID`, `UNITY_VERTEX_OUTPUT_STEREO`,
  `UNITY_SETUP_INSTANCE_ID`, `UNITY_INITIALIZE_VERTEX_OUTPUT_STEREO` and
  `UNITY_SETUP_STEREO_EYE_INDEX_POST_VERTEX`, a shader draws in the left eye only. Copy the skeleton from a
  template.
- Call `UNITY_SETUP_STEREO_EYE_INDEX_POST_VERTEX(i)` first in the fragment. After it, `_WorldSpaceCameraPos`,
  `unity_CameraToWorld` and `unity_CameraInvProjection` are the current eye's. Without it both eyes use the
  left eye's camera: raymarched rays, fresnel and parallax go flat.
- Sample screen, grab, depth and screen-texture images only with `UNITY_DECLARE_SCREENSPACE_TEXTURE` and
  `UNITY_SAMPLE_SCREENSPACE_TEXTURE(tex, UnityStereoTransformScreenSpaceTex(uv))`.
- **Anchor patterns to the world, not to the screen.** Noise, grain, pixel blocks, scanlines and the centre of
  radial effects computed from screen UV differ between the eyes. The brain cannot fuse them, so the image
  shimmers. Build the per-eye view direction from UV (`viewDirection` in the cookbook) and hash or measure
  on that. The world-blit template's ring is centred on a world direction (verified in game, 2026-09-23:
  it travels outward from the lane axis). A 1-bit dither against banding is the only exception.
- A billboard that faces each eye's camera swims when the head rolls. Face the head centre, or rotate
  around world up only.

### 2.2 Alpha is bloom

Beat Saber turns the frame's alpha channel into bloom. Every EXSII author treats alpha as a deliberate glow
control:

| Surface | Alpha | Why |
|---|---|---|
| Opaque scenery, floors, walls, terrain, skies | **0** | Large areas that write alpha bloom all at once. |
| Small glowing parts (rims, edges, lines, stars, flare cores) | `luminance × k` or a `_Bloom` value | Only what should glow does. |
| A flash (dissolve edge, cut edge, a strike) | large on purpose (EXSII uses up to 20) | A one-off hard bloom on a small area. |
| Surfaces that must not change the glow below them (trails, screens, water) | `ColorMask RGB` | Leaves the existing alpha alone. |
| Blits | pass `src.a` through | Replacing it rewrites the whole screen's bloom. |
| Additive blends | `Blend One One` also adds alpha | Overlaps pile up into white-out. Use `Blend One One, Zero One` to keep the bloom unchanged. |

**Captured lesson (2026-09-23, template test):** a 30 × 120 m floor that wrote a rim alpha of about 0.2
turned almost white for four frames whenever an additive raymarched object pulsed, a full-floor flash with
no event on the floor. Large surfaces write alpha 0. The stage-surface template defaults `_RimBloom` to 0
and keeps rim light off floors with `_RimStrength`.

Blits run after the bloom pass by default, so their alpha does not add glow (EXSII's luminescent forces
alpha 1 in its glitch blits and nothing blooms). Still pass `src.a` through: an `order: BeforeMainEffect`
blit or a later bundle change would otherwise bloom the whole screen.

### 2.3 Colour

- The forge builds in linear colour space. `Color` properties are converted from gamma to linear, while
  `Vector` properties are not. Inigo Quilez's cosine-palette presets are tuned in gamma, so pass them as
  Vectors and convert the result with `GammaToLinearSpace` (the templates do). Swifter composes in gamma and
  applies `pow(col, 2.2)` last; it is the same idea.
- Treat the frame as low dynamic range: RGB above 1 is not a reliable glow. Make things look hotter than
  white with a whitened core (`lerp(col, 1, k)`) plus alpha.
- Saturated darks read better than bright fills in a headset. The eye adapts to the average brightness,
  so a dark, saturated background makes small emissive accents and the notes read as bright without much
  luminance. Spend brightness on small things that carry information.
- Keep one accent hue for impacts, never the note colours as large fills behind the lane.

### 2.4 Depth, fog, lights

- `_CameraDepthTexture` exists only after the show enables it (`setup.camera_properties.depthTextureMode:
  ["Depth"]`), and only opaque objects with a ShadowCaster pass in queue ≤ 2500 write it (the
  stage-surface template has one). Transparent objects never do. *Unverified:* whether the game's notes and
  walls appear in it.
- The game's fog is computed inside its own shaders. Custom shaders get no fog unless they compute it
  (distance and height fog in the cookbook).
- Scenes have no useful Unity lights. Fake them: a `_LightDir` property, banded or wrapped diffuse, and a
  light-strength float the show animates (Aether turns its world "on" by animating strength from 0 when
  the music enters).

### 2.5 Sky

Two ways to draw a sky, both verified in the game (2026-09-23):

- **Skybox material:** `setup.rendering.renderSettings.skybox` plus `setup.camera_properties`
  `{"clearFlags": "Skybox"}`. The game's camera clears to a solid colour, so without the clear flag the
  sky stays black (`skybox_not_cleared` blocks export). Unity draws it after opaques, at infinity.
- **Sky sphere prefab:** a large `uv_sphere` with a direction-only shader, as a `scene` primitive. It can be
  swapped, layered, scaled and faded per section. Push its vertices to the far plane (the sky template
  does) so everything occludes it and hidden pixels cost nothing.

Stars need a brightness spread. A star field where every star has the same brightness reads as snow in
the capture; a steep power curve on a per-star hash gives a few bright stars and many faint ones.

### 2.6 What the forge and the show can express

| Need | How | Limits |
|---|---|---|
| Per-note values | Instanced properties (`UNITY_DEFINE_INSTANCED_PROP`) | The forge enables GPU instancing on every material. |
| Render state per material | `Blend [_SrcBlend] [_DstBlend]`, `ZWrite [_ZWrite]`, `Cull [_Cull]`, `[Enum(...)]` float properties | Set them as Float values in assets.json. `render_queue` overrides the queue. |
| Variants | Float uniforms and coherent branches | assets.json cannot switch material keywords on at build time. A runtime keyword needs `#pragma multi_compile _ KW` and a show `SetMaterialProperty` with `type: "Keyword"`. |
| Textures | `texture` assets: 2D or cube (equirectangular panorama) | No 3D textures, so volumes use procedural noise with few octaves. |
| Models, textures, photo skies | `assets fetch` (Poly Haven, ambientCG, Kenney; CC0) | Models arrive as OBJ with vertex colours, within the triangle budget; see section 5, fetched geometry. |
| Screen copies | Blit `source`/`destination` with `setup.screen_textures` | A named GrabPass lints as a warning; prefer a Blit. |
| Second camera | `setup.cameras` (culling by track, own texture) | Every camera renders the scene again; destroy it when its section ends. |
| Animation | `SetMaterialProperty` (Float, Color, Vector, Texture, Keyword), `SetGlobalProperty`, `AnimateTrack` | Point definitions with easings, including `easeStep` for hard cuts inside one event. |

## 3. Designing the look

### 3.1 Composition in a 360° headset

- The player faces forward along the track. The note lane fills the central forward cone (about ±30°), and
  notes arrive about 1 to 2 m away after spawning tens of metres ahead.
- **Behind the notes**, keep low contrast, low detail and low motion, at a value clearly different from the
  note colours. The sky template dims a cone around the lane (`_LaneDim`, `_LaneWidth`).
- **The strong idea** goes in the forward cone above or around the lane, or at 30-90° to the sides.
  Peripheral vision is motion-sensitive, so motion there reads without a direct look. Behind the player is
  unseen: spend nothing there.
- Keep what must be seen in a clear lane between the note corridor and the scenery (x ≈ ±1.9 to ±3 m at
  z ≈ 4-5 m, from Ko Phangan).
- **Depth layers.** Near (particles, beams across the track; sparse), mid (structures at 10-60 m that carry
  the beat motion), far (sky or raymarched set-pieces; slow drift and mood). Only near and mid layers have
  stereo depth, so give them the motion.
- A shape painted on the screen reads as glued to the face or at infinity. Anything that should sit in
  the world is geometry (a quad, a proxy cube) with a world-space shader.
- A raymarched torus lying flat above the player reads as a thin ellipse. Orient set-pieces towards the
  viewer; the raymarch template's ring faces the track (captured, 2026-09-23).

### 3.2 Palette and value

Derive a map's colours from one cosine palette (four vectors). Shift its phase between sections so the
world changes colour but stays coherent. Use two or three hues per section plus neutrals, and one accent
hue for hits. Decide for each section what is darkest and what is brightest. Brightness is scarce: notes,
sabers and bloom compete for it.

### 3.3 Restraint and escalation

Introduce one element at a time. Save full-screen effects, inversions and the strongest bloom for the drop
or the held key moment. Reset to calm after a peak so the next peak has contrast. Every visual event must
answer "which sound is this?", the same rule as for notes.

## 4. Driving shaders from the music

### 4.1 Handles: fast and small, slow and global

| Handle | On a hit (fast, small area) | Over a section (slow, global) |
|---|---|---|
| Bloom alpha on edges, rims, lines | spike, exponential decay | baseline |
| Palette phase / hue | +0.05 nudge | continuous drift; section changes over 1-2 beats |
| Domain-warp amount | none | ramp through the build, snap back on the drop |
| Smooth-min radius (blobs merge) | pulse | none |
| Vertex bulge `_Pulse`, travelling wave `_Wave` | primary use | wave speed |
| Seed or ID (`_Seed`, `_ID`, `_Mirrors`) | new value on each hit: a new pattern | none |
| Time offset (`_Flow`, `_TimeOffset`) | jump forward, easeOutExpo: the pattern lurches | slow drift |
| Fog density or height, sky rotation | none | thicken, clear, very slow turn (< 1°/s) |
| Colour grade exposure | ≤ ±0.3 EV, ≤ 3 Hz | mood per section |
| Dissolve or reveal | none | 1-4 beat sweeps at transitions |

### 4.2 Envelopes

- **Hit:** attack in a frame, fast decay (easeOutExpo or easeOutQuart), optional slow pre-roll into the next
  hit (easeIn). `you`'s drop sets sky, veins, wisps, flare and post effects on the same 1.75-beat hit
  with this one envelope, so every layer strikes together.
- **Anticipation:** accents start slightly early so the peak lands on the sound. A `pulse` with
  `attack_beats` does this: the rise starts before the onset.
- **Stutter:** `easeStep` points at small time deltas inside one keyframe give discrete jumps (droobix's
  VHS transitions, `you`'s outro).
- **Build and release:** ease in over 4-16 bars, then snap back on the drop. The contrast is the payoff.
- **Re-seed per hit:** stepping an integer seed or mirror count on each hit changes the whole pattern at
  zero cost (`you`'s kaleidoscope `_Mirrors` 5, 3, 7, 4; the intro sky's `_ID`).

### 4.3 Motion over brightness on large areas

WCAG 2.3.1 allows at most three flashes per second, and in a headset any large-area luminance pulse counts
as one. At 128 BPM, quarter notes are 2.1 Hz and eighth notes 4.3 Hz. Large surfaces therefore move on
the beat (bend, sway, scale, a travelling wave), change hue at constant brightness, or leave the accent to
small elements. `show validate` and the capture probe check flash rates; design so they never trip.

### 4.4 Comfort

No sustained head-locked motion: full-screen zoom, warp, rotation and feedback smears stay at or under one
beat and low amplitude, and favour the periphery. Never roll the whole world around the player. Streaks
and zooms (vection) come in bursts of one or two beats.

## 5. Technique catalogue

Each entry gives the look, how it works, when to use it, its cost in VR, and its handles. Functions are in
the cookbook; complete shaders are in `templates/`.

### Colour and noise

- **Cosine palette** `a + b·cos(2π(c·t + d))`. One scalar gives a whole gradient; `d` rotates the hue
  order. Section handle: phase. Cost: negligible.
- **Value noise and fbm** (hash without sine, 4 rotated octaves). Use texture-free fbm on small or sky
  areas; keep it to 3-4 octaves over large areas.
- **Domain warping** `f(p + k·fbm(p))`. Marble, ink and nebula looks, the best single trick for backdrops.
  The warp amount is a strong build handle. Cost: 3-4 fbm per pixel; fine on a sky, heavy on a large
  surface.
- **Animating noise without boiling:** scroll or rotate the domain, move layers at different speeds, or use
  a time offset that lurches on hits. Slicing noise with time too fast reads as TV static and shimmers.

### Skies and backdrops

- **Direction-only skies** (template `sky_sphere`). Every feature is a function of the view direction, so
  it is stereo-consistent and at infinity. Stars from a hash grid with `fwidth`-sized discs never go
  sub-pixel, so they don't sparkle.
- **Polar tunnel fields** (`you`). Work in polar coordinates around the track axis. Bands
  `sin(angle·N + twist(depth))` spiral down the tunnel, and multiplying the angle makes a kaleidoscope
  whose symmetry changes with the integer `N` on each hit. Colour with a palette over radius and bands.
- **Window onto a far field** (`you`'s portal notes and outro text). Intersect the view ray with a
  virtual plane far away and shade that point. The surface becomes a window that stays fixed in the world
  as the object moves, with correct depth per eye.

### Glow shapes on quads

Everything glowing can be a quad whose fragment draws an analytic shape in centred UV. Rings are
`pow(1 - |length(uv) - r|, n)` with `r` driven by `_Distance`, four-point flares are
`pow(1 - |x·y|, k)`, and superellipse stars are `|x|^b + |y|^b`. Use `Blend One One` or premultiplied
`One OneMinusSrcAlpha` with `ZWrite Off`. Accents on hits: `_Exaggerate`, `_Opacity`, a random z rotation
per hit. Hide a flare behind geometry by sampling the depth texture at its centre.

### Raymarched set-pieces (template `raymarch_volume`)

- Render a proxy cube. Each eye marches its own ray from `_WorldSpaceCameraPos` in object space, clipped
  to the cube, so the sculpture has real stereo depth and works when the head is inside it (`Cull Front`).
- SDF primitives blended with smooth-min, twisted and repeated in angle or space. Twists break the
  distance bound, so step 0.8 of the distance.
- Accumulating `exp(-d·falloff)` along the march gives neon glow for free. Tonemap it, then send part of it
  to alpha.
- Budget: at most 64 steps (the lint limit), `_Steps` as a property, a small screen footprint. Cost is
  steps × map cost × pixels covered. None of the EXSII maps raymarches solid shapes, which makes it a
  distinctive look if kept small and bright on a dark sky.
- Volumetric fog (Aether's vortex) is the one raymarch EXSII uses: 16 jittered steps through noise,
  stopped at scene depth, Beer-Lambert accumulation, rendered to a reduced screen texture and blurred.

### Surfaces for scene geometry (template `stage_surface`)

- **Fresnel rim** `pow(1 - N·V, p)`: silhouettes pop on dark skies. Keep it off floors and walls: at grazing
  angles a flat plane is all rim (captured, 2026-09-23).
- **Banded fake light** from `_LightDir`, anti-aliased with `fwidth` at the band edges.
- **World-space hologram lines**: stereo-stable, unlike screen-space scanlines.
- **Vertex bulge and travelling wave** from a world origin: the hit moves the geometry, not its brightness.
  Renderer bounds do not grow, so keep displacement small next to the mesh size.
- **Distance fog to a colour, and noise dissolve of far geometry**, so scenery fades into the sky instead of
  ending in a hard line or a black silhouette.
- **Inverted-hull outline** (Aether): a second pass with `Cull Front` pushes vertices along the normal.
  Shrinking the core first keeps the silhouette equal to the original, which matters for notes.
- **Gem interior** (Aether): refract the view into a virtual inner surface and evaluate 3D Voronoi there.
  It reads as a deep crystal in stereo with no loop.
- **Glass**: sample a screen copy at the clip position of `vertex + normal·k`. That is refraction without
  ray maths, which grows with curvature.

### Notes, debris and sabers (template `custom_note`)

- Vivify writes `_Color`, `_Cutout` and `_CutPlane` per note through property blocks. Declare them as
  instanced properties, or every note reads the material default.
- Live note: `clip(noise(localPos) - _Cutout)` with a bright edge where the clip value is small: a burn
  rather than a fade. Debris: clip by the signed distance to `_CutPlane` minus `_Cutout·k`, so the cut half
  is eaten from the slice face.
- `Cull Off`: a dissolving or cut note shows its inside.
- Keep the body readable: a dark core with a coloured fresnel rim works on any scene, and the two hands
  stay distinct (`presentation.note_colors`).
- Saber trails take `_Color` plus vertex colours; use `ColorMask RGB` so a trail never adds bloom.

### Full-screen passes (template `world_blit`)

- **World-anchored effects:** rebuild the view direction per eye and place rings, grain and tints on it.
- **Blur and warp shocks** (`you`'s drop): a separable blur split into two passes (two looks with `pass`
  and `priority`) plus a noise displacement weighted towards the screen edge. Each hit sets strength
  1 → 0 → slightly below 0. Warp the periphery, not the lane.
- **Peripheral colour** (`you`'s edge highlights): smear the centre's colours only into the left and right
  edges, which suit the wide peripheral field of a headset.
- **Glitch and VHS**: split channels, shift rows by a hashed seed, and step the seed with `easeStep` points
  so the glitch jumps between states on the stutters. Keep them short and away from dense note passages.
- **Freeze frames**: a Blit with only a `destination` copies the screen into a screen texture. A later
  shader shows it in short repeated blits on the rhythm (3 BIG SHOTS' gun shots).
- **Note-only effects**: a second camera renders only a track of notes into a texture, and a Blit uses it
  as a mask (Breezer's static notes, 3 BIG SHOTS' wiggle). Destroy the camera with the section.
- Cost: every Blit reads and writes the whole stereo frame. Fold effects into one shader, stack at most two
  to four, and add an early return when the effect's strength is 0.

### Fetched geometry and photo skies

EXSII restyles every real model it uses (cel shading, fog, glitch), and so should we. `assets fetch` brings in
CC0 geometry and panoramas (workflow in the skill, step 3). What makes them belong to the map:

- **Restyle, never stock.** Put fetched models on `stage_surface` (banded fake light, rim on silhouettes,
  distance fog to the palette, far dissolve). `_VertexColor 1` with grey `_Base`/`_Lit` shows a Kenney
  model's own palette; tint `_Base`/`_Lit` towards the concept to pull it into the map's colours.
- **Silhouettes over detail.** Low-poly packs (Kenney) read clearly at headset resolution. Scanned models
  (Poly Haven) are reduced by vertex clustering to the budget: the shape survives, the UV detail does not,
  so shade them in object or world space.
- **Placement:** keep models out of the note corridor (x ±1.2 m) and use them for the mid layer (10-60 m),
  where they carry motion on hits (the travelling `_Wave`/`_Pulse` bulge).
- **Photo skies** (`sm_sky_panorama`): lower `_Exposure` (about -0.5 to -2) and use `_LaneDim` so the photo
  never competes with the notes; a slow `_Rotation` drift gives life without motion sickness. A photo sky
  with stylised low-poly scenery makes a strong, cheap contrast; keep the palette consistent with `_Tint`.

Verified in the game (2026-09-23): a Poly Haven panorama as skybox, Kenney pines, cliffs and statues with
their own colours (after the sRGB correction), and decimated Poly Haven rocks all render, and Kenney models
face the player unrotated.

### Stencil portals

A mask mesh with `ColorMask 0` writes a stencil reference, and content tests against it. This gives
windows into another scene, or keeps particles out of a black hole. Aether's shattering portal explodes
the mask per triangle.

## 6. Cost in VR

- Frame time is 11.1 ms at 90 Hz and 6.9 ms at 144 Hz, and the game uses part of it. Modern headsets
  render 4 million or more pixels per eye, so full-screen work costs double.
- Cost levers: pixels covered × per-pixel work. Keep expensive shaders small on screen. Draw skies after
  opaques and push them to the far plane (the sky template does), so hidden pixels are never shaded.
- Loops: literal bounds with an early `break`, `[loop]` for marches, `[unroll]` for short octave loops.
  Expose step counts as properties.
- Branch on uniforms to skip whole blocks (the blit template's early return).
- Aliasing reads as sparkle in a headset. Anti-alias every hard threshold with `fwidth`, clamp line and star
  widths to at least one pixel and fade them instead of shrinking them, and fade out pattern frequencies
  above about half a cycle per pixel.
- Transparent layers near the face are the worst case for overdraw. Keep large transparent surfaces few,
  and never close to the camera.

## 7. Verification

1. `assets lint` for macros, loop and texture budgets, property values.
2. `assets build` compiles every shader in Unity. A shader error names your file and line.
3. `game capture` with a `--probe` over the busiest passage. Read full-resolution frames, not only the
   contact sheet, and check:
   - both halves of the idea are visible, and the lane stays calm;
   - nothing large brightens on hits (measure brightness of the floor or the sky across the probe frames
     when in doubt, as in the 2026-09-23 floor finding);
   - raymarched and window effects look deep, not pasted on;
   - the sky actually renders (see below).
4. Desktop captures show one eye. They cannot show stereo errors, comfort or frame rate; say so.

Verified in the game on 2026-09-23 with the templates (two captures of a test show, game log clean):

- The raymarched sculpture, the stage surface with hologram lines and the travelling bulge, the
  world-anchored blit ring (it travels outward from the lane axis over the probe frames), the custom note
  skin, the skybox (with the clear flag) and the sky sphere all render.
- A floor writing rim alpha turned near-white for four frames each time an additive object pulsed (floor
  brightness 124 → 234 of 255). With the floor at alpha 0 it stayed between 81 and 86 through the same
  probe. `frames summary` reported it as a flash and as `visual_change_unaligned` (a change with no
  event under it); treat either finding on a section with large surfaces as this bug first.
- A horizontal raymarched torus above the player read as a flat ellipse; turned to face the track, it
  reads as a ring.

Still unverified: whether notes and walls write the depth texture, whether `Color` properties sent by
`SetMaterialProperty` are converted to linear, and whether RGB above 1 survives into the bloom.

## 8. Bug checklist

1. Missing stereo macros: the shader shows in the left eye only.
2. `return float4(col, 1)` on a surface: it blooms white.
3. Alpha on a large surface: it flashes whenever the bloom changes.
4. A Blit that drops `src.a`.
5. `tex2D` on a screen texture instead of the screen-space macros.
6. Fragment code using `_WorldSpaceCameraPos` before `UNITY_SETUP_STEREO_EYE_INDEX_POST_VERTEX`.
7. Reading the depth texture without enabling it, or on objects without a ShadowCaster pass.
8. Screen-UV noise, grain or centres: the eyes disagree and the image shimmers.
9. Unfiltered edges and sub-pixel stars: they sparkle.
10. Beat sync from `_Time`: it drifts from the song and has no evidence under it.
11. Large-area brightness pulses above 3 Hz.
12. Cosine-palette presets passed as `Color`: they come out washed out and too bright.

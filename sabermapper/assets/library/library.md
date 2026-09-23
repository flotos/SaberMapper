# SaberMapper asset library

Generated from `library.json` (`sabermapper assets library --write-md`); edit the JSON, not this file.
Entries are written for an agent that composes without seeing the render. Safe ranges are the values to
use without extra frame review; the shader's own `Range()` is the hard limit that `assets lint` enforces.
Beat Saber's bloom reads the alpha channel, so `_Glow` sets how much a surface blooms. `post_process`
materials are applied with Vivify `Blit`, skyboxes with `SetRenderingSettings` (`renderSettings.skybox`)
together with the main camera clearing to the skybox (setup `camera_properties` `clearFlags: "Skybox"`;
the game clears to black otherwise), surface and particle materials inside prefabs. Large surfaces keep
`_Glow` at 0: a big area that writes alpha flashes whenever the bloom changes.

## Shaders

### `sm_color_grade`: SaberMapper/Post/ColorGrade

- **Kinds:** post_process
- **Intent:** Section-wide mood: exposure, contrast, saturation and a two-tint split-tone.
- **Looks like:** The whole view keeps its shapes but changes temperature: shadows lean towards one tint, highlights towards another. Low saturation reads as washed-out memory, high contrast as harsh daylight.

| Property | Type | Default | Safe range | Meaning |
|---|---|---|---|---|
| `_Exposure` | Float | `0` | -1.5 to 1.5 | Brightness in photographic stops |
| `_Contrast` | Float | `1` | 0.5 to 1.6 | Distance from mid grey; below 1 flattens |
| `_Saturation` | Float | `1` | 0 to 1.8 | 0 is monochrome |
| `_ShadowTint` | Color | `[0.5, 0.5, 0.5, 1]` | any | Grey (0.5) is neutral; push a channel above 0.5 to tint the shadows |
| `_HighlightTint` | Color | `[0.5, 0.5, 0.5, 1]` | any | Grey (0.5) is neutral; tint for the highlights |
| `_Balance` | Float | `0` | -1 to 1 | Moves the shadow/highlight pivot |
| `_Mix` | Float | `1` | 0 to 1 | Blend with the untouched image; animate for fades |

### `sm_chromatic_split`: SaberMapper/Post/ChromaticSplit

- **Kinds:** post_process
- **Intent:** Impact accents: red and blue fringes pulled apart on a hit, then relaxed.
- **Looks like:** Edges grow red and blue ghosts that separate outward from the centre (radial) or along one direction. Small amounts look like lens fringing; large amounts look like a glitch.

| Property | Type | Default | Safe range | Meaning |
|---|---|---|---|---|
| `_Amount` | Float | `0.006` | 0 to 0.02 | Offset of the red and blue copies in screen UV |
| `_Angle` | Float | `0` | 0 to 360 | Direction of the split when _Radial < 1 |
| `_Radial` | Float | `1` | 0 to 1 | 1 splits outward from _Center, 0 along _Angle |
| `_Center` | Vector | `[0.5, 0.5, 0, 0]` | any | Radial centre in screen UV (xy) |

### `sm_vignette`: SaberMapper/Post/Vignette

- **Kinds:** post_process
- **Intent:** Focus and tension: close the frame in during quiet or ominous passages.
- **Looks like:** The screen edges darken (or take the edge colour) in a soft oval, drawing the eye to the note corridor. Strong settings feel claustrophobic.

| Property | Type | Default | Safe range | Meaning |
|---|---|---|---|---|
| `_Strength` | Float | `0.4` | 0 to 0.85 | Opacity of the edge colour |
| `_Radius` | Float | `0.75` | 0.45 to 1.3 | Where the darkening reaches full strength |
| `_Softness` | Float | `0.45` | 0.1 to 1 | Width of the transition |
| `_Color` | Color | `[0, 0, 0, 1]` | any | Edge colour; alpha also dims bloom at the edge |

### `sm_glow`: SaberMapper/Post/Glow

- **Kinds:** post_process
- **Intent:** Euphoric lift: bright things bleed light during choruses and drops.
- **Looks like:** Bright areas get a soft halo that spreads a little around them; the rest of the image is unchanged. High intensity makes lights look hot and dreamy.

| Property | Type | Default | Safe range | Meaning |
|---|---|---|---|---|
| `_Threshold` | Float | `0.8` | 0.3 to 1.5 | Brightness above which pixels glow |
| `_Intensity` | Float | `1` | 0 to 2.5 | Strength of the added halo |
| `_Radius` | Float | `0.012` | 0.002 to 0.03 | Halo spread in screen UV |
| `_Tint` | Color | `[1, 1, 1, 1]` | any | Colour multiplied into the halo |

### `sm_pixelate`: SaberMapper/Post/Pixelate

- **Kinds:** post_process
- **Intent:** Digital or retro breakdowns; degrade the image as a transition.
- **Looks like:** The view turns into square blocks; fewer cells means chunkier blocks. Optional posterize reduces the colour steps like an old console.

| Property | Type | Default | Safe range | Meaning |
|---|---|---|---|---|
| `_Cells` | Float | `120` | 24 to 480 | Blocks across the screen width; below ~40 notes become hard to read |
| `_Levels` | Float | `0` | 0 to 16 | Colour steps per channel; 0 or 1 disables posterize |
| `_Mix` | Float | `1` | 0 to 1 | Blend with the untouched image |

### `sm_kaleidoscope`: SaberMapper/Post/Kaleidoscope

- **Kinds:** post_process
- **Intent:** Psychedelic set-pieces in sparse passages; never during dense note streams.
- **Looks like:** The screen is cut into mirrored wedges around a centre, like a kaleidoscope; rotating it spins the pattern. It duplicates notes visually, so keep it for breaks.

| Property | Type | Default | Safe range | Meaning |
|---|---|---|---|---|
| `_Segments` | Float | `6` | 3 to 12 | Number of mirror wedges (integer part used) |
| `_Rotation` | Float | `0` | 0 to 360 | Spin of the pattern in degrees |
| `_Zoom` | Float | `1` | 0.5 to 2 | Scale of the mirrored image |
| `_Center` | Vector | `[0.5, 0.5, 0, 0]` | any | Fold centre in screen UV (xy) |
| `_Mix` | Float | `1` | 0 to 0.7 | Blend with the untouched image; keep below 0.7 when notes are present |

### `sm_threshold_dissolve`: SaberMapper/Post/ThresholdDissolve

- **Kinds:** post_process
- **Intent:** Stark graphic sections: the image becomes two flat colours, revealed through a burning dissolve.
- **Looks like:** Everything brighter than the threshold becomes the light colour and the rest the dark colour, like a screen print. _Progress eats through the image in noisy patches with a glowing edge.

| Property | Type | Default | Safe range | Meaning |
|---|---|---|---|---|
| `_Threshold` | Float | `0.5` | 0.15 to 0.85 | Luminance split point |
| `_DarkColor` | Color | `[0, 0, 0, 1]` | any | Colour for dark pixels |
| `_LightColor` | Color | `[1, 1, 1, 1]` | any | Colour for bright pixels |
| `_Progress` | Float | `1` | 0 to 1 | 0 original image, 1 fully two-tone |
| `_NoiseScale` | Float | `40` | 4 to 120 | Dissolve patch count across the screen |
| `_EdgeWidth` | Float | `0.04` | 0 to 0.12 | Width of the burning edge |
| `_EdgeColor` | Color | `[1, 0.4, 0.1, 1]` | any | Colour of the burning edge |

### `sm_scanline_vhs`: SaberMapper/Post/ScanlineVHS

- **Kinds:** post_process
- **Intent:** Nostalgia, tape, surveillance: analogue texture over the whole view.
- **Looks like:** Thin dark horizontal lines, rows that wobble sideways, colour bleeding to the left and right, and fine grain. It reads as an old monitor or a worn tape.

| Property | Type | Default | Safe range | Meaning |
|---|---|---|---|---|
| `_LineCount` | Float | `360` | 120 to 720 | Scanlines over the screen height |
| `_LineStrength` | Float | `0.25` | 0 to 0.5 | Darkness of the lines |
| `_Jitter` | Float | `0.004` | 0 to 0.012 | Sideways row wobble in UV |
| `_JitterSpeed` | Float | `8` | 0 to 20 | Wobble changes per second |
| `_Bleed` | Float | `0.003` | 0 to 0.01 | Red/blue smear in UV |
| `_Noise` | Float | `0.06` | 0 to 0.2 | Grain amount |

### `sm_radial_blur`: SaberMapper/Post/RadialBlur

- **Kinds:** post_process
- **Intent:** Speed and impact: a zoom streak on drops, risers or the moment of a reveal.
- **Looks like:** The image streaks towards a centre point as if the camera lunged forward; the area around the centre stays sharp.

| Property | Type | Default | Safe range | Meaning |
|---|---|---|---|---|
| `_Strength` | Float | `0.1` | 0 to 0.3 | Streak length as a fraction of the distance to the centre |
| `_Center` | Vector | `[0.5, 0.5, 0, 0]` | any | Streak centre in screen UV (xy) |
| `_Falloff` | Float | `0.1` | 0 to 0.6 | Radius around the centre kept sharp |

### `sm_sky_gradient`: SaberMapper/Sky/Gradient

- **Kinds:** skybox, material
- **Intent:** Backdrop colour that carries the section palette; cross-fade between numbered copies at section boundaries.
- **Looks like:** The sky fades from the zenith colour overhead through a glowing horizon band to the nadir colour below, like dusk over a flat sea.

| Property | Type | Default | Safe range | Meaning |
|---|---|---|---|---|
| `_TopColor` | Color | `[0.05, 0.02, 0.15, 1]` | any | Colour straight up |
| `_BottomColor` | Color | `[0, 0, 0, 1]` | any | Colour straight down |
| `_HorizonColor` | Color | `[0.6, 0.2, 0.5, 1]` | any | Colour of the horizon band |
| `_HorizonWidth` | Float | `0.15` | 0.03 to 0.6 | Thickness of the band |
| `_HorizonHeight` | Float | `0` | -0.5 to 0.5 | Band height; negative lowers it |
| `_Exponent` | Float | `1` | 0.3 to 3 | Curve of the fade away from the horizon |
| `_Glow` | Float | `0` | 0 to 0.3 | Alpha written for Beat Saber's bloom; keep low for a sky |

### `sm_sky_nebula`: SaberMapper/Sky/Nebula

- **Kinds:** skybox, material
- **Intent:** Cosmic, dreamy or vast sections; slow drift under ambient passages.
- **Looks like:** Dark space with two-coloured cloudy nebula that slowly drifts, and sparse single-pixel stars in the gaps.

| Property | Type | Default | Safe range | Meaning |
|---|---|---|---|---|
| `_BaseColor` | Color | `[0.01, 0, 0.03, 1]` | any | Empty space colour |
| `_ColorA` | Color | `[0.5, 0.1, 0.6, 1]` | any | First cloud colour |
| `_ColorB` | Color | `[0.1, 0.4, 0.8, 1]` | any | Second cloud colour |
| `_Density` | Float | `0.8` | 0 to 1.5 | How much of the sky is cloud |
| `_Scale` | Float | `2` | 0.8 to 5 | Cloud size; larger is smaller clouds |
| `_Octaves` | Float | `4` | 2 to 5 | Detail layers; each adds cost |
| `_Drift` | Float | `0.02` | 0 to 0.08 | Cloud drift speed |
| `_Stars` | Float | `0.3` | 0 to 0.8 | Star density |
| `_Glow` | Float | `0` | 0 to 0.3 | Alpha written for Beat Saber's bloom |

### `sm_sky_panorama`: SaberMapper/Sky/Panorama

- **Kinds:** skybox, material
- **Intent:** A real place or painted world as the backdrop: a fetched sky panorama (assets fetch get --kind sky) behind the whole map or one section.
- **Looks like:** The equirectangular photo or painting surrounds the player at infinity, like standing inside it. Exposure and tint push it into the palette, rotation turns the world slowly, and a softly darker cone straight ahead keeps the notes readable.

| Property | Type | Default | Safe range | Meaning |
|---|---|---|---|---|
| `_Tex` | Texture | `"black"` | any | The panorama texture asset (2:1 equirectangular, srgb, wrap clamp) |
| `_Tint` | Color | `[1, 1, 1, 1]` | any | Multiplied into the image; use a palette colour to pull the photo into the concept |
| `_Exposure` | Float | `0` | -3 to 1 | Brightness in stops; photos usually want -1 to -2 behind notes |
| `_Saturation` | Float | `1` | 0 to 1.5 | 0 is monochrome |
| `_Rotation` | Float | `0` | 0 to 360 | Turns the world around the up axis; animate very slowly (under 1 degree per second) |
| `_Horizon` | Float | `0` | -0.3 to 0.3 | Moves the horizon up (positive) or down |
| `_LaneDim` | Float | `0.35` | 0 to 0.8 | How much darker the cone straight ahead is |
| `_LaneWidth` | Float | `28` | 15 to 45 | Half-angle of that cone in degrees |
| `_Glow` | Float | `0` | 0 to 0.1 | Alpha written for Beat Saber's bloom; keep 0 for a sky |

### `sm_unlit_emissive`: SaberMapper/Surface/UnlitEmissive

- **Kinds:** material
- **Intent:** Default surface for scene prefabs: rings, pillars, shards and tunnel segments that glow in the palette.
- **Looks like:** A flat self-lit colour, optionally with a bright rim where the surface turns away from the viewer and light bands scrolling along it. Looks like neon or light panels.

| Property | Type | Default | Safe range | Meaning |
|---|---|---|---|---|
| `_Color` | Color | `[0.2, 0.6, 1, 1]` | any | Base emission colour |
| `_Intensity` | Float | `1` | 0 to 4 | Emission multiplier |
| `_RimColor` | Color | `[1, 1, 1, 1]` | any | Rim colour |
| `_RimPower` | Float | `3` | 1 to 6 | Rim sharpness |
| `_RimStrength` | Float | `0` | 0 to 3 | Rim brightness; 0 disables |
| `_BandCount` | Float | `0` | 0 to 32 | Scrolling light bands along UV v; 0 disables |
| `_BandSpeed` | Float | `1` | -4 to 4 | Band scroll speed; flashing above ~3 bands/s is a photosensitivity risk |
| `_Glow` | Float | `0.5` | 0 to 1 | Alpha written for Beat Saber's bloom |

### `sm_particle_additive`: SaberMapper/Particles/Additive

- **Kinds:** material
- **Intent:** Particle renderer material: sparks, dust, embers and star fields.
- **Looks like:** Soft round glowing dots that add light where they overlap; colour comes from the particle system times the tint.

| Property | Type | Default | Safe range | Meaning |
|---|---|---|---|---|
| `_Color` | Color | `[1, 1, 1, 1]` | any | Tint multiplied with particle colour |
| `_Intensity` | Float | `1.5` | 0 to 4 | Brightness |
| `_Softness` | Float | `0.6` | 0.1 to 1 | Edge softness of each dot |
| `_Glow` | Float | `0.3` | 0 to 1 | Alpha written for Beat Saber's bloom |

## Mesh generators

Built into the forge (`vivify-src/Assets/SaberMapper/Editor/ForgeMeshes.cs`). Use as
`"mesh": {"generator": NAME, "params": {...}}`; `assets lint` checks the triangle count.

| Generator | Params (defaults) | Triangles | Shape |
|---|---|---|---|
| `quad` | `{"width": 1, "height": 1}` | `2` | Flat rectangle in the XY plane facing -Z (towards the player). |
| `plane` | `{"width": 10, "depth": 10, "segments_x": 1, "segments_z": 1}` | `2*segments_x*segments_z` | Horizontal grid in the XZ plane, facing up. |
| `cube` | `{"size": [1, 1, 1]}` | `12` | Box with flat faces and per-face UVs. |
| `uv_sphere` | `{"radius": 0.5, "segments": 24, "rings": 16}` | `2*segments*rings` | Latitude/longitude sphere (pole rows included). |
| `ring` | `{"inner_radius": 0.8, "outer_radius": 1, "segments": 64}` | `2*segments` | Flat annulus in the XY plane, like a halo facing the player. |
| `torus` | `{"radius": 1, "thickness": 0.05, "segments": 64, "sides": 8}` | `2*segments*sides` | Donut around the Z axis; thin ones read as neon rings. |
| `tube` | `{"radius": 2, "length": 4, "segments": 32, "length_segments": 1, "inside": true}` | `2*segments*length_segments` | Open cylinder along +Z; inside=true faces inward, making a tunnel segment around the player. |
| `cone` | `{"radius": 0.5, "height": 1, "segments": 24}` | `2*segments` | Cone along +Y with a closed base. |
| `shard` | `{"length": 1, "width": 0.25, "sides": 5, "seed": 1}` | `2*sides` | Double pyramid with jittered facets, like a crystal splinter. |

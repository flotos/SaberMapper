# Shader cookbook

Small HLSL functions for tier-2 shaders, in the style of the templates in `templates/` (which compile in
the forge and render in the game). Paste what you need above `vert`. Why each one exists is in
[shader-craft.md](shader-craft.md). Keep loops at literal bounds of 64 or fewer (`assets lint`).

## Skeletons

Start from a template rather than from scratch:

| Template | Kind | Use |
|---|---|---|
| `templates/raymarch_volume.shader` | material on a `cube` generator (size 1) | SDF set-pieces, light sculptures |
| `templates/sky_sphere.shader` | skybox, or material on a large `uv_sphere` | procedural skies |
| `templates/world_blit.shader` | post_process | full-screen effects anchored to world directions |
| `templates/custom_note.shader` | material in a note or debris prefab (`skin`) | notes, arrows, debris |
| `templates/stage_surface.shader` | material on scene meshes | restyling generator or fetched geometry |

Copy the template into `<project>/assets/shaders/`, rename the `Shader "..."` path, and reference it with
`"shader": {"source": "shaders/x.shader"}`, `"tier": 2` and a provenance description.

## Hashes and noise

```hlsl
// Hash without sine: stable across GPUs and far from the origin.
float hash13(float3 p)
{
    p = frac(p * 0.1031);
    p += dot(p, p.zyx + 31.32);
    return frac((p.x + p.y) * p.z);
}

float hash11(float x) { return hash13(float3(x, x * 1.37, x * 0.71)); }   // seeds, IDs, per-hit variety

// Value noise in 3D, smooth, in [0, 1].
float vnoise(float3 x)
{
    float3 i = floor(x);
    float3 f = frac(x);
    f = f * f * (3.0 - 2.0 * f);
    return lerp(lerp(lerp(hash13(i), hash13(i + float3(1, 0, 0)), f.x),
                     lerp(hash13(i + float3(0, 1, 0)), hash13(i + float3(1, 1, 0)), f.x), f.y),
                lerp(lerp(hash13(i + float3(0, 0, 1)), hash13(i + float3(1, 0, 1)), f.x),
                     lerp(hash13(i + float3(0, 1, 1)), hash13(i + 1.0), f.x), f.y), f.z);
}

// Four octaves, each rotated so grid artefacts never line up.
float fbm(float3 p)
{
    const float3x3 r = float3x3(0.00, 0.80, 0.60, -0.80, 0.36, -0.48, -0.60, -0.48, 0.64);
    float s = 0.0, a = 0.5;
    [unroll] for (int k = 0; k < 4; k++) { s += a * vnoise(p); p = mul(r, p) * 2.02; a *= 0.5; }
    return s;
}

// Domain warp: marble, ink, nebula. `warp` is the build handle (0 calm, 4-6 churning).
float warped(float3 p, float warp, out float3 q)
{
    q = float3(fbm(p), fbm(p + float3(5.2, 1.3, 2.8)), fbm(p + float3(1.7, 9.2, 4.1)));
    return fbm(p + warp * q);
}

// Ridged noise: veins, lightning, energy lines on dark ground.
float ridged(float3 p) { float n = 1.0 - abs(vnoise(p) * 2.0 - 1.0); return n * n; }
```

Animate noise by moving its domain (`p + float3(0, 0, _Flow)`), not by slicing it with time.

## Colour

```hlsl
// Cosine palette. Pass a..d as Vector properties (gamma-space presets), convert once at the end.
float3 palette(float t, float3 a, float3 b, float3 c, float3 d)
{
    return GammaToLinearSpace(saturate(a + b * cos(UNITY_TWO_PI * (c * t + d))));
}
// Presets (a, b, c, d): rainbow (.5,.5,.5)(.5,.5,.5)(1,1,1)(0,.33,.67);
// warm (.5,.5,.5)(.5,.5,.5)(1,1,1)(0,.1,.2); ice (.5,.5,.5)(.5,.5,.5)(1,1,1)(.55,.65,.8);
// duotone (.8,.5,.4)(.2,.4,.2)(2,1,1)(0,.25,.25).

float3 hsv2rgb(float3 c)
{
    float3 k = saturate(abs(fmod(c.x * 6.0 + float3(0, 4, 2), 6.0) - 3.0) - 1.0);
    k = k * k * (3.0 - 2.0 * k);
    return c.z * lerp(1.0, k, c.y);
}

// Hotter than white without HDR: whiten the core, and let alpha carry the glow.
float3 hot(float3 col, float heat) { return lerp(col, 1.0, heat * heat * heat); }
```

## Anti-aliasing

```hlsl
float aaStep(float edge, float x) { float w = fwidth(x); return smoothstep(edge - w, edge + w, x); }

// A line of half-width h around d = 0; never thinner than a pixel, dimmed instead of vanishing.
float aaLine(float d, float h)
{
    float w = fwidth(d);
    float hw = max(h, w);
    return (1.0 - smoothstep(hw - w, hw + w, abs(d))) * (h / hw);
}

// Fade a pattern out before it aliases (frequency above half a cycle per pixel).
float bandLimit(float coordinate) { return 1.0 - smoothstep(0.2, 0.5, fwidth(coordinate)); }
```

## Shapes on quads (glow sprites)

`uv` is the quad UV mapped to [-1, 1]: `float2 uv = i.uv * 2.0 - 1.0;`.

```hlsl
float ring(float2 uv, float radius, float sharpness) { return pow(saturate(1.0 - abs(length(uv) - radius)), sharpness); }
float flareCross(float2 uv, float k) { return pow(saturate(1.0 - abs(uv.x * uv.y) * 8.0), k) * saturate(1.0 - length(uv)); }
float core(float2 uv, float k) { return pow(saturate(1.0 - length(uv)), k); }
float superellipse(float2 uv, float b) { return pow(abs(uv.x), b) + pow(abs(uv.y), b); }   // 1 on the outline; b < 1 is a star
```

Drive `radius` with a `_Progress` 0..1 per hit and the brightness with an envelope. Additive
(`Blend One One, Zero One` keeps the bloom), `ZWrite Off`, `Cull Off`, queue Transparent.

## Polar and kaleidoscope

```hlsl
float2x2 rot2(float a) { float s, c; sincos(a, s, c); return float2x2(c, -s, s, c); }

// Fold the plane into `segments` mirrored wedges (integer; change it per hit for a new symmetry).
float2 kaleido(float2 p, float segments)
{
    float sector = UNITY_TWO_PI / max(floor(segments), 1.0);
    float a = atan2(p.y, p.x);
    a = abs(a - sector * round(a / sector));
    return length(p) * float2(cos(a), sin(a));
}

// Tunnel bands around the track axis: spiralling with depth z.
float tunnelBands(float3 p, float count, float twist, float phase)
{
    float a = atan2(p.y, p.x);
    return 0.5 + 0.5 * sin(a * count + p.z * twist + phase);
}
```

## Rays, directions and depth

```hlsl
// Per-eye ray in object space (fragment, after UNITY_SETUP_STEREO_EYE_INDEX_POST_VERTEX).
void objectRay(float3 objPos, out float3 ro, out float3 rd)
{
    ro = mul(unity_WorldToObject, float4(_WorldSpaceCameraPos, 1)).xyz;
    rd = normalize(objPos - ro);
}

// Entry and exit distances of a ray through the unit cube [-0.5, 0.5]^3.
float2 unitBox(float3 ro, float3 rd)
{
    float3 inv = 1.0 / rd;
    float3 t0 = (-0.5 - ro) * inv, t1 = (0.5 - ro) * inv;
    float3 lo = min(t0, t1), hi = max(t0, t1);
    return float2(max(max(lo.x, lo.y), lo.z), min(min(hi.x, hi.y), hi.z));
}

// In a Blit: the current eye's world view direction for a screen UV.
float3 viewDirection(float2 uv)
{
    float3 v = mul(unity_CameraInvProjection, float4(uv * 2.0 - 1.0, 0.0, 1.0)).xyz;
    v.z = -v.z;
    return normalize(mul((float3x3)unity_CameraToWorld, v));
}

// Window onto a far plane at world z = planeZ: shade the returned point instead of the surface.
float3 farPlanePoint(float3 worldPos, float planeZ)
{
    float3 v = normalize(worldPos - _WorldSpaceCameraPos);
    return worldPos + v * ((planeZ - worldPos.z) / max(v.z, 1e-3));
}

// Sky vertex pushed to the far plane: everything occludes it, hidden pixels are never shaded.
float4 toFarPlane(float4 clip)
{
#if defined(UNITY_REVERSED_Z)
    clip.z = 1e-6 * clip.w;
#else
    clip.z = clip.w * (1.0 - 1e-6);
#endif
    return clip;
}
```

Depth texture (the show must set `setup.camera_properties.depthTextureMode: ["Depth"]`):

```hlsl
UNITY_DECLARE_SCREENSPACE_TEXTURE(_CameraDepthTexture);
// vertex: o.screenPos = ComputeScreenPos(o.vertex); COMPUTE_EYEDEPTH(o.screenPos.z);
float softFade(float4 screenPos, float fadeDistance)
{
    float2 uv = UnityStereoTransformScreenSpaceTex(screenPos.xy / screenPos.w);
    float scene = LinearEyeDepth(UNITY_SAMPLE_SCREENSPACE_TEXTURE(_CameraDepthTexture, uv).r);
    return saturate((scene - screenPos.z) / fadeDistance);   // 0 where the surface meets geometry
}
```

## Signed distance functions

```hlsl
float sdSphere(float3 p, float r) { return length(p) - r; }
float sdBox(float3 p, float3 b) { float3 q = abs(p) - b; return length(max(q, 0.0)) + min(max(q.x, max(q.y, q.z)), 0.0); }
float sdTorusZ(float3 p, float R, float r) { return length(float2(length(p.xy) - R, p.z)) - r; }   // faces the track
float sdCapsule(float3 p, float3 a, float3 b, float r)
{
    float3 pa = p - a, ba = b - a;
    return length(pa - ba * saturate(dot(pa, ba) / dot(ba, ba))) - r;
}

float smin(float a, float b, float k)   // k in distance units; a kick handle (blobs merge on the beat)
{
    k = max(k, 1e-4) * 4.0;
    float h = max(k - abs(a - b), 0.0) / k;
    return min(a, b) - h * h * k * 0.25;
}

// Repeat space every s units, at most n cells either side.
float3 repeatLimited(float3 p, float s, float3 n) { return p - s * clamp(round(p / s), -n, n); }

// Surface normal from four SDF samples (define `map` first).
float3 sdfNormal(float3 p)
{
    const float2 k = float2(1, -1);
    const float h = 1e-3;
    return normalize(k.xyy * map(p + k.xyy * h) + k.yyx * map(p + k.yyx * h) +
                     k.yxy * map(p + k.yxy * h) + k.xxx * map(p + k.xxx * h));
}
```

March loop: `[loop] for (int k = 0; k < 64; k++)`, `break` on `k >= _Steps`, on a hit
(`d < 0.0015`) and on leaving the volume; step `0.8 · d` when the space is twisted or bent; accumulate
`exp(-d · falloff)` for glow and tonemap it with `1 - exp(-glow · gain)`.

## Surfaces

```hlsl
float fresnelRim(float3 n, float3 v, float power) { return pow(1.0 - saturate(dot(n, v)), power); }

// Banded light with anti-aliased steps; `bands` 0 keeps it smooth.
float toonLight(float3 n, float3 lightDir, float bands)
{
    float l = saturate(dot(n, normalize(lightDir)) * 0.5 + 0.5);
    if (bands < 1.0) return l;
    float s = l * bands;
    return (floor(s) + smoothstep(1.0 - fwidth(s), 1.0, frac(s))) / bands;
}

// Travelling bulge from a world origin: move geometry on hits instead of brightening it.
float3 bulge(float3 worldPos, float3 worldNormal, float3 origin, float travel, float height, float width)
{
    float x = (distance(worldPos, origin) - travel) / width;
    return worldPos + worldNormal * height * exp(-x * x);
}

// Distance and height fog combined.
float fogAmount(float dist, float height, float start, float end, float floorY, float thickness)
{
    float d = smoothstep(start, end, dist);
    float h = saturate((floorY + thickness - height) / max(thickness, 1e-3));
    return 1.0 - (1.0 - d) * (1.0 - h);
}
```

Dissolve (`reveal` 1 shown, 0 gone) with a burning edge that blooms:

```hlsl
float n = vnoise(objectPos * scale);
float front = n - (1.0 - reveal) * 1.05;
clip(front);
float edge = 1.0 - smoothstep(0.0, edgeWidth, front);
col = lerp(col, edgeColor, edge);
alpha = max(alpha, edge * edgeBloom);
```

## Notes

```hlsl
UNITY_INSTANCING_BUFFER_START(Props)
    UNITY_DEFINE_INSTANCED_PROP(float4, _Color)     // note colour, set by Vivify per note
    UNITY_DEFINE_INSTANCED_PROP(float, _Cutout)     // 0 visible -> 1 dissolved (debris: 0 just cut -> 1 gone)
    UNITY_DEFINE_INSTANCED_PROP(float4, _CutPlane)  // debris: xyz plane normal, w offset
UNITY_INSTANCING_BUFFER_END(Props)
// v2f carries UNITY_VERTEX_INPUT_INSTANCE_ID; vert calls UNITY_TRANSFER_INSTANCE_ID(v, o);
// frag calls UNITY_SETUP_INSTANCE_ID(i) and reads UNITY_ACCESS_INSTANCED_PROP(Props, _Cutout).
```

## Blend recipes

| Look | Render state | Alpha written |
|---|---|---|
| Opaque scenery | default (`Blend Off`), `ZWrite On` | 0 |
| Additive light that should not add glow | `Blend One One, Zero One`, `ZWrite Off` | ignored |
| Additive light that glows a little | `Blend One One`, `ZWrite Off` | small, capped |
| Premultiplied transparency | `Blend One OneMinusSrcAlpha`, `ZWrite Off` | coverage (it also changes the glow below) |
| Screen-like brightening | `Blend One OneMinusSrcColor`, `ZWrite Off` | 0 |
| Darkening shadow or card | `Blend Zero SrcColor` | unchanged |
| Must not touch the glow | `ColorMask RGB` | unchanged |
| Stencil mask | `ColorMask 0`, `ZWrite Off`, `Stencil { Ref 1 Comp Always Pass Replace }` | none |
| Blit | `ZTest Always ZWrite Off Cull Off` | `src.a` passed through |

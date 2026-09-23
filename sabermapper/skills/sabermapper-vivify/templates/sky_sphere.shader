// SaberMapper skill template: a direction-only procedural sky (domain-warped fbm nebula, anti-aliased
// stars with a few bright and many faint ones, horizon band) that keeps the note lane calm. Use it as a
// skybox material (setup rendering.renderSettings.skybox together with camera_properties
// clearFlags "Skybox"; without the clear flag the game clears to black) or on a large uv_sphere prefab:
// the vertex is pushed to the far plane, so every object occludes it and hidden pixels are never shaded.
// Everything is a function of the view direction, so both eyes see the same sky at infinity.
Shader "SaberMapper/Template/SkySphere"
{
    Properties
    {
        _Deep ("Empty-sky colour", Color) = (0.005, 0.004, 0.02, 1)
        _PalA ("Palette bias a (gamma space)", Vector) = (0.5, 0.5, 0.5, 0)
        _PalB ("Palette amplitude b", Vector) = (0.5, 0.5, 0.5, 0)
        _PalC ("Palette frequency c", Vector) = (1, 1, 1, 0)
        _PalD ("Palette phase d", Vector) = (0.0, 0.1, 0.2, 0)
        _Phase ("Palette drift (section handle)", Range(0, 1)) = 0
        _Density ("Nebula density", Range(0, 2)) = 0.9
        _Scale ("Nebula scale", Range(0.5, 6)) = 1.8
        _Warp ("Domain warp (build handle)", Range(0, 6)) = 2
        _Flow ("Flow offset (drift or lurch handle)", Float) = 0
        _Drift ("Idle drift speed", Range(0, 0.1)) = 0.01
        _StarScale ("Star grid cells", Range(20, 400)) = 140
        _StarDensity ("Fraction of cells with a star", Range(0, 1)) = 0.12
        _StarSize ("Star radius in cells", Range(0.02, 0.3)) = 0.08
        _Horizon ("Horizon glow", Range(0, 2)) = 0.5
        _LaneDim ("Dimming ahead, behind the notes", Range(0, 1)) = 0.6
        _LaneWidth ("Half-angle of the dimmed cone (degrees)", Range(5, 60)) = 28
        _Bloom ("Bloom (alpha) on stars", Range(0, 1)) = 0.3
    }
    SubShader
    {
        Tags { "Queue"="Geometry+450" "RenderType"="Background" "PreviewType"="Skybox" }
        Cull Off ZWrite Off ZTest LEqual
        Pass
        {
            CGPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #pragma multi_compile_instancing
            #include "UnityCG.cginc"

            struct appdata
            {
                float4 vertex : POSITION;
                UNITY_VERTEX_INPUT_INSTANCE_ID
            };

            struct v2f
            {
                float4 vertex : SV_POSITION;
                float3 dir : TEXCOORD0;
                UNITY_VERTEX_OUTPUT_STEREO
            };

            float4 _Deep, _PalA, _PalB, _PalC, _PalD;
            float _Phase, _Density, _Scale, _Warp, _Flow, _Drift;
            float _StarScale, _StarDensity, _StarSize, _Horizon, _LaneDim, _LaneWidth, _Bloom;

            float hash13(float3 p)
            {
                p = frac(p * 0.1031);
                p += dot(p, p.zyx + 31.32);
                return frac((p.x + p.y) * p.z);
            }

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

            float fbm(float3 p)
            {
                const float3x3 r = float3x3(0.00, 0.80, 0.60, -0.80, 0.36, -0.48, -0.60, -0.48, 0.64);
                float s = 0.0;
                float a = 0.5;
                [unroll]
                for (int k = 0; k < 4; k++)
                {
                    s += a * vnoise(p);
                    p = mul(r, p) * 2.02;
                    a *= 0.5;
                }
                return s;
            }

            float3 palette(float t)
            {
                float3 c = _PalA.xyz + _PalB.xyz * cos(UNITY_TWO_PI * (_PalC.xyz * t + _PalD.xyz));
                return GammaToLinearSpace(saturate(c));
            }

            v2f vert (appdata v)
            {
                v2f o;
                UNITY_SETUP_INSTANCE_ID(v);
                UNITY_INITIALIZE_OUTPUT(v2f, o);
                UNITY_INITIALIZE_VERTEX_OUTPUT_STEREO(o);
                o.vertex = UnityObjectToClipPos(v.vertex);
                #if defined(UNITY_REVERSED_Z)
                o.vertex.z = 1e-6 * o.vertex.w;
                #else
                o.vertex.z = o.vertex.w * (1.0 - 1e-6);
                #endif
                o.dir = mul((float3x3)unity_ObjectToWorld, v.vertex.xyz);
                return o;
            }

            float4 frag (v2f i) : SV_Target
            {
                UNITY_SETUP_STEREO_EYE_INDEX_POST_VERTEX(i);
                float3 d = normalize(i.dir);
                float3 p = d * _Scale + float3(0.0, 0.0, _Flow + _Time.y * _Drift);

                float3 q = float3(fbm(p), fbm(p + float3(5.2, 1.3, 2.8)), fbm(p + float3(1.7, 9.2, 4.1)));
                float n = fbm(p + _Warp * q);
                float clouds = saturate((n - 0.3) * 2.2 * _Density);
                float3 col = _Deep.rgb + palette(_Phase + length(q) * 0.6 + n * 0.4) * clouds * clouds;

                col += palette(_Phase + 0.5) * _Horizon * exp(-abs(d.y) * 14.0) * 0.25;

                float3 g = d * _StarScale;
                float3 id = floor(g);
                float3 offset = float3(hash13(id + 1.7), hash13(id + 3.1), hash13(id + 5.9)) - 0.5;
                float dist = length(frac(g) - 0.5 - offset * 0.5);
                float w = fwidth(dist);
                float radius = max(_StarSize, w);
                float star = (1.0 - smoothstep(radius - w, radius + w, dist)) * (_StarSize / radius);
                float magnitude = 0.08 + 1.4 * pow(hash13(id + 7.3), 8.0);
                star *= step(1.0 - _StarDensity, hash13(id)) * magnitude * (1.0 - clouds * 0.8);
                col += star;

                float ahead = acos(clamp(d.z, -1.0, 1.0)) * 57.29578;
                float lane = 1.0 - _LaneDim * (1.0 - smoothstep(_LaneWidth * 0.6, _LaneWidth, ahead));
                col *= lane;
                return float4(col, star * _Bloom * lane);
            }
            ENDCG
        }
    }
}

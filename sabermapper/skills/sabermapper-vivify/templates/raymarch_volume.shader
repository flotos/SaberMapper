// SaberMapper skill template: an SDF scene raymarched inside a unit cube proxy (cube generator, size 1).
// Each eye marches its own ray from _WorldSpaceCameraPos, so the sculpture has true stereo depth.
// Default mode is additive light (glowing twisted torus with orbiting beads); _Solid 1 with
// _SrcBlend One, _DstBlend Zero, _ZWrite On and render_queue 2000 turns it into an opaque object.
// Scale the prefab child uniformly: distances are measured in object space.
Shader "SaberMapper/Template/RaymarchVolume"
{
    Properties
    {
        _PalA ("Palette bias a (gamma space)", Vector) = (0.5, 0.5, 0.5, 0)
        _PalB ("Palette amplitude b", Vector) = (0.5, 0.5, 0.5, 0)
        _PalC ("Palette frequency c", Vector) = (1, 1, 1, 0)
        _PalD ("Palette phase d", Vector) = (0, 0.33, 0.67, 0)
        _Phase ("Palette drift (section handle)", Range(0, 1)) = 0
        _Spin ("Spin in turns (drift handle)", Float) = 0
        _Twist ("Twist per unit height", Range(-8, 8)) = 2
        _Beads ("Orbiting beads", Range(0, 12)) = 6
        _Blend ("Smooth-min radius (kick handle)", Range(0, 0.15)) = 0.03
        _Pulse ("Swell (kick handle)", Range(0, 1)) = 0
        _Steps ("March steps (cost)", Range(8, 64)) = 40
        _GlowFalloff ("Glow falloff", Range(4, 80)) = 28
        _GlowGain ("Glow gain", Range(0, 4)) = 1
        _Bloom ("Bloom (alpha) per unit of light", Range(0, 1)) = 0.2
        _Solid ("Opaque surfaces (0 = light only)", Range(0, 1)) = 0
        [Enum(UnityEngine.Rendering.BlendMode)] _SrcBlend ("Source blend", Float) = 1
        [Enum(UnityEngine.Rendering.BlendMode)] _DstBlend ("Destination blend", Float) = 1
        [Enum(Off, 0, On, 1)] _ZWrite ("Depth write", Float) = 0
    }
    SubShader
    {
        Tags { "Queue"="Transparent" "RenderType"="Transparent" }
        Blend [_SrcBlend] [_DstBlend]
        ZWrite [_ZWrite]
        Cull Front
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
                float3 objPos : TEXCOORD0;
                UNITY_VERTEX_OUTPUT_STEREO
            };

            float4 _PalA, _PalB, _PalC, _PalD;
            float _Phase, _Spin, _Twist, _Beads, _Blend, _Pulse, _Steps, _GlowFalloff, _GlowGain, _Bloom, _Solid;

            float3 palette(float t)
            {
                float3 c = _PalA.xyz + _PalB.xyz * cos(UNITY_TWO_PI * (_PalC.xyz * t + _PalD.xyz));
                return GammaToLinearSpace(saturate(c));
            }

            float2x2 rot(float a)
            {
                float s, c;
                sincos(a, s, c);
                return float2x2(c, -s, s, c);
            }

            float smin(float a, float b, float k)
            {
                k = max(k, 1e-4) * 4.0;
                float h = max(k - abs(a - b), 0.0) / k;
                return min(a, b) - h * h * k * 0.25;
            }

            // The ring faces the player (XY plane, axis along the track) and twists with depth.
            float map(float3 p)
            {
                p.xy = mul(rot(_Spin * UNITY_TWO_PI + p.z * _Twist), p.xy);
                float swell = 1.0 + 0.2 * _Pulse;
                float2 q = float2(length(p.xy) - 0.22 * swell, p.z);
                float d = length(q) - (0.025 + 0.02 * _Pulse);
                if (_Beads >= 1.0)
                {
                    float sector = UNITY_TWO_PI / floor(_Beads);
                    float a = atan2(p.y, p.x);
                    a -= sector * round(a / sector);
                    float r = length(p.xy);
                    float3 b = float3(r * cos(a) - 0.34 * swell, r * sin(a), p.z);
                    d = smin(d, length(b) - 0.045 * swell, _Blend);
                }
                return d;
            }

            float3 normalAt(float3 p)
            {
                const float2 k = float2(1, -1);
                const float h = 1e-3;
                return normalize(k.xyy * map(p + k.xyy * h) + k.yyx * map(p + k.yyx * h) +
                                 k.yxy * map(p + k.yxy * h) + k.xxx * map(p + k.xxx * h));
            }

            float2 unitBox(float3 ro, float3 rd)
            {
                float3 inv = 1.0 / rd;
                float3 t0 = (-0.5 - ro) * inv;
                float3 t1 = (0.5 - ro) * inv;
                float3 lo = min(t0, t1);
                float3 hi = max(t0, t1);
                return float2(max(max(lo.x, lo.y), lo.z), min(min(hi.x, hi.y), hi.z));
            }

            v2f vert (appdata v)
            {
                v2f o;
                UNITY_SETUP_INSTANCE_ID(v);
                UNITY_INITIALIZE_OUTPUT(v2f, o);
                UNITY_INITIALIZE_VERTEX_OUTPUT_STEREO(o);
                o.vertex = UnityObjectToClipPos(v.vertex);
                o.objPos = v.vertex.xyz;
                return o;
            }

            float4 frag (v2f i) : SV_Target
            {
                UNITY_SETUP_STEREO_EYE_INDEX_POST_VERTEX(i);
                float3 ro = mul(unity_WorldToObject, float4(_WorldSpaceCameraPos, 1)).xyz;
                float3 rd = normalize(i.objPos - ro);
                float2 span = unitBox(ro, rd);
                float t = max(span.x, 0.0);
                float glow = 0.0;
                bool hit = false;
                [loop]
                for (int k = 0; k < 64; k++)
                {
                    if (k >= (int)_Steps || t > span.y) break;
                    float d = map(ro + rd * t);
                    glow += exp(-max(d, 0.0) * _GlowFalloff);
                    if (d < 0.0015) { hit = true; break; }
                    t += d * 0.8;
                }
                float light = 1.0 - exp(-glow * _GlowGain * 0.06);
                float3 col = palette(_Phase + 0.3) * light;
                float bloom = light * _Bloom;
                if (hit)
                {
                    float3 p = ro + rd * t;
                    float3 n = normalAt(p);
                    float fres = pow(1.0 - saturate(dot(n, -rd)), 3.0);
                    float3 surf = palette(_Phase + p.y * 0.8 + fres * 0.25) * (0.3 + 0.7 * fres);
                    col = lerp(col + surf, surf, _Solid);
                    bloom = lerp(bloom + fres * _Bloom, fres * _Bloom, _Solid);
                }
                else if (_Solid > 0.5)
                {
                    discard;
                }
                return float4(col, bloom);
            }
            ENDCG
        }
    }
}

// SaberMapper skill template: a post-process (Vivify Blit) anchored to world directions instead of
// screen UV. Each pixel rebuilds its per-eye view direction, so the shockwave ring, the grain and the
// tint sit at the same place in both eyes (screen-UV patterns differ per eye and shimmer in VR).
// Animate _Progress 0 -> 1 per hit (the ring travels outward from the lane axis) and _Strength as the
// hit envelope; at _Strength 0 the pass returns the screen untouched. The incoming alpha (bloom) is kept.
Shader "SaberMapper/Template/WorldBlit"
{
    Properties
    {
        _MainTex ("Screen", 2D) = "white" {}
        _Axis ("Ring centre direction (world)", Vector) = (0, 0, 1, 0)
        _Strength ("Hit strength (kick handle)", Range(0, 1)) = 0
        _Progress ("Ring travel 0..1 (per hit)", Range(0, 1)) = 0
        _MaxAngle ("Ring end angle (degrees)", Range(10, 120)) = 70
        _Width ("Ring width (degrees)", Range(1, 30)) = 8
        _Split ("Colour split at the ring (UV)", Range(0, 0.02)) = 0.006
        _RingColor ("Ring light colour", Color) = (0.4, 0.7, 1, 1)
        _Tint ("Section tint", Color) = (1, 1, 1, 1)
        _TintMix ("Tint amount (section handle)", Range(0, 1)) = 0
        _Grain ("World-anchored grain", Range(0, 0.1)) = 0
    }
    SubShader
    {
        Tags { "RenderType"="Opaque" }
        Cull Off ZWrite Off ZTest Always
        Pass
        {
            CGPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #include "UnityCG.cginc"

            struct appdata
            {
                float4 vertex : POSITION;
                float2 uv : TEXCOORD0;
                UNITY_VERTEX_INPUT_INSTANCE_ID
            };

            struct v2f
            {
                float4 vertex : SV_POSITION;
                float2 uv : TEXCOORD0;
                UNITY_VERTEX_OUTPUT_STEREO
            };

            UNITY_DECLARE_SCREENSPACE_TEXTURE(_MainTex);
            float4 _Axis, _RingColor, _Tint;
            float _Strength, _Progress, _MaxAngle, _Width, _Split, _TintMix, _Grain;

            float hash13(float3 p)
            {
                p = frac(p * 0.1031);
                p += dot(p, p.zyx + 31.32);
                return frac((p.x + p.y) * p.z);
            }

            float3 viewDirection(float2 uv)
            {
                float3 v = mul(unity_CameraInvProjection, float4(uv * 2.0 - 1.0, 0.0, 1.0)).xyz;
                v.z = -v.z;
                return normalize(mul((float3x3)unity_CameraToWorld, v));
            }

            float3 screen(float2 uv)
            {
                return UNITY_SAMPLE_SCREENSPACE_TEXTURE(_MainTex, UnityStereoTransformScreenSpaceTex(uv)).rgb;
            }

            v2f vert (appdata v)
            {
                v2f o;
                UNITY_SETUP_INSTANCE_ID(v);
                UNITY_INITIALIZE_OUTPUT(v2f, o);
                UNITY_INITIALIZE_VERTEX_OUTPUT_STEREO(o);
                o.vertex = UnityObjectToClipPos(v.vertex);
                o.uv = v.uv;
                return o;
            }

            float4 frag (v2f i) : SV_Target
            {
                UNITY_SETUP_STEREO_EYE_INDEX_POST_VERTEX(i);
                float4 src = UNITY_SAMPLE_SCREENSPACE_TEXTURE(_MainTex, UnityStereoTransformScreenSpaceTex(i.uv));
                float3 col = lerp(src.rgb, src.rgb * _Tint.rgb, _TintMix);
                if (_Strength <= 0.0 && _Grain <= 0.0) return float4(col, src.a);

                float3 dir = viewDirection(i.uv);
                float angle = acos(clamp(dot(dir, normalize(_Axis.xyz)), -1.0, 1.0)) * 57.29578;
                float x = (angle - _Progress * _MaxAngle) / _Width;
                float ring = exp(-x * x) * _Strength * (1.0 - _Progress);

                float2 away = i.uv - 0.5;
                float2 shift = away * _Split * ring / max(length(away), 1e-3);
                float3 split = float3(screen(i.uv + shift).r, col.g, screen(i.uv - shift).b);
                col = lerp(col, split * lerp(1.0, _Tint.rgb, _TintMix), saturate(ring * 4.0));
                col += _RingColor.rgb * ring * 0.35;

                float grain = hash13(floor(dir * 900.0)) - 0.5;
                col += grain * _Grain;
                return float4(col, src.a + ring * 0.1);
            }
            ENDCG
        }
    }
}

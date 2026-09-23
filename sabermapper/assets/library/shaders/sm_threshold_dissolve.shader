// SaberMapper tier-1 library: two-colour threshold that dissolves in over the image through noise (Vivify Blit).
Shader "SaberMapper/Post/ThresholdDissolve"
{
    Properties
    {
        _MainTex ("Screen", 2D) = "white" {}
        _Threshold ("Luminance threshold", Range(0, 1)) = 0.5
        _DarkColor ("Dark colour", Color) = (0, 0, 0, 1)
        _LightColor ("Light colour", Color) = (1, 1, 1, 1)
        _Progress ("Dissolve progress", Range(0, 1)) = 1
        _NoiseScale ("Noise cell size (cells across)", Range(2, 200)) = 40
        _EdgeWidth ("Dissolve edge width", Range(0, 0.2)) = 0.04
        _EdgeColor ("Dissolve edge colour", Color) = (1, 0.4, 0.1, 1)
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
            float _Threshold, _Progress, _NoiseScale, _EdgeWidth;
            float4 _DarkColor, _LightColor, _EdgeColor;

            float hash21(float2 p)
            {
                p = frac(p * float2(123.34, 456.21));
                p += dot(p, p + 45.32);
                return frac(p.x * p.y);
            }

            float valueNoise(float2 p)
            {
                float2 c = floor(p);
                float2 f = frac(p);
                f = f * f * (3.0 - 2.0 * f);
                float a = hash21(c), b = hash21(c + float2(1, 0));
                float d = hash21(c + float2(0, 1)), e = hash21(c + float2(1, 1));
                return lerp(lerp(a, b, f.x), lerp(d, e, f.x), f.y);
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
                float luma = dot(src.rgb, float3(0.2126, 0.7152, 0.0722));
                float3 duo = luma > _Threshold ? _LightColor.rgb : _DarkColor.rgb;
                float n = valueNoise(i.uv * _NoiseScale);
                float p = _Progress * (1.0 + _EdgeWidth);
                float inside = step(n, p - _EdgeWidth);
                float edge = step(n, p) - inside;
                float3 c = lerp(src.rgb, duo, inside);
                c = lerp(c, _EdgeColor.rgb, edge);
                return float4(c, src.a);
            }
            ENDCG
        }
    }
}

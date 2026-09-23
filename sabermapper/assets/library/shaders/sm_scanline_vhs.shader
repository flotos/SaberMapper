// SaberMapper tier-1 library: scanlines, VHS line jitter and chroma bleed (Vivify Blit).
Shader "SaberMapper/Post/ScanlineVHS"
{
    Properties
    {
        _MainTex ("Screen", 2D) = "white" {}
        _LineCount ("Scanlines across height", Range(60, 1080)) = 360
        _LineStrength ("Scanline darkness", Range(0, 1)) = 0.25
        _Jitter ("Horizontal jitter (UV)", Range(0, 0.03)) = 0.004
        _JitterSpeed ("Jitter speed", Range(0, 30)) = 8
        _Bleed ("Chroma bleed (UV)", Range(0, 0.02)) = 0.003
        _Noise ("Grain", Range(0, 0.5)) = 0.06
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
            float _LineCount, _LineStrength, _Jitter, _JitterSpeed, _Bleed, _Noise;

            float hash11(float x)
            {
                return frac(sin(x * 127.1) * 43758.5453);
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
                float row = floor(i.uv.y * _LineCount);
                float t = floor(_Time.y * _JitterSpeed);
                float2 uv = i.uv + float2((hash11(row * 0.37 + t) - 0.5) * 2.0 * _Jitter, 0);
                float4 g = UNITY_SAMPLE_SCREENSPACE_TEXTURE(_MainTex, UnityStereoTransformScreenSpaceTex(uv));
                float r = UNITY_SAMPLE_SCREENSPACE_TEXTURE(_MainTex, UnityStereoTransformScreenSpaceTex(uv + float2(_Bleed, 0))).r;
                float b = UNITY_SAMPLE_SCREENSPACE_TEXTURE(_MainTex, UnityStereoTransformScreenSpaceTex(uv - float2(_Bleed, 0))).b;
                float3 c = float3(r, g.g, b);
                c *= 1.0 - _LineStrength * (0.5 + 0.5 * cos(i.uv.y * _LineCount * UNITY_TWO_PI));
                c += (hash11(dot(i.uv, float2(12.9898, 78.233)) + _Time.y) - 0.5) * _Noise;
                return float4(max(c, 0), g.a);
            }
            ENDCG
        }
    }
}

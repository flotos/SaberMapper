// SaberMapper tier-1 library: bloom-like glow from bright areas, 12-tap ring blur added back (Vivify Blit).
Shader "SaberMapper/Post/Glow"
{
    Properties
    {
        _MainTex ("Screen", 2D) = "white" {}
        _Threshold ("Brightness threshold", Range(0, 2)) = 0.8
        _Intensity ("Glow intensity", Range(0, 4)) = 1
        _Radius ("Blur radius (UV)", Range(0, 0.05)) = 0.012
        _Tint ("Glow tint", Color) = (1, 1, 1, 1)
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
            float _Threshold, _Intensity, _Radius;
            float4 _Tint;

            float3 bright(float2 uv)
            {
                float3 c = UNITY_SAMPLE_SCREENSPACE_TEXTURE(_MainTex, uv).rgb;
                float l = max(c.r, max(c.g, c.b));
                return c * saturate((l - _Threshold) / max(l, 1e-4));
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
                float2 uv = UnityStereoTransformScreenSpaceTex(i.uv);
                float4 src = UNITY_SAMPLE_SCREENSPACE_TEXTURE(_MainTex, uv);
                float3 glow = 0;
                [unroll]
                for (int k = 0; k < 12; k++)
                {
                    float a = k * 0.5235988;
                    float r = (k % 2 == 0) ? 1.0 : 0.5;
                    glow += bright(uv + float2(cos(a), sin(a)) * _Radius * r);
                }
                glow /= 12.0;
                return float4(src.rgb + glow * _Tint.rgb * _Intensity, src.a);
            }
            ENDCG
        }
    }
}

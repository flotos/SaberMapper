// SaberMapper tier-1 library: full-screen colour grade and split-tone (Vivify Blit).
Shader "SaberMapper/Post/ColorGrade"
{
    Properties
    {
        _MainTex ("Screen", 2D) = "white" {}
        _Exposure ("Exposure (stops)", Range(-2, 2)) = 0
        _Contrast ("Contrast", Range(0, 2)) = 1
        _Saturation ("Saturation", Range(0, 2)) = 1
        _ShadowTint ("Shadow tint", Color) = (0.5, 0.5, 0.5, 1)
        _HighlightTint ("Highlight tint", Color) = (0.5, 0.5, 0.5, 1)
        _Balance ("Split-tone balance", Range(-1, 1)) = 0
        _Mix ("Mix", Range(0, 1)) = 1
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
            float _Exposure, _Contrast, _Saturation, _Balance, _Mix;
            float4 _ShadowTint, _HighlightTint;

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
                float3 c = src.rgb * exp2(_Exposure);
                c = (c - 0.5) * _Contrast + 0.5;
                float luma = dot(c, float3(0.2126, 0.7152, 0.0722));
                c = lerp(luma.xxx, c, _Saturation);
                // Split-tone: soft-light the tints into shadows and highlights around a movable pivot.
                float pivot = saturate(0.5 + 0.5 * _Balance);
                float w = smoothstep(pivot - 0.35, pivot + 0.35, luma);
                float3 tint = lerp(_ShadowTint.rgb, _HighlightTint.rgb, w);
                float3 toned = c + (tint - 0.5) * 2.0 * c * (1.0 - c);
                c = max(toned, 0);
                return float4(lerp(src.rgb, c, _Mix), src.a);
            }
            ENDCG
        }
    }
}

// SaberMapper tier-1 library: vignette, darkening or tinting the screen edges (Vivify Blit).
Shader "SaberMapper/Post/Vignette"
{
    Properties
    {
        _MainTex ("Screen", 2D) = "white" {}
        _Strength ("Strength", Range(0, 1)) = 0.4
        _Radius ("Radius", Range(0.1, 1.5)) = 0.75
        _Softness ("Softness", Range(0.01, 1)) = 0.45
        _Color ("Edge colour", Color) = (0, 0, 0, 1)
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
            float _Strength, _Radius, _Softness;
            float4 _Color;

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
                float d = length((i.uv - 0.5) * 2.0);
                float edge = smoothstep(_Radius - _Softness, _Radius, d) * _Strength;
                return float4(lerp(src.rgb, _Color.rgb, edge), src.a * (1.0 - edge * _Color.a));
            }
            ENDCG
        }
    }
}

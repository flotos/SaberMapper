// SaberMapper tier-1 library: pixelate into square cells with optional colour posterize (Vivify Blit).
Shader "SaberMapper/Post/Pixelate"
{
    Properties
    {
        _MainTex ("Screen", 2D) = "white" {}
        _Cells ("Cells across", Range(8, 480)) = 120
        _Levels ("Posterize levels (0 = off)", Range(0, 32)) = 0
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
            float4 _MainTex_TexelSize;
            float _Cells, _Levels, _Mix;

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
                float aspect = _MainTex_TexelSize.w > 0 ? _MainTex_TexelSize.z / _MainTex_TexelSize.w : 1.0;
                float2 cells = float2(_Cells, _Cells / max(aspect, 1e-3));
                float2 snapped = (floor(i.uv * cells) + 0.5) / cells;
                float4 src = UNITY_SAMPLE_SCREENSPACE_TEXTURE(_MainTex, UnityStereoTransformScreenSpaceTex(i.uv));
                float4 px = UNITY_SAMPLE_SCREENSPACE_TEXTURE(_MainTex, UnityStereoTransformScreenSpaceTex(snapped));
                if (_Levels >= 2) px.rgb = floor(px.rgb * _Levels + 0.5) / _Levels;
                return lerp(src, px, _Mix);
            }
            ENDCG
        }
    }
}

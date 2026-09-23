// SaberMapper tier-1 library: kaleidoscope, the screen folded into mirrored wedges around a centre (Vivify Blit).
Shader "SaberMapper/Post/Kaleidoscope"
{
    Properties
    {
        _MainTex ("Screen", 2D) = "white" {}
        _Segments ("Mirror segments", Range(2, 16)) = 6
        _Rotation ("Rotation (degrees)", Range(0, 360)) = 0
        _Zoom ("Zoom", Range(0.25, 4)) = 1
        _Center ("Centre (UV)", Vector) = (0.5, 0.5, 0, 0)
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
            float _Segments, _Rotation, _Zoom, _Mix;
            float4 _Center;

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
                float2 p = i.uv - _Center.xy;
                float r = length(p) / _Zoom;
                float a = atan2(p.y, p.x) + radians(_Rotation);
                float wedge = UNITY_TWO_PI / floor(_Segments);
                a = abs(fmod(abs(a), wedge) - wedge * 0.5);
                float2 folded = saturate(_Center.xy + float2(cos(a), sin(a)) * r);
                float4 src = UNITY_SAMPLE_SCREENSPACE_TEXTURE(_MainTex, UnityStereoTransformScreenSpaceTex(i.uv));
                float4 k = UNITY_SAMPLE_SCREENSPACE_TEXTURE(_MainTex, UnityStereoTransformScreenSpaceTex(folded));
                return lerp(src, k, _Mix);
            }
            ENDCG
        }
    }
}

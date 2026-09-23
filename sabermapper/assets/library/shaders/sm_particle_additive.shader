// SaberMapper tier-1 library: soft additive particle sprite (procedural disc, no texture), vertex colour aware.
Shader "SaberMapper/Particles/Additive"
{
    Properties
    {
        _Color ("Tint", Color) = (1, 1, 1, 1)
        _Intensity ("Intensity", Range(0, 8)) = 1.5
        _Softness ("Edge softness", Range(0.01, 1)) = 0.6
        _Glow ("Bloom (alpha)", Range(0, 1)) = 0.3
    }
    SubShader
    {
        Tags { "Queue"="Transparent" "RenderType"="Transparent" "IgnoreProjector"="True" }
        Blend One One
        ZWrite Off
        Cull Off
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
                float4 color : COLOR;
                float2 uv : TEXCOORD0;
                UNITY_VERTEX_INPUT_INSTANCE_ID
            };

            struct v2f
            {
                float4 vertex : SV_POSITION;
                float4 color : COLOR;
                float2 uv : TEXCOORD0;
                UNITY_VERTEX_OUTPUT_STEREO
            };

            float4 _Color;
            float _Intensity, _Softness, _Glow;

            v2f vert (appdata v)
            {
                v2f o;
                UNITY_SETUP_INSTANCE_ID(v);
                UNITY_INITIALIZE_OUTPUT(v2f, o);
                UNITY_INITIALIZE_VERTEX_OUTPUT_STEREO(o);
                o.vertex = UnityObjectToClipPos(v.vertex);
                o.color = v.color;
                o.uv = v.uv;
                return o;
            }

            float4 frag (v2f i) : SV_Target
            {
                UNITY_SETUP_STEREO_EYE_INDEX_POST_VERTEX(i);
                float d = length(i.uv - 0.5) * 2.0;
                float disc = 1.0 - smoothstep(1.0 - _Softness, 1.0, d);
                float3 c = _Color.rgb * i.color.rgb * _Intensity * disc * i.color.a;
                return float4(c, _Glow * disc * i.color.a);
            }
            ENDCG
        }
    }
}

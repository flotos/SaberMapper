// SaberMapper tier-1 library: unlit emissive surface for prefabs, with fresnel rim, scrolling bands and bloom alpha.
Shader "SaberMapper/Surface/UnlitEmissive"
{
    Properties
    {
        _Color ("Base colour", Color) = (0.2, 0.6, 1, 1)
        _Intensity ("Emission intensity", Range(0, 8)) = 1
        _RimColor ("Rim colour", Color) = (1, 1, 1, 1)
        _RimPower ("Rim sharpness", Range(0.5, 8)) = 3
        _RimStrength ("Rim strength", Range(0, 4)) = 0
        _BandCount ("Scrolling bands (0 = off)", Range(0, 64)) = 0
        _BandSpeed ("Band scroll speed", Range(-10, 10)) = 1
        _Glow ("Bloom (alpha)", Range(0, 1)) = 0.5
    }
    SubShader
    {
        Tags { "RenderType"="Opaque" "Queue"="Geometry" }
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
                float3 normal : NORMAL;
                float2 uv : TEXCOORD0;
                UNITY_VERTEX_INPUT_INSTANCE_ID
            };

            struct v2f
            {
                float4 vertex : SV_POSITION;
                float2 uv : TEXCOORD0;
                float3 worldNormal : TEXCOORD1;
                float3 viewDir : TEXCOORD2;
                UNITY_VERTEX_OUTPUT_STEREO
            };

            float4 _Color, _RimColor;
            float _Intensity, _RimPower, _RimStrength, _BandCount, _BandSpeed, _Glow;

            v2f vert (appdata v)
            {
                v2f o;
                UNITY_SETUP_INSTANCE_ID(v);
                UNITY_INITIALIZE_OUTPUT(v2f, o);
                UNITY_INITIALIZE_VERTEX_OUTPUT_STEREO(o);
                o.vertex = UnityObjectToClipPos(v.vertex);
                o.uv = v.uv;
                o.worldNormal = UnityObjectToWorldNormal(v.normal);
                o.viewDir = WorldSpaceViewDir(v.vertex);
                return o;
            }

            float4 frag (v2f i) : SV_Target
            {
                UNITY_SETUP_STEREO_EYE_INDEX_POST_VERTEX(i);
                float3 n = normalize(i.worldNormal);
                float3 vd = normalize(i.viewDir);
                float rim = pow(1.0 - saturate(abs(dot(n, vd))), _RimPower) * _RimStrength;
                float bands = _BandCount > 0 ? 0.5 + 0.5 * sin((i.uv.y * _BandCount + _Time.y * _BandSpeed) * UNITY_TWO_PI) : 1.0;
                float3 c = _Color.rgb * _Intensity * bands + _RimColor.rgb * rim;
                return float4(c, _Glow);
            }
            ENDCG
        }
    }
}

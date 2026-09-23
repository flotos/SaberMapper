// SaberMapper tier-1 library: radial (zoom) blur streaking the image towards a centre (Vivify Blit).
Shader "SaberMapper/Post/RadialBlur"
{
    Properties
    {
        _MainTex ("Screen", 2D) = "white" {}
        _Strength ("Blur length (fraction of distance)", Range(0, 0.5)) = 0.1
        _Center ("Centre (UV)", Vector) = (0.5, 0.5, 0, 0)
        _Falloff ("Clear radius around centre", Range(0, 1)) = 0.1
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
            float _Strength, _Falloff;
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
                float2 toCenter = _Center.xy - i.uv;
                float fade = smoothstep(_Falloff, _Falloff + 0.3, length(toCenter));
                float2 stepUv = toCenter * _Strength * fade / 16.0;
                float4 src = UNITY_SAMPLE_SCREENSPACE_TEXTURE(_MainTex, UnityStereoTransformScreenSpaceTex(i.uv));
                float3 acc = 0;
                [unroll]
                for (int k = 0; k < 16; k++)
                {
                    acc += UNITY_SAMPLE_SCREENSPACE_TEXTURE(_MainTex, UnityStereoTransformScreenSpaceTex(i.uv + stepUv * k)).rgb;
                }
                return float4(acc / 16.0, src.a);
            }
            ENDCG
        }
    }
}

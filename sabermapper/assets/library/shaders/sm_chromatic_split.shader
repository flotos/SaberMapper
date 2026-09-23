// SaberMapper tier-1 library: chromatic split, red and blue pulled apart around a centre (Vivify Blit).
Shader "SaberMapper/Post/ChromaticSplit"
{
    Properties
    {
        _MainTex ("Screen", 2D) = "white" {}
        _Amount ("Split amount (UV)", Range(0, 0.05)) = 0.006
        _Angle ("Direction (degrees, 0 = radial)", Range(0, 360)) = 0
        _Radial ("Radial weight", Range(0, 1)) = 1
        _Center ("Centre (UV)", Vector) = (0.5, 0.5, 0, 0)
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
            float _Amount, _Angle, _Radial;
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
                float2 uv = UnityStereoTransformScreenSpaceTex(i.uv);
                float a = radians(_Angle);
                float2 linearDir = float2(cos(a), sin(a));
                float2 radialDir = uv - _Center.xy;
                float2 dir = lerp(linearDir, radialDir * 2.0, _Radial) * _Amount;
                float4 g = UNITY_SAMPLE_SCREENSPACE_TEXTURE(_MainTex, uv);
                float r = UNITY_SAMPLE_SCREENSPACE_TEXTURE(_MainTex, uv + dir).r;
                float b = UNITY_SAMPLE_SCREENSPACE_TEXTURE(_MainTex, uv - dir).b;
                return float4(r, g.g, b, g.a);
            }
            ENDCG
        }
    }
}

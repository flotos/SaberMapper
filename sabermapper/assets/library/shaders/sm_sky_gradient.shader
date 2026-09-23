// SaberMapper tier-1 library: two-colour vertical skybox gradient with a horizon band.
Shader "SaberMapper/Sky/Gradient"
{
    Properties
    {
        _TopColor ("Zenith colour", Color) = (0.05, 0.02, 0.15, 1)
        _BottomColor ("Nadir colour", Color) = (0.0, 0.0, 0.0, 1)
        _HorizonColor ("Horizon band colour", Color) = (0.6, 0.2, 0.5, 1)
        _HorizonWidth ("Horizon band width", Range(0.01, 1)) = 0.15
        _HorizonHeight ("Horizon height (-1..1)", Range(-1, 1)) = 0
        _Exponent ("Gradient curve", Range(0.2, 5)) = 1
        _Glow ("Bloom (alpha)", Range(0, 1)) = 0
    }
    SubShader
    {
        Tags { "Queue"="Background" "RenderType"="Background" "PreviewType"="Skybox" }
        Cull Off ZWrite Off
        Pass
        {
            CGPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #include "UnityCG.cginc"

            struct appdata
            {
                float4 vertex : POSITION;
                UNITY_VERTEX_INPUT_INSTANCE_ID
            };

            struct v2f
            {
                float4 vertex : SV_POSITION;
                float3 dir : TEXCOORD0;
                UNITY_VERTEX_OUTPUT_STEREO
            };

            float4 _TopColor, _BottomColor, _HorizonColor;
            float _HorizonWidth, _HorizonHeight, _Exponent, _Glow;

            v2f vert (appdata v)
            {
                v2f o;
                UNITY_SETUP_INSTANCE_ID(v);
                UNITY_INITIALIZE_OUTPUT(v2f, o);
                UNITY_INITIALIZE_VERTEX_OUTPUT_STEREO(o);
                o.vertex = UnityObjectToClipPos(v.vertex);
                o.dir = v.vertex.xyz;
                return o;
            }

            float4 frag (v2f i) : SV_Target
            {
                UNITY_SETUP_STEREO_EYE_INDEX_POST_VERTEX(i);
                float y = normalize(i.dir).y;
                float h = y - _HorizonHeight;
                float up = pow(saturate(h), 1.0 / _Exponent);
                float down = pow(saturate(-h), 1.0 / _Exponent);
                float3 c = lerp(_HorizonColor.rgb, _TopColor.rgb, up);
                c = lerp(c, _BottomColor.rgb, down);
                float band = exp(-abs(h) / _HorizonWidth);
                c = lerp(c, _HorizonColor.rgb, band * 0.5);
                return float4(c, _Glow);
            }
            ENDCG
        }
    }
}

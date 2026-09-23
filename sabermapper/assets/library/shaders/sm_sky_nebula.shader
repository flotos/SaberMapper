// SaberMapper tier-1 library: procedural nebula skybox, drifting two-colour fbm clouds over a star field.
Shader "SaberMapper/Sky/Nebula"
{
    Properties
    {
        _BaseColor ("Space colour", Color) = (0.01, 0.0, 0.03, 1)
        _ColorA ("Cloud colour A", Color) = (0.5, 0.1, 0.6, 1)
        _ColorB ("Cloud colour B", Color) = (0.1, 0.4, 0.8, 1)
        _Density ("Cloud density", Range(0, 2)) = 0.8
        _Scale ("Cloud scale", Range(0.5, 8)) = 2
        _Octaves ("Detail octaves", Range(1, 6)) = 4
        _Drift ("Drift speed", Range(0, 0.2)) = 0.02
        _Stars ("Star density", Range(0, 1)) = 0.3
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

            float4 _BaseColor, _ColorA, _ColorB;
            float _Density, _Scale, _Octaves, _Drift, _Stars, _Glow;

            float hash31(float3 p)
            {
                p = frac(p * 0.3183099 + 0.1);
                p *= 17.0;
                return frac(p.x * p.y * p.z * (p.x + p.y + p.z));
            }

            float noise3(float3 x)
            {
                float3 i = floor(x);
                float3 f = frac(x);
                f = f * f * (3.0 - 2.0 * f);
                return lerp(lerp(lerp(hash31(i), hash31(i + float3(1, 0, 0)), f.x),
                                 lerp(hash31(i + float3(0, 1, 0)), hash31(i + float3(1, 1, 0)), f.x), f.y),
                            lerp(lerp(hash31(i + float3(0, 0, 1)), hash31(i + float3(1, 0, 1)), f.x),
                                 lerp(hash31(i + float3(0, 1, 1)), hash31(i + float3(1, 1, 1)), f.x), f.y), f.z);
            }

            float fbm(float3 p)
            {
                float sum = 0, amp = 0.5;
                for (int k = 0; k < 6; k++)
                {
                    if (k >= _Octaves) break;
                    sum += amp * noise3(p);
                    p *= 2.03;
                    amp *= 0.5;
                }
                return sum;
            }

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
                float3 d = normalize(i.dir);
                float3 p = d * _Scale + float3(_Time.y * _Drift, 0, _Time.y * _Drift * 0.5);
                float n = fbm(p);
                float m = fbm(p * 1.7 + 3.1);
                float clouds = saturate((n - 0.35) * 2.0 * _Density);
                float3 c = _BaseColor.rgb + lerp(_ColorA.rgb, _ColorB.rgb, saturate(m * 1.5)) * clouds;
                float star = step(1.0 - _Stars * 0.02, hash31(floor(d * 400.0)));
                c += star * (1.0 - clouds);
                return float4(c, _Glow);
            }
            ENDCG
        }
    }
}

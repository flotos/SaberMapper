// SaberMapper skill template: the stage surface for scene geometry (generator meshes, fetched models).
// It restyles any mesh into the map's look with no textures: banded fake light from a direction,
// a fresnel rim that carries the bloom, world-space hologram lines (anti-aliased, stereo-stable),
// a travelling bulge wave for hits, distance fog to a colour and a noise dissolve of far geometry.
// A ShadowCaster pass with the same displacement puts it in the depth texture when a map enables it.
// _VertexColor 1 multiplies in the mesh's vertex colours (fetched Kenney models carry their palette there).
Shader "SaberMapper/Template/StageSurface"
{
    Properties
    {
        _Base ("Base colour", Color) = (0.05, 0.06, 0.12, 1)
        _Lit ("Lit colour", Color) = (0.25, 0.35, 0.6, 1)
        _VertexColor ("Use the mesh vertex colours", Range(0, 1)) = 0
        _LightDir ("Light direction (world, towards the light)", Vector) = (0.3, 0.8, -0.4, 0)
        _Bands ("Light bands (0 = smooth)", Range(0, 6)) = 3
        _RimColor ("Rim colour", Color) = (0.4, 0.8, 1, 1)
        _RimPower ("Rim sharpness", Range(0.5, 8)) = 3
        _RimStrength ("Rim strength (keep low on floors and walls)", Range(0, 2)) = 1
        _RimBloom ("Rim bloom (alpha; 0 on large surfaces)", Range(0, 1)) = 0
        _LineColor ("Hologram line colour", Color) = (0.5, 0.9, 1, 1)
        _LineDensity ("Hologram lines per metre (0 = off)", Range(0, 20)) = 0
        _LineScroll ("Hologram line offset (drift handle)", Float) = 0
        _PulseOrigin ("Wave origin (world)", Vector) = (0, 0, 0, 0)
        _Wave ("Wave travel in metres (per hit)", Float) = 0
        _Pulse ("Wave height in metres (kick handle)", Range(0, 0.5)) = 0
        _WaveWidth ("Wave width in metres", Range(0.1, 10)) = 1.5
        _FogColor ("Fog colour", Color) = (0.01, 0.01, 0.03, 1)
        _FogStart ("Fog start distance", Range(0, 200)) = 20
        _FogEnd ("Fog end distance", Range(1, 400)) = 120
        _DissolveStart ("Dissolve start distance", Range(1, 400)) = 150
        _DissolveEnd ("Dissolve end distance", Range(1, 500)) = 220
    }
    CGINCLUDE
    #include "UnityCG.cginc"

    float4 _PulseOrigin;
    float _Wave, _Pulse, _WaveWidth;

    float3 displace(float3 worldPos, float3 worldNormal)
    {
        float x = (distance(worldPos, _PulseOrigin.xyz) - _Wave) / _WaveWidth;
        return worldPos + worldNormal * _Pulse * exp(-x * x);
    }
    ENDCG
    SubShader
    {
        Tags { "Queue"="Geometry" "RenderType"="Opaque" }
        Pass
        {
            Tags { "LightMode"="ForwardBase" }
            CGPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #pragma multi_compile_instancing

            struct appdata
            {
                float4 vertex : POSITION;
                float3 normal : NORMAL;
                float4 color : COLOR;
                UNITY_VERTEX_INPUT_INSTANCE_ID
            };

            struct v2f
            {
                float4 vertex : SV_POSITION;
                float3 worldPos : TEXCOORD0;
                float3 worldNormal : TEXCOORD1;
                float4 color : COLOR;
                UNITY_VERTEX_OUTPUT_STEREO
            };

            float _VertexColor;
            float4 _Base, _Lit, _LightDir, _RimColor, _LineColor, _FogColor;
            float _Bands, _RimPower, _RimStrength, _RimBloom, _LineDensity, _LineScroll;
            float _FogStart, _FogEnd, _DissolveStart, _DissolveEnd;

            float hash13(float3 p)
            {
                p = frac(p * 0.1031);
                p += dot(p, p.zyx + 31.32);
                return frac((p.x + p.y) * p.z);
            }

            float vnoise(float3 x)
            {
                float3 i = floor(x);
                float3 f = frac(x);
                f = f * f * (3.0 - 2.0 * f);
                return lerp(lerp(lerp(hash13(i), hash13(i + float3(1, 0, 0)), f.x),
                                 lerp(hash13(i + float3(0, 1, 0)), hash13(i + float3(1, 1, 0)), f.x), f.y),
                            lerp(lerp(hash13(i + float3(0, 0, 1)), hash13(i + float3(1, 0, 1)), f.x),
                                 lerp(hash13(i + float3(0, 1, 1)), hash13(i + 1.0), f.x), f.y), f.z);
            }

            v2f vert (appdata v)
            {
                v2f o;
                UNITY_SETUP_INSTANCE_ID(v);
                UNITY_INITIALIZE_OUTPUT(v2f, o);
                UNITY_INITIALIZE_VERTEX_OUTPUT_STEREO(o);
                float3 worldNormal = UnityObjectToWorldNormal(v.normal);
                float3 worldPos = displace(mul(unity_ObjectToWorld, v.vertex).xyz, worldNormal);
                o.vertex = UnityWorldToClipPos(worldPos);
                o.worldPos = worldPos;
                o.worldNormal = worldNormal;
                o.color = v.color;
                return o;
            }

            float4 frag (v2f i) : SV_Target
            {
                UNITY_SETUP_STEREO_EYE_INDEX_POST_VERTEX(i);
                float dist = distance(i.worldPos, _WorldSpaceCameraPos);
                float fade = smoothstep(_DissolveStart, _DissolveEnd, dist);
                clip(vnoise(i.worldPos * 1.7) - fade);

                float3 n = normalize(i.worldNormal);
                float3 v = normalize(_WorldSpaceCameraPos - i.worldPos);
                float light = saturate(dot(n, normalize(_LightDir.xyz)) * 0.5 + 0.5);
                if (_Bands >= 1.0)
                {
                    float stepped = light * _Bands;
                    float w = fwidth(stepped);
                    light = (floor(stepped) + smoothstep(1.0 - w, 1.0, frac(stepped))) / _Bands;
                }
                float3 col = lerp(_Base.rgb, _Lit.rgb, light) * lerp(1.0, i.color.rgb, _VertexColor);

                float rim = pow(1.0 - saturate(dot(n, v)), _RimPower);
                col += _RimColor.rgb * rim * _RimStrength;

                float lines = 0.0;
                if (_LineDensity > 0.0)
                {
                    float y = i.worldPos.y * _LineDensity + _LineScroll;
                    float d = abs(frac(y) - 0.5);
                    float w = fwidth(y);
                    float halfWidth = 0.06;
                    lines = (1.0 - smoothstep(halfWidth - w, halfWidth + w, d)) * halfWidth / max(halfWidth, w);
                    col += _LineColor.rgb * lines;
                }

                float fog = smoothstep(_FogStart, _FogEnd, dist);
                col = lerp(col, _FogColor.rgb, fog);
                return float4(col, (rim * _RimBloom + lines * 0.1) * (1.0 - fog));
            }
            ENDCG
        }
        Pass
        {
            Tags { "LightMode"="ShadowCaster" }
            CGPROGRAM
            #pragma vertex vertShadow
            #pragma fragment fragShadow
            #pragma multi_compile_instancing
            #pragma multi_compile_shadowcaster

            struct appdata
            {
                float4 vertex : POSITION;
                float3 normal : NORMAL;
                UNITY_VERTEX_INPUT_INSTANCE_ID
            };

            struct v2f
            {
                float4 vertex : SV_POSITION;
                UNITY_VERTEX_OUTPUT_STEREO
            };

            v2f vertShadow (appdata v)
            {
                v2f o;
                UNITY_SETUP_INSTANCE_ID(v);
                UNITY_INITIALIZE_OUTPUT(v2f, o);
                UNITY_INITIALIZE_VERTEX_OUTPUT_STEREO(o);
                float3 worldNormal = UnityObjectToWorldNormal(v.normal);
                float3 worldPos = displace(mul(unity_ObjectToWorld, v.vertex).xyz, worldNormal);
                o.vertex = UnityApplyLinearShadowBias(UnityWorldToClipPos(worldPos));
                return o;
            }

            float4 fragShadow (v2f i) : SV_Target
            {
                UNITY_SETUP_STEREO_EYE_INDEX_POST_VERTEX(i);
                return 0;
            }
            ENDCG
        }
    }
}

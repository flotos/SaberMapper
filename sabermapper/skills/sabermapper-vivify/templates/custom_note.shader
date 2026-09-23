// SaberMapper skill template: a custom note, arrow or debris surface for the skin primitive
// (AssignObjectPrefab). Vivify feeds _Color, _Cutout and _CutPlane per note through the game's property
// blocks, so they are GPU-instanced properties (the forge enables instancing on every material).
// Live note: object-space noise dissolve on _Cutout with a hot edge that blooms. Debris material
// (_Debris 1): the cut half is eaten away from the slice plane as _Cutout rises after the hit.
// The body keeps a dark core with a coloured fresnel rim, so the two hands read against any scene.
Shader "SaberMapper/Template/CustomNote"
{
    Properties
    {
        _Color ("Note colour (set by Vivify per note)", Color) = (1, 0, 0, 1)
        _Cutout ("Dissolve (set by Vivify per note)", Range(0, 1)) = 0
        _CutPlane ("Cut plane xyz normal, w offset (debris)", Vector) = (0, 1, 0, 0)
        _Core ("Core darkness", Range(0, 1)) = 0.75
        _RimPower ("Rim sharpness", Range(0.5, 8)) = 2.5
        _RimBloom ("Rim bloom (alpha)", Range(0, 1)) = 0.35
        _EdgeWidth ("Dissolve edge width", Range(0, 0.2)) = 0.06
        _EdgeBloom ("Dissolve edge bloom (alpha)", Range(0, 4)) = 1.5
        _NoiseScale ("Dissolve noise scale", Range(1, 40)) = 9
        _Debris ("Debris material (0 note, 1 debris)", Range(0, 1)) = 0
    }
    SubShader
    {
        Tags { "Queue"="Geometry" "RenderType"="Opaque" }
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
                float3 normal : NORMAL;
                UNITY_VERTEX_INPUT_INSTANCE_ID
            };

            struct v2f
            {
                float4 vertex : SV_POSITION;
                float3 localPos : TEXCOORD0;
                float3 worldNormal : TEXCOORD1;
                float3 worldPos : TEXCOORD2;
                UNITY_VERTEX_INPUT_INSTANCE_ID
                UNITY_VERTEX_OUTPUT_STEREO
            };

            UNITY_INSTANCING_BUFFER_START(Props)
                UNITY_DEFINE_INSTANCED_PROP(float4, _Color)
                UNITY_DEFINE_INSTANCED_PROP(float, _Cutout)
                UNITY_DEFINE_INSTANCED_PROP(float4, _CutPlane)
            UNITY_INSTANCING_BUFFER_END(Props)

            float _Core, _RimPower, _RimBloom, _EdgeWidth, _EdgeBloom, _NoiseScale, _Debris;

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
                UNITY_TRANSFER_INSTANCE_ID(v, o);
                UNITY_INITIALIZE_VERTEX_OUTPUT_STEREO(o);
                o.vertex = UnityObjectToClipPos(v.vertex);
                o.localPos = v.vertex.xyz;
                o.worldNormal = UnityObjectToWorldNormal(v.normal);
                o.worldPos = mul(unity_ObjectToWorld, v.vertex).xyz;
                return o;
            }

            float4 frag (v2f i) : SV_Target
            {
                UNITY_SETUP_INSTANCE_ID(i);
                UNITY_SETUP_STEREO_EYE_INDEX_POST_VERTEX(i);
                float4 color = UNITY_ACCESS_INSTANCED_PROP(Props, _Color);
                float cutout = UNITY_ACCESS_INSTANCED_PROP(Props, _Cutout);
                float4 plane = UNITY_ACCESS_INSTANCED_PROP(Props, _CutPlane);

                float n = 0.65 * vnoise(i.localPos * _NoiseScale) + 0.35 * vnoise(i.localPos * _NoiseScale * 2.3);
                float front;
                if (_Debris > 0.5)
                {
                    float3 onPlane = i.localPos + plane.xyz * plane.w;
                    float distance = dot(onPlane, plane.xyz) / max(length(plane.xyz), 1e-4);
                    front = distance + n * 0.08 - cutout * 0.4;
                }
                else
                {
                    front = n - cutout * 1.05;
                }
                clip(front);

                float3 viewDir = normalize(_WorldSpaceCameraPos - i.worldPos);
                float rim = pow(1.0 - saturate(abs(dot(normalize(i.worldNormal), viewDir))), _RimPower);
                float3 col = color.rgb * lerp(1.0 - _Core, 1.0, rim);
                float bloom = rim * _RimBloom;

                float edge = 1.0 - smoothstep(0.0, _EdgeWidth, front);
                edge *= step(0.001, cutout);
                col = lerp(col, lerp(color.rgb, 1.0, 0.6), edge);
                bloom = max(bloom, edge * _EdgeBloom);
                return float4(col, bloom);
            }
            ENDCG
        }
    }
}

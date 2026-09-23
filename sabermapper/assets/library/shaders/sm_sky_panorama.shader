// SaberMapper tier-1 library: a photographed or painted equirectangular panorama as the sky (skybox or sky sphere).
// Sampled by view direction with seam-free gradients; exposure, tint, rotation and a calm cone behind the notes.
Shader "SaberMapper/Sky/Panorama"
{
    Properties
    {
        _Tex ("Panorama (equirectangular, 2:1)", 2D) = "black" {}
        _Tint ("Tint", Color) = (1, 1, 1, 1)
        _Exposure ("Exposure (stops)", Range(-4, 3)) = 0
        _Saturation ("Saturation", Range(0, 2)) = 1
        _Rotation ("Rotation around up (degrees)", Range(0, 360)) = 0
        _Horizon ("Horizon offset", Range(-0.5, 0.5)) = 0
        _LaneDim ("Dimming ahead, behind the notes", Range(0, 1)) = 0.35
        _LaneWidth ("Half-angle of the dimmed cone (degrees)", Range(5, 60)) = 28
        _Glow ("Bloom (alpha)", Range(0, 1)) = 0
    }
    SubShader
    {
        Tags { "Queue"="Geometry+450" "RenderType"="Background" "PreviewType"="Skybox" }
        Cull Off ZWrite Off
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
                UNITY_VERTEX_INPUT_INSTANCE_ID
            };

            struct v2f
            {
                float4 vertex : SV_POSITION;
                float3 dir : TEXCOORD0;
                UNITY_VERTEX_OUTPUT_STEREO
            };

            sampler2D _Tex;
            float4 _Tint;
            float _Exposure, _Saturation, _Rotation, _Horizon, _LaneDim, _LaneWidth, _Glow;

            v2f vert (appdata v)
            {
                v2f o;
                UNITY_SETUP_INSTANCE_ID(v);
                UNITY_INITIALIZE_OUTPUT(v2f, o);
                UNITY_INITIALIZE_VERTEX_OUTPUT_STEREO(o);
                o.vertex = UnityObjectToClipPos(v.vertex);
                #if defined(UNITY_REVERSED_Z)
                o.vertex.z = 1e-6 * o.vertex.w;
                #else
                o.vertex.z = o.vertex.w * (1.0 - 1e-6);
                #endif
                o.dir = mul((float3x3)unity_ObjectToWorld, v.vertex.xyz);
                return o;
            }

            float4 frag (v2f i) : SV_Target
            {
                UNITY_SETUP_STEREO_EYE_INDEX_POST_VERTEX(i);
                float3 d = normalize(i.dir);
                float u = atan2(d.x, d.z) / UNITY_TWO_PI + 0.5 + _Rotation / 360.0;
                float v = saturate(asin(clamp(d.y, -1.0, 1.0)) / UNITY_PI + 0.5 - _Horizon);
                float2 uv = float2(frac(u), v);
                float2 wrapped = float2(frac(u + 0.5), v);
                float2 dx = ddx(uv), dy = ddy(uv);
                float2 dxw = ddx(wrapped), dyw = ddy(wrapped);
                dx.x = abs(dx.x) < abs(dxw.x) ? dx.x : dxw.x;
                dy.x = abs(dy.x) < abs(dyw.x) ? dy.x : dyw.x;
                float3 col = tex2Dgrad(_Tex, uv, dx, dy).rgb * _Tint.rgb * exp2(_Exposure);
                float grey = dot(col, float3(0.2126, 0.7152, 0.0722));
                col = max(lerp(grey.xxx, col, _Saturation), 0.0);
                float ahead = acos(clamp(d.z, -1.0, 1.0)) * 57.29578;
                col *= 1.0 - _LaneDim * (1.0 - smoothstep(_LaneWidth * 0.6, _LaneWidth, ahead));
                return float4(col, _Glow);
            }
            ENDCG
        }
    }
}

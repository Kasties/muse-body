// Muse fur: shell fur for VRChat avatars (built-in render pipeline, forward).
// Based on Sorumi/UnityFurShader 0.4 (Apache-2.0, see LICENSE-UnityFurShader.txt).
// Changes from the original: fur mask, light probes and world lighting, VR single-pass
// instanced support, gravity in world space, empty shell pixels clipped, fog, 16 shells.
// Each pass defines FUR_LAYER (0 = solid surface, 1..FUR_LAYERS = shells) before including this.

#include "UnityCG.cginc"
#include "UnityLightingCommon.cginc"

#define FUR_LAYERS 16
#define FURSTEP (FUR_LAYER / (float)FUR_LAYERS)

sampler2D _MainTex;
float4 _MainTex_ST;
fixed4 _Color;
sampler2D _FurMask;
sampler2D _FurPattern;
float _FurLength;
float _HairCount;
float _TipThinning;
float _FurOpacity;
float _RootShadow;
float4 _Gravity;
float _LightWrap;
fixed4 _RimColor;
float _RimPower;

struct appdata
{
    float4 vertex : POSITION;
    float3 normal : NORMAL;
    float2 uv : TEXCOORD0;
    UNITY_VERTEX_INPUT_INSTANCE_ID
};

struct v2f
{
    float4 pos : SV_POSITION;
    float4 uv : TEXCOORD0;          // xy: colour texture, zw: fur pattern
    float3 worldNormal : TEXCOORD1;
    float3 worldPos : TEXCOORD2;
    half3 ambient : TEXCOORD3;      // light probes or world ambient
    half fur : TEXCOORD4;           // fur mask, 0 = bare skin
    UNITY_FOG_COORDS(5)
    UNITY_VERTEX_OUTPUT_STEREO
};

v2f vert(appdata v)
{
    v2f o;
    UNITY_SETUP_INSTANCE_ID(v);
    UNITY_INITIALIZE_OUTPUT(v2f, o);
    UNITY_INITIALIZE_VERTEX_OUTPUT_STEREO(o);

    float fur = tex2Dlod(_FurMask, float4(v.uv, 0, 0)).r;
    float3 normal = normalize(v.normal);
    // Gravity is given in world space; keep its strength in object units so fur scales with the avatar.
    float3 g = mul((float3x3)unity_WorldToObject, _Gravity.xyz);
    g *= length(_Gravity.xyz) * rsqrt(max(dot(g, g), 1e-8));
    float3 p = v.vertex.xyz + (normal * FURSTEP + g * FURSTEP * FURSTEP) * (_FurLength * fur);

    o.pos = UnityObjectToClipPos(float4(p, 1));
    o.worldPos = mul(unity_ObjectToWorld, float4(p, 1)).xyz;
    o.worldNormal = UnityObjectToWorldNormal(normal);
    o.uv.xy = TRANSFORM_TEX(v.uv, _MainTex);
    o.uv.zw = v.uv * _HairCount;
    o.ambient = ShadeSH9(float4(o.worldNormal, 1));
    o.fur = fur;
    UNITY_TRANSFER_FOG(o, o.pos);
    return o;
}

fixed4 frag(v2f i) : SV_Target
{
    UNITY_SETUP_STEREO_EYE_INDEX_POST_VERTEX(i);

    float alpha = 1;
#if FUR_LAYER > 0
    // A hair reaches this shell where the pattern is brighter than the threshold, which rises toward the tips.
    float hair = tex2D(_FurPattern, i.uv.zw).r;
    alpha = saturate((hair - FURSTEP * FURSTEP * _TipThinning) * _FurOpacity) * saturate(i.fur * 4);
    clip(alpha - 0.01);
#endif

    float3 n = normalize(i.worldNormal);
    float3 viewDir = normalize(_WorldSpaceCameraPos.xyz - i.worldPos);
    // _WorldSpaceLightPos0 is zero when the world has no realtime directional light.
    float ndl = saturate((dot(n, _WorldSpaceLightPos0.xyz) + _LightWrap) / (1 + _LightWrap));
    half3 light = i.ambient + _LightColor0.rgb * ndl;

    half3 albedo = tex2D(_MainTex, i.uv.xy).rgb * _Color.rgb;
    albedo *= 1 - _RootShadow * i.fur * (1 - FURSTEP) * (1 - FURSTEP);
    half rim = pow(1 - saturate(abs(dot(viewDir, n))), _RimPower);
    albedo += _RimColor.rgb * rim * i.fur;

    fixed4 col = fixed4(albedo * light, alpha);
    UNITY_APPLY_FOG(i.fogCoord, col);
    return col;
}

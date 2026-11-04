// Muse fur: shell fur for VRChat avatars. PC only, Quest can't use custom shaders.
// Based on Sorumi/UnityFurShader 0.4 (Apache-2.0, see LICENSE-UnityFurShader.txt).
// The mesh is drawn once solid, then 16 more times as see-through shells pushed outward;
// the fur pattern decides where hairs reach each shell. All shell code is in MuseFur.cginc.
Shader "Muse/Fur"
{
    Properties
    {
        _MainTex ("Texture", 2D) = "white" {}
        _Color ("Tint", Color) = (1, 1, 1, 1)
        [NoScaleOffset] _FurMask ("Fur Mask (white = fur)", 2D) = "white" {}
        [NoScaleOffset] _FurPattern ("Fur Pattern", 2D) = "gray" {}
        _FurLength ("Fur Length (m)", Range(0, 0.1)) = 0.045
        _HairCount ("Hair Count", Range(1, 40)) = 8
        _TipThinning ("Tip Thinning", Range(0, 2)) = 1
        _FurOpacity ("Fur Opacity", Range(0.5, 4)) = 1.5
        _RootShadow ("Root Shadow", Range(0, 1)) = 0.5
        _Gravity ("Gravity (world, xyz)", Vector) = (0, -0.3, 0, 0)
        _LightWrap ("Soft Lighting", Range(0, 1)) = 0.5
        _RimColor ("Rim Sheen", Color) = (0.25, 0.22, 0.18, 1)
        _RimPower ("Rim Width", Range(0.5, 8)) = 3
    }

    SubShader
    {
        Tags { "Queue" = "Transparent" "RenderType" = "Transparent" "IgnoreProjector" = "True" "VRCFallback" = "Toon" }
        Cull Off
        ZWrite On
        Blend SrcAlpha OneMinusSrcAlpha

        Pass
        {
            Name "SURFACE"
            Tags { "LightMode" = "ForwardBase" }
            Cull Back
            Blend Off
            CGPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #pragma multi_compile_fog
            #define FUR_LAYER 0
            #include "MuseFur.cginc"
            ENDCG
        }

        Pass
        {
            Tags { "LightMode" = "ForwardBase" }
            CGPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #pragma multi_compile_fog
            #define FUR_LAYER 1
            #include "MuseFur.cginc"
            ENDCG
        }

        Pass
        {
            Tags { "LightMode" = "ForwardBase" }
            CGPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #pragma multi_compile_fog
            #define FUR_LAYER 2
            #include "MuseFur.cginc"
            ENDCG
        }

        Pass
        {
            Tags { "LightMode" = "ForwardBase" }
            CGPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #pragma multi_compile_fog
            #define FUR_LAYER 3
            #include "MuseFur.cginc"
            ENDCG
        }

        Pass
        {
            Tags { "LightMode" = "ForwardBase" }
            CGPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #pragma multi_compile_fog
            #define FUR_LAYER 4
            #include "MuseFur.cginc"
            ENDCG
        }

        Pass
        {
            Tags { "LightMode" = "ForwardBase" }
            CGPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #pragma multi_compile_fog
            #define FUR_LAYER 5
            #include "MuseFur.cginc"
            ENDCG
        }

        Pass
        {
            Tags { "LightMode" = "ForwardBase" }
            CGPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #pragma multi_compile_fog
            #define FUR_LAYER 6
            #include "MuseFur.cginc"
            ENDCG
        }

        Pass
        {
            Tags { "LightMode" = "ForwardBase" }
            CGPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #pragma multi_compile_fog
            #define FUR_LAYER 7
            #include "MuseFur.cginc"
            ENDCG
        }

        Pass
        {
            Tags { "LightMode" = "ForwardBase" }
            CGPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #pragma multi_compile_fog
            #define FUR_LAYER 8
            #include "MuseFur.cginc"
            ENDCG
        }

        Pass
        {
            Tags { "LightMode" = "ForwardBase" }
            CGPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #pragma multi_compile_fog
            #define FUR_LAYER 9
            #include "MuseFur.cginc"
            ENDCG
        }

        Pass
        {
            Tags { "LightMode" = "ForwardBase" }
            CGPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #pragma multi_compile_fog
            #define FUR_LAYER 10
            #include "MuseFur.cginc"
            ENDCG
        }

        Pass
        {
            Tags { "LightMode" = "ForwardBase" }
            CGPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #pragma multi_compile_fog
            #define FUR_LAYER 11
            #include "MuseFur.cginc"
            ENDCG
        }

        Pass
        {
            Tags { "LightMode" = "ForwardBase" }
            CGPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #pragma multi_compile_fog
            #define FUR_LAYER 12
            #include "MuseFur.cginc"
            ENDCG
        }

        Pass
        {
            Tags { "LightMode" = "ForwardBase" }
            CGPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #pragma multi_compile_fog
            #define FUR_LAYER 13
            #include "MuseFur.cginc"
            ENDCG
        }

        Pass
        {
            Tags { "LightMode" = "ForwardBase" }
            CGPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #pragma multi_compile_fog
            #define FUR_LAYER 14
            #include "MuseFur.cginc"
            ENDCG
        }

        Pass
        {
            Tags { "LightMode" = "ForwardBase" }
            CGPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #pragma multi_compile_fog
            #define FUR_LAYER 15
            #include "MuseFur.cginc"
            ENDCG
        }

        Pass
        {
            Tags { "LightMode" = "ForwardBase" }
            CGPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #pragma multi_compile_fog
            #define FUR_LAYER 16
            #include "MuseFur.cginc"
            ENDCG
        }

        // Lets the solid surface cast shadows in worlds with realtime lights.
        Pass
        {
            Name "SHADOWCASTER"
            Tags { "LightMode" = "ShadowCaster" }
            Cull Back
            Blend Off
            CGPROGRAM
            #pragma vertex vert_shadow
            #pragma fragment frag_shadow
            #pragma multi_compile_shadowcaster
            #include "UnityCG.cginc"

            struct v2f_shadow
            {
                V2F_SHADOW_CASTER;
                UNITY_VERTEX_OUTPUT_STEREO
            };

            v2f_shadow vert_shadow(appdata_base v)
            {
                v2f_shadow o;
                UNITY_SETUP_INSTANCE_ID(v);
                UNITY_INITIALIZE_OUTPUT(v2f_shadow, o);
                UNITY_INITIALIZE_VERTEX_OUTPUT_STEREO(o);
                TRANSFER_SHADOW_CASTER_NORMALOFFSET(o)
                return o;
            }

            float4 frag_shadow(v2f_shadow i) : SV_Target
            {
                SHADOW_CASTER_FRAGMENT(i)
            }
            ENDCG
        }
    }
}

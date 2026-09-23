// Enables XR Plug-in Management with the OpenXR loader for Standalone so that asset bundle builds
// compile the single-pass-instanced (STEREO_INSTANCING_ON) shader variants Beat Saber 1.30+ renders with.
// Compiled only when com.unity.xr.management is installed (see the asmdef versionDefines).
#if SABERMAPPER_XR_MANAGEMENT
using UnityEditor;
using UnityEditor.XR.Management;
using UnityEditor.XR.Management.Metadata;
using UnityEngine;
using UnityEngine.XR.Management;
#endif

namespace SaberMapper.XR
{
    public static class ForgeXR
    {
        public const string OpenXRLoader = "UnityEngine.XR.OpenXR.OpenXRLoader";

        /// <summary>Returns null when Standalone uses the OpenXR loader, else the reason it could not be set.</summary>
        public static string EnsureStandaloneOpenXR()
        {
#if SABERMAPPER_XR_MANAGEMENT
#if !SABERMAPPER_OPENXR
            return "com.unity.xr.openxr is not installed; add it to Packages/manifest.json";
#else
            XRGeneralSettingsPerBuildTarget perTarget;
            EditorBuildSettings.TryGetConfigObject(XRGeneralSettings.k_SettingsKey, out perTarget);
            if (perTarget == null)
            {
                if (!AssetDatabase.IsValidFolder("Assets/XR")) AssetDatabase.CreateFolder("Assets", "XR");
                perTarget = ScriptableObject.CreateInstance<XRGeneralSettingsPerBuildTarget>();
                AssetDatabase.CreateAsset(perTarget, "Assets/XR/XRGeneralSettingsPerBuildTarget.asset");
                EditorBuildSettings.AddConfigObject(XRGeneralSettings.k_SettingsKey, perTarget, true);
            }
            XRGeneralSettings settings = perTarget.SettingsForBuildTarget(BuildTargetGroup.Standalone);
            if (settings == null)
            {
                settings = ScriptableObject.CreateInstance<XRGeneralSettings>();
                settings.name = "Standalone Settings";
                perTarget.SetSettingsForBuildTarget(BuildTargetGroup.Standalone, settings);
                AssetDatabase.AddObjectToAsset(settings, perTarget);
            }
            if (settings.Manager == null)
            {
                var manager = ScriptableObject.CreateInstance<XRManagerSettings>();
                manager.name = "Standalone Providers";
                settings.Manager = manager;
                AssetDatabase.AddObjectToAsset(manager, perTarget);
            }
            foreach (XRLoader loader in settings.Manager.activeLoaders)
                if (loader != null && loader.GetType().FullName == OpenXRLoader) return null;
            bool assigned = XRPackageMetadataStore.AssignLoader(settings.Manager, OpenXRLoader, BuildTargetGroup.Standalone);
            EditorUtility.SetDirty(perTarget);
            AssetDatabase.SaveAssets();
            return assigned ? null : "XRPackageMetadataStore.AssignLoader could not enable " + OpenXRLoader;
#endif
#else
            return "com.unity.xr.management is not installed; add it to Packages/manifest.json";
#endif
        }
    }
}

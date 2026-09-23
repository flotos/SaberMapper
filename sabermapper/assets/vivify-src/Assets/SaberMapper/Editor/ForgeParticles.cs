// Particle system configuration from an assets.json "particles" block (see docs/asset-forge.md).
using System;
using System.Collections.Generic;
using UnityEngine;

namespace SaberMapper
{
    public static class ForgeParticles
    {
        public static ParticleSystem.MinMaxCurve Curve(ForgeParams p, string key, float fallback)
        {
            float[] f = p.Floats(key, null);
            if (f == null || f.Length == 0) return new ParticleSystem.MinMaxCurve(fallback);
            if (f.Length == 1) return new ParticleSystem.MinMaxCurve(f[0]);
            return new ParticleSystem.MinMaxCurve(f[0], f[1]);
        }

        static AnimationCurve Keys(List<object> points, float fallback)
        {
            var curve = new AnimationCurve();
            foreach (object point in points)
            {
                var pair = point as List<object>;
                if (pair == null || pair.Count < 2) continue;
                curve.AddKey(Convert.ToSingle(pair[0]), Convert.ToSingle(pair[1]));
            }
            if (curve.length == 0) { curve.AddKey(0, fallback); curve.AddKey(1, fallback); }
            return curve;
        }

        static Gradient MakeGradient(List<object> stops)
        {
            var colors = new List<GradientColorKey>();
            var alphas = new List<GradientAlphaKey>();
            foreach (object stop in stops)
            {
                var s = stop as List<object>;
                if (s == null || s.Count < 5) continue;
                float t = Convert.ToSingle(s[0]);
                colors.Add(new GradientColorKey(new Color(Convert.ToSingle(s[1]), Convert.ToSingle(s[2]), Convert.ToSingle(s[3])), t));
                alphas.Add(new GradientAlphaKey(Convert.ToSingle(s[4]), t));
            }
            var g = new Gradient();
            if (colors.Count == 0)
            {
                colors.Add(new GradientColorKey(Color.white, 0)); colors.Add(new GradientColorKey(Color.white, 1));
                alphas.Add(new GradientAlphaKey(1, 0)); alphas.Add(new GradientAlphaKey(0, 1));
            }
            g.SetKeys(colors.ToArray(), alphas.ToArray());
            return g;
        }

        /// <summary>Adds and configures a ParticleSystem on go; returns its max particle count.</summary>
        public static int Configure(GameObject go, ForgeParams p, Material material, Mesh mesh)
        {
            var ps = go.AddComponent<ParticleSystem>();
            ps.Stop(true, ParticleSystemStopBehavior.StopEmittingAndClear);

            var main = ps.main;
            main.duration = p.Float("duration", 5f);
            main.loop = p.Bool("looping", true);
            main.prewarm = p.Bool("prewarm", false) && main.loop;
            main.startLifetime = Curve(p, "start_lifetime", 2f);
            main.startSpeed = Curve(p, "start_speed", 1f);
            main.startSize = Curve(p, "start_size", 0.1f);
            main.startRotation = Curve(p, "start_rotation", 0f);
            main.startColor = new ParticleSystem.MinMaxGradient(p.Color("start_color", Color.white));
            main.gravityModifier = p.Float("gravity", 0f);
            main.maxParticles = Math.Max(1, p.Int("max_particles", 500));
            main.playOnAwake = p.Bool("play_on_awake", true);
            main.simulationSpace = p.String("simulation_space", "local") == "world" ? ParticleSystemSimulationSpace.World : ParticleSystemSimulationSpace.Local;
            main.scalingMode = ParticleSystemScalingMode.Hierarchy;

            var emission = ps.emission;
            ForgeParams em = p.Child("emission");
            emission.enabled = true;
            emission.rateOverTime = em.Float("rate_over_time", 10f);
            emission.rateOverDistance = em.Float("rate_over_distance", 0f);
            var bursts = new List<ParticleSystem.Burst>();
            foreach (object b in em.List("bursts"))
            {
                var bp = new ForgeParams(b);
                var burst = new ParticleSystem.Burst(bp.Float("time", 0f), (short)Math.Min(short.MaxValue, bp.Int("count", 10)));
                burst.cycleCount = Math.Max(1, bp.Int("cycles", 1));
                burst.repeatInterval = Math.Max(0.01f, bp.Float("interval", 1f));
                bursts.Add(burst);
            }
            emission.SetBursts(bursts.ToArray());

            var shape = ps.shape;
            ForgeParams sh = p.Child("shape");
            shape.enabled = true;
            switch (sh.String("type", "cone"))
            {
                case "sphere": shape.shapeType = ParticleSystemShapeType.Sphere; break;
                case "hemisphere": shape.shapeType = ParticleSystemShapeType.Hemisphere; break;
                case "box": shape.shapeType = ParticleSystemShapeType.Box; break;
                case "circle": shape.shapeType = ParticleSystemShapeType.Circle; break;
                case "edge": shape.shapeType = ParticleSystemShapeType.SingleSidedEdge; break;
                case "donut": shape.shapeType = ParticleSystemShapeType.Donut; break;
                default: shape.shapeType = ParticleSystemShapeType.Cone; break;
            }
            shape.radius = sh.Float("radius", 1f);
            shape.angle = sh.Float("angle", 25f);
            shape.arc = sh.Float("arc", 360f);
            shape.donutRadius = sh.Float("donut_radius", 0.2f);
            shape.radiusThickness = sh.Float("thickness", 1f);
            shape.scale = sh.Vec3("scale", Vector3.one);
            shape.position = sh.Vec3("position", Vector3.zero);
            shape.rotation = sh.Vec3("rotation", Vector3.zero);

            if (p.Has("color_over_lifetime"))
            {
                var col = ps.colorOverLifetime;
                col.enabled = true;
                col.color = new ParticleSystem.MinMaxGradient(MakeGradient(p.Child("color_over_lifetime").List("gradient")));
            }
            if (p.Has("size_over_lifetime"))
            {
                var sol = ps.sizeOverLifetime;
                sol.enabled = true;
                sol.size = new ParticleSystem.MinMaxCurve(1f, Keys(p.Child("size_over_lifetime").List("curve"), 1f));
            }
            if (p.Has("velocity_over_lifetime"))
            {
                ForgeParams vp = p.Child("velocity_over_lifetime");
                var vel = ps.velocityOverLifetime;
                vel.enabled = true;
                vel.space = vp.String("space", "local") == "world" ? ParticleSystemSimulationSpace.World : ParticleSystemSimulationSpace.Local;
                Vector3 linear = vp.Vec3("linear", Vector3.zero);
                vel.x = new ParticleSystem.MinMaxCurve(linear.x);
                vel.y = new ParticleSystem.MinMaxCurve(linear.y);
                vel.z = new ParticleSystem.MinMaxCurve(linear.z);
                Vector3 orbital = vp.Vec3("orbital", Vector3.zero);
                vel.orbitalX = new ParticleSystem.MinMaxCurve(orbital.x);
                vel.orbitalY = new ParticleSystem.MinMaxCurve(orbital.y);
                vel.orbitalZ = new ParticleSystem.MinMaxCurve(orbital.z);
                vel.radial = new ParticleSystem.MinMaxCurve(vp.Float("radial", 0f));
            }
            if (p.Has("noise"))
            {
                ForgeParams np = p.Child("noise");
                var noise = ps.noise;
                noise.enabled = true;
                noise.strength = new ParticleSystem.MinMaxCurve(np.Float("strength", 0.5f));
                noise.frequency = np.Float("frequency", 0.5f);
                noise.scrollSpeed = new ParticleSystem.MinMaxCurve(np.Float("scroll_speed", 0f));
                noise.octaveCount = Math.Max(1, Math.Min(4, np.Int("octaves", 1)));
            }

            var renderer = go.GetComponent<ParticleSystemRenderer>();
            ForgeParams rp = p.Child("renderer");
            switch (rp.String("render_mode", "billboard"))
            {
                case "stretched":
                    renderer.renderMode = ParticleSystemRenderMode.Stretch;
                    renderer.velocityScale = rp.Float("velocity_scale", 0.1f);
                    renderer.lengthScale = rp.Float("length_scale", 2f);
                    break;
                case "horizontal": renderer.renderMode = ParticleSystemRenderMode.HorizontalBillboard; break;
                case "vertical": renderer.renderMode = ParticleSystemRenderMode.VerticalBillboard; break;
                case "mesh": renderer.renderMode = ParticleSystemRenderMode.Mesh; renderer.mesh = mesh; break;
                default: renderer.renderMode = ParticleSystemRenderMode.Billboard; break;
            }
            renderer.sharedMaterial = material;
            renderer.maxParticleSize = rp.Float("max_particle_size", 0.5f);
            renderer.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off;
            renderer.receiveShadows = false;
            return main.maxParticles;
        }
    }
}

# Read-only BeatForge reference audit

Inspected local `../external-ideas-dont-trust` at Git commit `3008140fdf6db6d7e00c5a1027c70a32d134dd7e` on 2026-09-22. The files were read, not executed or imported. Its README describes a broader directory layout and v3.0.0/v2.0.0 export, while the inspected source header and implementation disagree: `exporter.js:2-5` says v3.2.0/v2.1.0, yet `exporter.js:35` and `:113` actually serialize 3.0.0/2.0.0. Version claims require inspecting output, not trusting prose.

| Component | Observed behavior and caveat |
|---|---|
| `generator.js:72-178`, `:197-365` | Quantizes audio candidates into a beat grid, then assigns notes through settings and RNG. Musical timing and pattern quality depend on analyzer hypotheses and chosen seed; no human judgement is implied. |
| `patterns.js:33-72`, `generator.js:605` | Models parity and local flow; useful as a contrastive rules baseline. A local score cannot prove a full phrase feels good. |
| `validator.js:26-64`, `:96-118` | Mutates a map in place, clamps fields, removes same-cell notes, and flips directions to repair parity. This can erase intended emphasis or technical choices; retain original and repair log when comparing. Duplicate detection rounds beats to sixteenth cells, so finer subdivisions may collide. |
| `lighting.js:54-217` | Uses audio event types and seeded palette to generate basic lighting. Visibility and photo sensitivity still need review. |
| `exporter.js:31-90`, `:93-138`, `:237-246` | Builds v3 difficulty files and v2 Info data, shifts beat values, and packages ZIP. Negative shifted beats are clamped to zero; the effect on phrase timing must be measured. |
| `encoder.js:23-42`, `:62-109` | Sniffs first bytes for Vorbis and uses embedded WASM to encode other sources. It checks a signature, not the full decoded stream or alignment after encoding. |
| `zip.js:26`, `:50-106` | Writes ZIP entries with a current DOS timestamp, so byte-identical ZIPs are not guaranteed even with the same map seed. ZIP format limits and integrity need independent tests. |
| `app.js:225-227`, `util.js:10-44` | A blank seed uses `Math.random`; a fixed seed supports reproducible generation, but source audio, BPM/offset, title, settings and software revision must also be held fixed. |

License inventory: the inspected first-party code has no `LICENSE` or `COPYING` file in this local tree, so its license is **unknown**. `README-upstream.md:228` gives an MIT notice for `wasm-media-encoders`; `WasmMediaEncoder.min.js` and `ogg.wasm.js` appear vendored, but that notice does not license BeatForge's first-party files. Provenance for the binary needs verification against upstream release hashes before redistribution. This audit copies no source into SaberMapper.

Recommendation: **needs fixes and controlled validation before baseline use**. For an eventual rules-only comparison, pin the commit and environment, provide the same exact audio hash, BPM/offset and song metadata, set a fixed seed, disable mod-required features, record all generation settings and repair counts, decode/check the exported Vorbis, inspect v2/v3 JSON and timestamps, and test the ZIP in an editor and game. Compare the generated Expert map against a SaberMapper Expert map and a human reference concealed until authoring ends. The baseline has not been run here. Negative fixtures worth testing include Opus-in-Ogg, malformed Vorbis, a negative note shift, 1/32-beat near-collisions, parity repair that changes intended emphasis, and a no-seed rerun.

The format checks should use the [BSMG map format reference](https://bsmg.wiki/mapping/map-format.html) and its [Info fields](https://bsmg.wiki/mapping/map-format/info.html). These sources describe schemas, not proof that BeatForge's package loads on the user's build.

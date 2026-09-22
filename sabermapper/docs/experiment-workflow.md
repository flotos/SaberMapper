# Run the Milestone 0 slice

Run these commands from the repository root (`sabermapper/`). The checked-in files under `examples/` are synthetic demonstrations. They have no playable audio, cover, human timing review, community phrase provenance, or playtest result.

```powershell
python -m sabermapper validate examples/synthetic-arrangement.json
python -m sabermapper compile examples/synthetic-arrangement.json --output examples/synthetic-map.dat
python -m sabermapper validate examples/synthetic-arrangement-revised.json
python -m sabermapper compile examples/synthetic-arrangement-revised.json --output examples/synthetic-map-revised.dat
```

`validate` exits nonzero and prints JSON diagnostics for hard errors; it prints nothing when clean. `compile` writes Beat Saber v3.3 difficulty JSON and refuses to overwrite an existing output, so use a new path or remove only your disposable output before rerunning. These commands check structural behavior, not musical quality. The revised fixture changes the `drive` section while preserving the locked `intro`, the `outro`, and shared motifs. To verify that scope:

```powershell
python -c "import json; from pathlib import Path; a=json.loads(Path('examples/synthetic-arrangement.json').read_text()); b=json.loads(Path('examples/synthetic-arrangement-revised.json').read_text()); assert a['sections'][0] == b['sections'][0] and a['sections'][2] == b['sections'][2] and a['motifs'] == b['motifs']; print('unrelated sections and motifs preserved')"
```

For a real experiment, fill [the experiment record](../examples/experiment-record-template.md) before authoring. Select a familiar steady-tempo track, record the exact local audio SHA-256, check BPM, beat-zero audio offset and bar anchors by ear, and prepare a concise song report. Hand-inspect 15–20 phrases with exact map/version provenance and entry/exit context. Keep the target source map's note arrays out of the assistant's authoring inputs. The [prototype skill](../skills/sabermapper-map/SKILL.md) uses those inputs to author one difficulty as a JSON arrangement, then to make one requested section revision. The [architecture contract](architecture-v0.md) defines beat units and locks.

After filling a real arrangement and obtaining a locally licensed OGG Vorbis audio file and PNG cover, run:

```powershell
python -m sabermapper validate path/to/arrangement.json
python -m sabermapper compile path/to/arrangement.json --output path/to/difficulty.dat
python -m sabermapper export path/to/arrangement.json --audio path/to/track.ogg --cover path/to/cover.png --output path/to/map.zip
```

Record the diagnostics and artifact hashes. The exporter performs narrow structural checks and creates a ZIP; an export success does not establish that the chosen game build accepts or plays it. Open the ZIP in ArcViewer for visual and audio preview, then import it into the user's SteamVR Beat Saber installation and verify timing and playability. Record the exact build/mods and observations. Playtest before and after one scoped revision, compare with a simple manual or rules baseline given the same report and phrases, log user and assistant editing time, and record whether the user would replay the result. Choose **go**, **revise hypothesis**, or **stop** with reasons. None of those human gates have been completed by the synthetic fixtures.

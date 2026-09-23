# Blender MCP: agent-driven modelling

Agents model meshes, decimate generated models and render previews in a local Blender through the official
[Blender Lab MCP server](https://www.blender.org/lab/mcp-server/) (source: `projects.blender.org/lab/blender_mcp`).
It has two halves:

- **The add-on** (`mcp`, installed as a Blender extension) runs a TCP bridge inside Blender on `localhost:9876`.
- **The `blender-mcp` stdio server** is registered in the repository's `.mcp.json` as `blender`. Its tools send
  Python to the bridge (`execute_blender_code`), summarise scenes and objects, search the bundled Python API and
  manual, render the viewport or a thumbnail to a PNG, and, with a GUI Blender, take window screenshots.

## Per-user install (no admin rights)

| Part | Location | Version |
| --- | --- | --- |
| Blender (portable zip, SHA-256 checked) | `%LOCALAPPDATA%\Programs\Blender\blender.exe` | 5.2.2 LTS (the add-on needs 5.1+) |
| MCP add-on | `%APPDATA%\Blender Foundation\Blender\5.2\extensions\user_default\mcp` | 1.0.3 |
| MCP server venv (Python 3.12) | `%LOCALAPPDATA%\Programs\BlenderMCP\Scripts\blender-mcp.exe` | 1.0.3 (source in `...\BlenderMCP\src`) |

To reinstall or upgrade on this machine:

1. Download `blender-X.Y.Z-windows-x64.zip` from `https://download.blender.org/release/`, check it against the
   release's `.sha256`, and extract it so that `blender.exe` sits in `%LOCALAPPDATA%\Programs\Blender\`.
2. `blender --background --command extension install-file --repo user_default --enable mcp-1.0.3.zip`
   (from the project's releases page).
3. Clone `https://projects.blender.org/lab/blender_mcp.git` with `-c core.longpaths=true`,
   `git archive vX.Y.Z mcp | tar -x -C %LOCALAPPDATA%\Programs\BlenderMCP\src`, then
   `%LOCALAPPDATA%\Programs\BlenderMCP\Scripts\python -m pip install %LOCALAPPDATA%\Programs\BlenderMCP\src\mcp`.
   The archive step matters because long Windows paths are disabled on this machine, and pip cannot read the
   bundled manual under a deep checkout.

Keep the installs under `%LOCALAPPDATA%\Programs`. Folders created directly in `%LOCALAPPDATA%` from inside the
Claude desktop app are redirected into its package cache, where other programs cannot see them.

## Agent workflow

Run these from `sabermapper/` with `.venv/Scripts/python -m sabermapper`:

- `blender status`: the Blender and server paths, whether the bridge answers (version, open file, object count),
  and the Blender that `blender start` opened. When something is missing, the `fix` field says what to do.
- `blender start [--blend FILE] [--gui] [--port N]`: opens Blender with the bridge and waits until it answers.
  **Headless is the default**, so modelling never opens a window on the user's desktop. `--gui` opens the window,
  which the `get_screenshot_*` and `jump_to_*` tools need; it always listens on 9876. A running bridge is reused.
- `blender stop`: closes only the Blender that `blender start` opened. A Blender the user opened is left running.

Then call the `mcp__blender__*` tools. Look at the work through `render_viewport_to_path` or
`render_thumbnail_to_path` (a headless Blender renders too) and read the returned PNG path. Save `.blend` files
and exports (glTF/FBX/OBJ) inside the project's workspace, and close Blender with `blender stop` when finished.

`--online-mode` is passed on the command line, so it applies to that Blender run only. Blender's saved
"Allow Online Access" preference stays off. The add-on runs model-written Python without a sandbox, so give it
only code the task needs.

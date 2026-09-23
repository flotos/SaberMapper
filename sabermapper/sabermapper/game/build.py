"""Build the SaberMapper Bridge BSIPA plugin with the installed Roslyn compiler (no .NET SDK needed).

The plugin compiles against the game's own assemblies (`Beat Saber_Data/Managed`, `Libs`, `Plugins`) with
`-nostdlib`, and embeds `manifest.json` as `SaberMapperBridge.manifest.json` (BSIPA's loader looks for a
resource ending in `.manifest.json`). See docs/game-bridge.md.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess

from .errors import GameError
from .logs import default_game_dir

ASSEMBLY = "SaberMapperBridge"
BRIDGE_DIR = Path(__file__).resolve().parents[2] / "game-bridge"
CSC_CANDIDATES = (
    "C:/Program Files (x86)/Microsoft Visual Studio/18/BuildTools/MSBuild/Current/Bin/Roslyn/csc.exe",
    "C:/Program Files/Microsoft Visual Studio/18/BuildTools/MSBuild/Current/Bin/Roslyn/csc.exe",
    "C:/Program Files (x86)/Microsoft Visual Studio/2022/BuildTools/MSBuild/Current/Bin/Roslyn/csc.exe",
    "C:/Program Files/Microsoft Visual Studio/2022/Community/MSBuild/Current/Bin/Roslyn/csc.exe",
)
# (folder relative to the game dir, assembly name); keep in sync with SaberMapperBridge.csproj.
REFERENCES = tuple(("Beat Saber_Data/Managed", name) for name in (
    "mscorlib", "netstandard", "System", "System.Core", "UnityEngine", "UnityEngine.CoreModule",
    "UnityEngine.ImageConversionModule", "UnityEngine.ScreenCaptureModule", "UnityEngine.AudioModule", "Main",
    "DataModels", "BeatmapCore", "GameplayCore", "BGLib.AppFlow", "BGLib.UnityExtension", "HMLib", "Zenject",
    "Zenject-usage", "Newtonsoft.Json", "IPA.Loader", "Unity.ResourceManager", "Unity.Addressables", "Colors",
    "BGLib.Polyglot", "BeatSaber.ViewSystem")) + (("Plugins", "SongCore"),)
_DIAGNOSTIC = re.compile(r"^(?P<file>.+?)\((?P<line>\d+),(?P<column>\d+)\): (?P<severity>error|warning) "
                         r"(?P<code>[A-Z]+\d+): (?P<message>.*)$")
_GLOBAL = re.compile(r"^(?:(?P<file>[^:]+?) ?: )?(?P<severity>error|warning) (?P<code>[A-Z]+\d+): (?P<message>.*)$")


def find_csc(csc: str | Path | None = None) -> Path:
    candidates = [csc] if csc else [os.environ.get("SABERMAPPER_CSC"), *CSC_CANDIDATES, shutil.which("csc")]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    raise GameError("csc_missing", "Roslyn csc.exe was not found", {"searched": [str(c) for c in candidates if c]},
                    fix="Install Visual Studio Build Tools (C# compiler) or pass --csc PATH / set SABERMAPPER_CSC")


def reference_paths(game_dir: str | Path | None = None) -> list[Path]:
    game = default_game_dir(game_dir)
    if not (game / "Beat Saber_Data" / "Managed").is_dir():
        raise GameError("game_not_found", f"No Beat Saber install at {game}", {"game_dir": str(game)},
                        fix="Pass --game-dir or set SABERMAPPER_GAME_DIR")
    paths = [game / folder / f"{name}.dll" for folder, name in REFERENCES]
    missing = [str(p) for p in paths if not p.is_file()]
    if missing:
        raise GameError("reference_missing", "Game assemblies the bridge compiles against are missing",
                        {"missing": missing}, fix="Install SongCore/BSIPA for this game version, or update REFERENCES")
    return paths


def sources(bridge_dir: Path = BRIDGE_DIR) -> list[Path]:
    files = sorted((bridge_dir / "src").glob("*.cs"))
    if not files:
        raise GameError("bridge_source_missing", f"No C# sources in {bridge_dir / 'src'}")
    return files


def csc_command(csc: Path, references: list[Path], source_files: list[Path], output: Path, manifest: Path) -> list[str]:
    return [str(csc), "-nologo", "-noconfig", "-nostdlib+", "-target:library", "-langversion:latest", "-optimize+",
            "-debug:portable", "-deterministic", "-nowarn:CS0618,CS1701,CS1702", f"-out:{output}",
            f"-resource:{manifest},{ASSEMBLY}.manifest.json", *[f"-reference:{r}" for r in references],
            *[str(s) for s in source_files]]


def parse_diagnostics(output: str) -> list[dict]:
    diagnostics = []
    for line in output.splitlines():
        line = line.strip()
        if match := _DIAGNOSTIC.match(line):
            item = match.groupdict()
            item["line"], item["column"] = int(item["line"]), int(item["column"])
        elif match := _GLOBAL.match(line):
            item = {**match.groupdict(), "line": None, "column": None}
        else:
            continue
        diagnostics.append(item)
    return diagnostics


def build(*, game_dir: str | Path | None = None, csc: str | Path | None = None, install: bool = False,
          bridge_dir: Path = BRIDGE_DIR, run=subprocess.run) -> dict:
    compiler = find_csc(csc)
    references = reference_paths(game_dir)
    output = bridge_dir / "bin" / f"{ASSEMBLY}.dll"
    output.parent.mkdir(parents=True, exist_ok=True)
    command = csc_command(compiler, references, sources(bridge_dir), output, bridge_dir / "manifest.json")
    result = run(command, capture_output=True, text=True, cwd=bridge_dir,
                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    text = (result.stdout or "") + (result.stderr or "")
    diagnostics = parse_diagnostics(text)
    errors = [d for d in diagnostics if d["severity"] == "error"]
    if result.returncode != 0 or errors:
        raise GameError("bridge_compile_failed", f"csc failed with {len(errors)} error(s)",
                        {"errors": errors, "warnings": [d for d in diagnostics if d["severity"] == "warning"],
                         "exit_code": result.returncode, "output": text[-4000:] if not errors else None},
                        fix="Fix the listed C# errors in sabermapper/game-bridge/src and rebuild")
    report = {"built": True, "dll": str(output), "size": output.stat().st_size, "csc": str(compiler),
              "warnings": [d for d in diagnostics if d["severity"] == "warning"], "installed": None}
    if install:
        report["installed"] = str(install_dll(output, game_dir))
    return report


def install_dll(dll: Path, game_dir: str | Path | None = None) -> Path:
    from .process import find_game_pids
    target = default_game_dir(game_dir) / "Plugins" / dll.name
    if find_game_pids():
        raise GameError("game_running", "Beat Saber is running; the plugin DLL is locked and loads only at startup",
                        {"target": str(target)}, fix="Close the game (game close, or ask the user), then install")
    shutil.copy2(dll, target)
    return target

"""Run tiddl with workspace-local settings, downloads and FFmpeg."""
import os
from pathlib import Path
import shutil
import subprocess
import sys

import imageio_ffmpeg


def main():
    root = Path(__file__).resolve().parents[1]
    state = root / "workspace" / "tidal"
    downloads = state / "downloads"
    binaries = state / "bin"
    downloads.mkdir(parents=True, exist_ok=True)
    binaries.mkdir(parents=True, exist_ok=True)
    ffmpeg = binaries / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
    if not ffmpeg.exists():
        shutil.copy2(imageio_ffmpeg.get_ffmpeg_exe(), ffmpeg)
    config = state / "config.toml"
    if not config.exists():
        config.write_text(
            "[download]\ndownload_path = '" + downloads.as_posix() + "'\n",
            encoding="utf-8",
        )
    env = os.environ.copy()
    env["TIDDL_PATH"] = str(state)
    env["PATH"] = str(binaries) + os.pathsep + env.get("PATH", "")
    env["PYTHONUTF8"] = "1"
    executable = Path(sys.executable).parent / ("tiddl.exe" if os.name == "nt" else "tiddl")
    if not executable.exists():
        raise SystemExit('Install the optional dependency: .venv/Scripts/python -m pip install -e ".[tidal]"')
    return subprocess.call([str(executable), *sys.argv[1:]], env=env, cwd=root)


if __name__ == "__main__":
    sys.exit(main())

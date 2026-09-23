"""Build (and optionally install) the SaberMapperBridge BSIPA plugin with Roslyn csc.

Same as `python -m sabermapper game build-bridge [--install]`; prints JSON, exits 2 on a structured error.
Run from the application directory: `.venv/Scripts/python scripts/build_game_bridge.py --install`.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sabermapper.game.build import build  # noqa: E402
from sabermapper.game.errors import GameError  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--install", action="store_true", help="Copy the DLL into <game>/Plugins (game closed)")
    parser.add_argument("--csc", type=Path)
    parser.add_argument("--game-dir", type=Path)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(build(game_dir=args.game_dir, csc=args.csc, install=args.install), indent=2))
        return 0
    except GameError as error:
        print(json.dumps(error.to_dict(), indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

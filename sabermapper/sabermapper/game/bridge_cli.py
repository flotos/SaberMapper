"""`sabermapper game` subcommands that drive the game through the SaberMapper Bridge (docs/game-bridge.md)."""
from __future__ import annotations

import argparse
from pathlib import Path

DIFFICULTIES = ("Easy", "Normal", "Hard", "Expert", "ExpertPlus")


def _common(parser, *, workspace: bool = False):
    parser.add_argument("--session", help="Lease session id; default: $SABERMAPPER_SESSION or sha1 of the worktree")
    parser.add_argument("--holder", help="Lease holder name; default: agent:<worktree folder>")
    parser.add_argument("--game-dir", type=Path, help="Beat Saber install; default: $SABERMAPPER_GAME_DIR or Steam path")
    parser.add_argument("--lease-dir", type=Path, help=argparse.SUPPRESS)
    if workspace:
        parser.add_argument("--workspace", type=Path, default=Path("workspace"))


def _options(args) -> dict:
    return {"session": args.session, "holder": args.holder, "game_dir": args.game_dir, "root": args.lease_dir}


def _store(args):
    from ..projects import ProjectStore
    return ProjectStore(args.workspace)


def _project(parser):
    parser.add_argument("project")
    parser.add_argument("--difficulty", choices=DIFFICULTIES, help="Default: the primary difficulty")
    parser.add_argument("--revision", help="Saved revision SHA; default: the current revision")


def register_build(actions):
    parser = actions.add_parser("build-bridge", help="Compile the SaberMapperBridge BSIPA plugin with Roslyn csc")
    parser.add_argument("--install", action="store_true", help="Copy the DLL into <game>/Plugins (game must be closed)")
    parser.add_argument("--csc", type=Path, help="csc.exe path; default: VS Build Tools Roslyn or $SABERMAPPER_CSC")
    parser.add_argument("--game-dir", type=Path, help="Beat Saber install to compile against")


def run_build(args, emit):
    from .build import build
    emit(build(game_dir=args.game_dir, csc=args.csc, install=args.install))


def register_launch(actions):
    parser = actions.add_parser("launch", help="Acquire the agent lease and start Beat Saber (FPFC by default)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--fpfc", dest="fpfc", action="store_true", default=True, help="Desktop first-person mode")
    mode.add_argument("--vr", dest="fpfc", action="store_false", help="Headset mode")
    parser.add_argument("--wait", type=float, default=0.0, help="Queue up to SECONDS for the lease")
    parser.add_argument("--purpose", default="game launch")
    parser.add_argument("--project")
    _common(parser)


def run_launch(args, emit):
    from .api import launch
    emit(launch(fpfc=args.fpfc, wait=args.wait, purpose=args.purpose, project=args.project, **_options(args)))


def register_status(actions):
    parser = actions.add_parser("status", help="Game process, lease and bridge state (song time, scene, level)")
    _common(parser)


def run_status(args, emit):
    from .api import game_status
    emit(game_status(**_options(args)))


def register_play(actions):
    parser = actions.add_parser("play", help="Export, install and start a project in the leased game")
    _project(parser)
    parser.add_argument("--at", type=float, default=0.0, help="Song time to start at (seconds)")
    parser.add_argument("--speed", type=float, default=1.0, help="Practice song speed")
    parser.add_argument("--no-hud", action="store_true", help="Hide the score HUD")
    _common(parser, workspace=True)


def run_play(args, emit):
    from .api import play_project
    emit(play_project(_store(args), args.project, difficulty=args.difficulty, revision=args.revision, at=args.at,
                      speed=args.speed, hud=not args.no_hud, **_options(args)))


def register_install(actions):
    parser = actions.add_parser("install", help="Export and install a project into CustomWIPLevels/SaberMapper-<id>")
    _project(parser)
    parser.add_argument("--no-refresh", action="store_true", help="Do not ask the running game to reload songs")
    _common(parser, workspace=True)


def run_install(args, emit):
    from .api import install
    emit(install(_store(args), args.project, difficulty=args.difficulty, revision=args.revision,
                 refresh=not args.no_refresh, **_options(args)))


def _simple(name, help_text, *, arg=None):
    def register(actions):
        parser = actions.add_parser(name, help=help_text)
        if arg == "seconds":
            parser.add_argument("seconds", type=float)
        elif arg == "at":
            parser.add_argument("--at", type=float, help="Restart at this song time instead of the last start")
        _common(parser)
    return register


def run_seek(args, emit):
    from .api import seek_to
    emit(seek_to(args.seconds, **_options(args)))


def run_pause(args, emit):
    from .api import pause_game
    emit(pause_game(**_options(args)))


def run_resume(args, emit):
    from .api import resume_game
    emit(resume_game(**_options(args)))


def run_restart(args, emit):
    from .api import restart_game
    emit(restart_game(args.at, **_options(args)))


def run_stop(args, emit):
    from .api import menu
    emit(menu(**_options(args)))


def run_close(args, emit):
    from .api import close
    emit(close(**_options(args)))


def run_refresh(args, emit):
    from .api import refresh
    emit(refresh(**_options(args)))


def register_capture(actions):
    parser = actions.add_parser("capture", help="Leased run: launch FPFC, install, capture PNG frames, close the game")
    _project(parser)
    parser.add_argument("--times", help="Comma-separated song seconds (replaces the default set)")
    parser.add_argument("--every-beats", type=float, help="Beat grid spacing (default 16 when --times is absent)")
    parser.add_argument("--probe", help="Dense probe START-END@FPS for flash checks (default: 3 s @30 fps at the "
                                        "strongest moment or densest notes)")
    parser.add_argument("--no-probe", action="store_true", help="Skip the default dense probe")
    parser.add_argument("--probe-with-notes", action="store_true",
                        help="Render probe frames with notes visible (default: hidden, because uncut notes fly through "
                             "the camera during a capture and read as flashes a player never sees)")
    parser.add_argument("--camera", choices=("player", "wide"), default="player",
                        help="player: the FPFC screen incl. Vivify post-processing; wide: raised camera behind the track")
    parser.add_argument("--width", type=int, help="Output width (aspect kept when --height is absent)")
    parser.add_argument("--height", type=int)
    parser.add_argument("--out", type=Path, help="Default: <project>/captures/<revision[:10]>-<timestamp>/")
    parser.add_argument("--wait", type=float, default=0.0, help="Queue up to SECONDS for the lease")
    parser.add_argument("--speed", type=float, default=1.0)
    start = parser.add_mutually_exclusive_group()
    start.add_argument("--exact", dest="exact", action="store_true", default=None,
                       help="Play from 0 so every earlier event is applied (default for Heck/Vivify maps)")
    start.add_argument("--fast-start", dest="exact", action="store_false",
                       help="Start 3 s before the first frame even for Heck/Vivify maps (inexact state)")
    parser.add_argument("--keep-open", action="store_true", help="Leave the game running and keep the lease")
    parser.add_argument("--no-hud", action="store_true", help="Hide the score HUD in frames")
    _common(parser, workspace=True)


def run_capture(args, emit):
    from .capture import parse_probe, parse_times, run_capture as capture
    emit(capture(_store(args), args.project, difficulty=args.difficulty, revision=args.revision,
                 times=parse_times(args.times) or None, every_beats=args.every_beats, probe=parse_probe(args.probe),
                 auto_probe=not args.no_probe, camera=args.camera, out=args.out, wait=args.wait, speed=args.speed,
                 exact=args.exact, keep_open=args.keep_open, width=args.width, height=args.height,
                 hud=not args.no_hud, probe_with_notes=args.probe_with_notes, **_options(args)))


SUBCOMMANDS = {
    "build-bridge": (register_build, run_build),
    "launch": (register_launch, run_launch),
    "status": (register_status, run_status),
    "play": (register_play, run_play),
    "install": (register_install, run_install),
    "seek": (_simple("seek", "Restart the leased level at a song time", arg="seconds"), run_seek),
    "pause": (_simple("pause", "Pause the leased level"), run_pause),
    "resume": (_simple("resume", "Resume the leased level"), run_resume),
    "restart": (_simple("restart", "Restart the leased level", arg="at"), run_restart),
    "stop": (_simple("stop", "Return the leased game to the menu"), run_stop),
    "close": (_simple("close", "Close the game this session launched and release the lease"), run_close),
    "refresh": (_simple("refresh", "Ask SongCore in the leased game to reload songs"), run_refresh),
    "capture": (register_capture, run_capture),
}

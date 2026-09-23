"""`sabermapper game ...` commands. Add a subcommand by registering (register, run) in SUBCOMMANDS."""
from __future__ import annotations

import argparse
from pathlib import Path

from .errors import GameError


def _identity(parser):
    parser.add_argument("--session", help="Session id; default: $SABERMAPPER_SESSION or sha1 of the git worktree path")
    parser.add_argument("--holder", help="Holder name; default: agent:<worktree folder>")


def _lease_root(parser):
    parser.add_argument("--lease-dir", type=Path, help=argparse.SUPPRESS)  # tests; else $SABERMAPPER_LEASE_DIR


def register_lease(actions):
    parser = actions.add_parser("lease", help="Machine-wide game lease: status (default), acquire, heartbeat, release")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--acquire", action="store_true", help="Acquire an agent lease for this session")
    mode.add_argument("--release", action="store_true", help="Release this session's lease (own lease only)")
    mode.add_argument("--heartbeat", action="store_true", help="Refresh this session's lease heartbeat")
    parser.add_argument("--purpose", help="Why the game is needed (required with --acquire)")
    parser.add_argument("--project", help="Project id the lease is for")
    parser.add_argument("--wait", type=float, default=0.0, help="Queue up to SECONDS for the lease instead of failing")
    _identity(parser)
    _lease_root(parser)


def run_lease(args, emit):
    from .lease import GameLease, public_lease
    manager = GameLease(args.lease_dir)
    if args.acquire:
        if not args.purpose:
            raise GameError("lease_invalid", "--acquire needs --purpose TEXT", fix="Pass --purpose 'capture PROJECT'")
        lease = manager.acquire(args.holder, session=args.session, project=args.project, purpose=args.purpose,
                                wait=args.wait)
        emit({"acquired": True, "lease": public_lease(lease, manager), "lease_file": str(manager.lease_file)})
    elif args.heartbeat:
        emit({"heartbeat": True, "lease": public_lease(manager.heartbeat(args.session), manager)})
    elif args.release:
        emit(manager.release(args.session))
    else:
        emit(manager.status(args.session))


def register_logs(actions):
    parser = actions.add_parser("logs", help="Structured Heck/Vivify/Noodle/Chroma/SongCore diagnostics from the game log")
    parser.add_argument("--log", type=Path, help="Log file; default: GAME_DIR/Logs/_latest.log")
    parser.add_argument("--game-dir", type=Path, help="Beat Saber install; default: $SABERMAPPER_GAME_DIR or Steam path")
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--since-level", action="store_true", help="Only lines after the last level start")
    scope.add_argument("--level", help="Only the last run of this level folder (path or folder name)")
    parser.add_argument("--all", action="store_true", dest="all_mods", help="Do not filter to mapping-relevant mods")
    parser.add_argument("--info", action="store_true", dest="include_info", help="Include info-level lines")
    parser.add_argument("--limit", type=int, default=200, help="Keep the newest N diagnostics (default 200)")


def run_logs(args, emit):
    from .logs import game_logs
    emit(game_logs(args.log, game_dir=args.game_dir, since_level=args.since_level, level=args.level,
                   all_mods=args.all_mods, limit=args.limit, include_info=args.include_info))


SUBCOMMANDS = {"lease": (register_lease, run_lease), "logs": (register_logs, run_logs)}


def register_game(commands):
    root = commands.add_parser("game", help="Beat Saber integration: lease, logs (errors print JSON and exit 2)")
    actions = root.add_subparsers(dest="game_action", required=True)
    for register, _ in SUBCOMMANDS.values():
        register(actions)


def dispatch_game(args, emit):
    """Run a game subcommand. Returns None when not a game command, else the exit code."""
    if args.command != "game":
        return None
    try:
        SUBCOMMANDS[args.game_action][1](args, emit)
        return 0
    except GameError as error:
        emit(error.to_dict())
        return 2

"""`game capture`: a self-contained leased run that renders a project in the real game and saves PNG frames.

Flow: acquire the agent lease (queue with --wait) -> launch FPFC if needed -> export + install + SongCore
refresh -> load at max(0, first time - preroll) (0 with --exact) -> capture -> write capture.json -> close the
game it launched and release the lease (unless --keep-open), also on error.

capture.json (schema 1, read by frames.py / frame_metrics.py):
{schema_version, project, revision, difficulty, camera, width, height, game_version, level_path, created_at,
 frames: [{file, requested_time, song_time, beat, section_id, reason, notes_hidden?}], log_diagnostics: [...]}
`notes_hidden: true` appears only on frames the bridge rendered with notes, bombs, chains and arcs hidden.

The dense flash probe hides notes by default (`probe.hide_notes`): nobody cuts notes during a capture, so uncut
notes fly through the FPFC camera and fill half the frame for one frame each, which a player never sees (they cut
notes about 1 m ahead). The flash check measures the scene. The bridge hides notes continuously from the first probe
frame to the end of the probe window and shows them again once, so the live game window never blinks them; regular
frames inside that window are also rendered without notes and flagged, and frames outside it keep their notes.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import time

from .api import Game, _bridge_view
from .errors import GameError
from .install import uses_custom_events
from .lease import LeaseHandle, held_lease, public_lease

SCHEMA_VERSION = 1
PREROLL = 3.0
DEFAULT_EVERY_BEATS = 16
PROBE_SECONDS, PROBE_FPS = 3.0, 30.0
MERGE_WINDOW = 0.1
END_MARGIN = 0.25
PRIORITY = {"requested": 0, "section_start": 1, "moment": 2, "grid": 3}
_PROBE = re.compile(r"^\s*(?P<start>\d+(?:\.\d+)?)\s*-\s*(?P<end>\d+(?:\.\d+)?)\s*(?:@\s*(?P<fps>\d+(?:\.\d+)?))?\s*$")


def frame_name(seconds: float) -> str:
    return f"t{seconds:08.3f}.png"


def parse_times(text: str | None) -> list[float]:
    if not text:
        return []
    try:
        values = [float(part) for part in text.split(",") if part.strip()]
    except ValueError:
        raise GameError("capture_invalid", f"--times must be comma-separated seconds, got {text!r}",
                        fix="Example: --times 12.5,30,61.25") from None
    if any(v < 0 for v in values):
        raise GameError("capture_invalid", "--times must be nonnegative seconds")
    return values


def parse_probe(text: str | None) -> dict | None:
    if not text:
        return None
    match = _PROBE.match(text)
    if not match or float(match["end"]) <= float(match["start"]):
        raise GameError("capture_invalid", f"--probe must look like START-END@FPS (seconds), got {text!r}",
                        fix="Example: --probe 40-43@30")
    fps = float(match["fps"] or PROBE_FPS)
    if not 0 < fps <= 120:
        raise GameError("capture_invalid", "--probe fps must be within 1..120")
    return {"start": float(match["start"]), "end": float(match["end"]), "fps": fps, "source": "requested"}


def project_moments(project_dir) -> list[dict]:
    """Key moments from the listen workstream (`latest_listen`), or [] when it is absent or has not run."""
    try:
        from ..listen import latest_listen
    except ImportError:
        return []
    try:
        data = latest_listen(project_dir) or {}
    except Exception:  # listen evidence is optional here; a broken run must not block capture
        return []
    return [m for m in data.get("moments") or [] if isinstance(m.get("time"), (int, float))]


def capture_plan(arrangement: dict, *, duration: float, times=None, every_beats: float | None = None,
                 moments=(), explicit_grid: bool = False) -> list[dict]:
    """Requested frames [{time, reason, name}] sorted by time; duplicates within 0.1 s keep the best reason.

    With explicit `times`, only those (plus the beat grid when `explicit_grid`); otherwise every section start,
    every key moment and every `every_beats` beats.
    """
    from ..critique import beat_to_seconds
    from ..frames import section_spans
    items = [(float(t), "requested") for t in times or []]
    if not times:
        items += [(s["start_seconds"], "section_start") for s in section_spans(arrangement)]
        items += [(float(m["time"]), "moment") for m in moments]
    if every_beats and (not times or explicit_grid):
        if every_beats <= 0:
            raise GameError("capture_invalid", "--every-beats must be positive")
        beat = 0.0
        while True:
            seconds = beat_to_seconds(beat, arrangement)
            if seconds > duration:
                break
            items.append((seconds, "grid"))
            beat += every_beats
    limit = max(0.0, duration - END_MARGIN) if duration else None
    plan = []
    for seconds, reason in sorted(items, key=lambda item: (item[0], PRIORITY[item[1]])):
        seconds = max(0.0, seconds if limit is None else min(seconds, limit))
        if plan and seconds - plan[-1]["time"] < MERGE_WINDOW:
            if PRIORITY[reason] < PRIORITY[plan[-1]["reason"]]:
                plan[-1]["reason"] = reason
            continue
        plan.append({"time": round(seconds, 3), "reason": reason, "name": frame_name(seconds)})
    return plan


def default_probe(arrangement: dict, *, duration: float, moments=()) -> dict | None:
    """A 3 s, 30 fps probe for the flash check: at the strongest key moment, else the densest notes."""
    from ..arrangement import expanded_notes
    from ..critique import beat_to_seconds
    span = min(PROBE_SECONDS, duration) if duration else PROBE_SECONDS
    if moments:
        best = max(moments, key=lambda m: (m.get("kind") in ("drop", "final_chorus"), m.get("strength") or 0))
        start = float(best["time"])
        source = f"moment {best.get('id') or best.get('kind')}"
    else:
        try:
            seconds = sorted(beat_to_seconds(n["beat"], arrangement) for n in expanded_notes(arrangement))
        except (KeyError, ValueError, TypeError):
            seconds = []
        if not seconds:
            return None
        j, best_count, start = 0, -1, seconds[0]
        for i, t in enumerate(seconds):
            while seconds[j] < t - span:
                j += 1
            if i - j + 1 > best_count:
                best_count, start = i - j + 1, max(0.0, t - span)
        source = f"densest notes ({best_count} in {span:g} s)"
    if duration:
        start = max(0.0, min(start, duration - span - END_MARGIN))
    return {"start": round(start, 3), "end": round(start + span, 3), "fps": PROBE_FPS, "source": source}


def _annotate(frame: dict, arrangement: dict, spans: list[dict]) -> dict:
    from ..musical import seconds_to_beat
    seconds = frame["song_time"] if frame.get("song_time") is not None else frame["requested_time"]
    beat = seconds_to_beat(seconds, arrangement)
    frame["beat"] = round(float(beat), 4) if beat is not None else None
    frame["section_id"] = next((s["id"] for s in spans if s["start_seconds"] <= seconds < s["end_seconds"]), None)
    return frame


def build_manifest(*, meta: dict, results: list[dict], plan: list[dict], arrangement: dict,
                   log_diagnostics: list) -> dict:
    from ..frames import section_spans
    spans = section_spans(arrangement)
    reasons = {item["name"]: item["reason"] for item in plan}
    frames = []
    for result in results:
        if not result.get("written"):
            continue
        name = result["name"]
        frame = _annotate({"file": name, "requested_time": result.get("requested_time"),
                           "song_time": result.get("song_time"),
                           "reason": "probe" if result.get("reason") == "probe" else reasons.get(name, "requested")},
                          arrangement, spans)
        if result.get("notes_hidden"):
            frame["notes_hidden"] = True
        frames.append(frame)
    frames.sort(key=lambda f: (f["song_time"] if f["song_time"] is not None else f["requested_time"], f["file"]))
    return {"schema_version": SCHEMA_VERSION, **meta, "frames": frames, "log_diagnostics": log_diagnostics}


@contextmanager
def _capture_lease(game: Game, *, keep_open: bool, **acquire):
    """held_lease (closes the game it launched and releases on exit), or a kept lease with --keep-open."""
    def close_if_launched(owned):
        if owned.get("launched_by_agent") and owned.get("game_pid"):
            game.closer(owned["game_pid"])
    if keep_open:
        lease = game.manager.acquire(game.holder, session=game.session, **acquire)
        yield LeaseHandle(game.manager, game.session, lease)
        return
    with held_lease(game.holder, session=game.session, manager=game.manager, on_release=close_if_launched,
                    **acquire) as handle:
        yield handle


def run_capture(store, project_id: str, *, difficulty: str | None = None, revision: str | None = None,
                times=None, every_beats: float | None = None, probe: dict | None = None, auto_probe: bool = True,
                camera: str = "player", out: str | Path | None = None, wait: float = 0.0, speed: float = 1.0,
                exact: bool | None = None, keep_open: bool = False, width: int | None = None, height: int | None = None,
                hud: bool = True, probe_with_notes: bool = False, game: Game | None = None, **options) -> dict:
    from ..revisions import arrangement_revision
    from ..storage import read_json
    if camera not in ("player", "wide"):
        raise GameError("capture_invalid", "--camera must be player or wide")
    game = game or Game(**options)
    with store.lock:
        path = store.directory(project_id)
        arrangement = read_json(store.arrangement_file(path, difficulty))
        duration = float(read_json(path / "project.json").get("duration_seconds") or 0)
    current = arrangement_revision(arrangement)
    if revision not in (None, current):
        old = store.revision_arrangement(path, revision, arrangement["difficulty"]["name"])
        if old is None:
            raise GameError("stale_revision", f"Revision {str(revision)[:12]} is not a saved revision of {project_id}",
                            {"current_revision": current}, fix="Omit --revision to capture the current revision")
        arrangement = old
    revision = revision or current
    moments = project_moments(path)
    plan = capture_plan(arrangement, duration=duration, times=times, moments=moments,
                        every_beats=every_beats if every_beats is not None else (None if times else DEFAULT_EVERY_BEATS),
                        explicit_grid=every_beats is not None)
    if probe is None and auto_probe:
        probe = default_probe(arrangement, duration=duration, moments=moments)
    if not plan and not probe:
        raise GameError("capture_invalid", "Nothing to capture", fix="Pass --times, --every-beats or --probe")
    if probe:
        probe = {**probe, "hide_notes": not probe_with_notes}
    starts = [item["time"] for item in plan] + ([probe["start"]] if probe else [])
    ends = [item["time"] for item in plan] + ([probe["end"]] if probe else [])
    preroll_start = max(0.0, min(starts) - PREROLL)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = Path(out) if out else path / "captures" / f"{revision[:10]}-{stamp}"
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    report = {"project": project_id, "revision": revision, "difficulty": arrangement["difficulty"]["name"],
              "capture_dir": str(out_dir), "speed": speed,
              "planned": len(plan), "probe": probe, "launched": False, "closed": None}
    with _capture_lease(game, keep_open=keep_open, project=project_id, purpose=f"capture {project_id}",
                        wait=wait) as handle:
        info = game.ensure_running(handle.lease, fpfc=True)
        report["launched"], report["pid"] = info["launched"], info["pid"]
        handle.check()
        client = game.client_factory(handle.token)
        ready = game.wait_ready(client, info["pid"])
        handle.check()
        installed = game.install_refresh(client, store, project_id, difficulty=difficulty, revision=revision)
        level_path = installed["level_path"]
        custom = uses_custom_events(level_path)
        exact = custom if exact is None else exact
        start = 0.0 if exact else preroll_start
        report.update(start_time=start, exact=exact, custom_events=custom)
        client.load(level_path=level_path, difficulty=installed["export"]["difficulty"], start_time=start,
                    speed=speed, modifiers="no_fail", hud=hud)
        job = client.capture(out_dir=out_dir, camera=camera, width=width, height=height, probe=probe and {
            k: probe[k] for k in ("start", "end", "fps", "hide_notes")},
            frames=[{"time": item["time"], "name": item["name"], "reason": item["reason"]} for item in plan])
        report["job_id"] = job.get("job_id")
        final = _wait_capture(client, handle, timeout=(max(ends) - start) / max(speed, 0.1) + 90)
        status = client.capture_status() or {}
        results = status.get("frames") or []
        if final.get("scene") == "game":
            client.menu()
        health = ready["health"]
        from .logs import game_logs
        try:
            diagnostics = game_logs(game_dir=game.game_dir, level=level_path)["diagnostics"]
        except (GameError, OSError) as error:  # frames are still valid without log diagnostics
            diagnostics = [{"severity": "warning", "code": getattr(error, "code", "log_unreadable"),
                            "message": f"Game log diagnostics unavailable: {error}"}]
        size = _frame_size(out_dir, results) or (width, height)
        meta = {"project": project_id, "revision": revision, "difficulty": arrangement["difficulty"]["name"],
                "camera": camera, "width": size[0], "height": size[1],
                "game_version": game_build(game.game_dir) or health.get("game_version"),
                "level_path": level_path, "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "start_time": start, "exact": exact, "speed": speed, "probe": probe,
                "bridge_version": health.get("bridge_version")}
        manifest = build_manifest(meta=meta, results=results, plan=plan, arrangement=arrangement,
                                  log_diagnostics=diagnostics)
        (out_dir / "capture.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        missing = [r["name"] for r in results if not r.get("written")]
        captured = {r["name"] for r in results}
        probe_frames = [f for f in manifest["frames"] if f["reason"] == "probe"]
        hidden = sum(1 for f in probe_frames if f.get("notes_hidden"))
        report["probe_notes_hidden"] = {"requested": bool(probe and probe["hide_notes"]), "frames": len(probe_frames),
                                        "notes_hidden": hidden,
                                        "regular_frames_notes_hidden": [f["file"] for f in manifest["frames"]
                                                                        if f["reason"] != "probe" and f.get("notes_hidden")]}
        if probe and probe["hide_notes"] and probe_frames and hidden < len(probe_frames):
            report["warnings"] = [{
                "code": "probe_notes_visible",
                "message": f"{len(probe_frames) - hidden} of {len(probe_frames)} probe frames were rendered with notes "
                           f"visible (bridge {health.get('bridge_version')}); uncut notes flying through the camera "
                           "can read as flashes.",
                "fix": "Run `sabermapper game build-bridge --install` with the game closed, then capture again"}]
        report.update(status=status.get("status"), frames=len(manifest["frames"]),
                      not_reached=[item["name"] for item in plan if item["name"] not in captured],
                      failed=missing, dropped=status.get("dropped"), manifest=str(out_dir / "capture.json"),
                      log_errors=sum(1 for d in diagnostics if d.get("severity") == "error"),
                      final_state=_bridge_view(final), lease=public_lease(handle.lease))
    report["closed"] = not keep_open and report["launched"]
    return report


def game_build(game_dir=None) -> str | None:
    """Full game build from BeatSaberVersion.txt (e.g. 1.40.8_7379); the bridge reports only 1.40.8."""
    from .logs import default_game_dir
    try:
        return (default_game_dir(game_dir) / "BeatSaberVersion.txt").read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def _frame_size(out_dir: Path, results: list[dict]) -> tuple[int, int] | None:
    from PIL import Image
    for result in results:
        if result.get("written"):
            try:
                with Image.open(out_dir / result["name"]) as image:
                    return image.size
            except OSError:
                continue
    return None


def _wait_capture(client, handle, *, timeout: float) -> dict:
    """Poll until the bridge job finishes, the level ends without reaching every frame, or the deadline."""
    deadline = time.monotonic() + timeout
    started, left_at = False, None
    state = client.state()
    while True:
        handle.check()
        job = state.get("capture") or {}
        if job.get("status") in ("done", "failed", "cancelled"):
            return state
        in_level = state.get("scene") == "game"
        started = started or in_level
        if started and not in_level and state.get("scene") != "loading":
            left_at = left_at or time.monotonic()
            if time.monotonic() - left_at > 3.0:
                client.capture_cancel()
                return client.state()
        if time.monotonic() > deadline:
            client.capture_cancel()
            raise GameError("timeout", f"Capture did not finish within {timeout:.0f} s", {"state": state},
                            fix="Check `sabermapper game logs --since-level`; retry with fewer frames or --speed")
        state = client.state(wait_ms=1000, since=state.get("version"))

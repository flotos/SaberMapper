"""Research subcommands for the shared SaberMapper CLI."""

from __future__ import annotations

import json
from pathlib import Path

from .corpus import CorpusStore, corpus_report, coverage_report, ingest_seeds, process_all, seeds_from_candidate_snapshot
from .evaluation import SplitRegistry
from .learning import LabelStore, label_report, train_and_record
from .patterns import retrieve_patterns
from .profile import player_profile, summarize_scores
from .star_tiers import TIER_IDS, load_profile, player_tiers


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def _write(path, data):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(target.suffix + ".part")
    temp.write_text(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(target)


def _leaf(parent, name):
    sub = parent.add_parser(name)
    sub.add_argument("--workspace", type=Path, default=Path("workspace"))
    return sub


def register_subcommands(subparsers):
    corpus = subparsers.add_parser("corpus", help="Exact-version corpus ingestion and processing")
    c = corpus.add_subparsers(dest="research_action", required=True)
    _leaf(c, "status")
    analyze = _leaf(c, "analyze")
    analyze.add_argument("--min-stars", type=float, default=6.5)
    analyze.add_argument("--max-stars", type=float, default=8)
    analyze.add_argument("--shortlist-limit", type=int, default=60)
    analyze.add_argument("--tier-shortlist-limit", type=int, default=40,
                         help="References per star tier in tier-pattern-shortlist.json")
    tiers = _leaf(c, "tiers")
    tiers.add_argument("--tier", choices=TIER_IDS, help="Show one tier in full")
    local = _leaf(c, "import")
    local.add_argument("archive", type=Path)
    local.add_argument("--hash", required=True)
    local.add_argument("--retain-audio", action="store_true")
    fetch = _leaf(c, "fetch")
    fetch.add_argument("hash")
    fetch.add_argument("--max-bytes", type=int, default=64_000_000)
    fetch.add_argument("--retain-audio", action="store_true")
    batch = _leaf(c, "batch")
    batch.add_argument("seeds", type=Path)
    batch.add_argument("--max-items", type=int, default=100)
    batch.add_argument("--max-bytes", type=int, default=500_000_000)
    process = _leaf(c, "process")
    process.add_argument("--max-maps", type=int, default=100)
    process.add_argument("--max-seconds", type=float, default=300)
    retrieve = _leaf(c, "retrieve")
    retrieve.add_argument("--bpm", type=float)
    retrieve.add_argument("--nps", type=float)
    retrieve.add_argument("--length-beats", type=float)
    retrieve.add_argument("--forbid-song-family", action="append", default=[])
    retrieve.add_argument("--limit", type=int, default=8)
    retrieve.add_argument("--player-fit", action="store_true", help="Use PLAYER.md provisional 6.5-8 ScoreSaber-star band")
    retrieve.add_argument("--min-stars", type=float)
    retrieve.add_argument("--max-stars", type=float)
    retrieve.add_argument("--pattern-tag", help="Observable category such as varied_spacing or alternating_hands")
    retrieve.add_argument("--tier", choices=TIER_IDS,
                          help="Player star tier of the source chart (see `corpus tiers`)")
    cleanup = _leaf(c, "cleanup")
    cleanup.add_argument("hash")
    profile = subparsers.add_parser("profile", help="Historical calibration and explicit preferences")
    p = profile.add_subparsers(dest="research_action", required=True)
    calibrate = _leaf(p, "calibrate")
    calibrate.add_argument("snapshot", type=Path)
    feedback = _leaf(p, "feedback")
    feedback.add_argument("record", type=Path, help="JSON with liked/disliked arrays and optional overrides")
    labels = subparsers.add_parser("labels", help="Provenanced pairwise research labels")
    l = labels.add_subparsers(dest="research_action", required=True)
    add = _leaf(l, "add")
    add.add_argument("record", type=Path)
    _leaf(l, "report")
    train = _leaf(l, "train")
    train.add_argument("--dimension", default="enjoyment")
    train.add_argument("--min-labels", type=int, default=20)
    train.add_argument("--min-heldout", type=int, default=10)
    splits = subparsers.add_parser("splits", help="Freeze song-family evaluation membership")
    s = splits.add_subparsers(dest="research_action", required=True)
    freeze = _leaf(s, "freeze")
    freeze.add_argument("records", type=Path)
    freeze.add_argument("--output", type=Path, required=True)
    development = _leaf(s, "mark-development")
    development.add_argument("records", type=Path)
    development.add_argument("--reason", required=True)


def dispatch(args) -> bool:
    command = getattr(args, "command", None)
    if command not in {"corpus", "profile", "labels", "splits"}:
        return False
    workspace = args.workspace
    workspace.mkdir(parents=True, exist_ok=True)
    action = args.research_action
    if command == "corpus":
        store = CorpusStore(workspace / "corpus")
        try:
            if action == "status":
                result = {"corpus": corpus_report(store.rows()), "library": store.library_summary(limit=0)}
            elif action == "analyze":
                from .corpus_analysis import analyze_corpus
                result = analyze_corpus(store, min_stars=args.min_stars, max_stars=args.max_stars,
                                        shortlist_limit=args.shortlist_limit,
                                        tier_shortlist_limit=args.tier_shortlist_limit)
            elif action == "tiers":
                reference_path = workspace / "corpus" / "tier-reference.json"
                reference = _read(reference_path) if reference_path.exists() else None
                rows = reference["tiers"] if reference else player_tiers(load_profile(workspace))
                if args.tier:
                    result = next(row for row in rows if row["id"] == args.tier)
                else:
                    result = {"generated_utc": reference and reference["generated_utc"],
                              "note": None if reference else "No tier-reference.json yet; run `corpus analyze`.",
                              "tiers": [{k: row.get(k) for k in ("id", "label", "role", "charts", "windows")} |
                                        ({"median_window_nps": row["window_nps"].get("median"),
                                          "median_swings_per_second": row["window_movement"]["swing_rate_per_second"].get("median"),
                                          "median_peak_one_second_swings": row["window_movement"]["peak_one_second_swing_count"].get("median"),
                                          "median_chart_nps": row["chart_nps"].get("median"),
                                          "median_chart_njs": row["chart_njs"].get("median")} if reference else {})
                                        for row in rows]}
            elif action == "import":
                result = store.import_archive(args.archive.read_bytes(), version_hash=args.hash,
                                              retain_audio=args.retain_audio,
                                              provenance={"local_archive": str(args.archive.resolve())})
            elif action == "fetch":
                result = store.fetch_exact(args.hash, retain_audio=args.retain_audio,
                                           max_download_bytes=args.max_bytes)
            elif action == "batch":
                source = _read(args.seeds)
                seeds = source.get("seeds", source.get("candidates")) if isinstance(source, dict) else source
                if not isinstance(seeds, list):
                    raise ValueError("seed file requires seeds array")
                if seeds and "hash" not in seeds[0] and isinstance(source, dict):
                    seeds = seeds_from_candidate_snapshot(source)
                result = ingest_seeds(store, seeds, max_items=args.max_items,
                                      max_new_archive_bytes=args.max_bytes)
                _write(workspace / "corpus" / "last-batch.json", result)
            elif action == "process":
                result = store.process_all(max_maps=args.max_maps, max_seconds=args.max_seconds)
            elif action == "retrieve":
                from .corpus_analysis import chart_records, filter_patterns, pattern_tags
                charts = chart_records(store)
                lower, upper = getattr(args, "min_stars", None), getattr(args, "max_stars", None)
                if getattr(args, "player_fit", False):
                    lower = 6.5 if lower is None else lower
                    upper = 8 if upper is None else upper
                patterns = filter_patterns(store.catalog_patterns(), charts, min_stars=lower, max_stars=upper,
                                           tag=getattr(args, "pattern_tag", None), tier=getattr(args, "tier", None))
                result = retrieve_patterns(patterns, bpm=args.bpm, target_nps=args.nps,
                                           length_beats=args.length_beats,
                                           forbidden_song_families=set(args.forbid_song_family),
                                           limit=args.limit)
                for item in result:
                    pattern = item["pattern"]
                    item["source_chart"] = charts.get((pattern["version_hash"], pattern["difficulty"]))
                    item["star_tier"] = (item["source_chart"] or {}).get("star_tier")
                    item["pattern_tags"] = pattern_tags(pattern)
                    item["review_status"] = "unreviewed"
            elif action == "cleanup":
                result = store.discard_archive_after_processing(args.hash)
            else:
                raise ValueError(f"unknown corpus action {action}")
        finally:
            store.close()
    elif command == "profile":
        path = workspace / "player-profile.json"
        if action == "calibrate":
            snapshot = _read(args.snapshot)
            summary = summarize_scores(snapshot)
            existing = _read(path) if path.exists() else {}
            result = player_profile(player_id=summary["player_id"], score_summary=summary,
                                    liked=existing.get("liked"), disliked=existing.get("disliked"),
                                    overrides=existing.get("overrides"))
        elif action == "feedback":
            if not path.exists():
                raise ValueError("run profile calibrate first")
            result = _read(path)
            change = _read(args.record)
            for key in ("liked", "disliked"):
                if key in change:
                    if not isinstance(change[key], list):
                        raise ValueError(f"{key} must be an array")
                    result[key].extend(change[key])
            result["overrides"].update(change.get("overrides", {}))
        else:
            raise ValueError(f"unknown profile action {action}")
        _write(path, result)
    elif command == "labels":
        store = LabelStore(workspace / "labels.json")
        if action == "add":
            result = store.append(_read(args.record))
        elif action == "report":
            result = label_report(store.labels())
        elif action == "train":
            registry = SplitRegistry(workspace / "corpus" / "splits.json")
            train_families = {family for family, split in registry.data["families"].items()
                              if split in {"train", "development"}}
            heldout_families = {family for family, split in registry.data["families"].items()
                                if split in {"validation", "test"}}
            human_count = sum(label["origin"] == "human" and label["dimension"] == args.dimension
                              and label["winner"] in {"left", "right"} for label in store.labels())
            patterns = {}
            if human_count >= args.min_labels:
                catalog = _read(workspace / "corpus" / "patterns.json")
                patterns = {p["id"]: p for p in catalog["patterns"]}
            result = train_and_record(patterns, store.labels(), train_families=train_families,
                                      heldout_families=heldout_families,
                                      output=workspace / f"ranker-{args.dimension}.json",
                                      dimension=args.dimension, min_labels=args.min_labels,
                                      min_heldout_pairs=args.min_heldout)
        else:
            raise ValueError(f"unknown labels action {action}")
    else:
        from .storage import WorkspaceLock
        with WorkspaceLock(workspace / "corpus" / "catalog.lock"):
            registry = SplitRegistry(workspace / "corpus" / "splits.json")
            records = _read(args.records)
            if isinstance(records, dict):
                records = records.get("records", records.get("seeds", records.get("version_hashes", [])))
            if action == "mark-development":
                result = registry.mark_development(
                    [r if isinstance(r, str) else r.get("version_hash", r.get("hash")) for r in records],
                    reason=args.reason)
            else:
                result = registry.freeze([{"version_hash": r.get("version_hash", r.get("hash")),
                                           "audio_sha256": r.get("audio_sha256"),
                                           "family_id": r.get("family_id")} for r in records], args.output)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return True

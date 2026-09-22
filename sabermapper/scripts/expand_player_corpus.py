"""Explicit, bounded local reference search and ingestion; never run at app startup."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sabermapper.corpus import CorpusStore, _atomic_json, _read_url, ingest_seeds


def select_candidates(documents, existing_hashes, quotas=None):
    quotas = quotas or {"player_target": 80, "easier_contrast": 10, "challenge": 10}
    candidates, excluded = [], []
    for item in documents:
        if item.get("automapper") or not item.get("ranked"):
            excluded.append({"map_id": item.get("id"), "reason": "automapped or not ScoreSaber ranked"})
            continue
        versions = [v for v in item.get("versions", []) if v.get("state") == "Published"]
        if not versions:
            excluded.append({"map_id": item.get("id"), "reason": "no published version"})
            continue
        version = max(versions, key=lambda v: v.get("createdAt", ""))
        hash_ = version.get("hash", "").upper()
        if len(hash_) != 40 or any(c not in "0123456789ABCDEF" for c in hash_) or hash_ in existing_hashes:
            excluded.append({"map_id": item.get("id"), "reason": "invalid or already inventoried exact version"})
            continue
        meta = item.get("metadata", {})
        for diff in version.get("diffs", []):
            stars = diff.get("stars") or 0
            if diff.get("characteristic") != "Standard" or diff.get("ne") or diff.get("me"):
                excluded.append({"map_id": item.get("id"), "difficulty": diff.get("difficulty"),
                                 "reason": "non-Standard or requires gameplay mods"})
                continue
            cohort = ("player_target" if 6.5 <= stars <= 8 else
                      "easier_contrast" if 5 <= stars < 6.5 else
                      "challenge" if 8 < stars <= 9 else None)
            if cohort:
                candidates.append({"hash": hash_, "map_id": item["id"], "song": meta.get("songName"),
                    "mapper": meta.get("levelAuthorName", "unknown"), "era": item.get("uploaded", "")[:4],
                    "difficulty": diff["difficulty"], "characteristic": "Standard", "stars": stars,
                    "rating_source": "BeatSaver exact-version diffs[].stars (ScoreSaber)",
                    "nps": diff.get("nps"), "bpm": meta.get("bpm"), "tags": item.get("tags") or [],
                    "cohort": cohort, "retain_audio": False, "reviewed": False,
                    "rights_status": "redistribution_unknown; local reference study only",
                    "source_url": f"https://api.beatsaver.com/maps/hash/{hash_}"})
            else:
                excluded.append({"map_id": item.get("id"), "difficulty": diff.get("difficulty"),
                                 "stars": stars, "reason": "unrated or outside 5-9 star research range"})
    selected, seen, maps = [], set(existing_hashes), set()
    mappers, eras, counts = Counter(), Counter(), Counter()
    for cohort, quota in quotas.items():
        pool = [c for c in candidates if c["cohort"] == cohort]
        while counts[cohort] < quota:
            eligible = [c for c in pool if c["hash"] not in seen and c["map_id"] not in maps
                        and mappers[c["mapper"].casefold()] < 3]
            if not eligible:
                break
            choice = min(eligible, key=lambda c: (mappers[c["mapper"].casefold()], eras[c["era"]],
                abs(c["stars"] - {"player_target": 7.43, "easier_contrast": 5.75, "challenge": 8.5}[cohort]), c["hash"]))
            selected.append(choice)
            seen.add(choice["hash"])
            maps.add(choice["map_id"])
            mappers[choice["mapper"].casefold()] += 1
            eras[choice["era"]] += 1
            counts[cohort] += 1
    return {"schema_version": "1.0", "seeds": selected, "quotas": quotas, "counts": dict(counts),
            "gaps": {c: n-counts[c] for c, n in quotas.items()}, "eligible_charts": len(candidates),
            "mapper_counts": dict(mappers), "eras": dict(eras),
            "selection": "Exact Standard difficulty stars; maximum three new versions per mapper; balance eras.",
            "excluded": excluded, "role": "development_only_unreviewed"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["search", "ingest"])
    parser.add_argument("--workspace", type=Path, default=Path("workspace"))
    parser.add_argument("--max-bytes", type=int, default=1_000_000_000)
    args = parser.parse_args()
    root = args.workspace / "corpus"
    store = CorpusStore(root)
    try:
        if args.action == "search":
            docs, searches = {}, []
            # Search multiple styles and upload eras; filter exact ratings locally.
            jobs = [("", {"tags": tag}) for tag in ("tech", "balanced", "dance-style", "speed", "accuracy", "rock|metal", "electronic")]
            jobs += [("", {"from": f"{year}-01-01T00:00:00Z", "to": f"{year}-12-31T23:59:59Z"}) for year in range(2019, 2027)]
            for query, filters in jobs:
                for page in range(3):
                    params = {"q": query, "leaderboard": "ScoreSaber", "order": "Rating", **filters}
                    url = f"https://api.beatsaver.com/search/v1/{page}?{urlencode(params)}"
                    try:
                        payload = json.loads(_read_url(url, max_bytes=4_000_000, timeout=20))
                        found = payload.get("docs", [])
                        searches.append({"url": url, "count": len(found)})
                        for item in found:
                            docs[item["id"]] = item
                        print(json.dumps({"filters": filters, "page": page, "found": len(found), "unique": len(docs)}), flush=True)
                        if not found:
                            break
                    except (OSError, ValueError) as exc:
                        searches.append({"url": url, "error": str(exc)})
                    time.sleep(.25)
            now = datetime.now(timezone.utc).isoformat()
            _atomic_json(root / "player-expansion-search.json", {"retrieved_utc": now, "searches": searches, "documents": list(docs.values())})
            manifest = select_candidates(list(docs.values()), {r["version_hash"] for r in store.rows()})
            manifest.update({"retrieved_utc": now, "unique_search_maps": len(docs)})
            manifest["existing_hashes_at_search"] = sorted(r["version_hash"] for r in store.rows())
            _atomic_json(root / "player-expansion-seeds.json", manifest)
            print(json.dumps({k: v for k, v in manifest.items() if k not in {"seeds", "mapper_counts", "excluded"}}, indent=2))
        else:
            manifest = json.loads((root / "player-expansion-seeds.json").read_text(encoding="utf-8"))
            done = {r["version_hash"] for r in store.rows() if r["status"] == "processed"}
            results, spent = [], 0
            for i, seed in enumerate(manifest["seeds"]):
                if seed["hash"] in done:
                    continue
                report = ingest_seeds(store, [seed], max_items=1, max_new_archive_bytes=max(0, args.max_bytes-spent))
                spent += report["new_archive_bytes"]
                results.extend(report["results"])
                _atomic_json(root / "player-expansion-ingest.json", {"new_archive_bytes": spent, "results": results})
                print(json.dumps({"item": i+1, "bytes": spent, "result": report["results"]}), flush=True)
                if any(r["status"] == "budget_exhausted" for r in report["results"]):
                    break
                time.sleep(.25)
    finally:
        store.close()


if __name__ == "__main__":
    main()

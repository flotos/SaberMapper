"""Bounded, exact-version BeatSaver and local archive corpus storage."""

from __future__ import annotations

import hashlib
import io
import json
import os
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
import sqlite3
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile


API = "https://api.beatsaver.com"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_zip_members(data: bytes, *, max_files: int = 256,
                     max_expanded_bytes: int = 256_000_000,
                     max_member_bytes: int = 128_000_000) -> list[zipfile.ZipInfo]:
    """Validate an untrusted ZIP before any member is read or extracted."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
        entries = archive.infolist()
        if not entries or len(entries) > max_files:
            raise ValueError("archive file count outside budget")
        seen, total = set(), 0
        for item in entries:
            name = item.filename.replace("\\", "/")
            path = PurePosixPath(name)
            if not path.parts or name.startswith("/") or path.is_absolute() or ".." in path.parts or ":" in path.parts[0]:
                raise ValueError(f"unsafe archive path: {name}")
            key = str(path).casefold()
            if key in seen:
                raise ValueError(f"duplicate archive path: {name}")
            seen.add(key)
            mode = (item.external_attr >> 16) & 0o170000
            if mode == 0o120000:
                raise ValueError(f"archive link rejected: {name}")
            if item.flag_bits & 1:
                raise ValueError("encrypted archive member")
            total += item.file_size
            if item.file_size > max_member_bytes or total > max_expanded_bytes:
                raise ValueError("expanded archive size exceeds budget")
            if item.file_size > 1_000_000 and item.file_size > max(item.compress_size, 1) * 500:
                raise ValueError("archive compression ratio exceeds budget")
        if archive.testzip() is not None:
            raise ValueError("archive CRC failure")
        return entries
    except (zipfile.BadZipFile, EOFError) as exc:
        raise ValueError("invalid ZIP archive") from exc


def beat_saber_map_hashes(data: bytes) -> set[str]:
    """Candidate game-style SHA-1 hashes for v2 and v4 Info file layouts."""
    safe_zip_members(data)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = {PurePosixPath(name).name.casefold(): name for name in archive.namelist()}
        info_name = names.get("info.dat")
        if not info_name:
            raise ValueError("Info.dat missing for map hash")
        info_bytes = archive.read(info_name)
        try:
            info = json.loads(info_bytes.decode("utf-8-sig"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("invalid Info.dat for map hash") from exc
        groups = info.get("_difficultyBeatmapSets", info.get("difficultyBeatmapSets", []))
        direct = info.get("difficultyBeatmaps", [])
        if not groups and not direct:
            raise ValueError("no declared difficulties for map hash")
        entries = [entry for group in groups for entry in group.get("_difficultyBeatmaps", group.get("difficultyBeatmaps", []))] + direct
        data_bytes, light_bytes = [], []
        for entry in entries:
                filename = entry.get("_beatmapFilename", entry.get("beatmapDataFilename", entry.get("beatmapFilename")))
                match = names.get(PurePosixPath(str(filename)).name.casefold())
                if not match:
                    raise ValueError(f"declared difficulty missing: {filename}")
                data_bytes.append(archive.read(match))
                light_file = entry.get("lightshowDataFilename")
                if light_file:
                    light_match = names.get(PurePosixPath(light_file).name.casefold())
                    if not light_match:
                        raise ValueError(f"declared lightshow missing: {light_file}")
                    light_bytes.append(archive.read(light_match))
        def digest(chunks):
            value = hashlib.sha1(info_bytes)
            for chunk in chunks:
                value.update(chunk)
            return value.hexdigest().upper()
        candidates = {digest(data_bytes)}
        if light_bytes:
            candidates.add(digest(data_bytes + light_bytes))
        return candidates


def beat_saber_map_hash(data: bytes) -> str:
    """Return a deterministic hash; use hashes() when verifying v4 variants."""
    return sorted(beat_saber_map_hashes(data))[0]


def _read_url(url: str, *, max_bytes: int, timeout: float, retries: int = 2) -> bytes:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in {"api.beatsaver.com", "cdn.beatsaver.com", "r2cdn.beatsaver.com"}:
        raise ValueError("URL must use approved BeatSaver HTTPS host")
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "SaberMapper/0.1 (bounded research client)"})
            with urllib.request.urlopen(req, timeout=timeout) as response:
                if urllib.parse.urlparse(response.url).hostname not in {"api.beatsaver.com", "cdn.beatsaver.com", "r2cdn.beatsaver.com"}:
                    raise ValueError("download redirected outside approved host")
                payload = response.read(max_bytes + 1)
            if len(payload) > max_bytes:
                raise ValueError("download byte budget exceeded")
            return payload
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise FileNotFoundError(url) from exc
            if exc.code not in {429, 500, 502, 503, 504} or attempt == retries:
                raise
            time.sleep(min(2 ** attempt, 4))
        except (TimeoutError, urllib.error.URLError):
            if attempt == retries:
                raise
            time.sleep(min(2 ** attempt, 4))
    raise RuntimeError("request retry exhausted")


def fetch_metadata_exact(map_hash: str, *, timeout: float = 10) -> dict:
    expected = map_hash.upper()
    if len(expected) != 40 or any(c not in "0123456789ABCDEF" for c in expected):
        raise ValueError("BeatSaver version hash must be 40 hex characters")
    payload = json.loads(_read_url(f"{API}/maps/hash/{expected}", max_bytes=2_000_000, timeout=timeout))
    if isinstance(payload, list):
        payload = next((row for row in payload if any(v.get("hash", "").upper() == expected for v in row.get("versions", []))), None)
    if not isinstance(payload, dict) or not any(v.get("hash", "").upper() == expected for v in payload.get("versions", [])):
        raise ValueError("BeatSaver response lacks requested exact version")
    return payload


def discover_maps(query: str, *, pages: int = 1, max_results: int = 100,
                  curated: bool | None = None, leaderboard: str | None = None,
                  tags: str | None = None, from_date: str | None = None,
                  to_date: str | None = None, timeout: float = 10) -> list[dict]:
    """Bounded metadata-only search using documented BeatSaver search/v1 pages."""
    if not query.strip() or not 1 <= pages <= 10 or not 1 <= max_results <= 200:
        raise ValueError("query and bounded pages/results required")
    if leaderboard not in {None, "All", "Ranked", "BeatLeader", "ScoreSaber"}:
        raise ValueError("invalid leaderboard filter")
    params = {"q": query}
    if curated is not None:
        params["curated"] = str(curated).lower()
    if leaderboard:
        params["leaderboard"] = leaderboard
    if tags:
        params["tags"] = tags
    if from_date:
        params["from"] = from_date
    if to_date:
        params["to"] = to_date
    found, seen = [], set()
    for page in range(pages):
        url = f"{API}/search/v1/{page}?{urllib.parse.urlencode(params)}"
        response = json.loads(_read_url(url, max_bytes=4_000_000, timeout=timeout))
        docs = response.get("docs", [])
        if not isinstance(docs, list):
            raise ValueError("invalid BeatSaver search response")
        for item in docs:
            if not isinstance(item, dict) or item.get("id") in seen:
                continue
            seen.add(item.get("id"))
            found.append(item)
            if len(found) >= max_results:
                return found
        if not docs:
            break
    return found


def select_corpus_seeds(candidates: list[dict], *, quotas: dict[str, int],
                        exclude_mods: set[str] | None = None) -> dict:
    """Apply explicit cohort quotas to metadata, retaining exclusions and gaps."""
    selected, excluded, counts = [], [], {cohort: 0 for cohort in quotas}
    excluded_mods = exclude_mods or {"ne", "me"}
    seen = set()
    for item in candidates:
        version_hash = str(item.get("hash", "")).upper()
        cohort = item.get("cohort")
        if version_hash in seen:
            excluded.append({"hash": version_hash, "reason": "duplicate version"})
        elif any(item.get(mod) for mod in excluded_mods):
            excluded.append({"hash": version_hash, "reason": "excluded mod"})
        elif len(version_hash) != 40 or any(c not in "0123456789ABCDEF" for c in version_hash):
            excluded.append({"hash": version_hash, "reason": "missing exact version hash"})
        elif cohort not in quotas:
            excluded.append({"hash": version_hash, "reason": "unknown cohort"})
        elif counts[cohort] >= quotas[cohort]:
            excluded.append({"hash": version_hash, "reason": "cohort quota full"})
        else:
            selected.append(item)
            seen.add(version_hash)
            counts[cohort] += 1
    return {"selected": selected, "excluded": excluded,
            "counts": counts, "gaps": {key: max(0, quota - counts[key]) for key, quota in quotas.items()}}


def seeds_from_candidate_snapshot(snapshot: dict) -> list[dict]:
    """Convert the saved metadata shortlist into explicit, still-unreviewed seeds."""
    seeds = []
    for row in snapshot.get("candidates", []):
        hash_ = row.get("hash")
        if not hash_:
            continue
        seeds.append({"hash": hash_.upper(), "map_id": row.get("mapId"),
                      "difficulty": row.get("difficulty"), "mapper": row.get("mapper"),
                      "song": row.get("song"), "cohort": "unsupported_modded" if row.get("ne") or row.get("me") else "calibration",
                      "status": "metadata_only", "source_url": row.get("source"),
                      "retain_audio": True, "reviewed": False,
                      "provenance": {"snapshot_retrieved_utc": snapshot.get("retrievedAtUtc"),
                                     "score_saber_stars": row.get("scoreSaberStars"),
                                     "accuracy_percent": row.get("accuracyPercent")}})
    return seeds


def build_diverse_pilot(search_cohorts: dict[str, list[dict]], *,
                        quotas: dict[str, int], max_per_mapper: int = 3,
                        max_per_era: int | None = None,
                        existing_hashes: set[str] | None = None) -> dict:
    """Select exact Standard versions with cohort and mapper diversity."""
    selected, exclusions, mapper_counts, era_counts = [], [], {}, {}
    hashes = {x.upper() for x in (existing_hashes or set())}
    counts = {name: 0 for name in quotas}
    for cohort, maps in search_cohorts.items():
        if cohort not in quotas:
            continue
        for item in maps:
            if counts[cohort] >= quotas[cohort]:
                break
            mapper = item.get("metadata", {}).get("levelAuthorName") or item.get("uploader", {}).get("name") or "unknown"
            era = str(item.get("uploaded", ""))[:4]
            if max_per_era is not None and era_counts.get(era, 0) >= max_per_era:
                exclusions.append({"map_id": item.get("id"), "reason": "era quota"})
                continue
            if mapper_counts.get(mapper, 0) >= max_per_mapper:
                exclusions.append({"map_id": item.get("id"), "reason": "mapper quota"})
                continue
            versions = item.get("versions") or []
            if not versions:
                exclusions.append({"map_id": item.get("id"), "reason": "no version"})
                continue
            version = versions[-1]
            hash_ = str(version.get("hash", "")).upper()
            if len(hash_) != 40 or any(c not in "0123456789ABCDEF" for c in hash_):
                exclusions.append({"map_id": item.get("id"), "reason": "invalid exact hash"})
                continue
            if hash_ in hashes:
                exclusions.append({"map_id": item.get("id"), "reason": "duplicate or calibration version"})
                continue
            diffs = [d for d in version.get("diffs", []) if d.get("characteristic") == "Standard"
                     and not any(d.get(flag) for flag in ("ne", "me"))]
            if not diffs:
                exclusions.append({"map_id": item.get("id"), "reason": "no vanilla Standard difficulty"})
                continue
            chosen = max(diffs, key=lambda d: (d.get("nps") or 0, d.get("difficulty") or ""))
            selected.append({"hash": hash_, "map_id": item.get("id"), "difficulty": chosen.get("difficulty"),
                             "mapper": mapper, "song": item.get("metadata", {}).get("songName"),
                             "cohort": cohort, "era": era,
                             "tags": item.get("tags") or [], "retain_audio": False,
                             "source_url": f"{API}/maps/hash/{hash_}", "reviewed": False,
                             "status": "metadata_only"})
            hashes.add(hash_)
            mapper_counts[mapper] = mapper_counts.get(mapper, 0) + 1
            era_counts[era] = era_counts.get(era, 0) + 1
            counts[cohort] += 1
    return {"schema_version": "1.0", "seeds": selected, "quotas": quotas,
            "counts": counts, "gaps": {c: quotas[c] - counts[c] for c in quotas},
            "mapper_counts": mapper_counts,
            "eras": {era: sum(s["era"] == era for s in selected) for era in sorted({s["era"] for s in selected})},
            "exclusions": exclusions, "role": "development_metadata_unreviewed"}


def ingest_seeds(store: "CorpusStore", seeds: list[dict], *, max_items: int,
                 max_new_archive_bytes: int, per_archive_bytes: int = 64_000_000,
                 timeout: float = 20) -> dict:
    """Process a bounded explicit list; resume cached versions and log each failure."""
    if max_items < 0 or max_new_archive_bytes < 0 or per_archive_bytes <= 0:
        raise ValueError("invalid ingestion budget")
    started = time.monotonic()
    results, spent = [], 0
    known = {row["version_hash"]: row for row in store.rows()}
    for seed in seeds[:max_items]:
        hash_ = seed["hash"].upper()
        prior = known.get(hash_)
        cached = bool(prior and prior.get("archive_sha256") and
                      (store.blobs / f"{prior['archive_sha256']}.zip").exists())
        if not cached and spent >= max_new_archive_bytes:
            results.append({"hash": hash_, "status": "budget_exhausted"})
            break
        try:
            row = store.fetch_exact(hash_, retain_audio=bool(seed.get("retain_audio")),
                                    max_download_bytes=min(per_archive_bytes, max_new_archive_bytes - spent)
                                    if not cached else per_archive_bytes, timeout=timeout)
            if not cached:
                spent += row["archive_bytes"] or 0
            results.append({"hash": hash_, "status": row["status"], "archive_bytes": row["archive_bytes"],
                            "cached": cached})
        except (OSError, ValueError, urllib.error.URLError) as exc:
            status = "budget_exhausted" if str(exc) == "download byte budget exceeded" else "failed"
            results.append({"hash": hash_, "status": status, "error": str(exc)})
            if status == "budget_exhausted":
                break
    return {"requested": min(len(seeds), max_items), "processed": len(results),
            "new_archive_bytes": spent, "elapsed_seconds": round(time.monotonic() - started, 4),
            "results": results}


def coverage_report(seeds: list[dict], manifest_rows: list[dict]) -> dict:
    """Reconcile declared cohorts and observed statuses for an audit."""
    by_hash = {row["version_hash"].upper(): row for row in manifest_rows}
    coverage = {}
    for seed in seeds:
        cohort = seed.get("cohort", "unspecified")
        status = by_hash.get(seed["hash"].upper(), {}).get("status", "not_fetched")
        cohort_counts = coverage.setdefault(cohort, {})
        cohort_counts[status] = cohort_counts.get(status, 0) + 1
    return {"seed_count": len(seeds), "cohorts": coverage,
            "unresolved_count": sum(by_hash.get(seed["hash"].upper(), {}).get("status") != "processed"
                                    for seed in seeds)}


_GAMEPLAY_COLLECTIONS = {"colorNotes", "_notes", "bombNotes", "obstacles", "_obstacles",
                         "sliders", "burstSliders", "_sliders", "_burstSliders"}
_MOTION_CUSTOM_KEYS = {"_customEvents", "customEvents", "_pointDefinitions", "pointDefinitions",
                       "_track", "track", "_animation", "animation"}


def _vanilla_exclusion_reasons(entry: dict, ir: dict) -> list[str]:
    """Exclude unsupported gameplay mechanics, while allowing lighting/editor data."""
    custom = entry.get("_customData", entry.get("customData", {})) or {}
    requirements = custom.get("_requirements", custom.get("requirements", []))
    reasons = []
    if requirements:
        reasons.append("required mods: " + ", ".join(map(str, requirements)))
    for unsupported in ir.get("unsupported", []):
        path = unsupported.get("path", "")
        collection = path.split("[")[0].split(".")[0]
        if collection in _GAMEPLAY_COLLECTIONS:
            reasons.append("unsupported gameplay object: " + path)
        elif unsupported.get("reason", "").startswith("legacy BPM event"):
            reasons.append("uninterpreted tempo event: " + path)
        elif path in {"_customData", "customData"}:
            value = unsupported.get("value")
            if isinstance(value, dict) and _MOTION_CUSTOM_KEYS & set(value):
                reasons.append("uninterpreted motion custom data: " + ", ".join(sorted(_MOTION_CUSTOM_KEYS & set(value))))
    return sorted(set(reasons))


def audit_pilot(store: "CorpusStore", seeds: list[dict]) -> dict:
    """Measure observed pilot coverage and a clearly provisional 1,000-map estimate."""
    rows = store.rows()
    by_hash = {r["version_hash"]: r for r in rows}
    accepted = [r for r in rows if r["status"] == "processed"]
    sample_bytes = sum(r["archive_bytes"] or 0 for r in accepted)
    by_era, by_mapper = {}, {}
    for seed in seeds:
        if by_hash.get(seed["hash"].upper(), {}).get("status") != "processed":
            continue
        era, mapper = seed.get("era", "unknown"), seed.get("mapper", "unknown")
        by_era[era] = by_era.get(era, 0) + 1
        by_mapper[mapper] = by_mapper.get(mapper, 0) + 1
    status = coverage_report(seeds, rows)
    return {"schema_version": "1.0", "seed_coverage": status,
            "accepted_versions": len(accepted), "accepted_archive_bytes": sample_bytes,
            "mean_archive_bytes": round(sample_bytes / len(accepted)) if accepted else None,
            "estimated_1000_archive_bytes": round(sample_bytes / len(accepted) * 1000) if accepted else None,
            "estimate_scope": "extrapolation from this biased pilot; not a resource commitment",
            "eras": dict(sorted(by_era.items())), "mapper_count": len(by_mapper),
            "max_versions_per_mapper": max(by_mapper.values(), default=0),
            "raw_json_retained": sum(bool(store.processed(r["version_hash"]).get("raw_map_files")) for r in accepted),
            "zip_bytes_on_disk": sum(p.stat().st_size for p in store.blobs.glob("*.zip")),
            "human_reviewed": 0, "heldout_evaluation": False}


class CorpusStore:
    """SQLite status manifest plus content-addressed ZIP cache; no extraction."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.blobs = self.root / "archives"
        self.blobs.mkdir(exist_ok=True)
        self.db = sqlite3.connect(self.root / "manifest.sqlite")
        self.db.execute("""CREATE TABLE IF NOT EXISTS maps (
            version_hash TEXT PRIMARY KEY, map_id TEXT, status TEXT NOT NULL,
            archive_sha256 TEXT, archive_bytes INTEGER, expanded_bytes INTEGER,
            audio_bytes INTEGER, retain_audio INTEGER NOT NULL, source_url TEXT,
            provenance_json TEXT NOT NULL, error TEXT, updated_utc TEXT NOT NULL
        )""")
        existing = {row[1] for row in self.db.execute("PRAGMA table_info(maps)")}
        if "processing_json" not in existing:
            self.db.execute("ALTER TABLE maps ADD COLUMN processing_json TEXT")
        if "archive_deleted" not in existing:
            self.db.execute("ALTER TABLE maps ADD COLUMN archive_deleted INTEGER DEFAULT 0")
        self.db.commit()

    def close(self):
        self.db.close()

    def rows(self, *, include_processing: bool = False) -> list[dict]:
        """Return compact manifest rows; opt in to large JSON payload columns."""
        columns = ("version_hash,map_id,status,archive_sha256,archive_bytes,expanded_bytes,"
                   "audio_bytes,retain_audio,source_url,error,updated_utc,archive_deleted")
        if include_processing:
            columns += ",provenance_json,processing_json"
        cur = self.db.execute(f"SELECT {columns} FROM maps ORDER BY version_hash")
        return [dict(zip([x[0] for x in cur.description], row)) for row in cur.fetchall()]

    def library_summary(self, *, limit: int = 100) -> dict:
        """Read a compact index; never deserialize the full pattern catalog."""
        if not 0 <= limit <= 100:
            raise ValueError("library summary limit must be 0..100")
        path = self.root / "library-index.json"
        if not path.exists():
            return {"schema_version": "1.0", "available": False,
                    "corpus": corpus_report(self.rows()), "patterns": [], "groups": []}
        index = json.loads(path.read_text(encoding="utf-8"))
        current = _processing_fingerprints(index.get("window_beats", 4))
        stale = any(index.get(key) != current[key] for key in ("parser_fingerprint", "pattern_fingerprint"))
        return {**index, "stale": stale,
                "patterns": index["patterns"][:limit], "groups": index["groups"][:limit]}

    def import_archive(self, data: bytes, *, version_hash: str, map_id: str | None = None,
                       source_url: str | None = None, retain_audio: bool = False,
                       provenance: dict | None = None, max_archive_bytes: int = 64_000_000) -> dict:
        version_hash = version_hash.upper()
        if len(version_hash) != 40 or any(c not in "0123456789ABCDEF" for c in version_hash):
            raise ValueError("version hash must be 40 hex characters")
        if len(data) > max_archive_bytes:
            raise ValueError("archive byte budget exceeded")
        members = safe_zip_members(data)
        expanded = sum(x.file_size for x in members)
        audio_bytes = sum(x.file_size for x in members if x.filename.lower().endswith((".ogg", ".egg", ".mp3", ".wav")))
        digest = sha256(data)
        target = self.blobs / f"{digest}.zip"
        if not target.exists():
            staging = target.with_suffix(".part")
            staging.write_bytes(data)
            staging.replace(target)
        row = {"version_hash": version_hash, "map_id": map_id, "status": "ready",
               "archive_sha256": digest, "archive_bytes": len(data), "expanded_bytes": expanded,
               "audio_bytes": audio_bytes, "retain_audio": int(retain_audio),
               "source_url": source_url, "provenance_json": json.dumps(provenance or {}, sort_keys=True),
               "error": None, "updated_utc": datetime.now(timezone.utc).isoformat()}
        self.db.execute("""INSERT INTO maps (version_hash,map_id,status,archive_sha256,archive_bytes,
            expanded_bytes,audio_bytes,retain_audio,source_url,provenance_json,error,updated_utc) VALUES (:version_hash,:map_id,:status,:archive_sha256,
            :archive_bytes,:expanded_bytes,:audio_bytes,:retain_audio,:source_url,:provenance_json,
            :error,:updated_utc) ON CONFLICT(version_hash) DO UPDATE SET
            map_id=excluded.map_id,status=excluded.status,archive_sha256=excluded.archive_sha256,
            archive_bytes=excluded.archive_bytes,expanded_bytes=excluded.expanded_bytes,
            audio_bytes=excluded.audio_bytes,retain_audio=excluded.retain_audio,
            source_url=excluded.source_url,provenance_json=excluded.provenance_json,
            error=NULL,archive_deleted=0,updated_utc=excluded.updated_utc""", row)
        self.db.commit()
        return row

    def fetch_exact(self, version_hash: str, *, retain_audio: bool = False,
                    max_download_bytes: int = 64_000_000, timeout: float = 20) -> dict:
        expected = version_hash.upper()
        current = self.db.execute("SELECT status,archive_sha256 FROM maps WHERE version_hash=?", (expected,)).fetchone()
        if current and current[0] in {"ready", "processed", "partial", "unsupported"} and (self.blobs / f"{current[1]}.zip").exists():
            return next(row for row in self.rows() if row["version_hash"] == expected)
        try:
            metadata = fetch_metadata_exact(expected, timeout=timeout)
            version = next(v for v in metadata["versions"] if v["hash"].upper() == expected)
            url = version.get("downloadURL")
            if not isinstance(url, str):
                raise ValueError("exact version has no download URL")
            data = _read_url(url, max_bytes=max_download_bytes, timeout=timeout)
            if expected not in beat_saber_map_hashes(data):
                raise ValueError("downloaded map content hash does not match requested BeatSaver version")
            return self.import_archive(data, version_hash=expected, map_id=metadata.get("id"),
                                       source_url=url, retain_audio=retain_audio,
                                       provenance={"metadata_url": f"{API}/maps/hash/{expected}",
                                                   "metadata": metadata})
        except (FileNotFoundError, ValueError, OSError, urllib.error.URLError) as exc:
            self.db.execute("""INSERT INTO maps (version_hash,status,retain_audio,provenance_json,error,updated_utc)
                VALUES (?,?,?,?,?,?) ON CONFLICT(version_hash) DO UPDATE SET
                status=excluded.status,error=excluded.error,updated_utc=excluded.updated_utc""",
                (expected, "missing" if isinstance(exc, FileNotFoundError) else
                 "deferred_budget" if str(exc) == "download byte budget exceeded" else "failed",
                 int(retain_audio), "{}", str(exc), datetime.now(timezone.utc).isoformat()))
            self.db.commit()
            raise

    def read_map_files(self, version_hash: str) -> dict[str, dict]:
        """Read JSON map members without extracting untrusted paths to disk."""
        row = self.db.execute("SELECT archive_sha256 FROM maps WHERE version_hash=? AND status IN ('ready','processed','partial','unsupported')", (version_hash.upper(),)).fetchone()
        if not row:
            raise KeyError(version_hash)
        data = (self.blobs / f"{row[0]}.zip").read_bytes()
        safe_zip_members(data)
        out = {}
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for info in archive.infolist():
                if info.filename.lower().endswith((".dat", ".json")):
                    try:
                        obj = json.loads(archive.read(info).decode("utf-8-sig"))
                    except (UnicodeError, json.JSONDecodeError):
                        continue
                    if isinstance(obj, dict):
                        out[info.filename] = obj
        return out

    def process_maps(self, version_hash: str, *, difficulty: str | None = None,
                     window_beats: float = 4, song_family_id: str | None = None,
                     persist: bool = True, _raw_files: dict | None = None) -> dict:
        """Normalize playable map files and extract phrases; report unsupported files."""
        from .mapio import parse_map
        from .patterns import extract_patterns
        files = _raw_files if _raw_files is not None else self.read_map_files(version_hash)
        info = next((v for k, v in files.items() if PurePosixPath(k).name.lower() in {"info.dat", "info.json"}), None)
        if not info:
            result = {"version_hash": version_hash.upper(), "normalized": {}, "patterns": [],
                      "failures": {"Info.dat": "missing or invalid Info metadata"}, "status": "unsupported"}
            if persist:
                self.db.execute("UPDATE maps SET status=?,processing_json=? WHERE version_hash=?",
                                ("unsupported", json.dumps(result), version_hash.upper()))
                self.db.commit()
            return result
        bpm = info.get("_beatsPerMinute", info.get("beatsPerMinute", info.get("audio", {}).get("bpm", 120)))
        declared = []
        for group in info.get("_difficultyBeatmapSets", info.get("difficultyBeatmapSets", [])):
            characteristic = group.get("_beatmapCharacteristicName", group.get("beatmapCharacteristicName"))
            if characteristic != "Standard":
                continue
            for entry in group.get("_difficultyBeatmaps", group.get("difficultyBeatmaps", [])):
                name = entry.get("_beatmapFilename", entry.get("beatmapDataFilename", entry.get("beatmapFilename")))
                label = entry.get("_difficulty", entry.get("difficulty"))
                if name and (difficulty is None or label == difficulty):
                    declared.append((name.casefold(), label, entry))
        for entry in info.get("difficultyBeatmaps", []):
            if entry.get("characteristic") != "Standard":
                continue
            name, label = entry.get("beatmapDataFilename"), entry.get("difficulty")
            if name and (difficulty is None or label == difficulty):
                declared.append((name.casefold(), label, entry))
        normalized, patterns, failures, excluded = {}, [], {}, {}
        if not declared:
            failures["Info.dat"] = "no declared Standard difficulty matched"
        for filename, data in sorted(files.items()):
            matching = next(((label, entry) for name, label, entry in declared
                             if PurePosixPath(filename).name.casefold() == PurePosixPath(name).name.casefold()), None)
            if matching is None:
                continue
            try:
                ir = parse_map(data, bpm=bpm, audio_offset_seconds=0,
                               provenance={"version_hash": version_hash.upper(), "filename": filename})
                normalized[filename] = ir
                label, entry = matching
                reasons = _vanilla_exclusion_reasons(entry, ir)
                if reasons:
                    excluded[filename] = reasons
                else:
                    patterns.extend(extract_patterns(ir, version_hash=version_hash,
                                                     song_family_id=song_family_id,
                                                     difficulty=label, window_beats=window_beats))
            except (ValueError, TypeError, KeyError) as exc:
                failures[filename] = str(exc)
        fingerprints = _processing_fingerprints(window_beats)
        result = {"version_hash": version_hash.upper(), "song_family_id": song_family_id,
                "bpm": bpm,
                "timing_note": "Info songTimeOffset ignored for native Beat Saber note timing; review audio timing separately",
                "normalized": normalized, "raw_map_files": files,
                "raw_map_files_sha256": sha256(json.dumps(files, sort_keys=True, separators=(",", ":"),
                                                     ensure_ascii=False).encode("utf-8")),
                "source_archive_sha256": self.db.execute(
                    "SELECT archive_sha256 FROM maps WHERE version_hash=?", (version_hash.upper(),)).fetchone()[0],
                "patterns": patterns, "failures": failures,
                "excluded_difficulties": excluded,
                **fingerprints,
                "status": "processed" if normalized and not failures else "partial" if normalized else "unsupported"}
        if persist:
            self.db.execute("UPDATE maps SET status=?,processing_json=?,updated_utc=? WHERE version_hash=?",
                            (result["status"], json.dumps(result, sort_keys=True),
                             datetime.now(timezone.utc).isoformat(), version_hash.upper()))
            self.db.commit()
        return result

    def processed(self, version_hash: str) -> dict | None:
        row = self.db.execute("SELECT processing_json FROM maps WHERE version_hash=?", (version_hash.upper(),)).fetchone()
        return json.loads(row[0]) if row and row[0] else None

    def valid_processed(self, version_hash: str) -> dict | None:
        """Return only catalog records matching current parser and movement code."""
        hash_ = version_hash.upper()
        row = self.db.execute("SELECT status FROM maps WHERE version_hash=?", (hash_,)).fetchone()
        if not row or row[0] != "processed":
            return None
        cached = self.processed(hash_)
        if not cached or cached.get("status") != "processed":
            return None
        expected = _processing_fingerprints(cached.get("window_beats", 4))
        if any(cached.get(key) != expected[key] for key in
               ("parser_fingerprint", "pattern_fingerprint", "movement_model_version")):
            return None
        split_path = self.root / "splits.json"
        if split_path.exists():
            from .evaluation import SplitRegistry
            registry = SplitRegistry(split_path)
            if any(item.get("version_hash") == hash_ for item in registry.data.get("quarantine", [])):
                return None
        return cached

    def catalog_patterns(self) -> list[dict]:
        """Current catalog phrases from processed, unquarantined versions.

        Reads the on-disk catalog written by ``process_all`` instead of
        deserializing every version's processing record. Returns an empty
        list when the catalog is missing or was built by older parser,
        pattern, or movement code, so callers must reprocess first.
        """
        path = self.root / "patterns.json"
        index_path = self.root / "library-index.json"
        if not path.is_file() or not index_path.is_file():
            return []
        index = json.loads(index_path.read_text(encoding="utf-8"))
        current = _processing_fingerprints(index.get("window_beats", 4))
        if any(index.get(key) != current[key] for key in
               ("parser_fingerprint", "pattern_fingerprint", "movement_model_version")):
            return []
        stat = path.stat()
        signature = (str(path.resolve()), stat.st_mtime_ns, stat.st_size)
        cached = _CATALOG_CACHE.get(signature[0])
        if cached is None or cached[0] != signature:
            payload = json.loads(path.read_text(encoding="utf-8"))
            cached = (signature, payload.get("patterns", []))
            _CATALOG_CACHE.clear()
            _CATALOG_CACHE[signature[0]] = cached
        processed = {row["version_hash"] for row in self.rows() if row["status"] == "processed"}
        quarantined = set()
        split_path = self.root / "splits.json"
        if split_path.exists():
            from .evaluation import SplitRegistry
            quarantined = {item.get("version_hash") for item in SplitRegistry(split_path).data.get("quarantine", [])}
        return [pattern for pattern in cached[1]
                if pattern.get("version_hash") in processed and pattern.get("version_hash") not in quarantined]

    def process_all(self, *, max_maps: int = 100, max_seconds: float = 300,
                    window_beats: float = 4, split_registry=None) -> dict:
        return process_all(self, max_maps=max_maps, max_seconds=max_seconds,
                           window_beats=window_beats, split_registry=split_registry)

    def discard_archive_after_processing(self, version_hash: str) -> dict:
        """Apply per-map retention only after normalized content is saved."""
        row = self.db.execute("SELECT archive_sha256,retain_audio,status,processing_json FROM maps WHERE version_hash=?",
                              (version_hash.upper(),)).fetchone()
        if not row or row[2] != "processed" or not row[3]:
            raise ValueError("successful persisted processing required before cleanup")
        if not json.loads(row[3]).get("raw_map_files"):
            raise ValueError("raw map JSON must be retained before archive cleanup")
        if row[1]:
            raise ValueError("archive retention protected for this map")
        blob = self.blobs / f"{row[0]}.zip"
        references = self.db.execute("SELECT COUNT(*) FROM maps WHERE archive_sha256=? AND version_hash<>? AND archive_deleted=0",
                                     (row[0], version_hash.upper())).fetchone()[0]
        if references:
            raise ValueError("archive shared by another manifest entry")
        if blob.exists():
            blob.unlink()
        self.db.execute("UPDATE maps SET archive_deleted=1,updated_utc=? WHERE version_hash=?",
                        (datetime.now(timezone.utc).isoformat(), version_hash.upper()))
        self.db.commit()
        return {"version_hash": version_hash.upper(), "archive_deleted": True, "processed_retained": True}


_CATALOG_CACHE: dict[str, tuple] = {}


def corpus_report(rows: list[dict]) -> dict:
    counts = {}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    return {"total": len(rows), "status": counts,
            "archive_bytes": sum(row.get("archive_bytes") or 0 for row in rows),
            "expanded_bytes": sum(row.get("expanded_bytes") or 0 for row in rows),
            "audio_bytes": sum(row.get("audio_bytes") or 0 for row in rows)}


def _atomic_json(path: Path, value: dict | list):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".part", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, ensure_ascii=False, sort_keys=True)
            stream.write("\n")
        Path(name).replace(path)
    finally:
        Path(name).unlink(missing_ok=True)


def _processing_fingerprints(window_beats: float) -> dict:
    from . import mapio, movement, patterns
    parser = hashlib.sha256(Path(mapio.__file__).read_bytes() + Path(__file__).read_bytes()).hexdigest()
    pattern = hashlib.sha256(Path(patterns.__file__).read_bytes() +
                             Path(movement.__file__).read_bytes() +
                             str(window_beats).encode()).hexdigest()
    return {"parser_fingerprint": parser, "pattern_fingerprint": pattern,
            "window_beats": window_beats, "movement_model_version": movement.MODEL_VERSION}


def _archive_audio_hash(data: bytes) -> str | None:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        info_name = next((n for n in archive.namelist() if PurePosixPath(n).name.casefold() == "info.dat"), None)
        if not info_name:
            return None
        info = json.loads(archive.read(info_name).decode("utf-8-sig"))
        filename = info.get("_songFilename", info.get("songFilename", info.get("audio", {}).get("songFilename")))
        if not filename:
            return None
        audio_name = next((n for n in archive.namelist() if PurePosixPath(n).name.casefold() == PurePosixPath(filename).name.casefold()), None)
        return sha256(archive.read(audio_name)) if audio_name else None


def process_all(store: CorpusStore, *, max_maps: int = 100,
                max_seconds: float = 300, window_beats: float = 4,
                split_registry=None) -> dict:
    """Serialize local processing; a second caller gets a clear busy timeout."""
    from .storage import WorkspaceLock
    with WorkspaceLock(store.root / "catalog.lock"):
        return _process_all_unlocked(store, max_maps=max_maps, max_seconds=max_seconds,
                                     window_beats=window_beats, split_registry=split_registry)


def _process_all_unlocked(store: CorpusStore, *, max_maps: int,
                          max_seconds: float, window_beats: float,
                          split_registry=None) -> dict:
    """Incrementally build an on-disk research catalog from cached exact versions."""
    from .evaluation import SplitRegistry
    from .patterns import group_patterns, repetition_report
    if max_maps < 0 or max_seconds < 0:
        raise ValueError("invalid processing budget")
    registry = split_registry or SplitRegistry(store.root / "splits.json")
    started = time.monotonic()
    processed_now, failures = [], {}
    records = []
    fingerprints = _processing_fingerprints(window_beats)
    for row in store.rows():
        if row["status"] not in {"ready", "processed", "partial", "unsupported"}:
            continue
        hash_ = row["version_hash"]
        cached = store.processed(hash_)
        blob = store.blobs / f"{row['archive_sha256']}.zip"
        parser_stale = cached is not None and cached.get("parser_fingerprint") != fingerprints["parser_fingerprint"]
        pattern_stale = cached is not None and cached.get("pattern_fingerprint") != fingerprints["pattern_fingerprint"]
        if cached is None or parser_stale:
            if len(processed_now) >= max_maps or time.monotonic() - started >= max_seconds:
                failures[hash_] = "processing budget exhausted; source remains pending"
                continue
            if not blob.exists() and cached and cached.get("raw_map_files"):
                try:
                    prior = cached
                    cached = store.process_maps(hash_, song_family_id=cached.get("song_family_id"),
                                                window_beats=window_beats,
                                                _raw_files=cached["raw_map_files"])
                    for key in ("audio_sha256", "split"):
                        if key in prior:
                            cached[key] = prior[key]
                    store.db.execute("UPDATE maps SET processing_json=? WHERE version_hash=?",
                                     (json.dumps(cached, sort_keys=True), hash_))
                    store.db.commit()
                    processed_now.append(hash_)
                except (ValueError, TypeError, KeyError) as exc:
                    failures[hash_] = str(exc)
                    continue
            elif not blob.exists():
                failures[hash_] = "parser changed but source archive unavailable; re-download required"
                continue
            else:
              try:
                audio_sha = _archive_audio_hash(blob.read_bytes())
                family = registry.resolve(version_hash=hash_, audio_sha256=audio_sha)
                if family["split"] == "quarantine":
                    failures[hash_] = "song family alias conflict quarantined"
                    continue
                cached = store.process_maps(hash_, song_family_id=family["family_id"], window_beats=window_beats)
                cached["audio_sha256"] = audio_sha
                cached["song_family_id"] = family["family_id"]
                cached["split"] = family["split"]
                store.db.execute("UPDATE maps SET processing_json=? WHERE version_hash=?",
                                 (json.dumps(cached, sort_keys=True), hash_))
                store.db.commit()
                processed_now.append(hash_)
              except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
                failures[hash_] = str(exc)
                continue
        elif pattern_stale:
            if len(processed_now) >= max_maps or time.monotonic() - started >= max_seconds:
                failures[hash_] = "processing budget exhausted; pattern cache remains stale"
                continue
            from .patterns import extract_patterns
            try:
                refreshed = []
                for filename, ir in cached.get("normalized", {}).items():
                    old = next((p for p in cached.get("patterns", []) if p.get("source", {}).get("filename") == filename), None)
                    difficulty = old["difficulty"] if old else PurePosixPath(filename).stem
                    refreshed.extend(extract_patterns(ir, version_hash=hash_, difficulty=difficulty,
                                                     song_family_id=cached.get("song_family_id"),
                                                     window_beats=window_beats))
                cached["patterns"] = refreshed
                cached.update(fingerprints)
                store.db.execute("UPDATE maps SET processing_json=? WHERE version_hash=?",
                                 (json.dumps(cached, sort_keys=True), hash_))
                store.db.commit()
                processed_now.append(hash_)
            except (ValueError, TypeError, KeyError) as exc:
                failures[hash_] = str(exc)
                continue
        # Keep only what the catalog needs; raw map files stay in SQLite.
        records.append({"version_hash": hash_, "patterns": cached.get("patterns", [])})
    patterns = [pattern for record in records for pattern in record.get("patterns", [])]
    payload = {"schema_version": "1.0", "source_versions": [r["version_hash"] for r in records],
               "patterns": patterns, "groups": group_patterns(patterns),
               "repetition": repetition_report(patterns)}
    index = {
        "schema_version": "1.0", "available": True,
        **fingerprints,
        "source_versions": len(records), "pattern_count": len(patterns),
        "motif_group_count": len(payload["groups"]),
        "patterns": [{key: pattern.get(key) for key in (
            "id", "version_hash", "song_family_id", "motif_family_id", "difficulty",
            "start_beat", "length_beats", "bpm", "nps", "note_count")}
            for pattern in patterns[:100]],
        "groups": [{key: group.get(key) for key in ("family_key", "count", "exemplar")}
                   for group in payload["groups"][:100]]}
    development_manifest = {
        "schema_version": "1.0", "role": "development_only_unreviewed",
        "version_hashes": [r["version_hash"] for r in records],
        "families": [{"version_hash": r["version_hash"],
                      "family_id": registry.data["aliases"].get(f"version:{r['version_hash']}"),
                      "split": registry.data["families"].get(
                          registry.data["aliases"].get(f"version:{r['version_hash']}"))}
                     for r in records],
        "retired_prior_heldout_memberships": registry.data.get("retired_evaluation_memberships", []),
        "warning": "Collection/processing does not make a version human inspected or eligible as held-out test data."}
    report = {"processed_now": processed_now, "catalogued_versions": len(records),
              "pattern_count": len(patterns), "motif_group_count": len(payload["groups"]),
              "failures": failures,
              "elapsed_seconds": round(time.monotonic() - started, 4),
              "corpus": corpus_report(store.rows())}
    _atomic_json(store.root / "patterns.json", payload)
    _atomic_json(store.root / "library-index.json", index)
    _atomic_json(store.root / "development-manifest.json", development_manifest)
    _atomic_json(store.root / "processing-report.json", report)
    return report

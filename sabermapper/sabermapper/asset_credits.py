"""Credits for the third-party and generated media in a project's asset bundle, for citing when the map is published.

Built from the provenance records in assets.json (``assets fetch`` writes them): every tier-3 asset, fetched or
generated, with where it came from, who made it, its licence and what was changed. Library and agent-written
assets (tiers 1 and 2) are SaberMapper's own and are not listed. ``assets build`` writes the result next to the
bundle as ``credits.json`` and ``project export`` ships it inside the map ZIP.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .storage import now

CREDITS_FORMAT = "sabermapper-credits/1"
CREDITS_FILE = "credits.json"
SOURCE_NAMES = {"polyhaven": ("Poly Haven", "https://polyhaven.com"), "ambientcg": ("ambientCG", "https://ambientcg.com"),
                "kenney": ("Kenney", "https://kenney.nl")}
LICENSE_URLS = {"CC0-1.0": "https://creativecommons.org/publicdomain/zero/1.0/"}


def _media_file(asset: dict) -> str | None:
    mesh = asset.get("mesh")
    return asset.get("source") or (mesh.get("file") if isinstance(mesh, dict) else None)


def credits_for_spec(spec: dict, spec_path: Path | None = None) -> dict:
    """The credits document for an assets.json spec (a dict), grouped per source asset."""
    fetched, generated = {}, []
    for asset in spec.get("assets", []):
        prov = asset.get("provenance") if asset.get("tier") == 3 else None
        if not isinstance(prov, dict):
            continue
        usage = {"asset_id": asset.get("id"), "kind": asset.get("kind"), "file": _media_file(asset),
                 "modifications": prov.get("postprocess") or []}
        if isinstance(prov.get("fetched"), dict):
            f = prov["fetched"]
            key = (f.get("source"), f.get("asset"))
            source_name, source_url = SOURCE_NAMES.get(f.get("source"), (f.get("source"), None))
            entry = fetched.setdefault(key, {
                "title": f.get("name") or f.get("asset"), "source": f.get("source"), "source_name": source_name,
                "source_url": source_url, "source_asset": f.get("asset"), "url": f.get("url"),
                "authors": f.get("authors") or [], "license": prov.get("license"),
                "license_url": LICENSE_URLS.get(prov.get("license")), "retrieved_at": f.get("retrieved_at"),
                "downloads": f.get("files") or [], "used_as": []})
            if f.get("model"):
                usage["model"] = f["model"]
            entry["used_as"].append(usage)
        elif isinstance(prov.get("generator"), dict):
            g = prov["generator"]
            generated.append({**usage, "generator": {k: g.get(k) for k in ("kind", "model", "model_version", "backend",
                                                                          "prompt", "seed")},
                              "license": prov.get("license"), "created_at": prov.get("created_at")})
    works = list(fetched.values())
    licences = sorted({w["license"] for w in works if w["license"]} | {g["license"] for g in generated if g["license"]})
    document = {"format": CREDITS_FORMAT, "project": spec.get("project"), "generated_at": now(),
                "third_party": works, "generated_media": generated,
                "licenses": licences, "attribution_text": attribution_text(works, generated),
                "note": ("CC0 works need no attribution; crediting their authors and sources is the courtesy they ask for. "
                         "Paste attribution_text into the map description when publishing.")}
    if spec_path is not None and Path(spec_path).is_file():
        document["spec_sha256"] = hashlib.sha256(Path(spec_path).read_bytes()).hexdigest()
    return document


def attribution_text(works: list[dict], generated: list[dict]) -> str:
    """One paragraph listing every work, its author and source, ready for a map description."""
    if not works and not generated:
        return "All visual assets were made for this map with SaberMapper."
    parts = []
    for w in works:
        by = f" by {', '.join(w['authors'])}" if w["authors"] and w["authors"] != [w["source_name"]] else ""
        models = sorted({u["model"] for u in w["used_as"] if u.get("model")})
        detail = f" ({', '.join(models)})" if models else ""
        licence = w["license"].replace("-1.0", "") if w["license"] else "licence unknown"
        parts.append(f"\"{w['title']}\"{detail}{by}, {w['source_name']}, {w['url']} ({licence})")
    text = "Third-party assets: " + "; ".join(parts) + "." if parts else ""
    if generated:
        models = sorted({f"{g['generator']['model']} {g['generator']['model_version'] or ''}".strip() for g in generated})
        text += (" " if text else "") + f"Generated media made with {', '.join(models)}."
    return text


def credits_for_file(spec_path: Path) -> dict:
    spec_path = Path(spec_path)
    return credits_for_spec(json.loads(spec_path.read_text(encoding="utf-8")), spec_path)

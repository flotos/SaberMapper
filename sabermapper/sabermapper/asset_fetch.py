"""Free (CC0) models, textures and sky panoramas for Vivify maps: Poly Haven, ambientCG and Kenney.

Agent-facing flow: ``search`` lists candidates with licence, size and preview; ``info`` downloads one candidate into
the machine cache and lists what it contains (mesh nodes, pack models, texture maps) with preview images to read;
``get`` converts it into the project (a normalised OBJ within the triangle budget, or an image within the texture
budget), writes a provenance sidecar and returns the assets.json entry, or appends it with ``add``.

Downloads go only to the hosts in ``ALLOWED_HOSTS``, are size-capped, and zip members are read in memory, never
extracted by their own paths. Fetched assets are tier 3 with a ``fetched`` provenance record that ``assets lint``
checks against the file actually used.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

from .forge import DEFAULT_BUDGETS, ForgeError, project_slug
from .mesh_files import (MeshFileError, bounds, decimate, gltf_buffers, gltf_nodes, load_gltf, normalise,
                         parse_glb, read_mtl, read_obj, triangle_count, write_obj)
from .storage import now

USER_AGENT = "SaberMapper-assets-fetch/1 (local Beat Saber mapping tool)"
ALLOWED_HOSTS = {"api.polyhaven.com", "dl.polyhaven.org", "cdn.polyhaven.com", "ambientcg.com",
                 "acg-download.struffelproductions.com", "acg-media.struffelproductions.com", "kenney.nl"}
SOURCES = ("polyhaven", "ambientcg", "kenney")
KINDS = ("model", "texture", "sky")
LICENSE = "CC0-1.0"
DEFAULT_MAX_DOWNLOAD_MB = 200
TEXTURE_MAPS = {"color": ("Color", "Diffuse", "diff"), "normal": ("NormalGL", "nor_gl"), "roughness": ("Roughness", "Rough", "rough"),
                "ao": ("AmbientOcclusion", "AO", "ao"), "height": ("Displacement", "disp")}

# Kenney has no API; these 3D packs were checked on 2026-09-23. Recent releases also come from its RSS feed.
KENNEY_3D = {
    "nature-kit": "trees rocks plants grass flowers cliffs bridges camp nature forest",
    "space-kit": "space rockets planets craters satellites aliens sci-fi",
    "space-station-kit": "space station corridors modules sci-fi interior",
    "modular-space-kit": "space modular walls corridors sci-fi",
    "castle-kit": "castle walls towers gates medieval",
    "fantasy-town-kit": "fantasy town houses medieval roofs market",
    "graveyard-kit": "graveyard tombstones crypt fences spooky halloween",
    "holiday-kit": "christmas holiday snow presents trees winter",
    "pirate-kit": "pirate ships docks palm island treasure",
    "watercraft-kit": "boats ships water",
    "city-kit-commercial": "city skyscrapers buildings commercial urban",
    "city-kit-suburban": "city houses suburban urban",
    "city-kit-industrial": "city factory industrial chimneys urban",
    "city-kit-roads": "roads streets city lights signs",
    "retro-urban-kit": "retro urban city buildings street",
    "building-kit": "building walls floors roofs modular",
    "survival-kit": "survival camp tools tents barrels",
    "platformer-kit": "platformer blocks coins flags trees",
    "prototype-kit": "prototype blocks shapes grid",
    "hexagon-kit": "hexagon tiles terrain board",
    "tower-defense-kit": "tower defense paths towers enemies",
    "mini-dungeon": "dungeon walls floors torches chests",
    "mini-arena": "arena characters weapons walls",
    "mini-characters": "characters people figures",
    "mini-market": "market stalls shop food",
    "furniture-kit": "furniture chairs tables beds lamps interior",
    "food-kit": "food fruit vegetables drinks",
    "car-kit": "cars vehicles trucks",
    "train-kit": "trains tracks wagons stations",
    "racing-kit": "racing track cars barriers",
    "coaster-kit": "roller coaster tracks rails",
    "minigolf-kit": "minigolf course holes",
    "marble-kit": "marble run tracks tubes",
    "brick-kit": "bricks blocks building toy",
    "blaster-kit": "blasters guns weapons sci-fi",
}


class FetchError(ForgeError):
    pass


# --------------------------------------------------------------------------- network and cache


def cache_dir() -> Path:
    base = os.environ.get("SABERMAPPER_FETCH_CACHE")
    if base:
        return Path(base)
    root = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".cache")
    return Path(root) / "SaberMapper" / "fetch-cache"


def _check_url(url: str) -> None:
    parts = urllib.parse.urlparse(url)
    if parts.scheme != "https" or parts.hostname not in ALLOWED_HOSTS:
        raise FetchError("fetch_host_not_allowed", f"{url} is not on the fetch allowlist",
                         f"Only https downloads from {sorted(ALLOWED_HOSTS)} are allowed")


class _Redirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def http_get(url: str, max_bytes: int) -> bytes:
    """GET an allowlisted https URL (redirects re-checked) with a size cap."""
    _check_url(url)
    opener = urllib.request.build_opener(_Redirects)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with opener.open(request, timeout=60) as response:
            declared = int(response.headers.get("Content-Length") or 0)
            if declared > max_bytes:
                raise FetchError("fetch_too_large", f"{url} is {declared / 1e6:.1f} MB; the cap is {max_bytes / 1e6:.0f} MB",
                                 "Pick a lower resolution or pass --max-download-mb deliberately")
            data = response.read(max_bytes + 1)
    except FetchError:
        raise
    except Exception as exc:  # noqa: BLE001 - network failures become a structured error
        raise FetchError("fetch_network", f"Download failed for {url}: {exc}", "Check the network and retry") from exc
    if len(data) > max_bytes:
        raise FetchError("fetch_too_large", f"{url} exceeds {max_bytes / 1e6:.0f} MB",
                         "Pick a lower resolution or pass --max-download-mb deliberately")
    return data


HTTP = http_get  # tests replace this with a fixture server


def cached(url: str, relative: str, max_bytes: int, *, refresh: bool = False) -> Path:
    path = cache_dir() / relative
    if refresh or not path.is_file():
        data = HTTP(url, max_bytes)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".part")
        tmp.write_bytes(data)
        tmp.replace(path)
    return path


def _json(url: str, relative: str, max_age_s: float = 86400) -> object:
    path = cache_dir() / relative
    fresh = path.is_file() and time.time() - path.stat().st_mtime < max_age_s
    return json.loads(cached(url, relative, 50_000_000, refresh=not fresh).read_text(encoding="utf-8"))


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name)[:120]


def parse_ref(ref: str) -> tuple[str, str]:
    source, _, ident = ref.partition(":")
    if source not in SOURCES or not ident or not re.fullmatch(r"[A-Za-z0-9_.-]+", ident):
        raise FetchError("fetch_ref_invalid", f"{ref!r} is not SOURCE:ID",
                         f"Use a ref from `assets fetch search`, e.g. polyhaven:rock_moss_set_01 ({', '.join(SOURCES)})")
    return source, ident


# --------------------------------------------------------------------------- search


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _score(query: str, *fields) -> float:
    wanted = _words(query)
    if not wanted:
        return 1.0
    have = set()
    for f in fields:
        have |= _words(" ".join(f) if isinstance(f, (list, tuple)) else str(f or ""))
    hits = sum(1 for w in wanted if w in have or any(h.startswith(w) for h in have))
    return hits / len(wanted)


def _polyhaven_search(query, kind, limit, max_triangles):
    ptype = {"model": "models", "texture": "textures", "sky": "hdris"}[kind]
    assets = _json(f"https://api.polyhaven.com/assets?t={ptype}", f"polyhaven/index-{ptype}.json")
    rows = []
    for ident, a in assets.items():
        score = _score(query, ident, a.get("name"), a.get("tags", []), a.get("categories", []))
        tris = a.get("polycount")
        if score <= 0 or (kind == "model" and max_triangles and tris and tris > max_triangles * 20):
            continue
        rows.append((score, a.get("download_count", 0), {
            "ref": f"polyhaven:{ident}", "source": "polyhaven", "kind": kind, "name": a.get("name"),
            "license": LICENSE, "authors": sorted(a.get("authors", {})),
            "triangles": tris, "fits_budget": (tris <= max_triangles) if tris and max_triangles else None,
            "dimensions_m": [round(d / 1000, 3) for d in a["dimensions"]] if a.get("dimensions") else None,
            "tags": a.get("tags", [])[:10], "preview_url": f"https://cdn.polyhaven.com/asset_img/thumbs/{ident}.png?width=256",
            "page_url": f"https://polyhaven.com/a/{ident}"}))
    return rows


def _ambientcg_search(query, kind, limit):
    if kind == "model":
        return []
    dtype = {"texture": "Material", "sky": "HDRI"}[kind]
    q = urllib.parse.quote(query or "")
    url = (f"https://ambientcg.com/api/v2/full_json?type={dtype}&q={q}&limit={max(limit, 10)}&sort=popular"
           "&include=tagData,previewData,downloadData")
    data = _json(url, f"ambientcg/search-{dtype}-{_safe(query or 'all')}-{limit}.json")
    rows = []
    for rank, a in enumerate(data.get("foundAssets", [])):
        resolutions = sorted({d.get("attribute") for f in a.get("downloadFolders", {}).values()
                              for c in f.get("downloadFiletypeCategories", {}).values() for d in c.get("downloads", [])
                              if d.get("filetype") == "zip"})
        rows.append((1.0, -rank, {
            "ref": f"ambientcg:{a['assetId']}", "source": "ambientcg", "kind": kind, "name": a.get("displayName"),
            "license": LICENSE, "authors": ["ambientCG"], "tags": a.get("tags", [])[:10], "resolutions": resolutions,
            "preview_url": (a.get("previewImage") or {}).get("256-PNG"), "page_url": a.get("shortLink")}))
    return rows


def _kenney_feed() -> list[dict]:
    try:
        path = cache_dir() / "kenney" / "feed.xml"
        fresh = path.is_file() and time.time() - path.stat().st_mtime < 86400
        root = ET.fromstring(cached("https://kenney.nl/feed", "kenney/feed.xml", 5_000_000, refresh=not fresh).read_bytes())
    except (FetchError, ET.ParseError):
        return []
    items = []
    for item in root.iter("item"):
        link = item.findtext("link") or ""
        if item.findtext("category") == "3D" and "/assets/" in link:
            items.append({"slug": link.rstrip("/").rsplit("/", 1)[-1], "title": item.findtext("title"),
                          "description": (item.findtext("description") or "").strip()})
    return items


def _kenney_search(query, kind, limit):
    if kind != "model":
        return []
    packs = {slug: {"title": slug.replace("-", " ").title(), "description": words} for slug, words in KENNEY_3D.items()}
    for item in _kenney_feed():
        packs.setdefault(item["slug"], {"title": item["title"], "description": item["description"]})
    rows = []
    for slug, pack in packs.items():
        score = _score(query, slug, pack["title"], pack["description"])
        if score > 0:
            rows.append((score, 0, {
                "ref": f"kenney:{slug}", "source": "kenney", "kind": "model", "name": pack["title"], "license": LICENSE,
                "authors": ["Kenney"], "pack": True, "tags": pack["description"].split()[:10],
                "page_url": f"https://kenney.nl/assets/{slug}",
                "next": f"assets fetch info kenney:{slug} lists the pack's models with preview images"}))
    return rows


def search(query: str, *, kind: str = "model", sources=SOURCES, limit: int = 20,
           max_triangles: int = DEFAULT_BUDGETS["max_triangles_per_mesh"]) -> dict:
    if kind not in KINDS:
        raise FetchError("fetch_kind_invalid", f"kind must be one of {KINDS}", "Use --kind model|texture|sky")
    results, errors = [], []
    for source in sources:
        try:
            if source == "polyhaven":
                results += _polyhaven_search(query, kind, limit, max_triangles)
            elif source == "ambientcg":
                results += _ambientcg_search(query, kind, limit)
            elif source == "kenney":
                results += _kenney_search(query, kind, limit)
        except FetchError as exc:
            errors.append({"source": source, **exc.as_dict()["error"]})
    results.sort(key=lambda r: (-r[0], r[2].get("fits_budget") is False, -(r[1] or 0)))
    rows = [r[2] for r in results[:limit]]
    return {"query": query, "kind": kind, "sources": list(sources), "count": len(rows), "results": rows,
            "source_errors": errors,
            "next": "Run `assets fetch info REF` on the best candidates and read their preview images before choosing"}


# --------------------------------------------------------------------------- download per source


def _polyhaven_model(ident: str, max_bytes: int) -> tuple[dict, dict, list[str], Path]:
    files = _json(f"https://api.polyhaven.com/files/{ident}", f"polyhaven/{_safe(ident)}/files.json")
    gltf = (files.get("gltf") or {})
    resolution = next((r for r in ("1k", "2k", "4k") if r in gltf), None)
    if resolution is None:
        raise FetchError("fetch_format_missing", f"polyhaven:{ident} has no glTF download", "Pick another model")
    entry = gltf[resolution]["gltf"]
    folder = f"polyhaven/{_safe(ident)}/{resolution}"
    gltf_path = cached(entry["url"], f"{folder}/{_safe(Path(entry['url']).name)}", max_bytes)
    doc = json.loads(gltf_path.read_text(encoding="utf-8"))
    includes = entry.get("include", {})

    def load(uri):
        item = includes.get(uri)
        if item is None:
            raise FetchError("gltf_buffer_missing", f"polyhaven:{ident} does not list {uri}", "Pick another model")
        return cached(item["url"], f"{folder}/{_safe(uri)}", max_bytes).read_bytes()

    buffers = gltf_buffers(doc, {}, load)
    urls = [entry["url"]] + [i["url"] for u, i in includes.items() if u.endswith(".bin")]
    return doc, buffers, urls, gltf_path.parent


def _kenney_pack(slug: str, max_bytes: int) -> tuple[zipfile.ZipFile, str]:
    page = cached(f"https://kenney.nl/assets/{slug}", f"kenney/{_safe(slug)}/page.html", 5_000_000)
    match = re.search(r"https://kenney\.nl/media/pages/assets/[^'\"\s]+\.zip", page.read_text(encoding="utf-8", errors="replace"))
    if not match:
        raise FetchError("fetch_format_missing", f"kenney:{slug} has no download link on its page", "Pick another pack")
    url = match.group(0)
    path = cached(url, f"kenney/{_safe(slug)}/{_safe(Path(url).name)}", max_bytes)
    return zipfile.ZipFile(path), url


def _kenney_models(pack: zipfile.ZipFile) -> dict[str, str]:
    """Model name -> member path, preferring GLB, then glTF, then OBJ."""
    found = {}
    for rank, ext in enumerate((".glb", ".gltf", ".obj")):
        for member in pack.namelist():
            if member.lower().endswith(ext) and "__macosx" not in member.lower():
                found.setdefault(Path(member).stem, member)
    return dict(sorted(found.items()))


def _kenney_mesh(pack: zipfile.ZipFile, member: str) -> dict:
    folder = member.rsplit("/", 1)[0] + "/" if "/" in member else ""
    if member.lower().endswith(".obj"):
        text = pack.read(member).decode("utf-8", errors="replace")
        mtl = None
        lib = re.search(r"^mtllib\s+(.+)$", text, re.M)
        if lib and folder + lib.group(1).strip() in pack.namelist():
            mtl = read_mtl(pack.read(folder + lib.group(1).strip()).decode("utf-8", errors="replace"))
        return read_obj(text, mtl)
    if member.lower().endswith(".glb"):
        doc, embedded = parse_glb(pack.read(member))
    else:
        doc, embedded = json.loads(pack.read(member)), {}
    buffers = gltf_buffers(doc, embedded, lambda uri: pack.read(folder + urllib.parse.unquote(uri)))
    return load_gltf(doc, buffers, srgb_factors=True)[0]


def _kenney_previews(pack: zipfile.ZipFile, slug: str, names) -> dict[str, str]:
    images = [m for m in pack.namelist() if m.lower().endswith(".png")]
    previews = {}
    for name in names:
        match = next((m for m in images if Path(m).stem.lower() == name.lower()), None) or \
            next((m for m in images if Path(m).stem.lower().startswith(name.lower() + "_")), None)
        if match:
            dest = cache_dir() / "kenney" / _safe(slug) / "previews" / _safe(Path(match).name)
            if not dest.is_file():
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(pack.read(match))
            previews[name] = str(dest)
    return previews


def _ambientcg_zip(ident: str, resolution: str, max_bytes: int) -> tuple[zipfile.ZipFile, str]:
    url = f"https://ambientcg.com/get?file={urllib.parse.quote(ident)}_{urllib.parse.quote(resolution)}.zip"
    path = cached(url, f"ambientcg/{_safe(ident)}/{_safe(resolution)}.zip", max_bytes)
    try:
        return zipfile.ZipFile(path), url
    except zipfile.BadZipFile as exc:
        path.unlink(missing_ok=True)
        raise FetchError("fetch_resolution_missing", f"ambientcg:{ident} has no {resolution} download",
                         "Use a resolution listed by `assets fetch search` (e.g. 1K-JPG for textures, 2K for skies)") from exc


def _preview(url: str | None, relative: str) -> str | None:
    if not url:
        return None
    try:
        return str(cached(url, relative, 5_000_000))
    except FetchError:
        return None


def info(ref: str, *, max_download_mb: float = DEFAULT_MAX_DOWNLOAD_MB) -> dict:
    """What a candidate contains, with local preview images, after caching its files."""
    source, ident = parse_ref(ref)
    max_bytes = int(max_download_mb * 1e6)
    if source == "polyhaven":
        meta = _json(f"https://api.polyhaven.com/info/{ident}", f"polyhaven/{_safe(ident)}/info.json")
        result = {"ref": ref, "name": meta.get("name"), "license": LICENSE, "authors": sorted(meta.get("authors", {})),
                  "tags": meta.get("tags", []), "page_url": f"https://polyhaven.com/a/{ident}",
                  "preview": _preview(f"https://cdn.polyhaven.com/asset_img/thumbs/{ident}.png?width=512",
                                      f"polyhaven/{_safe(ident)}/preview.png")}
        if meta.get("type") == 2:
            doc, buffers, _, _ = _polyhaven_model(ident, max_bytes)
            nodes = []
            for node in gltf_nodes(doc):
                mesh, _ = load_gltf(doc, buffers, [node["name"]])
                nodes.append({"node": node["name"], "triangles": triangle_count(mesh), "bounds_m": bounds(mesh)})
            whole, _ = load_gltf(doc, buffers)
            result.update(kind="model", triangles=triangle_count(whole), bounds_m=bounds(whole), nodes=nodes,
                          next=f"assets fetch get {ref} PROJECT [--node NAME ...] [--height M] [--max-triangles N]")
        elif meta.get("type") == 0:
            result.update(kind="sky", next=f"assets fetch get {ref} PROJECT --kind sky")
        else:
            files = _json(f"https://api.polyhaven.com/files/{ident}", f"polyhaven/{_safe(ident)}/files.json")
            result.update(kind="texture", maps=sorted(files), resolutions=sorted((files.get("Diffuse") or {}).keys()),
                          next=f"assets fetch get {ref} PROJECT --kind texture [--maps color,normal] [--resolution 1k]")
        return result
    if source == "kenney":
        pack, url = _kenney_pack(ident, max_bytes)
        models = _kenney_models(pack)
        licence = next((pack.read(m).decode("utf-8", "replace") for m in pack.namelist() if m.lower().endswith("license.txt")), "")
        previews = _kenney_previews(pack, ident, list(models)[:400])
        return {"ref": ref, "kind": "model", "pack": True, "download_url": url,
                "license": LICENSE if "CC0" in licence or "Creative Commons Zero" in licence else "see License.txt",
                "authors": ["Kenney"], "page_url": f"https://kenney.nl/assets/{ident}", "model_count": len(models),
                "models": [{"model": name, "file": Path(member).name, "preview": previews.get(name)}
                           for name, member in models.items()],
                "next": f"assets fetch get {ref} PROJECT --model NAME [--height M]"}
    data = _json(f"https://ambientcg.com/api/v2/full_json?id={urllib.parse.quote(ident)}&include=tagData,previewData,downloadData",
                 f"ambientcg/{_safe(ident)}/info.json")
    assets = data.get("foundAssets", [])
    if not assets:
        raise FetchError("fetch_unknown_asset", f"ambientcg:{ident} was not found", "Use a ref from `assets fetch search`")
    a = assets[0]
    downloads = [{"resolution": d.get("attribute"), "filetype": d.get("filetype"), "size_mb": round((d.get("size") or 0) / 1e6, 1)}
                 for f in a.get("downloadFolders", {}).values() for c in f.get("downloadFiletypeCategories", {}).values()
                 for d in c.get("downloads", [])]
    kind = "sky" if a.get("dataType") == "HDRI" else "texture"
    return {"ref": ref, "kind": kind, "name": a.get("displayName"), "license": LICENSE, "authors": ["ambientCG"],
            "tags": a.get("tags", []), "page_url": a.get("shortLink"), "downloads": downloads,
            "preview": _preview((a.get("previewImage") or {}).get("512-PNG") or (a.get("previewImage") or {}).get("256-PNG"),
                                f"ambientcg/{_safe(ident)}/preview.png"),
            "next": f"assets fetch get {ref} PROJECT --kind {kind} [--resolution {'2K' if kind == 'sky' else '1K-JPG'}]"}


# --------------------------------------------------------------------------- write into a project


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _asset_id(requested: str | None, fallback: str) -> str:
    aid = (requested or re.sub(r"[^a-z0-9_-]+", "_", fallback.lower())).strip("_-")[:60] or "fetched"
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", aid):
        raise FetchError("fetch_id_invalid", f"Asset id {aid!r} must match [a-z0-9][a-z0-9_-]*", "Pass --id with a short slug")
    return aid


def _provenance(source, ident, page_url, urls, authors, output: Path, postprocess) -> dict:
    return {"fetched": {"source": source, "asset": ident, "url": page_url, "files": urls, "authors": authors,
                        "retrieved_at": now()},
            "license": LICENSE, "output_sha256": _sha256(output), "postprocess": postprocess}


def _image_out(data: bytes, dest: Path, max_size: int) -> tuple[dict | None, tuple[int, int]]:
    from PIL import Image
    with Image.open(io.BytesIO(data)) as image:
        image = image.convert("RGB")
        width, height = image.size
        scale = min(1.0, max_size / max(width, height))
        op = None
        if scale < 1.0:
            size = (max(1, int(width * scale)), max(1, int(height * scale)))
            image = image.resize(size, Image.LANCZOS)
            op = {"op": "resize", "from": [width, height], "to": list(size)}
        dest.parent.mkdir(parents=True, exist_ok=True)
        image.save(dest, quality=92)
        return op, image.size


def get(ref: str, project_dir: Path, project_id: str, *, kind: str | None = None, model: str | None = None,
        nodes: list[str] | None = None, asset_id: str | None = None, height: float | None = None,
        origin: str = "base", max_triangles: int | None = None, resolution: str | None = None,
        maps: list[str] | None = None, max_size: int | None = None, add: bool = False, force: bool = False,
        max_download_mb: float = DEFAULT_MAX_DOWNLOAD_MB) -> dict:
    """Convert one candidate into ``<project>/assets/{models,textures}/`` and return its assets.json entries."""
    source, ident = parse_ref(ref)
    slug = project_slug(project_id)
    assets_dir = Path(project_dir) / "assets"
    spec_path = assets_dir / "assets.json"
    budgets = dict(DEFAULT_BUDGETS)
    if spec_path.is_file():
        budgets.update((json.loads(spec_path.read_text(encoding="utf-8")).get("budgets") or {}))
    max_triangles = int(max_triangles or budgets["max_triangles_per_mesh"])
    max_size = int(max_size or min(budgets["max_texture_size"], 2048 if kind != "sky" else 4096))
    max_bytes = int(max_download_mb * 1e6)
    if kind is None:
        kind = "model" if source == "kenney" else info(ref, max_download_mb=max_download_mb)["kind"]
    entries, warnings, written = [], [], []

    if kind == "model":
        postprocess = []
        if source == "polyhaven":
            doc, buffers, urls, _ = _polyhaven_model(ident, max_bytes)
            mesh, warnings = load_gltf(doc, buffers, nodes)
            meta = _json(f"https://api.polyhaven.com/info/{ident}", f"polyhaven/{_safe(ident)}/info.json")
            authors, page = sorted(meta.get("authors", {})), f"https://polyhaven.com/a/{ident}"
            name = model or (nodes[0] if nodes and len(nodes) == 1 else ident)
        elif source == "kenney":
            pack, url = _kenney_pack(ident, max_bytes)
            models = _kenney_models(pack)
            if not model or model not in models:
                raise FetchError("fetch_model_required", f"kenney:{ident} is a pack of {len(models)} models; name one with --model",
                                 f"Models include {list(models)[:30]}; `assets fetch info {ref}` lists all with previews")
            mesh = _kenney_mesh(pack, models[model])
            urls, authors, page, name = [url], ["Kenney"], f"https://kenney.nl/assets/{ident}", model
            postprocess.append({"op": "extract", "member": models[model], "base_colors": "srgb_to_linear"})
        else:
            raise FetchError("fetch_kind_unavailable", "ambientCG offers textures and skies, not models",
                             "Search models with --source polyhaven or kenney")
        mesh = normalise(mesh, origin=origin, height=height)
        postprocess.append({"op": "normalise", "origin": origin, "height_m": height})
        mesh, step = decimate(mesh, max_triangles)
        if step:
            postprocess.append(step)
        aid = _asset_id(asset_id, name)
        out = assets_dir / "models" / f"{aid}.obj"
        if out.exists() and not force:
            raise FetchError("fetch_exists", f"{out} exists", "Pass --force to replace it, or --id for a new asset id")
        out.parent.mkdir(parents=True, exist_ok=True)
        write_obj(mesh, out, [f"{ref} ({LICENSE}) by {', '.join(authors)}; {page}", "right-handed, +Y up, metres; "
                              "the forge converts to Unity space"])
        written.append(str(out))
        entries.append({"id": aid, "kind": "mesh", "tier": 3, "path": f"assets/sabermapper/{slug}/meshes/{aid}.asset",
                        "mesh": {"file": f"models/{aid}.obj"},
                        "provenance": _provenance(source, ident, page, urls, authors, out, postprocess)})
        summary = {"triangles": triangle_count(mesh), "bounds_m": bounds(mesh), "has_vertex_colors": mesh.get("colors") is not None,
                   "has_uvs": mesh.get("uvs") is not None, "parts": mesh.get("parts", [])[:40]}
    elif kind in ("texture", "sky"):
        summary = {}
        if source == "kenney":
            raise FetchError("fetch_kind_unavailable", "Kenney packs are fetched as models", "Use --kind model")
        if source == "polyhaven" and kind == "sky":
            files = _json(f"https://api.polyhaven.com/files/{ident}", f"polyhaven/{_safe(ident)}/files.json")
            tonemapped = files.get("tonemapped")
            if not tonemapped:
                raise FetchError("fetch_format_missing", f"{ref} has no tonemapped panorama", "Pick another sky")
            images = {"color": (tonemapped["url"], cached(tonemapped["url"], f"polyhaven/{_safe(ident)}/tonemapped.jpg", max_bytes).read_bytes())}
        elif source == "polyhaven":
            files = _json(f"https://api.polyhaven.com/files/{ident}", f"polyhaven/{_safe(ident)}/files.json")
            images = {}
            for m in maps or ["color"]:
                key = next((k for k in TEXTURE_MAPS.get(m, ()) if k in files), None)
                if key is None:
                    warnings.append(f"{ref} has no {m} map")
                    continue
                res = resolution or ("1k" if "1k" in files[key] else sorted(files[key])[0])
                entry = files[key][res].get("jpg") or files[key][res].get("png")
                images[m] = (entry["url"], cached(entry["url"], f"polyhaven/{_safe(ident)}/{m}-{res}{Path(entry['url']).suffix}", max_bytes).read_bytes())
        else:
            res = resolution or ("2K" if kind == "sky" else "1K-JPG")
            pack, url = _ambientcg_zip(ident, res, max_bytes)
            members = pack.namelist()
            images = {}
            wanted = ["color"] if kind == "sky" else (maps or ["color"])
            for m in wanted:
                keys = ("TONEMAPPED",) if kind == "sky" else TEXTURE_MAPS.get(m, ())
                member = next((x for x in members for k in keys if f"_{k}." in x and x.lower().endswith((".jpg", ".png"))), None)
                if member is None:
                    warnings.append(f"{ref} {res} has no {m} image")
                    continue
                images[m] = (url, pack.read(member))
        if not images:
            raise FetchError("fetch_format_missing", f"{ref} produced no image", "Pick another asset or map")
        authors = ["ambientCG"] if source == "ambientcg" else sorted(_json(f"https://api.polyhaven.com/info/{ident}",
                                                                            f"polyhaven/{_safe(ident)}/info.json").get("authors", {}))
        page = f"https://polyhaven.com/a/{ident}" if source == "polyhaven" else f"https://ambientcg.com/a/{ident}"
        base_id = _asset_id(asset_id, ident)
        for m, (url, data) in images.items():
            aid = base_id if m == "color" else f"{base_id}_{m}"
            out = assets_dir / "textures" / f"{aid}.jpg"
            if out.exists() and not force:
                raise FetchError("fetch_exists", f"{out} exists", "Pass --force to replace it, or --id for a new asset id")
            op, size = _image_out(data, out, max_size)
            written.append(str(out))
            settings = {"srgb": m == "color", "mipmaps": True, "wrap": "clamp" if kind == "sky" else "repeat",
                        "max_size": max(size)}
            entries.append({"id": aid, "kind": "texture", "tier": 3, "path": f"assets/sabermapper/{slug}/textures/{aid}.jpg",
                            "source": f"textures/{aid}.jpg", "texture": settings,
                            "provenance": _provenance(source, ident, page, [url], authors, out, [op] if op else [])})
            summary[aid] = {"size": list(size)}
    else:
        raise FetchError("fetch_kind_invalid", f"kind must be one of {KINDS}", "Use --kind model|texture|sky")

    if add:
        _append(spec_path, slug, entries, force)
    facing = ("Kenney models face the player with rotation [0, 0, 0] (seen in game, 2026-09-23)" if source == "kenney" else
              "the model keeps its source orientation; if a capture shows its back, rotate the prefab child [0, 180, 0]")
    hint = {"model": ("Reference it from a prefab child with {\"mesh\": {\"asset\": \"%s\"}} and restyle it with a scene "
                      "shader (templates/stage_surface.shader; _VertexColor 1 shows the model's own colours); %s"
                      % (entries[0]["id"], facing)) if kind == "model" else "",
            "sky": ("Use it on a sm_sky_panorama skybox material (\"_Tex\": {\"texture\": \"%s\"}); the setup needs "
                    "camera_properties clearFlags Skybox" % entries[0]["id"]),
            "texture": "Reference it from a material property of type Texture: {\"texture\": \"%s\"}" % entries[0]["id"]}[kind]
    return {"ref": ref, "kind": kind, "license": LICENSE, "written": written, "summary": summary, "warnings": warnings,
            "assets": entries, "added_to_spec": bool(add), "next": hint}


def _append(spec_path: Path, slug: str, entries: list[dict], force: bool) -> None:
    if spec_path.is_file():
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
    else:
        spec = {"format": "sabermapper-assets/1", "project": slug, "target": "windows2021", "compression": "lz4", "assets": []}
    existing = {a.get("id"): i for i, a in enumerate(spec.get("assets", []))}
    for entry in entries:
        if entry["id"] in existing:
            if not force:
                raise FetchError("fetch_id_taken", f"assets.json already has an asset {entry['id']!r}",
                                 "Pass --id for a new id, or --force to replace the entry")
            spec["assets"][existing[entry["id"]]] = entry
        else:
            spec.setdefault("assets", []).append(entry)
    spec_path.parent.mkdir(parents=True, exist_ok=True)
    spec_path.write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8", newline="\n")

"""Model files for the asset forge: glTF/GLB and OBJ in, a normalised OBJ out, and Unity mesh data for the build.

A mesh here is a dict of numpy arrays: ``positions`` (N, 3), ``uvs`` (N, 2) or None, ``colors`` (N, 4) linear RGBA
or None, and ``triangles`` (M, 3), plus ``parts`` naming the source meshes that were merged. Files on disk use the
usual OBJ and glTF convention (right-handed, +Y up, metres, counter-clockwise front faces). ``unity_mesh_data``
converts to Unity's left-handed space by negating x and reversing the winding, as Unity's own model importers do.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path
import struct

import numpy as np

OBJ_HEADER = "# sabermapper-mesh/1"

_COMPONENT = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16, 5125: np.uint32, 5126: np.float32}
_NORMALISE = {5120: 127.0, 5121: 255.0, 5122: 32767.0, 5123: 65535.0}
_WIDTH = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}
_COMPRESSED = ("KHR_draco_mesh_compression", "EXT_meshopt_compression", "KHR_meshopt_compression")


class MeshFileError(ValueError):
    """A model file that cannot be read, with a stable code and a fix."""

    def __init__(self, code: str, message: str, fix: str | None = None):
        super().__init__(message)
        self.code, self.message, self.fix = code, message, fix


def triangle_count(mesh: dict) -> int:
    return int(len(mesh["triangles"]))


# --------------------------------------------------------------------------- glTF


def parse_glb(data: bytes) -> tuple[dict, dict]:
    """(glTF JSON, {buffer index: bytes}) from a binary .glb container."""
    if data[:4] != b"glTF":
        raise MeshFileError("gltf_invalid", "Not a GLB file (missing glTF magic)")
    length = struct.unpack_from("<I", data, 8)[0]
    offset, doc, binary = 12, None, None
    while offset < min(length, len(data)):
        chunk_length, chunk_type = struct.unpack_from("<II", data, offset)
        body = data[offset + 8: offset + 8 + chunk_length]
        if chunk_type == 0x4E4F534A:
            doc = json.loads(body.decode("utf-8"))
        elif chunk_type == 0x004E4942:
            binary = body
        offset += 8 + chunk_length
    if doc is None:
        raise MeshFileError("gltf_invalid", "GLB has no JSON chunk")
    return doc, ({0: binary} if binary is not None else {})


def gltf_buffers(doc: dict, embedded: dict, load_uri) -> dict:
    """Every buffer's bytes: the GLB binary chunk, data URIs, or files fetched with ``load_uri(uri)``."""
    buffers = dict(embedded)
    for index, buffer in enumerate(doc.get("buffers", [])):
        if index in buffers:
            continue
        uri = buffer.get("uri")
        if uri is None:
            raise MeshFileError("gltf_invalid", f"buffer {index} has no data")
        if uri.startswith("data:"):
            buffers[index] = base64.b64decode(uri.split(",", 1)[1])
        else:
            buffers[index] = load_uri(uri)
    return buffers


def _accessor(doc: dict, buffers: dict, index: int) -> np.ndarray:
    acc = doc["accessors"][index]
    if "sparse" in acc:
        raise MeshFileError("gltf_sparse", "Sparse glTF accessors are not supported", "Pick another model or format")
    width = _WIDTH[acc["type"]]
    dtype = np.dtype(_COMPONENT[acc["componentType"]]).newbyteorder("<")
    count = acc["count"]
    if "bufferView" not in acc:
        return np.zeros((count, width), dtype=np.float64)
    view = doc["bufferViews"][acc["bufferView"]]
    data = buffers[view["buffer"]]
    start = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
    element = dtype.itemsize * width
    stride = view.get("byteStride") or element
    raw = data[start: start + (count - 1) * stride + element] if count else b""
    array = np.ndarray((count, width), dtype=dtype, buffer=raw, strides=(stride, dtype.itemsize)).copy()
    if acc.get("normalized") and acc["componentType"] in _NORMALISE:
        return np.maximum(array.astype(np.float64) / _NORMALISE[acc["componentType"]], -1.0)
    return array.astype(np.float64)


def _node_matrix(node: dict) -> np.ndarray:
    if "matrix" in node:
        return np.array(node["matrix"], dtype=np.float64).reshape(4, 4).T
    t = np.array(node.get("translation", [0, 0, 0]), dtype=np.float64)
    x, y, z, w = node.get("rotation", [0, 0, 0, 1])
    s = np.array(node.get("scale", [1, 1, 1]), dtype=np.float64)
    rotation = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                         [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                         [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
    matrix = np.eye(4)
    matrix[:3, :3] = rotation * s
    matrix[:3, 3] = t
    return matrix


def _srgb_to_linear(c: np.ndarray) -> np.ndarray:
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def gltf_nodes(doc: dict) -> list[dict]:
    """Mesh-bearing nodes of the default scene with their world matrices: [{name, mesh, matrix}]."""
    nodes = doc.get("nodes", [])
    scenes = doc.get("scenes") or []
    if scenes:
        roots = scenes[doc.get("scene", 0)].get("nodes", [])
    else:
        children = {c for n in nodes for c in n.get("children", [])}
        roots = [i for i in range(len(nodes)) if i not in children]
    found, stack = [], [(i, np.eye(4)) for i in roots]
    while stack:
        index, parent = stack.pop()
        node = nodes[index]
        matrix = parent @ _node_matrix(node)
        if "mesh" in node:
            mesh = doc["meshes"][node["mesh"]]
            found.append({"name": node.get("name") or mesh.get("name") or f"node{index}", "mesh": node["mesh"],
                          "matrix": matrix})
        stack.extend((c, matrix) for c in node.get("children", []))
    return found


def load_gltf(doc: dict, buffers: dict, nodes: list[str] | None = None, *,
              srgb_factors: bool = False) -> tuple[dict, list[str]]:
    """Merge the triangle primitives of the chosen nodes (all by default) into one mesh in glTF space.

    Material base colours become vertex colours. glTF defines them as linear; ``srgb_factors`` converts files whose
    exporter wrote display (sRGB) values instead, as Kenney's packs do (their factors equal their MTL Kd values and
    their preview renders show them as sRGB).
    """
    for ext in doc.get("extensionsRequired", []):
        if ext in _COMPRESSED:
            raise MeshFileError("gltf_compressed", f"The model uses {ext}, which cannot be decoded here",
                                "Pick the OBJ or an uncompressed glTF variant of the model")
    materials = doc.get("materials", [])
    wanted = {n.lower() for n in nodes} if nodes else None
    positions, uvs, colors, triangles, parts, warnings = [], [], [], [], [], []
    base = 0
    has_uv = has_color = False
    chosen = [n for n in gltf_nodes(doc) if wanted is None or n["name"].lower() in wanted]
    if not chosen:
        names = sorted(n["name"] for n in gltf_nodes(doc))
        raise MeshFileError("model_node_unknown", f"No mesh node named {sorted(wanted or [])}; nodes: {names[:40]}",
                            "Pick node names from `assets fetch info`")
    for node in chosen:
        matrix = node["matrix"]
        flip = np.linalg.det(matrix[:3, :3]) < 0
        for primitive in doc["meshes"][node["mesh"]].get("primitives", []):
            mode = primitive.get("mode", 4)
            if mode != 4:
                warnings.append(f"{node['name']}: primitive mode {mode} (not triangles) skipped")
                continue
            attributes = primitive["attributes"]
            if "POSITION" not in attributes:
                continue
            p = _accessor(doc, buffers, attributes["POSITION"])[:, :3]
            p = (np.c_[p, np.ones(len(p))] @ matrix.T)[:, :3]
            n = len(p)
            if "indices" in primitive:
                tris = _accessor(doc, buffers, primitive["indices"]).astype(np.int64).reshape(-1, 3)
            else:
                tris = np.arange(n - n % 3, dtype=np.int64).reshape(-1, 3)
            if flip:
                tris = tris[:, [0, 2, 1]]
            uv = _accessor(doc, buffers, attributes["TEXCOORD_0"])[:, :2] if "TEXCOORD_0" in attributes else None
            factor = np.array([1.0, 1.0, 1.0, 1.0])
            if "material" in primitive and primitive["material"] < len(materials):
                pbr = materials[primitive["material"]].get("pbrMetallicRoughness", {})
                factor = np.array(pbr.get("baseColorFactor") or [1, 1, 1, 1], dtype=np.float64)[:4]
                if srgb_factors:
                    factor[:3] = _srgb_to_linear(factor[:3])
            col = np.tile(factor, (n, 1))
            if "COLOR_0" in attributes:
                c = _accessor(doc, buffers, attributes["COLOR_0"])
                c = np.c_[c, np.ones(n)] if c.shape[1] == 3 else c
                col = col * c
            has_uv |= uv is not None
            has_color |= not np.allclose(col, 1.0)
            positions.append(p)
            uvs.append(uv if uv is not None else np.zeros((n, 2)))
            colors.append(col)
            triangles.append(tris + base)
            base += n
        parts.append(node["name"])
    if not positions:
        raise MeshFileError("model_empty", "The model has no triangle geometry", "Pick another model")
    mesh = {"positions": np.vstack(positions), "uvs": np.vstack(uvs) if has_uv else None,
            "colors": np.vstack(colors) if has_color else None, "triangles": np.vstack(triangles), "parts": parts}
    return mesh, warnings


# --------------------------------------------------------------------------- OBJ


def read_obj(text: str, mtl_colors: dict | None = None) -> dict:
    """OBJ with optional vertex colours (``v x y z r g b``) and ``usemtl`` diffuse colours (sRGB, from an MTL)."""
    vs, vcs, vts, faces = [], [], [], []
    material = None
    for line in text.splitlines():
        parts = line.split()
        if not parts:
            continue
        head = parts[0]
        if head == "v":
            values = [float(x) for x in parts[1:]]
            vs.append(values[:3])
            vcs.append(values[3:6] if len(values) >= 6 else None)
        elif head == "vt":
            vts.append([float(x) for x in parts[1:3]])
        elif head == "usemtl":
            material = parts[1] if len(parts) > 1 else None
        elif head == "f":
            corners = []
            for token in parts[1:]:
                fields = token.split("/")
                vi = int(fields[0])
                ti = int(fields[1]) if len(fields) > 1 and fields[1] else 0
                corners.append((vi - 1 if vi > 0 else len(vs) + vi, (ti - 1 if ti > 0 else len(vts) + ti) if ti else -1))
            for k in range(1, len(corners) - 1):
                faces.append((corners[0], corners[k], corners[k + 1], material))
    if not faces:
        raise MeshFileError("model_empty", "The OBJ has no faces", "Export triangles or polygons")
    index, positions, uvs, colors, triangles = {}, [], [], [], []
    any_uv = any(c[1] >= 0 for f in faces for c in f[:3])
    any_color = any(c is not None for c in vcs) or bool(mtl_colors)
    for face in faces:
        tri = []
        for vi, ti in face[:3]:
            key = (vi, ti, face[3])
            if key not in index:
                index[key] = len(positions)
                positions.append(vs[vi])
                uvs.append(vts[ti] if ti >= 0 else [0.0, 0.0])
                if vcs[vi] is not None:
                    colors.append(list(vcs[vi]) + [1.0])
                elif mtl_colors and face[3] in mtl_colors:
                    colors.append(list(_srgb_to_linear(np.array(mtl_colors[face[3]]))) + [1.0])
                else:
                    colors.append([1.0, 1.0, 1.0, 1.0])
            tri.append(index[key])
        triangles.append(tri)
    return {"positions": np.array(positions, dtype=np.float64), "uvs": np.array(uvs) if any_uv else None,
            "colors": np.array(colors) if any_color else None, "triangles": np.array(triangles, dtype=np.int64),
            "parts": []}


def read_mtl(text: str) -> dict:
    colors, name = {}, None
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] == "newmtl":
            name = parts[1]
        elif len(parts) >= 4 and parts[0] == "Kd" and name:
            colors[name] = [float(x) for x in parts[1:4]]
    return colors


def obj_triangle_count(path: Path) -> int:
    """Triangles an OBJ yields once its polygons are fanned (for lint, without loading the geometry)."""
    count = 0
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if line.startswith("f "):
                count += max(len(line.split()) - 3, 0)
    return count


def write_obj(mesh: dict, path: Path, comments: list[str] = ()) -> None:
    lines = [OBJ_HEADER, *[f"# {c}" for c in comments]]
    colors = mesh.get("colors")
    for i, p in enumerate(mesh["positions"]):
        if colors is not None:
            c = colors[i]
            lines.append(f"v {p[0]:.5f} {p[1]:.5f} {p[2]:.5f} {c[0]:.4f} {c[1]:.4f} {c[2]:.4f}")
        else:
            lines.append(f"v {p[0]:.5f} {p[1]:.5f} {p[2]:.5f}")
    uvs = mesh.get("uvs")
    if uvs is not None:
        lines.extend(f"vt {u:.5f} {v:.5f}" for u, v in uvs)
        lines.extend(f"f {a + 1}/{a + 1} {b + 1}/{b + 1} {c + 1}/{c + 1}" for a, b, c in mesh["triangles"])
    else:
        lines.extend(f"f {a + 1} {b + 1} {c + 1}" for a, b, c in mesh["triangles"])
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


# --------------------------------------------------------------------------- processing


def bounds(mesh: dict) -> dict:
    p = mesh["positions"]
    lo, hi = p.min(axis=0), p.max(axis=0)
    return {"min": [round(float(x), 4) for x in lo], "max": [round(float(x), 4) for x in hi],
            "size": [round(float(x), 4) for x in hi - lo]}


def normalise(mesh: dict, *, origin: str = "base", height: float | None = None) -> dict:
    """Move the origin (``base``: centre of the footprint at the lowest point; ``center``; ``keep``) and scale
    uniformly so the model is ``height`` metres tall."""
    p = mesh["positions"].copy()
    lo, hi = p.min(axis=0), p.max(axis=0)
    if origin == "base":
        p -= np.array([(lo[0] + hi[0]) / 2, lo[1], (lo[2] + hi[2]) / 2])
    elif origin == "center":
        p -= (lo + hi) / 2
    if height:
        extent = hi[1] - lo[1]
        if extent > 1e-9:
            p *= height / extent
    return {**mesh, "positions": p}


def _cluster(mesh: dict, cells: int):
    p = mesh["positions"]
    lo = p.min(axis=0)
    size = max(float((p.max(axis=0) - lo).max()), 1e-9)
    keys = np.floor((p - lo) / (size / cells)).astype(np.int64)
    _, inverse = np.unique(keys, axis=0, return_inverse=True)
    inverse = inverse.reshape(-1)
    tris = inverse[mesh["triangles"]]
    keep = (tris[:, 0] != tris[:, 1]) & (tris[:, 1] != tris[:, 2]) & (tris[:, 0] != tris[:, 2])
    tris = tris[keep]
    if len(tris):
        _, unique_rows = np.unique(np.sort(tris, axis=1), axis=0, return_index=True)
        tris = tris[np.sort(unique_rows)]
    return inverse, tris


def decimate(mesh: dict, max_triangles: int) -> tuple[dict, dict | None]:
    """Vertex clustering on a uniform grid, searched for the finest grid within ``max_triangles``.

    Positions and colours average per cell; UVs keep the first vertex's value, so decimated models suit
    object- or world-space shaders better than their original textures.
    """
    before = triangle_count(mesh)
    if before <= max_triangles:
        return mesh, None
    low, high, best = 2, 2048, None
    while low <= high:
        cells = (low + high) // 2
        inverse, tris = _cluster(mesh, cells)
        if len(tris) <= max_triangles:
            best, low = (cells, inverse, tris), cells + 1
        else:
            high = cells - 1
    if best is None:
        raise MeshFileError("decimate_failed", f"Cannot bring {before} triangles under {max_triangles}",
                            "Raise --max-triangles or pick a simpler model")
    cells, inverse, tris = best
    count = int(inverse.max()) + 1
    weight = np.bincount(inverse, minlength=count).astype(np.float64)[:, None]
    positions = np.zeros((count, 3))
    np.add.at(positions, inverse, mesh["positions"])
    positions /= weight
    colors = None
    if mesh.get("colors") is not None:
        colors = np.zeros((count, 4))
        np.add.at(colors, inverse, mesh["colors"])
        colors /= weight
    uvs = None
    if mesh.get("uvs") is not None:
        first = np.full(count, -1, dtype=np.int64)
        order = np.arange(len(inverse))[::-1]
        first[inverse[order]] = order
        uvs = mesh["uvs"][first]
    used = np.unique(tris)
    remap = np.full(count, -1, dtype=np.int64)
    remap[used] = np.arange(len(used))
    result = {"positions": positions[used], "uvs": uvs[used] if uvs is not None else None,
              "colors": colors[used] if colors is not None else None, "triangles": remap[tris],
              "parts": mesh.get("parts", [])}
    return result, {"op": "decimate", "method": "vertex_clustering", "grid_cells": int(cells),
                    "triangles_before": before, "triangles_after": int(len(tris))}


def unity_mesh_data(mesh: dict) -> dict:
    """Flat arrays for the C# forge, converted to Unity's left-handed space (x negated, winding reversed)."""
    p = mesh["positions"].copy()
    p[:, 0] = -p[:, 0]
    tris = mesh["triangles"][:, [0, 2, 1]]
    data = {"format": "sabermapper-mesh-data/1", "vertices": [round(float(x), 5) for x in p.reshape(-1)],
            "triangles": [int(x) for x in tris.reshape(-1)]}
    if mesh.get("uvs") is not None:
        data["uvs"] = [round(float(x), 5) for x in mesh["uvs"].reshape(-1)]
    if mesh.get("colors") is not None:
        data["colors"] = [round(float(x), 4) for x in mesh["colors"].reshape(-1)]
    return data


def load_model_file(path: Path) -> dict:
    """A model file as a mesh: OBJ (with its MTL next to it) or a self-contained GLB."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".obj":
        text = path.read_text(encoding="utf-8", errors="replace")
        mtl = None
        for line in text.splitlines():
            if line.startswith("mtllib "):
                candidate = path.parent / line.split(None, 1)[1].strip()
                if candidate.is_file():
                    mtl = read_mtl(candidate.read_text(encoding="utf-8", errors="replace"))
        return read_obj(text, mtl)
    if suffix == ".glb":
        doc, embedded = parse_glb(path.read_bytes())
        return load_gltf(doc, gltf_buffers(doc, embedded, lambda uri: (path.parent / uri).read_bytes()))[0]
    if suffix == ".gltf":
        doc = json.loads(path.read_text(encoding="utf-8"))
        return load_gltf(doc, gltf_buffers(doc, {}, lambda uri: (path.parent / uri).read_bytes()))[0]
    raise MeshFileError("model_format", f"{path.name}: use .obj, .glb or .gltf", "Convert the model to OBJ or glTF")

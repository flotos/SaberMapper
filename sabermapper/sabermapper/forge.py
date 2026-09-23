"""Vivify asset forge: assets.json validation, shader lint, budgets and the Unity batchmode build driver.

Everything except `build` runs without Unity. `build` stages the spec into a machine-local copy of the
VivifyTemplate-style project in `assets/vivify-src/`, runs `SaberMapper.Forge.Build` in batchmode and turns
the editor log and build report into structured errors. See docs/asset-forge.md.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import uuid

from .storage import WorkspaceLock, now, read_json, write_json

ASSETS_ROOT = Path(__file__).resolve().parents[1] / "assets"
LIBRARY_DIR = ASSETS_ROOT / "library"
TEMPLATE_DIR = ASSETS_ROOT / "vivify-src"
SPEC_FORMAT = "sabermapper-assets/1"
STAGED_FORMAT = "sabermapper-forge-staged/1"
DEFAULT_TARGET = "windows2021"
# Researched 2026-09-23 (docs/asset-forge.md): Vivify loads bundle<Suffix>.vivify and checks
# Info.dat _assetBundle.<key>; every build except the one for game 1.29.1 uses Windows2021/_windows2021,
# including 1.40.8 (Unity 2022.3.33). The Heck docs name Unity 2021.3.16f1 for game 1.30.0+.
TARGETS = {
    "windows2021": {"bundle_file": "bundleWindows2021.vivify", "crc_key": "_windows2021",
                    "unity_version": "2021.3.16f1", "unity_changeset": "4016570cf34f",
                    "game_versions": "1.30.0 and later, including the installed 1.40.8",
                    "stereo": "single-pass instanced"},
    "windows2019": {"bundle_file": "bundleWindows2019.vivify", "crc_key": "_windows2019",
                    "unity_version": "2019.4.28f1", "unity_changeset": "1381962e9d08",
                    "game_versions": "1.29.1 only", "stereo": "single-pass (legacy VR)"},
}
UNSUPPORTED_TARGETS = {"android2021": "Quest bundles are out of scope: the user chose PCVR only (2026-09-23)"}
KINDS = {"material": (".mat",), "post_process": (".mat",), "skybox": (".mat",), "prefab": (".prefab",),
         "particles": (".prefab",), "mesh": (".asset",), "texture": (".png", ".jpg", ".jpeg", ".tga", ".exr")}
MATERIAL_KINDS = ("material", "post_process", "skybox")
DEFAULT_BUDGETS = {"max_triangles_per_mesh": 20000, "max_total_triangles": 150000, "max_renderers": 64,
                   "max_particles": 4000, "max_texture_samples": 24, "max_loop_iterations": 64,
                   "max_texture_size": 4096, "max_bundle_mb": 64}
ASSUMED_UNBOUNDED_LOOP = 16
RESERVED_SLUGS = {"editor", "staging", "xr", "library"}
BUILTIN_SHADER_INCLUDES = {"unitycg.cginc", "unityshadervariables.cginc", "lighting.cginc", "autolight.cginc",
                           "unitypbslighting.cginc", "unitystandardutils.cginc", "unityinstancing.cginc",
                           "hlslsupport.cginc", "unityshaderutilities.cginc", "unitysprites.cginc", "unityui.cginc",
                           "unitystandardcore.cginc", "unitystandardbrdf.cginc", "unityglobalillumination.cginc"}
GENERATOR_KINDS = {
    "image": "text-to-image model (texture or equirectangular skybox), e.g. a FLUX/SDXL pipeline on the local RTX 5070 Ti",
    "skybox": "text-to-image model producing a 2:1 equirectangular panorama for a cubemap skybox",
    "mesh": "text-to-3D model (e.g. TRELLIS or Hunyuan3D) followed by Blender decimation to the triangle budget",
}


class ForgeError(Exception):
    """Failure with a stable code, an actionable fix and optional structured details."""

    def __init__(self, code: str, message: str, fix: str | None = None, **details):
        super().__init__(message)
        self.code, self.message, self.fix, self.details = code, message, fix, details

    def as_dict(self) -> dict:
        error = {"code": self.code, "message": self.message}
        if self.fix:
            error["fix"] = self.fix
        error.update(self.details)
        return {"error": error}


def _diag(severity, rule, message, fix=None, file=None, line=None, asset=None) -> dict:
    item = {"severity": severity, "rule": rule, "message": message}
    for key, value in (("asset", asset), ("file", str(file) if file else None), ("line", line), ("fix", fix)):
        if value is not None:
            item[key] = value
    return item


# --------------------------------------------------------------------------- library

def load_library(library_dir: Path | None = None) -> dict:
    directory = Path(library_dir or LIBRARY_DIR)
    library = read_json(directory / "library.json")
    library["_dir"] = str(directory)
    return library


def library_shader_path(library: dict, shader_id: str) -> Path:
    return Path(library["_dir"]) / library["shaders"][shader_id]["file"]


# --------------------------------------------------------------------------- shader analysis

_COMMENT = re.compile(r"//[^\n]*|/\*.*?\*/", re.S)
_PROPERTY = re.compile(
    r'^\s*(?:\[[^\]]*\]\s*)*(?P<name>[A-Za-z_]\w*)\s*\(\s*"(?P<label>[^"]*)"\s*,\s*'
    r'(?P<type>Range\s*\(\s*(?P<min>[-+\d.eE]+)\s*,\s*(?P<max>[-+\d.eE]+)\s*\)|Float|Int|Integer|Color|Vector|'
    r'2DArray|2D|3D|CubeArray|Cube|Any)\s*\)\s*=\s*(?P<default>.+?)\s*$')
_SAMPLE = re.compile(r"\b(?:tex2D\w*|tex3D\w*|texCUBE\w*|UNITY_SAMPLE_\w+|SAMPLE_TEXTURE\w*|SAMPLE_DEPTH_TEXTURE\w*)\s*\(|"
                     r"\.Sample(?:Level|Bias|Grad)?\s*\(")
_FOR = re.compile(r"\bfor\s*\(([^;]*);([^;]*);[^)]*\)")
_FUNC = re.compile(r"\b(?P<ret>[A-Za-z_]\w*)\s+(?P<name>[A-Za-z_]\w*)\s*\((?P<args>[^;{}()]*)\)\s*(?::\s*\w+\s*)?\{")
_KEYWORDS = {"if", "for", "while", "switch", "return", "else", "do"}


def _strip_comments(text: str) -> str:
    return _COMMENT.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), text)


def _line(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _block(text: str, open_index: int) -> tuple[int, int]:
    """(start, end) of the brace block whose '{' is at open_index; end is exclusive of the closing brace."""
    depth = 0
    for index in range(open_index, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return open_index + 1, index
    return open_index + 1, len(text)


def _number(text: str):
    value = float(text)
    return int(value) if value.is_integer() else value


def _vivify_type(shader_type: str) -> str:
    if shader_type.startswith("Range") or shader_type in ("Float", "Int", "Integer"):
        return "Float"
    if shader_type in ("Color", "Vector"):
        return shader_type
    return "Texture"


def parse_shader(text: str) -> dict:
    """Shader name, typed Properties and program blocks, with 1-based line numbers."""
    clean = _strip_comments(text)
    name = re.search(r'\bShader\s+"([^"]+)"', clean)
    result = {"name": name.group(1) if name else None, "name_line": _line(clean, name.start()) if name else None,
              "properties": {}, "programs": []}
    props = re.search(r"\bProperties\s*\{", clean)
    if props:
        start, end = _block(clean, props.end() - 1)
        first_line = _line(clean, start)
        for offset, raw in enumerate(clean[start:end].split("\n")):
            match = _PROPERTY.match(raw)
            if not match:
                continue
            kind = match.group("type").replace(" ", "")
            default = match.group("default").strip()
            entry = {"label": match.group("label"), "shader_type": kind.split("(")[0], "type": _vivify_type(kind),
                     "line": first_line + offset}
            if match.group("min") is not None:
                entry["range"] = [_number(match.group("min")), _number(match.group("max"))]
            tuple_match = re.match(r"\(\s*([^)]*)\)", default)
            if tuple_match:
                entry["default"] = [_number(part) for part in tuple_match.group(1).split(",") if part.strip()]
            elif re.match(r"[-+\d.]", default):
                entry["default"] = _number(default.split()[0])
            else:
                entry["default"] = default.split("{")[0].strip().strip('"')
            result["properties"][match.group("name")] = entry
    for match in re.finditer(r"\b(CGPROGRAM|HLSLPROGRAM)\b(.*?)\b(ENDCG|ENDHLSL)\b", clean, re.S):
        result["programs"].append({"start": match.start(2), "line": _line(clean, match.start(1)), "body": match.group(2)})
    result["_clean"] = clean
    return result


def _functions(body: str) -> dict:
    found = {}
    for match in _FUNC.finditer(body):
        if match.group("ret") in _KEYWORDS or match.group("name") in _KEYWORDS:
            continue
        start, end = _block(body, match.end() - 1)
        found[match.group("name")] = {"ret": match.group("ret"), "args": match.group("args"), "offset": match.start(),
                                      "body": body[start:end]}
    return found


def _struct(body: str, name: str):
    match = re.search(r"\bstruct\s+" + re.escape(name) + r"\s*\{", body)
    if not match:
        return None, None
    start, end = _block(body, match.end() - 1)
    return body[start:end], match.start()


def _loop_bound(condition: str):
    match = re.search(r"\w+\s*(<=|<)\s*(\d+)\b", condition)
    if not match:
        return None
    return int(match.group(2)) + (1 if match.group(1) == "<=" else 0)


def _cost(text: str, functions: dict, stack: tuple = ()) -> tuple[int, int, int]:
    """(texture samples, loop iterations, unbounded loops) for code, following calls one level at a time."""
    samples, iterations, unbounded = len(_SAMPLE.findall(text)), 0, 0
    for name, info in functions.items():
        if name in stack:
            continue
        calls = len(re.findall(r"\b" + re.escape(name) + r"\s*\(", text))
        if calls:
            s, i, u = _cost(info["body"], functions, stack + (name,))
            samples, iterations, unbounded = samples + calls * s, iterations + calls * i, unbounded + u
    for match in _FOR.finditer(text):
        after = match.end()
        while after < len(text) and text[after].isspace():
            after += 1
        if after < len(text) and text[after] == "{":
            start, end = _block(text, after)
            loop_body = text[start:end]
        else:
            loop_body = text[after:text.find(";", after) + 1]
        bound = _loop_bound(match.group(2))
        if bound is None:
            unbounded += 1
            bound = ASSUMED_UNBOUNDED_LOOP
        s, i, u = _cost(loop_body, functions, stack)
        # The body was already counted once in this text; add the remaining iterations.
        samples += s * (bound - 1)
        iterations += bound + i * (bound - 1)
    return samples, iterations, unbounded


def shader_cost(text: str) -> dict:
    parsed = parse_shader(text)
    samples = iterations = unbounded = 0
    for program in parsed["programs"]:
        body = program["body"]
        functions = _functions(body)
        fragment = re.search(r"#pragma\s+fragment\s+(\w+)", body)
        entry = functions.get(fragment.group(1)) if fragment else None
        s, i, u = _cost(entry["body"], {k: v for k, v in functions.items() if k != fragment.group(1)}) if entry \
            else _cost(body, {})
        samples, iterations, unbounded = samples + s, iterations + i, unbounded + u
    return {"texture_samples": samples, "loop_iterations": iterations, "unbounded_loops": unbounded}


def _with_includes(body: str, shader_path: Path | None) -> str:
    if shader_path is None:
        return body
    extra = []
    for include in re.findall(r'#include\s+"([^"]+)"', body):
        if include.lower().split("/")[-1] in BUILTIN_SHADER_INCLUDES or include.startswith("Packages/"):
            continue
        candidate = (shader_path.parent / include)
        if candidate.is_file():
            extra.append(_strip_comments(candidate.read_text(encoding="utf-8-sig", errors="replace")))
    return body + "\n" + "\n".join(extra)


def lint_shader(text: str, *, kind: str = "material", file=None, budgets: dict | None = None, asset=None) -> list[dict]:
    """Single-pass-instanced and screen-space rules plus the cost heuristic; returns diagnostics."""
    budgets = {**DEFAULT_BUDGETS, **(budgets or {})}
    parsed = parse_shader(text)
    clean = parsed["_clean"]
    out = []

    def add(severity, rule, message, fix, offset=None, line=None):
        out.append(_diag(severity, rule, message, fix, file, line if line else (_line(clean, offset) if offset is not None else None), asset))

    if not parsed["name"]:
        add("error", "shader_name_missing", 'No `Shader "Name"` declaration found', 'Start the file with Shader "SaberMapper/..."', line=1)
    if not parsed["programs"]:
        add("error", "shader_program_missing", "No CGPROGRAM/HLSLPROGRAM block found",
            "Write a vertex/fragment program; fixed-function and Shader Graph shaders are not supported")
    if re.search(r"\bGrabPass\b", clean):
        add("warning", "grabpass", "GrabPass copies the screen for every use and is expensive in VR",
            "Prefer a Vivify Blit post-process material", offset=re.search(r"\bGrabPass\b", clean).start())
    for program in parsed["programs"]:
        base = program["start"]
        body = _with_includes(program["body"], Path(file) if file else None)
        if re.search(r"#pragma\s+surface\b", body):
            add("warning", "surface_shader", "Surface shaders get stereo support generated by Unity but are lit and heavier",
                "Prefer an unlit vertex/fragment shader from the library template", line=program["line"])
            continue
        vertex = re.search(r"#pragma\s+vertex\s+(\w+)", body)
        fragment = re.search(r"#pragma\s+fragment\s+(\w+)", body)
        if not vertex or not fragment:
            add("error", "shader_entry_missing", "Program lacks #pragma vertex or #pragma fragment",
                "Declare both entry points", line=program["line"])
            continue
        functions = _functions(body)
        vert, frag = functions.get(vertex.group(1)), functions.get(fragment.group(1))
        at = lambda local: base + local if local is not None and local < len(program["body"]) else None
        if vert is None or frag is None:
            add("error", "shader_entry_missing", f"Entry function {vertex.group(1) if vert is None else fragment.group(1)} not found",
                "Define the functions named by #pragma vertex/fragment", line=program["line"])
            continue
        arg = re.match(r"\s*(?:in\s+)?(\w+)\s+(\w+)", vert["args"])
        in_body, in_offset = _struct(body, arg.group(1)) if arg else (None, None)
        out_body, out_offset = _struct(body, vert["ret"])
        if in_body is not None and "UNITY_VERTEX_INPUT_INSTANCE_ID" not in in_body:
            add("error", "stereo_input_instance_id", f"Vertex input struct {arg.group(1)} lacks UNITY_VERTEX_INPUT_INSTANCE_ID",
                "Add UNITY_VERTEX_INPUT_INSTANCE_ID as the last member of the vertex input struct", offset=at(in_offset))
        elif in_body is None and "UNITY_VERTEX_INPUT_INSTANCE_ID" not in body:
            add("error", "stereo_input_instance_id", "No UNITY_VERTEX_INPUT_INSTANCE_ID in the vertex input",
                "Add UNITY_VERTEX_INPUT_INSTANCE_ID to the vertex input struct", offset=at(vert["offset"]))
        if out_body is not None and "UNITY_VERTEX_OUTPUT_STEREO" not in out_body:
            add("error", "stereo_output", f"Vertex output struct {vert['ret']} lacks UNITY_VERTEX_OUTPUT_STEREO",
                "Add UNITY_VERTEX_OUTPUT_STEREO as the last member of the vertex output struct", offset=at(out_offset))
        elif out_body is None and "UNITY_VERTEX_OUTPUT_STEREO" not in body:
            add("error", "stereo_output", "No UNITY_VERTEX_OUTPUT_STEREO in the vertex output",
                "Add UNITY_VERTEX_OUTPUT_STEREO to the vertex output struct", offset=at(vert["offset"]))
        if "UNITY_SETUP_INSTANCE_ID" not in vert["body"]:
            add("error", "stereo_setup_instance", f"{vertex.group(1)} does not call UNITY_SETUP_INSTANCE_ID(v)",
                "Call UNITY_SETUP_INSTANCE_ID(v) first in the vertex function", offset=at(vert["offset"]))
        if "UNITY_INITIALIZE_VERTEX_OUTPUT_STEREO" not in vert["body"]:
            add("error", "stereo_init_output", f"{vertex.group(1)} does not call UNITY_INITIALIZE_VERTEX_OUTPUT_STEREO(o)",
                "Call UNITY_INITIALIZE_OUTPUT(v2f, o); UNITY_INITIALIZE_VERTEX_OUTPUT_STEREO(o); after UNITY_SETUP_INSTANCE_ID",
                offset=at(vert["offset"]))
        if "UNITY_SETUP_STEREO_EYE_INDEX_POST_VERTEX" not in frag["body"]:
            add("error", "stereo_eye_index", f"{fragment.group(1)} does not call UNITY_SETUP_STEREO_EYE_INDEX_POST_VERTEX(i)",
                "Call UNITY_SETUP_STEREO_EYE_INDEX_POST_VERTEX(i) first in the fragment function", offset=at(frag["offset"]))
        if kind == "post_process":
            sampler = re.search(r"\bsampler2D\s+_MainTex\b", body)
            if sampler:
                add("error", "screenspace_declare", "Blit shaders must not declare _MainTex as sampler2D: in single-pass instanced "
                    "the screen is a texture array", "Use UNITY_DECLARE_SCREENSPACE_TEXTURE(_MainTex);", offset=at(sampler.start()))
            elif not re.search(r"UNITY_DECLARE_SCREENSPACE_TEXTURE\s*\(\s*_MainTex\s*\)", body):
                add("error", "screenspace_declare", "Blit shader does not declare UNITY_DECLARE_SCREENSPACE_TEXTURE(_MainTex)",
                    "Declare the screen with UNITY_DECLARE_SCREENSPACE_TEXTURE(_MainTex);", line=program["line"])
            direct = re.search(r"\btex2D\w*\s*\(\s*_MainTex\b", body)
            if direct:
                add("error", "screenspace_sample", "tex2D on the screen texture samples the left eye only",
                    "Use UNITY_SAMPLE_SCREENSPACE_TEXTURE(_MainTex, uv)", offset=at(direct.start()))
            elif "UNITY_SAMPLE_SCREENSPACE_TEXTURE" not in body:
                add("error", "screenspace_sample", "Blit shader never samples the screen with UNITY_SAMPLE_SCREENSPACE_TEXTURE",
                    "Sample with UNITY_SAMPLE_SCREENSPACE_TEXTURE(_MainTex, uv)", line=program["line"])
            if "UnityStereoTransformScreenSpaceTex" not in body:
                add("warning", "screenspace_transform", "UVs are not passed through UnityStereoTransformScreenSpaceTex",
                    "Wrap screen UVs in UnityStereoTransformScreenSpaceTex(i.uv) (Vivify docs; needed for single-pass double-wide)",
                    line=program["line"])
        for loop in _FOR.finditer(program["body"]):
            if _loop_bound(loop.group(2)) is None:
                add("warning", "unbounded_loop", "Loop bound is not a literal; the cost heuristic assumes "
                    f"{ASSUMED_UNBOUNDED_LOOP} iterations", "Use a literal bound with an early break on the property",
                    offset=base + loop.start())
    cost = shader_cost(text)
    if cost["texture_samples"] > budgets["max_texture_samples"]:
        add("error", "cost_texture_samples", f"Fragment cost estimate is {cost['texture_samples']} texture samples per pixel; "
            f"budgets.max_texture_samples is {budgets['max_texture_samples']}",
            "Reduce taps or loop counts (every sample runs twice per frame in VR at full resolution)", line=1)
    if cost["loop_iterations"] > budgets["max_loop_iterations"]:
        add("error", "cost_loop_iterations", f"Loop iterations per pixel estimate is {cost['loop_iterations']}; "
            f"budgets.max_loop_iterations is {budgets['max_loop_iterations']}", "Lower loop bounds or octave counts", line=1)
    return out


# --------------------------------------------------------------------------- meshes

def _safe_eval(formula: str, names: dict) -> float:
    tree = ast.parse(formula, mode="eval")
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant, ast.Name, ast.Load,
                                 ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.USub, ast.UAdd)):
            raise ValueError(f"Unsupported expression in triangle formula {formula!r}")
    return eval(compile(tree, "<formula>", "eval"), {"__builtins__": {}}, names)


def mesh_triangles(generator: str, params: dict, library: dict) -> int:
    """Triangle count of a built-in generator from the library formula (params merged with its defaults)."""
    entry = library["meshes"][generator]
    names = {**entry["params"], **(params or {})}
    minimums = {"segments": 3, "sides": 3, "rings": 2, "segments_x": 1, "segments_z": 1, "length_segments": 1}
    for key, minimum in minimums.items():
        if key in names and isinstance(names[key], (int, float)):
            names[key] = max(minimum, int(round(names[key])))
    return int(_safe_eval(entry["triangles"], names))


# --------------------------------------------------------------------------- spec validation

_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")
_SLUG = re.compile(r"[a-z0-9][a-z0-9_-]{0,79}")
_PATH_CHARS = re.compile(r"[a-z0-9_./-]+")


def project_slug(project_id: str) -> str:
    slug = project_id.lower()
    if not _SLUG.fullmatch(slug) or slug in RESERVED_SLUGS:
        raise ForgeError("project_slug_invalid", f"Project id {project_id!r} cannot be an asset path segment",
                         f"Use lowercase letters, digits, '-' or '_' and avoid {sorted(RESERVED_SLUGS)}")
    return slug


def _num(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _numbers(value, lengths) -> bool:
    return isinstance(value, list) and len(value) in lengths and all(_num(v) for v in value)


def _check_property(name, value, prop, safe, add):
    kind = prop["type"]
    if kind == "Float":
        if not _num(value):
            return add("error", "property_type", f"{name} is a Float; got {value!r}", "Use a number")
        low, high = prop.get("range", [None, None])
        if low is not None and not low <= value <= high:
            return add("error", "property_out_of_range", f"{name}={value} is outside the shader Range({low}, {high})",
                       f"Clamp to [{low}, {high}]")
        if safe and not safe[0] <= value <= safe[1]:
            add("warning", "property_outside_safe_range", f"{name}={value} is outside the library safe range {safe}",
                "Keep inside the safe range unless the concept needs the extreme and a frame check confirms it reads")
    elif kind == "Color":
        if not _numbers(value, (3, 4)):
            return add("error", "property_type", f"{name} is a Color; got {value!r}", "Use [r, g, b] or [r, g, b, a]")
        if any(v < 0 for v in value):
            add("error", "property_out_of_range", f"{name} has a negative channel", "Use channels >= 0 (HDR above 1 is allowed)")
    elif kind == "Vector":
        if not _numbers(value, (2, 3, 4)):
            return add("error", "property_type", f"{name} is a Vector; got {value!r}", "Use a list of 2-4 numbers")
    elif not (isinstance(value, dict) and isinstance(value.get("texture"), str)):
        add("error", "property_type", f"{name} is a Texture; got {value!r}", 'Use {"texture": "<texture asset id>"}')


def _provenance(asset, tier, add, base_dir):
    prov = asset.get("provenance")
    if tier == 1:
        return
    if not isinstance(prov, dict):
        return add("error", "provenance_missing", f"Tier {tier} assets need a provenance record",
                   'Tier 2: {"author": "agent", "description": ...}; tier 3: see docs/asset-forge.md#tier-3')
    if tier == 2:
        for key in ("author", "description"):
            if not prov.get(key):
                add("error", "provenance_incomplete", f"Tier 2 provenance lacks {key!r}", f"Add provenance.{key}")
        return
    gen = prov.get("generator")
    if not isinstance(gen, dict):
        return add("error", "provenance_incomplete", "Tier 3 provenance lacks the generator record",
                   'Add provenance.generator {kind, model, model_version, backend, prompt, seed}')
    for key in ("kind", "model", "model_version", "backend", "prompt", "seed"):
        if gen.get(key) in (None, ""):
            add("error", "provenance_incomplete", f"Tier 3 provenance.generator lacks {key!r}", f"Record provenance.generator.{key}")
    for key in ("created_at", "license", "output_sha256"):
        if not prov.get(key):
            add("error", "provenance_incomplete", f"Tier 3 provenance lacks {key!r}", f"Record provenance.{key}")
    source = asset.get("source")
    if source and prov.get("output_sha256") and (base_dir / source).is_file():
        actual = hashlib.sha256((base_dir / source).read_bytes()).hexdigest()
        if actual != prov["output_sha256"]:
            add("error", "provenance_hash_mismatch", f"{source} does not match provenance.output_sha256",
                "Regenerate the provenance record for the file actually used")


def validate_spec(spec, base_dir: Path, library: dict | None = None) -> tuple[list[dict], dict]:
    """Diagnostics plus a summary (budget usage, shader costs) for an assets.json document."""
    library = library or load_library()
    base_dir = Path(base_dir)
    diags: list[dict] = []
    summary = {"assets": 0, "triangles": 0, "renderers": 0, "max_particles": 0, "shaders": {}}

    def top(severity, rule, message, fix=None):
        diags.append(_diag(severity, rule, message, fix))

    if not isinstance(spec, dict):
        top("error", "spec_type", "assets.json must be a JSON object", "See docs/asset-forge.md for the format")
        return diags, summary
    if spec.get("format", SPEC_FORMAT) != SPEC_FORMAT:
        top("error", "spec_format", f"Unknown format {spec.get('format')!r}", f'Set "format": "{SPEC_FORMAT}"')
    slug = spec.get("project")
    if not isinstance(slug, str) or not _SLUG.fullmatch(slug) or slug in RESERVED_SLUGS:
        top("error", "project_slug_invalid", f"project must be a lowercase slug (not {sorted(RESERVED_SLUGS)}); got {slug!r}",
            "Use the project id in lowercase")
        slug = None
    target = spec.get("target", DEFAULT_TARGET)
    if target in UNSUPPORTED_TARGETS:
        top("error", "target_unsupported", UNSUPPORTED_TARGETS[target], f"Use {DEFAULT_TARGET}")
    elif target not in TARGETS:
        top("error", "target_unknown", f"Unknown target {target!r}", f"Use one of {sorted(TARGETS)}")
    budgets = dict(DEFAULT_BUDGETS)
    for key, value in (spec.get("budgets") or {}).items():
        if key not in DEFAULT_BUDGETS:
            top("error", "budget_unknown", f"Unknown budget {key!r}", f"Use one of {sorted(DEFAULT_BUDGETS)}")
        elif not _num(value) or value <= 0:
            top("error", "budget_invalid", f"budgets.{key} must be a positive number", "Use a positive number")
        else:
            budgets[key] = value
    summary["budgets"] = budgets
    if spec.get("compression", "lz4") not in ("lz4", "lzma", "none"):
        top("error", "compression_invalid", "compression must be lz4, lzma or none", 'Use "lz4"')
    assets = spec.get("assets")
    if not isinstance(assets, list) or not assets:
        top("error", "assets_missing", "assets must be a non-empty list", "Add at least one asset")
        return diags, summary
    ids, entries, paths, stems = {}, [], {}, {"mat": {}, "prefab": {}}
    for index, asset in enumerate(assets):
        if not isinstance(asset, dict):
            top("error", "asset_type", f"assets[{index}] is not an object")
            continue
        aid = asset.get("id")
        if not isinstance(aid, str) or not _ID.fullmatch(aid):
            top("error", "asset_id_invalid", f"assets[{index}].id must match [a-z0-9][a-z0-9_-]*; got {aid!r}",
                "Use a short lowercase id")
            continue
        if aid in ids:
            top("error", "asset_id_duplicate", f"Asset id {aid!r} is used twice", "Give every asset a unique id")
        ids.setdefault(aid, asset)
        entries.append((aid, asset))
    kinds_by_id = {aid: a.get("kind") for aid, a in ids.items()}
    for aid, asset in entries:
        summary["assets"] += 1

        def add(severity, rule, message, fix=None, file=None, line=None, _aid=aid):
            diags.append(_diag(severity, rule, message, fix, file, line, _aid))

        kind = asset.get("kind")
        if kind not in KINDS:
            add("error", "asset_kind_unknown", f"kind {kind!r} is not one of {sorted(KINDS)}", "Pick a supported kind")
            continue
        path = asset.get("path")
        if not isinstance(path, str) or not path:
            add("error", "asset_path_missing", "path is required", f"Use assets/sabermapper/{slug or '<project>'}/...")
        else:
            if path != path.lower():
                add("error", "path_not_lowercase", f"{path} is not lowercase; Vivify looks assets up by lowercase path",
                    f"Use {path.lower()}")
            lower = path.lower()
            prefix = f"assets/sabermapper/{slug}/" if slug else "assets/sabermapper/"
            if not lower.startswith(prefix) or ".." in lower.split("/"):
                add("error", "path_outside_project", f"{path} must live under {prefix}", f"Move it under {prefix}")
            elif lower.split("/")[3:4] in (["editor"], ["staging"]):
                add("error", "path_reserved", f"{path} uses a reserved folder", "Use materials/, prefabs/, meshes/, textures/ or post/")
            if not _PATH_CHARS.fullmatch(lower):
                add("error", "path_characters", f"{path} contains characters other than a-z 0-9 _ - . /", "Rename without spaces")
            if not lower.endswith(KINDS[kind]):
                add("error", "path_extension", f"{kind} paths end with {' or '.join(KINDS[kind])}", f"Rename to *{KINDS[kind][0]}")
            if lower in paths:
                add("error", "path_duplicate", f"{path} is also used by {paths[lower]}", "Give every asset its own path")
            paths[lower] = aid
            ext = "mat" if kind in MATERIAL_KINDS else "prefab" if kind in ("prefab", "particles") else None
            if ext:
                stem = lower.rsplit("/", 1)[-1].rsplit(".", 1)[0]
                if stem in stems[ext]:
                    add("warning", "bundleinfo_key_collision", f"bundleinfo.json keys {ext} files by name; {stem!r} is also "
                        f"{stems[ext][stem]} and will be listed as '{stem} (1)'", "Use distinct file names")
                stems[ext][stem] = aid
        tier = asset.get("tier")
        if tier not in (1, 2, 3):
            add("error", "tier_invalid", f"tier must be 1, 2 or 3; got {tier!r}",
                "1 = library, 2 = agent-written code, 3 = generative media")
            tier = None
        if tier:
            _provenance(asset, tier, add, base_dir)
        if kind in MATERIAL_KINDS:
            _validate_material(asset, kind, tier, base_dir, library, budgets, kinds_by_id, add, summary)
        elif kind == "mesh":
            _validate_mesh(asset.get("mesh"), tier, base_dir, library, budgets, add)
        elif kind == "texture":
            _validate_texture(asset, tier, base_dir, budgets, add)
        else:
            _validate_prefab(asset, kind, tier, base_dir, library, budgets, ids, add, summary)
    for key, used in (("max_total_triangles", summary["triangles"]), ("max_renderers", summary["renderers"]),
                      ("max_particles", summary["max_particles"])):
        if used > budgets[key]:
            top("error", "budget_exceeded", f"Spec uses {used} against budgets.{key}={budgets[key]}",
                f"Simplify the assets or raise budgets.{key} deliberately")
    return diags, summary


def _shader_source(asset, base_dir, library, add):
    shader = asset.get("shader")
    if not isinstance(shader, dict) or (("library" in shader) == ("source" in shader)):
        add("error", "shader_reference", 'shader must be {"library": id} or {"source": "relative/file.shader"}',
            "Pick a library shader (assets library) or write one")
        return None, None
    if "library" in shader:
        if shader["library"] not in library["shaders"]:
            add("error", "shader_library_unknown", f"Library shader {shader['library']!r} does not exist",
                f"Use one of {sorted(library['shaders'])}")
            return None, None
        return library_shader_path(library, shader["library"]), shader["library"]
    path = (base_dir / shader["source"]).resolve()
    if not path.is_file():
        add("error", "shader_source_missing", f"Shader source {shader['source']} was not found next to assets.json",
            "Write the shader file or fix the relative path")
        return None, None
    if path.suffix.lower() != ".shader":
        add("error", "shader_source_extension", f"{shader['source']} is not a .shader file", "Use a .shader file")
        return None, None
    return path, None


def _validate_material(asset, kind, tier, base_dir, library, budgets, kinds_by_id, add, summary):
    path, library_id = _shader_source(asset, base_dir, library, add)
    if path is None:
        return
    if tier == 1 and library_id is None:
        add("error", "tier_mismatch", "Tier 1 assets must use a library shader", "Set tier 2 for agent-written shaders")
    if tier == 2 and library_id is not None:
        add("warning", "tier_mismatch", "Tier 2 asset uses a library shader", "Set tier 1")
    if library_id and kind not in library["shaders"][library_id]["kinds"]:
        add("error", "shader_kind_mismatch", f"{library_id} is a {'/'.join(library['shaders'][library_id]['kinds'])} shader, not {kind}",
            "Pick a library shader made for this kind")
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    for item in lint_shader(text, kind=kind, file=path, budgets=budgets, asset=asset["id"]):
        add(item["severity"], item["rule"], item["message"], item.get("fix"), item.get("file"), item.get("line"))
    summary["shaders"][str(path)] = shader_cost(text)
    parsed = parse_shader(text)
    safe = library["shaders"][library_id]["properties"] if library_id else {}
    props = asset.get("properties") or {}
    if not isinstance(props, dict):
        return add("error", "properties_type", "properties must be an object", "Map property names to values")
    for name, value in props.items():
        if name not in parsed["properties"]:
            add("error", "property_unknown", f"{parsed['name']} has no property {name}",
                f"Use one of {sorted(parsed['properties'])}")
            continue
        _check_property(name, value, parsed["properties"][name], safe.get(name, {}).get("safe"), add)
        if parsed["properties"][name]["type"] == "Texture" and isinstance(value, dict):
            if kinds_by_id.get(value.get("texture")) != "texture":
                add("error", "texture_reference", f"{name} references {value.get('texture')!r}, which is not a texture asset",
                    "Declare the texture as an asset of kind texture")
    if kind == "post_process" and "_MainTex" not in parsed["properties"]:
        add("warning", "post_main_tex", "Blit materials receive the screen in _MainTex; the shader does not declare it",
            'Add _MainTex ("Screen", 2D) = "white" {} to Properties')


def _validate_mesh(mesh, tier, base_dir, library, budgets, add):
    """Triangle count when computable (built-in generator), else None; custom generators declare max_triangles."""
    if not isinstance(mesh, dict):
        add("error", "mesh_missing", "Mesh spec must be an object", 'Use {"generator": "torus", "params": {...}}')
        return None
    if "asset" in mesh:
        return None
    if "generator" in mesh:
        if mesh["generator"] not in library["meshes"]:
            add("error", "mesh_generator_unknown", f"Unknown built-in generator {mesh['generator']!r}",
                f"Use one of {sorted(library['meshes'])} or a tier-2 source/class")
            return None
        params = mesh.get("params") or {}
        unknown = set(params) - set(library["meshes"][mesh["generator"]]["params"])
        if unknown:
            add("error", "mesh_param_unknown", f"{mesh['generator']} has no params {sorted(unknown)}",
                f"Use {sorted(library['meshes'][mesh['generator']]['params'])}")
            return None
        try:
            tris = mesh_triangles(mesh["generator"], params, library)
        except (TypeError, ValueError, ZeroDivisionError) as exc:
            add("error", "mesh_param_invalid", f"Cannot evaluate {mesh['generator']} params: {exc}", "Use numeric params")
            return None
        limit = min(budgets["max_triangles_per_mesh"], mesh.get("max_triangles", budgets["max_triangles_per_mesh"]))
        if tris > limit:
            add("error", "mesh_budget_exceeded", f"{mesh['generator']} makes {tris} triangles; the limit is {limit}",
                "Lower segment counts")
        return tris
    if "source" in mesh or "class" in mesh:
        if tier == 1:
            add("error", "tier_mismatch", "Custom generator code is tier 2", "Set tier 2")
        source = base_dir / str(mesh.get("source", ""))
        if not mesh.get("source") or not source.is_file() or source.suffix.lower() != ".cs":
            add("error", "generator_source_missing", f"Generator source {mesh.get('source')!r} was not found",
                "Write the C# generator next to assets.json (see docs/asset-forge.md#tier-2)")
        elif not re.search(r"public\s+static\s+(?:UnityEngine\.)?Mesh\s+Generate\s*\(\s*(?:SaberMapper\.)?ForgeParams\b",
                           source.read_text(encoding="utf-8-sig", errors="replace")):
            add("error", "generator_signature", f"{mesh['source']} lacks `public static Mesh Generate(SaberMapper.ForgeParams p)`",
                "Expose the generator with exactly that signature")
        if not isinstance(mesh.get("class"), str) or not re.fullmatch(r"[A-Za-z_][\w.]*", mesh.get("class", "")):
            add("error", "generator_class", "Custom generators need the fully qualified class name in mesh.class",
                'e.g. "class": "SaberMapper.Generated.RibbonMesh"')
        if not _num(mesh.get("max_triangles")):
            add("error", "mesh_budget_undeclared", "Custom generators must declare max_triangles (checked after generation)",
                "Add mesh.max_triangles")
        elif mesh["max_triangles"] > budgets["max_triangles_per_mesh"]:
            add("error", "mesh_budget_exceeded", f"max_triangles {mesh['max_triangles']} exceeds budgets.max_triangles_per_mesh",
                "Lower it or raise the budget deliberately")
        return int(mesh.get("max_triangles") or 0)
    add("error", "mesh_missing", "Mesh spec needs generator, asset, or source+class", 'Use {"generator": "quad"}')
    return None


def _validate_texture(asset, tier, base_dir, budgets, add):
    source = asset.get("source")
    if not isinstance(source, str) or not (base_dir / source).is_file():
        return add("error", "texture_source_missing", f"Texture source {source!r} was not found next to assets.json",
                   "Place the image file there (tier 3 generators write it with a provenance record)")
    if Path(source).suffix.lower() not in KINDS["texture"]:
        return add("error", "texture_format", f"{source} is not one of {KINDS['texture']}", "Convert it to PNG")
    if tier == 1:
        add("error", "tier_mismatch", "Textures are tier 2 (agent-made) or tier 3 (generated)", "Set tier 2 or 3")
    try:
        from PIL import Image
        with Image.open(base_dir / source) as image:
            width, height = image.size
    except Exception:  # noqa: BLE001 - unreadable images are reported, not raised
        return add("error", "texture_unreadable", f"{source} could not be read as an image", "Re-export it as PNG")
    if max(width, height) > budgets["max_texture_size"]:
        add("error", "texture_budget_exceeded", f"{source} is {width}x{height}; budgets.max_texture_size is {budgets['max_texture_size']}",
            "Downscale the image")
    if width & (width - 1) or height & (height - 1):
        add("warning", "texture_not_power_of_two", f"{source} is {width}x{height}", "Power-of-two sizes compress and mip better")
    settings = asset.get("texture") or {}
    if settings.get("shape", "2d") not in ("2d", "cube"):
        add("error", "texture_shape", "texture.shape must be 2d or cube", 'Use "cube" for equirectangular skyboxes')


def _validate_particles(block, budgets, add, where):
    if not isinstance(block, dict):
        add("error", "particles_missing", f"{where} needs a particles object", "See docs/asset-forge.md#particles")
        return 0
    count = block.get("max_particles", 500)
    if not _num(count) or count < 1:
        add("error", "particles_invalid", f"{where}.max_particles must be a positive number", "Use e.g. 500")
        return 0
    for key in ("duration", "gravity"):
        if key in block and not _num(block[key]):
            add("error", "particles_invalid", f"{where}.{key} must be a number", "Use a number")
    for key in ("start_lifetime", "start_speed", "start_size", "start_rotation"):
        if key in block and not (_num(block[key]) or _numbers(block[key], (1, 2))):
            add("error", "particles_invalid", f"{where}.{key} must be a number or [min, max]", "Use a number or [min, max]")
    shape = (block.get("shape") or {}).get("type", "cone")
    if shape not in ("sphere", "hemisphere", "cone", "box", "circle", "edge", "donut"):
        add("error", "particles_invalid", f"{where}.shape.type {shape!r} is unknown", "Use sphere, hemisphere, cone, box, circle, edge or donut")
    mode = (block.get("renderer") or {}).get("render_mode", "billboard")
    if mode not in ("billboard", "stretched", "horizontal", "vertical", "mesh"):
        add("error", "particles_invalid", f"{where}.renderer.render_mode {mode!r} is unknown", "Use billboard, stretched, horizontal, vertical or mesh")
    rate = (block.get("emission") or {}).get("rate_over_time", 10)
    if _num(rate) and rate > 2000:
        add("warning", "particles_rate", f"{where} emits {rate}/s", "Keep emission modest; VR renders every particle twice")
    return int(count)


def _validate_prefab(asset, kind, tier, base_dir, library, budgets, by_id, add, summary):
    def material_ref(ref, where):
        if (by_id.get(ref) or {}).get("kind") != "material":
            add("error", "material_reference", f"{where} references {ref!r}, which is not a material asset",
                "Reference an asset of kind material (post_process and skybox materials are not for renderers)")

    if kind == "particles":
        material_ref(asset.get("material"), "material")
        summary["max_particles"] += _validate_particles(asset.get("particles"), budgets, add, "particles")
        summary["renderers"] += 1
    children = asset.get("children", [] if kind == "particles" else None)
    if not isinstance(children, list) or (kind == "prefab" and not children):
        return add("error", "prefab_children", "prefab needs a non-empty children list", "Add at least one child")
    names = set()
    for index, child in enumerate(children):
        where = f"children[{index}]"
        if not isinstance(child, dict):
            add("error", "prefab_child", f"{where} is not an object")
            continue
        name = child.get("name", f"child{index}")
        if not isinstance(name, str) or not re.fullmatch(r"[a-z0-9_-]{1,40}", name) or name in names:
            add("error", "prefab_child_name", f"{where}.name must be a unique lowercase slug; got {name!r}", "Use e.g. ring_a")
        names.add(name)
        for key in ("position", "rotation"):
            if key in child and not _numbers(child[key], (3,)):
                add("error", "transform_invalid", f"{where}.{key} must be [x, y, z]", "Use three numbers")
        if "scale" in child and not (_num(child["scale"]) or _numbers(child["scale"], (3,))):
            add("error", "transform_invalid", f"{where}.scale must be a number or [x, y, z]", "Use three numbers")
        material_ref(child.get("material"), f"{where}.material")
        if ("mesh" in child) == ("particles" in child):
            add("error", "prefab_child", f"{where} needs exactly one of mesh or particles", "Give the child a mesh or a particles block")
            continue
        summary["renderers"] += 1
        if "particles" in child:
            summary["max_particles"] += _validate_particles(child["particles"], budgets, add, f"{where}.particles")
            continue
        mesh = child["mesh"]
        if isinstance(mesh, dict) and "asset" in mesh:
            target = by_id.get(mesh["asset"]) or {}
            if target.get("kind") != "mesh":
                add("error", "mesh_reference", f"{where}.mesh references {mesh['asset']!r}, which is not a mesh asset",
                    "Reference an asset of kind mesh")
                continue
            # The mesh asset reports its own problems; here only its triangle count is needed.
            tris = _validate_mesh(target.get("mesh"), target.get("tier"), base_dir, library, budgets, lambda *a, **k: None)
        else:
            tris = _validate_mesh(mesh, tier, base_dir, library, budgets, add)
        summary["triangles"] += tris or 0


def lint_spec(spec_path: Path, library: dict | None = None, expected_project: str | None = None) -> dict:
    spec_path = Path(spec_path)
    try:
        spec = read_json(spec_path)
    except FileNotFoundError:
        raise ForgeError("spec_missing", f"{spec_path} does not exist",
                         "Create it with `sabermapper assets init PROJECT` or write it by hand") from None
    except json.JSONDecodeError as exc:
        return {"spec": str(spec_path), "ok": False, "diagnostics": [
            _diag("error", "spec_json", f"Invalid JSON: {exc.msg}", "Fix the JSON syntax", spec_path, exc.lineno)]}
    diags, summary = validate_spec(spec, spec_path.parent, library)
    if expected_project and isinstance(spec, dict) and spec.get("project") != expected_project:
        diags.insert(0, _diag("error", "project_mismatch", f"assets.json declares project {spec.get('project')!r}; "
                              f"this project's asset slug is {expected_project!r}", f'Set "project": "{expected_project}"'))
    text = spec_path.read_text(encoding="utf-8-sig")
    for item in diags:
        if "file" not in item:
            item["file"] = str(spec_path)
            anchor = re.search(r'"id"\s*:\s*"' + re.escape(item["asset"]) + '"', text) if item.get("asset") else None
            if anchor:
                item["line"] = _line(text, anchor.start())
    return {"spec": str(spec_path), "ok": not any(d["severity"] == "error" for d in diags),
            "errors": sum(d["severity"] == "error" for d in diags), "warnings": sum(d["severity"] == "warning" for d in diags),
            "diagnostics": diags, "summary": summary}


# --------------------------------------------------------------------------- Unity location

def forge_config_path() -> Path:
    if os.environ.get("SABERMAPPER_FORGE_CONFIG"):
        return Path(os.environ["SABERMAPPER_FORGE_CONFIG"])
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
    return Path(base) / "SaberMapper" / "forge.json"


def load_config() -> dict:
    path = forge_config_path()
    try:
        return read_json(path) if path.is_file() else {}
    except (OSError, json.JSONDecodeError):
        raise ForgeError("forge_config_invalid", f"{path} is not valid JSON",
                         "Fix or delete it, or rewrite it with `sabermapper assets config`") from None


def save_config(updates: dict) -> dict:
    config = load_config()
    for key, value in updates.items():
        if value == "":
            config.pop(key, None)
        elif value is not None:
            config[key] = value
    write_json(forge_config_path(), config)
    return {"config": str(forge_config_path()), **config}


def _hub_roots() -> list[Path]:
    if os.environ.get("SABERMAPPER_UNITY_HUB_ROOTS"):
        return [Path(p) for p in os.environ["SABERMAPPER_UNITY_HUB_ROOTS"].split(os.pathsep) if p]
    roots = []
    for base in (os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramW6432", "")):
        if base:
            roots.append(Path(base) / "Unity" / "Hub" / "Editor")
    appdata = os.environ.get("APPDATA")
    if appdata:
        secondary = Path(appdata) / "UnityHub" / "secondaryInstallPath.json"
        try:
            value = json.loads(secondary.read_text(encoding="utf-8-sig")) if secondary.is_file() else ""
            if isinstance(value, str) and value:
                roots.append(Path(value))
        except (OSError, json.JSONDecodeError):
            pass
    return list(dict.fromkeys(roots))


def _hub_listed_editors() -> dict[str, Path]:
    """Editors recorded by Unity Hub (editors-v2.json / editors.json), keyed by version."""
    found = {}
    appdata = os.environ.get("APPDATA")
    if not appdata or os.environ.get("SABERMAPPER_UNITY_HUB_ROOTS"):
        return found

    def walk(value):
        if isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, str) and value.lower().endswith("unity.exe"):
            version = _version_from_path(Path(value))
            if version:
                found[version] = Path(value)

    for name in ("editors-v2.json", "editors.json"):
        path = Path(appdata) / "UnityHub" / name
        try:
            if path.is_file():
                walk(json.loads(path.read_text(encoding="utf-8-sig")))
        except (OSError, json.JSONDecodeError):
            continue
    return found


def installed_editors() -> dict[str, Path]:
    editors = dict(_hub_listed_editors())
    for root in _hub_roots():
        if root.is_dir():
            for child in root.iterdir():
                exe = child / "Editor" / "Unity.exe"
                if exe.is_file():
                    editors.setdefault(child.name, exe)
    return {k: v for k, v in editors.items() if Path(v).is_file()}


def _version_from_path(exe: Path) -> str | None:
    for part in (exe.parent.parent.name, exe.parent.name):
        if re.fullmatch(r"\d{4}\.\d+\.\d+[abfp]\d+", part):
            return part
    return None


def locate_unity(explicit: str | Path | None = None, version: str | None = None, target: str = DEFAULT_TARGET) -> dict:
    """{path, version, source, warnings}; raises unity_missing with the install fix when nothing is found."""
    config = load_config()
    wanted = version or config.get("unity_version") or TARGETS[target]["unity_version"]
    tried = []
    for source, candidate in (("--unity", explicit), ("SABERMAPPER_UNITY", os.environ.get("SABERMAPPER_UNITY")),
                              ("config", config.get("unity_path"))):
        if not candidate:
            continue
        path = Path(candidate)
        tried.append(f"{source}: {path}")
        if not path.is_file():
            raise ForgeError("unity_missing", f"Unity from {source} does not exist: {path}",
                             f"Point {source} at Unity.exe (e.g. C:/Program Files/Unity/Hub/Editor/{wanted}/Editor/Unity.exe)",
                             required_version=wanted, tried=tried)
        found = _version_from_path(path)
        warnings = []
        if found and found != wanted:
            warnings.append({"code": "unity_version_mismatch", "message": f"Using Unity {found}; the target expects {wanted}"})
        return {"path": str(path), "version": found or "unknown", "source": source, "warnings": warnings}
    editors = installed_editors()
    tried += [f"hub: {root}" for root in _hub_roots()]
    if wanted in editors:
        return {"path": str(editors[wanted]), "version": wanted, "source": "hub", "warnings": []}
    stream = ".".join(wanted.split(".")[:2]) + "."
    same_stream = sorted((v for v in editors if v.startswith(stream)), reverse=True)
    if same_stream:
        chosen = same_stream[0]
        return {"path": str(editors[chosen]), "version": chosen, "source": "hub", "warnings": [
            {"code": "unity_version_mismatch", "message": f"Unity {wanted} is not installed; using {chosen} from the same "
             f"LTS stream. Bundles load in the game, but rebuilds differ from a {wanted} build"}]}
    changeset = TARGETS[target]["unity_changeset"] if wanted == TARGETS[target]["unity_version"] else None
    raise ForgeError(
        "unity_missing", f"Unity {wanted} was not found (installed editors: {sorted(editors) or 'none'})",
        f"Install Unity {wanted} with Unity Hub" + (f" (unityhub://{wanted}/{changeset})" if changeset else "") +
        " and activate a Personal license once, then rerun",
        required_version=wanted, target=target, tried=tried, installed=sorted(editors))


# --------------------------------------------------------------------------- staging

def default_unity_project(version: str) -> Path:
    config = load_config()
    if config.get("unity_project_dir"):
        return Path(config["unity_project_dir"])
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
    return Path(base) / "SaberMapper" / "forge" / f"unity-{version}"


def sync_template(unity_project: Path, version: str, template: Path = TEMPLATE_DIR) -> None:
    """Refresh the machine-local Unity project from the repo template, keeping Library/ for fast rebuilds."""
    ours = unity_project / "Assets" / "SaberMapper"
    if ours.exists():
        shutil.rmtree(ours)
    shutil.copytree(template / "Assets" / "SaberMapper", ours, ignore=shutil.ignore_patterns("*.meta", "Staging"))
    (unity_project / "Packages").mkdir(parents=True, exist_ok=True)
    manifest = (template / "Packages" / "manifest.json").read_bytes()
    target_manifest = unity_project / "Packages" / "manifest.json"
    if not target_manifest.is_file() or target_manifest.read_bytes() != manifest:
        target_manifest.write_bytes(manifest)
    settings = unity_project / "ProjectSettings"
    settings.mkdir(exist_ok=True)
    for item in (template / "ProjectSettings").iterdir():
        if item.name != "ProjectVersion.txt" and not (settings / item.name).exists():
            shutil.copy2(item, settings / item.name)
    changeset = next((t["unity_changeset"] for t in TARGETS.values() if t["unity_version"] == version), None)
    (settings / "ProjectVersion.txt").write_text(
        f"m_EditorVersion: {version}\n" + (f"m_EditorVersionWithRevision: {version} ({changeset})\n" if changeset else ""),
        encoding="utf-8", newline="\n")


def _unity_path(spec_path: str) -> str:
    return "/".join(["Assets", "SaberMapper"] + spec_path.lower().split("/")[2:])


def stage(spec: dict, base_dir: Path, unity_project: Path, library: dict, target: str,
          allow_no_xr: bool = False) -> tuple[dict, dict]:
    """Copy shaders, textures and generator code into the Unity project; return (staged spec, source map).

    Inline prefab-child meshes become separate mesh assets so the editor script only resolves references.
    """
    slug = spec["project"]
    ours = unity_project / "Assets" / "SaberMapper"
    for folder in (ours / slug, ours / "Staging"):
        if folder.exists():
            shutil.rmtree(folder)
    source_map = {"files": {}, "shaders": {}}

    def copy(source: Path, unity_rel: str):
        dest = unity_project / unity_rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest)
        source_map["files"][unity_rel.lower()] = str(source)

    shader_paths: dict[str, Path] = {}

    def shader_unity(asset):
        shader = asset["shader"]
        if "library" in shader:
            source, name = library_shader_path(library, shader["library"]), shader["library"] + ".shader"
        else:
            source = (base_dir / shader["source"]).resolve()
            name = source.name.lower()
        rel = f"Assets/SaberMapper/{slug}/shaders/{name}"
        if rel not in shader_paths:
            copy(source, rel)
            shader_paths[rel] = source
            parsed = parse_shader(source.read_text(encoding="utf-8-sig", errors="replace"))
            if parsed["name"]:
                source_map["shaders"][parsed["name"]] = str(source)
        return rel

    def mesh_entry(mesh: dict, mesh_id: str, unity_rel: str, tier) -> dict:
        entry = {"id": mesh_id, "kind": "mesh", "unity_path": unity_rel, "tier": tier, "mesh": dict(mesh)}
        if "source" in mesh:
            source = (base_dir / mesh["source"]).resolve()
            copy(source, f"Assets/SaberMapper/Staging/Editor/{slug}_{source.name}")
            entry["mesh"].pop("source")
        return entry

    textures, meshes, rest = [], [], []
    for asset in spec["assets"]:
        if asset["kind"] == "texture":
            copy((base_dir / asset["source"]).resolve(), _unity_path(asset["path"]))
            textures.append({**{k: v for k, v in asset.items() if k not in ("source", "provenance")},
                             "unity_path": _unity_path(asset["path"])})
        elif asset["kind"] == "mesh":
            meshes.append(mesh_entry(asset["mesh"], asset["id"], _unity_path(asset["path"]), asset.get("tier")))
    for asset in sorted(spec["assets"], key=lambda a: a["kind"] in ("prefab", "particles")):
        kind = asset["kind"]
        if kind in ("texture", "mesh"):
            continue
        staged = {k: v for k, v in asset.items() if k not in ("provenance", "library", "shader")}
        staged["unity_path"] = _unity_path(asset["path"])
        if kind in MATERIAL_KINDS:
            staged["shader_unity_path"] = shader_unity(asset)
        else:
            stem = asset["path"].rsplit("/", 1)[-1].rsplit(".", 1)[0]
            children = []
            for index, child in enumerate(asset.get("children", [])):
                child = dict(child, name=child.get("name", f"child{index}"))
                if "mesh" in child and "asset" not in child["mesh"]:
                    mesh_id = f"{asset['id']}__{child['name']}"
                    rel = f"Assets/SaberMapper/{slug}/meshes/{stem}__{child['name']}.asset"
                    meshes.append(mesh_entry(child["mesh"], mesh_id, rel, asset.get("tier")))
                    child["mesh"] = {"asset": mesh_id}
                if isinstance(child.get("scale"), (int, float)):
                    child["scale"] = [child["scale"]] * 3
                children.append(child)
            staged["children"] = children
        rest.append(staged)
    target_info = TARGETS[target]
    staged_spec = {"format": STAGED_FORMAT, "project": slug, "bundle_name": f"sabermapper_{slug}", "target": target,
                   "bundle_file": target_info["bundle_file"], "crc_key": target_info["crc_key"],
                   "compression": spec.get("compression", "lz4"), "allow_no_xr": bool(allow_no_xr),
                   "budgets": {**DEFAULT_BUDGETS, **(spec.get("budgets") or {})},
                   "assets": textures + meshes + rest}
    for folder in {str(Path(a["unity_path"]).parent) for a in staged_spec["assets"]}:
        (unity_project / folder).mkdir(parents=True, exist_ok=True)
    return staged_spec, source_map


# --------------------------------------------------------------------------- Unity log parsing

_CS_ERROR = re.compile(r"^(?P<file>[^\s(][^(\n]*?)\((?P<line>\d+),(?P<col>\d+)\):\s*(?P<sev>error|warning)\s+"
                       r"(?P<code>CS\d+):\s*(?P<msg>.*?)\s*$", re.M)
_SHADER_ERROR = re.compile(r"Shader (?P<sev>error|warning) in '(?P<shader>[^']+)':\s*(?P<msg>.*?)\s+at\s+"
                           r"(?:line (?P<line>\d+)|(?P<file>[^\s()][^()\n]*)\((?P<line2>\d+)\))(?:\s*\(on (?P<api>\w+)\))?",
                           re.M)
_UNITY_FAILURES = (
    (re.compile(r"No valid Unity Editor license found|License is not active|Failed to activate|Unity has not been activated|"
                r"com\.unity\.editor\.headless", re.I),
     "unity_license_missing", "Unity has no active license",
     "Open Unity Hub, sign in and add a free Personal license once (Preferences > Licenses > Add), then rerun"),
    (re.compile(r"another Unity instance is running with this project open|"
                r"Multiple Unity instances cannot open the same project", re.I),
     "unity_project_locked", "Another Unity editor has the forge project open",
     "Close the other editor (or wait for the other build) and rerun"),
    (re.compile(r"An error occurred while resolving packages|Cannot perform upm operation|Failed to resolve packages", re.I),
     "package_resolution_failed", "Unity could not resolve Packages/manifest.json",
     "The first build downloads com.unity.xr.management and com.unity.xr.openxr; check the network and rerun"),
    (re.compile(r"executeMethod[^\n]*SaberMapper\.Forge[^\n]*could not be found|"
                r"executeMethod class '?SaberMapper\.Forge'? could not be found", re.I),
     "forge_method_missing", "Unity could not find SaberMapper.Forge.Build",
     "The editor scripts did not compile; fix the C# errors listed and rerun"),
)


def parse_unity_log(text: str, source_map: dict | None = None) -> list[dict]:
    """Structured C#, shader, forge and editor failures from a Unity batchmode log."""
    source_map = source_map or {"files": {}, "shaders": {}}
    issues, seen = [], set()

    def add(item):
        key = (item.get("code"), item.get("file"), item.get("line"), item.get("message"))
        if key not in seen:
            seen.add(key)
            issues.append(item)

    for match in _CS_ERROR.finditer(text):
        rel = match.group("file").strip().replace("\\", "/")
        original = source_map["files"].get(rel.lower())
        if original is None and rel.startswith("Assets/SaberMapper/") and (TEMPLATE_DIR / rel).is_file():
            original = str(TEMPLATE_DIR / rel)
        add({"source": "csharp", "severity": match.group("sev"), "code": match.group("code"),
             "file": original or rel, "line": int(match.group("line")), "column": int(match.group("col")),
             "message": match.group("msg"),
             "fix": "Fix the C# at this line (tier-2 generator code compiles into the editor assembly with the forge)"})
    for match in _SHADER_ERROR.finditer(text):
        shader, file = match.group("shader"), match.group("file")
        original = source_map["files"].get(file.lower()) if file else source_map["shaders"].get(shader)
        add({"source": "shader", "severity": match.group("sev"), "code": "shader_compile_error", "shader": shader,
             "file": original or file or shader, "line": int(match.group("line") or match.group("line2")),
             "api": match.group("api"), "message": match.group("msg").strip(),
             "fix": "Fix the shader source at this line and rerun `assets lint` before rebuilding"})
    for line in text.splitlines():
        if "[SaberMapperForge] {" in line:
            try:
                item = json.loads(line.split("[SaberMapperForge] ", 1)[1])
            except json.JSONDecodeError:
                continue
            if item.get("file"):
                item["file"] = source_map["files"].get(str(item["file"]).lower(), item["file"])
            add({"source": "forge", "severity": "error", **item})
    for pattern, code, message, fix in _UNITY_FAILURES:
        if pattern.search(text):
            add({"source": "unity", "severity": "error", "code": code, "message": message, "fix": fix})
    return issues


# --------------------------------------------------------------------------- build

def _unity_command(unity: str) -> list[str]:
    # A .py "editor" is the test stand-in (tests/test_forge.py); real builds always run Unity.exe.
    return [sys.executable, unity] if unity.lower().endswith(".py") else [unity]


def _bundle_header(path: Path) -> dict:
    parts = [p.decode("ascii", "replace") for p in path.read_bytes()[:64].split(b"\0") if p]
    return {"signature": parts[0] if parts else "", "unity_version": parts[2] if len(parts) > 2 else None}


def _manifest_crc(path: Path):
    if not path.is_file():
        return None
    match = re.search(r"^CRC:\s*(\d+)", path.read_text(encoding="utf-8", errors="replace"), re.M)
    return int(match.group(1)) if match else None


def build(spec_path: Path, dest: Path, *, target: str | None = None, unity: str | None = None,
          unity_version: str | None = None, unity_project: Path | None = None, timeout: float = 3600,
          allow_no_xr: bool = False, nographics: bool = True, library: dict | None = None,
          expected_project: str | None = None) -> dict:
    """Lint, stage and build in Unity batchmode, then copy the outputs to dest. Failures raise ForgeError."""
    library = library or load_library()
    spec_path = Path(spec_path)
    lint = lint_spec(spec_path, library, expected_project)
    if not lint["ok"]:
        raise ForgeError("lint_failed", f"{lint['errors']} lint error(s) in {spec_path}; nothing was built",
                         "Fix the diagnostics (file, line, rule, fix) and rerun",
                         diagnostics=[d for d in lint["diagnostics"] if d["severity"] == "error"])
    spec = read_json(spec_path)
    target = target or spec.get("target") or DEFAULT_TARGET
    if target in UNSUPPORTED_TARGETS:
        raise ForgeError("target_unsupported", UNSUPPORTED_TARGETS[target], f"Use --target {DEFAULT_TARGET}")
    if target not in TARGETS:
        raise ForgeError("target_unknown", f"Unknown target {target!r}", f"Use one of {sorted(TARGETS)}")
    editor = locate_unity(unity, unity_version, target)
    version = editor["version"] if editor["version"] != "unknown" else (unity_version or TARGETS[target]["unity_version"])
    unity_project = Path(unity_project or default_unity_project(version))
    unity_project.mkdir(parents=True, exist_ok=True)
    build_id = time.strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:6]
    lock = WorkspaceLock(unity_project.parent / f".{unity_project.name}.forge.lock")
    try:
        lock.__enter__()
    except TimeoutError:
        raise ForgeError("forge_busy", f"Another forge build is using {unity_project}", "Wait for it to finish and rerun") from None
    try:
        return _build_locked(spec, spec_path, Path(dest), target, editor, version, unity_project, build_id, timeout,
                             allow_no_xr, nographics, library, lint)
    finally:
        lock.__exit__(None, None, None)


def _build_locked(spec, spec_path, dest, target, editor, version, unity_project, build_id, timeout, allow_no_xr,
                  nographics, library, lint) -> dict:
    sync_template(unity_project, version)
    staged, source_map = stage(spec, spec_path.parent, unity_project, library, target, allow_no_xr)
    work = unity_project / "ForgeOut" / build_id
    work.mkdir(parents=True)
    staged_path = unity_project / "ForgeStaging" / "spec.json"
    write_json(staged_path, staged)
    log_path = work / "unity.log"
    command = _unity_command(editor["path"]) + [
        "-batchmode", "-quit", "-projectPath", str(unity_project), "-buildTarget", "Win64",
        "-executeMethod", "SaberMapper.Forge.Build", "-forgeSpec", str(staged_path), "-forgeOut", str(work),
        "-forgeTarget", target, "-logFile", str(log_path)] + (["-nographics"] if nographics else [])
    started = time.monotonic()
    try:
        exit_code = subprocess.run(command, capture_output=True, text=True, timeout=timeout).returncode
    except subprocess.TimeoutExpired:
        exit_code = None
    except OSError as exc:
        raise ForgeError("unity_launch_failed", f"Could not start {editor['path']}: {exc}",
                         "Check the Unity path with `sabermapper assets doctor` and rerun") from None
    log_text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.is_file() else ""
    report_path = work / "build-report.json"
    report = read_json(report_path) if report_path.is_file() else None
    history = dest / "builds" / build_id
    history.mkdir(parents=True, exist_ok=True)
    if log_path.is_file():
        shutil.copy2(log_path, history / "build.log")
    if report is not None:
        write_json(history / "build-report.json", report)
    errors = [i for i in parse_unity_log(log_text, source_map) if i["severity"] == "error"]
    for item in (report or {}).get("errors", []):
        if item.get("file"):
            item["file"] = source_map["files"].get(str(item["file"]).lower(), item["file"])
        if not any(e.get("code") == item.get("code") and e.get("message") == item.get("message") for e in errors):
            errors.append({"source": "forge", "severity": "error", **item})
    context = {"build_id": build_id, "unity": editor, "target": target, "log": str(history / "build.log"),
               "duration_s": round(time.monotonic() - started, 1)}
    if exit_code is None:
        raise ForgeError("unity_timeout", f"Unity did not finish within {timeout:.0f} s",
                         "The first build resolves packages and imports everything; rerun with a larger --timeout",
                         errors=errors, **context)
    info = TARGETS[target]
    bundle = work / info["bundle_file"]
    if exit_code != 0 or not (report or {}).get("ok") or not bundle.is_file() or errors:
        raise ForgeError("unity_build_failed", f"Unity exited with {exit_code}; {len(errors)} error(s)",
                         "Fix the listed errors (file and line point at your sources) and rerun",
                         errors=errors or [{"source": "unity", "severity": "error", "code": "no_output",
                                            "message": "Unity produced no bundle or report", "fix": "Read the log"}],
                         exit_code=exit_code, **context)
    info_path = work / "bundleinfo.json"
    if not info_path.is_file():
        raise ForgeError("bundleinfo_missing", "The build produced no bundleinfo.json", "Read the log", **context)
    crc = int(report["crc"])
    manifest = work / (info["bundle_file"] + ".manifest")
    manifest_crc = _manifest_crc(manifest)
    if manifest_crc is not None and manifest_crc != crc:
        raise ForgeError("crc_mismatch", f"Report CRC {crc} differs from the Unity manifest CRC {manifest_crc}",
                         "Rebuild; do not ship this bundle", **context)
    header = _bundle_header(bundle)
    if header["signature"] != "UnityFS":
        raise ForgeError("bundle_invalid", f"{bundle.name} is not a UnityFS asset bundle", "Read the log", **context)
    size_mb = bundle.stat().st_size / 1e6
    if size_mb > staged["budgets"]["max_bundle_mb"]:
        raise ForgeError("bundle_budget_exceeded", f"Bundle is {size_mb:.1f} MB; budgets.max_bundle_mb is "
                         f"{staged['budgets']['max_bundle_mb']}", "Shrink textures and meshes", **context)
    dest.mkdir(parents=True, exist_ok=True)
    final_bundle = dest / info["bundle_file"]
    shutil.copy2(bundle, final_bundle)
    if manifest.is_file():
        shutil.copy2(manifest, dest / manifest.name)
    bundleinfo = read_json(info_path)
    bundleinfo["bundleFiles"] = [final_bundle.resolve().as_posix()]
    report.update({"source_spec": str(spec_path), "spec_sha256": hashlib.sha256(spec_path.read_bytes()).hexdigest(),
                   "bundle_header": header, "bundle_mb": round(size_mb, 3), "build_id": build_id})
    for folder in (dest, history):
        write_json(folder / "bundleinfo.json", bundleinfo)
        write_json(folder / "build-report.json", report)
    if log_path.is_file():
        shutil.copy2(log_path, dest / "build.log")
    shutil.rmtree(work, ignore_errors=True)
    return {"ok": True, **context, "log": str(dest / "build.log"), "bundle_paths": [str(final_bundle)],
            "bundleinfo": bundleinfo, "crc": crc, "crc_key": info["crc_key"], "build_report": report,
            "warnings": editor["warnings"] + report.get("warnings", []) +
            [d for d in lint["diagnostics"] if d["severity"] == "warning"]}


# --------------------------------------------------------------------------- init, promote, generate

def starter_spec(slug: str) -> dict:
    """A small, valid spec built only from the tier-1 library, for the agent to edit."""
    base = f"assets/sabermapper/{slug}"

    def material(aid, kind, folder, shader, props):
        return {"id": aid, "kind": kind, "tier": 1, "path": f"{base}/{folder}/{aid}.mat", "shader": {"library": shader},
                "properties": props, "provenance": {"library": shader}}

    return {
        "format": SPEC_FORMAT, "project": slug, "target": DEFAULT_TARGET, "compression": "lz4",
        "budgets": dict(DEFAULT_BUDGETS),
        "assets": [
            material("grade", "post_process", "post", "sm_color_grade", {"_Saturation": 0.85, "_Contrast": 1.1}),
            material("vignette", "post_process", "post", "sm_vignette", {"_Strength": 0.35}),
            material("sky", "skybox", "sky", "sm_sky_gradient", {}),
            material("neon", "material", "materials", "sm_unlit_emissive", {"_Color": [0.2, 0.6, 1, 1], "_Intensity": 1.5}),
            material("spark", "material", "materials", "sm_particle_additive", {}),
            {"id": "ring", "kind": "prefab", "tier": 1, "path": f"{base}/prefabs/ring.prefab",
             "children": [{"name": "ring", "mesh": {"generator": "torus", "params": {"radius": 3, "thickness": 0.04}},
                           "material": "neon", "position": [0, 2, 20]}]},
            {"id": "sparks", "kind": "particles", "tier": 1, "path": f"{base}/prefabs/sparks.prefab", "material": "spark",
             "particles": {"max_particles": 300, "start_lifetime": [1, 2], "start_speed": [0.5, 1.5],
                           "start_size": [0.03, 0.08], "shape": {"type": "sphere", "radius": 4},
                           "emission": {"rate_over_time": 60}, "simulation_space": "world",
                           "color_over_lifetime": {"gradient": [[0, 1, 1, 1, 0], [0.2, 1, 1, 1, 1], [1, 1, 1, 1, 0]]}}},
        ]}


def init_spec(project_dir: Path, slug: str, force: bool = False) -> dict:
    path = Path(project_dir) / "assets" / "assets.json"
    if path.exists() and not force:
        raise ForgeError("spec_exists", f"{path} already exists", "Edit it, or pass --force to replace it with the starter")
    spec = starter_spec(slug)
    write_json(path, spec)
    lint = lint_spec(path)
    return {"spec": str(path), "assets": [a["id"] for a in spec["assets"]], "ok": lint["ok"],
            "errors": lint["errors"], "warnings": lint["warnings"]}


def library_entry_stub(asset: dict, shader_text: str | None) -> dict:
    stub = {"id": f"sm_{asset['id']}", "intent": "", "description": "", "properties": {}}
    if shader_text:
        for name, prop in parse_shader(shader_text)["properties"].items():
            if name == "_MainTex" and asset.get("kind") == "post_process":
                continue
            stub["properties"][name] = {"meaning": "", **({"safe": prop.get("range", [0, 1])} if prop["type"] == "Float" else {})}
    return stub


def promote(spec_path: Path, asset_id: str, library_dir: Path | None = None, library_id: str | None = None) -> dict:
    """Copy a project's agent-written shader into the library; intent, properties, safe ranges and description required."""
    library_dir = Path(library_dir or LIBRARY_DIR)
    library = load_library(library_dir)
    spec_path = Path(spec_path)
    spec = read_json(spec_path)
    asset = next((a for a in spec.get("assets", []) if isinstance(a, dict) and a.get("id") == asset_id), None)
    if asset is None:
        raise ForgeError("asset_unknown", f"No asset {asset_id!r} in {spec_path}", "Use an id from assets.json")
    if asset.get("kind") not in MATERIAL_KINDS or "source" not in (asset.get("shader") or {}):
        raise ForgeError("promote_unsupported", "Only assets with an agent-written shader (shader.source) can be promoted",
                         "Library-shader assets are already in the library")
    source = (spec_path.parent / asset["shader"]["source"]).resolve()
    text = source.read_text(encoding="utf-8-sig")
    problems = [d for d in lint_shader(text, kind=asset["kind"], file=source) if d["severity"] == "error"]
    if problems:
        raise ForgeError("promote_lint_failed", "The shader must be lint-clean before it enters the library",
                         "Fix the diagnostics and rerun", diagnostics=problems)
    meta = asset.get("library") or {}
    new_id = library_id or meta.get("id") or f"sm_{asset_id}"
    if not re.fullmatch(r"sm_[a-z0-9_]+", new_id):
        raise ForgeError("library_id_invalid", f"Library ids look like sm_name; got {new_id!r}", "Pass --library-id sm_name")
    if new_id in library["shaders"]:
        raise ForgeError("library_id_taken", f"{new_id} already exists in the library", "Pass another --library-id")
    parsed = parse_shader(text)
    missing = [key for key in ("intent", "description") if not str(meta.get(key, "")).strip()]
    props = {}
    for name, prop in parsed["properties"].items():
        if name == "_MainTex" and asset["kind"] == "post_process":
            continue
        given = (meta.get("properties") or {}).get(name) or {}
        if not str(given.get("meaning", "")).strip():
            missing.append(f"properties.{name}.meaning")
        entry = {"type": prop["type"], "default": prop.get("default"), "meaning": str(given.get("meaning", "")).strip()}
        if prop["type"] == "Float":
            safe = given.get("safe")
            low, high = prop.get("range", [float("-inf"), float("inf")])
            if not _numbers(safe, (2,)) or not low <= safe[0] <= safe[1] <= high:
                missing.append(f"properties.{name}.safe")
            entry["safe"] = safe
        props[name] = entry
    if missing:
        raise ForgeError("library_entry_incomplete", f"Fill {len(missing)} field(s) in the asset's `library` block first",
                         "Copy `stub` into the asset as \"library\", describe intent and look in words (the agent composes "
                         "without seeing the render), give each Float a safe [min, max] inside its Range, and rerun",
                         missing=missing, stub=library_entry_stub(asset, text))
    shader_file = f"shaders/{new_id}.shader"
    (library_dir / "shaders").mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, library_dir / shader_file)
    raw = read_json(library_dir / "library.json")
    raw["shaders"][new_id] = {"file": shader_file, "shader_name": parsed["name"], "kinds": [asset["kind"]],
                              "intent": meta["intent"].strip(), "description": meta["description"].strip(),
                              "properties": props,
                              "promoted_from": {"project": spec.get("project"), "asset": asset_id, "at": now(),
                                                "provenance": asset.get("provenance")}}
    write_json(library_dir / "library.json", raw)
    (library_dir / "library.md").write_text(render_library_md(raw), encoding="utf-8", newline="\n")
    return {"promoted": new_id, "file": str(library_dir / shader_file), "library": str(library_dir / "library.json"),
            "library_md": str(library_dir / "library.md"),
            "next": "Commit the library change in a worktree; rebuild projects to pick it up via {\"library\": \"" + new_id + "\"}"}


def generate(kind: str, prompt: str, *, backend: str = "local", seed: int | None = None) -> dict:
    """Tier-3 generative media interface. No model is integrated yet, so this always raises generator_unavailable."""
    if kind not in GENERATOR_KINDS:
        raise ForgeError("generator_kind_unknown", f"Unknown generator kind {kind!r}", f"Use one of {sorted(GENERATOR_KINDS)}")
    if backend != "local":
        raise ForgeError("generator_backend_unsupported", f"Backend {backend!r} is not supported",
                         "Generative models run locally on the RTX 5070 Ti (user decision 2026-09-23)")
    raise ForgeError(
        "generator_unavailable", f"No local {kind} generator is installed (needs a {GENERATOR_KINDS[kind]})",
        "Ask the user to approve installing a local model; until then use tier-1 library assets or tier-2 procedural code",
        kind=kind, backend=backend,
        provenance_template={"generator": {"kind": kind, "model": "", "model_version": "", "backend": backend,
                                           "device": "cuda:0", "prompt": prompt, "negative_prompt": "", "seed": seed,
                                           "params": {}},
                             "created_at": "", "license": "", "output_sha256": "", "postprocess": []})


# --------------------------------------------------------------------------- library.md

def render_library_md(library: dict) -> str:
    lines = ["# SaberMapper asset library", "",
             "Generated from `library.json` (`sabermapper assets library --write-md`); edit the JSON, not this file.",
             "Entries are written for an agent that composes without seeing the render. Safe ranges are the values to",
             "use without extra frame review; the shader's own `Range()` is the hard limit that `assets lint` enforces.",
             "Beat Saber's bloom reads the alpha channel, so `_Glow` sets how much a surface blooms. `post_process`",
             "materials are applied with Vivify `Blit`, skyboxes with `SetRenderingSettings` (`renderSettings.skybox`),",
             "surface and particle materials inside prefabs.", "", "## Shaders", ""]
    for sid, entry in library["shaders"].items():
        lines += [f"### `{sid}`: {entry['shader_name']}", "",
                  f"- **Kinds:** {', '.join(entry['kinds'])}", f"- **Intent:** {entry['intent']}",
                  f"- **Looks like:** {entry['description']}", "",
                  "| Property | Type | Default | Safe range | Meaning |", "|---|---|---|---|---|"]
        for name, prop in entry["properties"].items():
            safe = f"{prop['safe'][0]} to {prop['safe'][1]}" if prop.get("safe") else "any"
            lines.append(f"| `{name}` | {prop['type']} | `{json.dumps(prop.get('default'))}` | {safe} | {prop.get('meaning', '')} |")
        lines.append("")
    lines += ["## Mesh generators", "",
              "Built into the forge (`vivify-src/Assets/SaberMapper/Editor/ForgeMeshes.cs`). Use as",
              '`"mesh": {"generator": NAME, "params": {...}}`; `assets lint` checks the triangle count.', "",
              "| Generator | Params (defaults) | Triangles | Shape |", "|---|---|---|---|"]
    for name, entry in library["meshes"].items():
        lines.append(f"| `{name}` | `{json.dumps(entry['params'])}` | `{entry['triangles']}` | {entry['description']} |")
    return "\n".join(lines) + "\n"

"""Explicit annotation provenance and small local pairwise baseline/ranker."""

from __future__ import annotations

import math
import hashlib
import json
import os
from pathlib import Path
import tempfile


def _save_json(path: Path, value: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".part", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
        Path(name).replace(path)
    finally:
        Path(name).unlink(missing_ok=True)


DIMENSIONS = {"structural", "timing", "readability", "flow", "difficulty_fit", "variation", "enjoyment"}


def validate_label(label: dict) -> dict:
    required = {"left_id", "right_id", "winner", "dimension", "rater", "origin", "family_id", "seconds_spent"}
    if missing := required - set(label):
        raise ValueError(f"label missing {sorted(missing)}")
    if label["dimension"] not in DIMENSIONS or label["winner"] not in {"left", "right", "tie", "unknown"}:
        raise ValueError("invalid dimension or winner")
    if label["origin"] not in {"human", "assistant_proposed", "synthetic"}:
        raise ValueError("invalid label origin")
    if not label["rater"] or label["seconds_spent"] < 0:
        raise ValueError("rater and nonnegative duration required")
    if label["dimension"] == "enjoyment" and label["origin"] == "human" and not label.get("feedback_reference"):
        raise ValueError("human preference label requires feedback reference")
    return label


def label_report(labels: list[dict]) -> dict:
    for label in labels:
        validate_label(label)
    return {"count": len(labels), "human_count": sum(x["origin"] == "human" for x in labels),
            "minutes": round(sum(x["seconds_spent"] for x in labels) / 60, 2),
            "unknown_count": sum(x["winner"] in {"tie", "unknown"} for x in labels),
            "dimensions": {dim: sum(x["dimension"] == dim for x in labels) for dim in sorted(DIMENSIONS)}}


class LabelStore:
    """Append-only JSON labels with stable IDs and retained human provenance."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.data = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {
            "schema_version": "1.0", "labels": []}

    def append(self, label: dict) -> dict:
        validate_label(label)
        from .storage import WorkspaceLock
        with WorkspaceLock(self.path.with_suffix(".lock")):
            if self.path.exists():
                self.data = json.loads(self.path.read_text(encoding="utf-8"))
            body = {key: value for key, value in label.items() if key != "id"}
            identifier = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:20]
            if any(item["id"] == identifier for item in self.data["labels"]):
                raise ValueError("duplicate label")
            item = {"id": identifier, **body}
            self.data["labels"].append(item)
            _save_json(self.path, self.data)
            return item

    def labels(self) -> list[dict]:
        return list(self.data["labels"])


def feature_vector(pattern: dict) -> list[float]:
    return [float(pattern.get("nps", 0)), float(pattern.get("active_nps", 0)),
            float(pattern.get("note_count", 0)), float(pattern.get("length_beats", 0))]


def train_pairwise(patterns: dict[str, dict], labels: list[dict], *, allowed_families: set[str],
                   dimension: str = "enjoyment", epochs: int = 500,
                   learning_rate: float = 0.02, min_labels: int = 20) -> dict:
    """Train deterministic L2 logistic pairwise weights; never auto-promote sparse data."""
    examples = []
    unresolved = 0
    for item in labels:
        validate_label(item)
        if (item["origin"] != "human" or item["winner"] not in {"left", "right"}
                or item["dimension"] != dimension):
            continue
        left, right = patterns.get(item["left_id"]), patterns.get(item["right_id"])
        if left is None or right is None:
            # The catalog may be absent (too few labels to load it) or the
            # pattern may have been reprocessed away; count rather than crash.
            unresolved += 1
            continue
        if (left.get("song_family_id") not in allowed_families
                or right.get("song_family_id") not in allowed_families):
            continue
        x = [a - b for a, b in zip(feature_vector(left), feature_vector(right))]
        examples.append((x, 1 if item["winner"] == "left" else 0))
    if len(examples) < min_labels or len({y for _, y in examples}) < 2:
        return {"status": "no_go", "reason": "insufficient balanced human training labels",
                "count": len(examples), "unresolved_pattern_labels": unresolved}
    means = [sum(abs(x[j]) for x, _ in examples) / len(examples) or 1 for j in range(4)]
    weights = [0.0] * 4
    for _ in range(epochs):
        gradient = [0.001 * w for w in weights]
        for x, y in examples:
            scaled = [v / m for v, m in zip(x, means)]
            z = max(-30, min(30, sum(a * b for a, b in zip(weights, scaled))))
            error = 1 / (1 + math.exp(-z)) - y
            for j in range(4):
                gradient[j] += error * scaled[j] / len(examples)
        weights = [w - learning_rate * g for w, g in zip(weights, gradient)]
    return {"status": "trained_not_promoted", "model_version": "1.0", "dimension": dimension,
            "features": ["nps", "active_nps", "note_count", "length_beats"],
            "weights": weights, "scale": means, "training_count": len(examples),
            "family_count": len(allowed_families), "scope": "pairwise preference proxy; held-out evaluation and baseline comparison required"}


def pairwise_probability(model: dict, left: dict, right: dict) -> float:
    if model.get("status") not in {"trained_not_promoted", "promoted"}:
        raise ValueError("ranker unavailable; use deterministic retrieval baseline")
    delta = [a - b for a, b in zip(feature_vector(left), feature_vector(right))]
    z = sum(w * x / scale for w, x, scale in zip(model["weights"], delta, model["scale"]))
    return 1 / (1 + math.exp(-max(-30, min(30, z))))


def evaluate_ranker(model: dict, patterns: dict[str, dict], labels: list[dict], *,
                    heldout_families: set[str], min_pairs: int = 10,
                    min_improvement: float = 0.05) -> dict:
    """Compare to a fixed higher-density baseline; promote only on preregistered evidence."""
    if model.get("status") != "trained_not_promoted":
        return {"decision": "no_go", "reason": "no fitted candidate"}
    pairs = []
    for label in labels:
        validate_label(label)
        if (label["origin"] != "human" or label["dimension"] != model["dimension"]
                or label["winner"] not in {"left", "right"}):
            continue
        left, right = patterns.get(label["left_id"]), patterns.get(label["right_id"])
        if left is None or right is None:
            continue
        if (left.get("song_family_id") not in heldout_families
                or right.get("song_family_id") not in heldout_families):
            continue
        predicted = pairwise_probability(model, left, right) >= 0.5
        baseline = left.get("nps", 0) >= right.get("nps", 0)
        answer = label["winner"] == "left"
        pairs.append((predicted == answer, baseline == answer))
    if len(pairs) < min_pairs:
        return {"decision": "no_go", "reason": "insufficient held-out human pairs", "count": len(pairs)}
    accuracy = sum(x for x, _ in pairs) / len(pairs)
    baseline_accuracy = sum(x for _, x in pairs) / len(pairs)
    decision = "promote" if accuracy >= baseline_accuracy + min_improvement else "no_go"
    return {"decision": decision, "count": len(pairs), "accuracy": accuracy,
            "baseline_accuracy": baseline_accuracy, "required_improvement": min_improvement,
            "dimension": model["dimension"]}


def train_and_record(patterns: dict[str, dict], labels: list[dict], *,
                     train_families: set[str], heldout_families: set[str],
                     output: str | Path, dimension: str = "enjoyment",
                     min_labels: int = 20, min_heldout_pairs: int = 10,
                     min_improvement: float = 0.05) -> dict:
    """Persist reproducible no-go or held-out decision with an unactivated model."""
    if train_families & heldout_families:
        raise ValueError("training and held-out song families overlap")
    model = train_pairwise(patterns, labels, allowed_families=train_families,
                           dimension=dimension, min_labels=min_labels)
    result = evaluate_ranker(model, patterns, labels, heldout_families=heldout_families,
                             min_pairs=min_heldout_pairs, min_improvement=min_improvement)
    config = {"dimension": dimension, "min_labels": min_labels,
              "min_heldout_pairs": min_heldout_pairs, "min_improvement": min_improvement}
    label_payload = json.dumps(labels, sort_keys=True, ensure_ascii=False).encode()
    pattern_fingerprints = {key: hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
                            for key, value in patterns.items() if value.get("song_family_id") in train_families | heldout_families}
    artifact = {"schema_version": "1.0", "dimension": dimension,
                "config": config,
                "labels_sha256": hashlib.sha256(label_payload).hexdigest(),
                "patterns_sha256": hashlib.sha256(json.dumps(pattern_fingerprints, sort_keys=True).encode()).hexdigest(),
                "implementation_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "train_families": sorted(train_families), "heldout_families": sorted(heldout_families),
                "label_report": label_report(labels), "model": model, "evaluation": result,
                "active": False}
    _save_json(Path(output), artifact)
    return artifact

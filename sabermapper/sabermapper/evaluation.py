"""Family split registry and frozen evaluation manifests."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile


SPLIT_RULE_VERSION = "1.0"


def assign_split(family_id: str, *, salt: str = "sabermapper-v1", fractions=(0.7, 0.15, 0.15)) -> str:
    if not family_id or abs(sum(fractions) - 1) > 1e-9:
        raise ValueError("family ID and normalized fractions required")
    value = int(hashlib.sha256(f"{salt}:{family_id}".encode()).hexdigest()[:16], 16) / 2**64
    return "train" if value < fractions[0] else "validation" if value < fractions[0] + fractions[1] else "test"


class SplitRegistry:
    """Explicit aliases and audio hashes override title-based guesses."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.data = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {
            "schema_version": SPLIT_RULE_VERSION, "families": {}, "aliases": {},
            "quarantine": [], "retired_evaluation_memberships": []}
        self.data.setdefault("retired_evaluation_memberships", [])

    def resolve(self, *, version_hash: str, audio_sha256: str | None = None,
                family_id: str | None = None) -> dict:
        key = version_hash.upper()
        aliases = self.data["aliases"]
        matches = {aliases[x] for x in (f"version:{key}", f"audio:{audio_sha256}") if x in aliases}
        if family_id:
            matches.add(family_id)
        if len(matches) > 1:
            self.data["quarantine"].append({"version_hash": key, "candidate_families": sorted(matches),
                                             "reason": "alias merge requires review"})
            self.save()
            return {"version_hash": key, "split": "quarantine", "candidate_families": sorted(matches)}
        family = next(iter(matches), family_id or f"version:{key}")
        split = self.data["families"].setdefault(family, assign_split(family))
        aliases[f"version:{key}"] = family
        if audio_sha256:
            aliases[f"audio:{audio_sha256}"] = family
        self.save()
        return {"version_hash": key, "family_id": family, "split": split}

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle, name = tempfile.mkstemp(prefix=self.path.name + ".", suffix=".part", dir=self.path.parent)
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(self.data, stream, indent=2, sort_keys=True)
                stream.write("\n")
            Path(name).replace(self.path)
        finally:
            Path(name).unlink(missing_ok=True)

    def mark_development(self, version_hashes: list[str], *, reason: str) -> dict:
        """Reserve inspected/pilot families for development, retiring held-out claims."""
        if not reason.strip():
            raise ValueError("development reason required")
        families = set()
        for hash_ in version_hashes:
            key = f"version:{hash_.upper()}"
            family = self.data["aliases"].get(key)
            if not family:
                family = self.resolve(version_hash=hash_)["family_id"]
            families.add(family)
        retired = []
        for family in sorted(families):
            prior = self.data["families"].get(family)
            if prior in {"validation", "test"}:
                record = {"family_id": family, "previous_split": prior,
                          "reason": reason, "action": "retire any frozen evaluation containing this family"}
                self.data["retired_evaluation_memberships"].append(record)
                retired.append(record)
            self.data["families"][family] = "development"
        self.save()
        return {"marked_families": len(families), "retired_memberships": retired,
                "reason": reason}

    def freeze(self, records: list[dict], path: str | Path) -> dict:
        resolved = [self.resolve(version_hash=r["version_hash"], audio_sha256=r.get("audio_sha256"),
                                 family_id=r.get("family_id")) for r in records]
        family_splits = {}
        for item in resolved:
            if item["split"] == "quarantine":
                continue
            old = family_splits.setdefault(item["family_id"], item["split"])
            if old != item["split"]:
                raise ValueError("family leakage across splits")
        payload = {"schema_version": SPLIT_RULE_VERSION, "rule": "sha256 salt + explicit alias registry",
                   "records": resolved, "quarantine_count": sum(x["split"] == "quarantine" for x in resolved),
                   "retired_evaluation_memberships": self.data["retired_evaluation_memberships"]}
        payload["manifest_sha256"] = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        Path(path).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return payload


def evaluation_report(*, predicted: list[float], expected: list[int],
                      family_ids: list[str], split: list[str]) -> dict:
    if not (len(predicted) == len(expected) == len(family_ids) == len(split)):
        raise ValueError("evaluation arrays have different lengths")
    if any(y not in (0, 1) for y in expected):
        raise ValueError("binary pairwise expectations required")
    memberships = {}
    for family, cohort in zip(family_ids, split):
        memberships.setdefault(family, set()).add(cohort)
    if any(len(cohorts) > 1 for cohorts in memberships.values()):
        raise ValueError("family leakage")
    out = {}
    for cohort in ("train", "validation", "test"):
        indices = [i for i, s in enumerate(split) if s == cohort]
        out[cohort] = {"count": len(indices),
                       "accuracy": sum((predicted[i] >= 0.5) == bool(expected[i]) for i in indices) / len(indices)
                       if indices else None}
    return out

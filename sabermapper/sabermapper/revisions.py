"""Small, explicit section edits for the disposable authoring experiment."""

from copy import deepcopy
import hashlib
import json


def arrangement_revision(arrangement: dict) -> str:
    """Identify exact JSON content independently of formatting and key order."""
    if not isinstance(arrangement, dict):
        raise ValueError("Arrangement must be an object")
    try:
        payload = json.dumps(arrangement, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("Arrangement must contain valid JSON values") from exc
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def apply_section_revision(arrangement: dict, *, expected_revision: str,
                           section_id: str, replacement: dict) -> dict:
    """Return a validated copy; never modify the source or unrelated sections.

    A locked section cannot be replaced, including by a patch removing its lock.
    Callers save the prior artifact and the feedback request alongside the result.
    """
    from .validation import validate_arrangement

    if arrangement_revision(arrangement) != expected_revision:
        raise ValueError("Stale revision: reload the current arrangement before editing")
    sections = arrangement.get("sections")
    if not isinstance(sections, list):
        raise ValueError("Arrangement sections must be an array")
    matches = [i for i, section in enumerate(sections)
               if isinstance(section, dict) and section.get("id") == section_id]
    if len(matches) != 1:
        raise ValueError(f"Expected one section with ID {section_id!r}")
    index = matches[0]
    if arrangement["sections"][index].get("locked", False):
        raise ValueError(f"Section {section_id!r} is locked")
    if not isinstance(replacement, dict) or replacement.get("id") != section_id:
        raise ValueError("Replacement must preserve the section ID")
    result = deepcopy(arrangement)
    result["sections"][index] = deepcopy(replacement)
    errors = [item for item in validate_arrangement(result)
              if item["severity"] == "error"]
    if errors:
        raise ValueError("Invalid section revision: " + "; ".join(
            item["message"] for item in errors))
    return result

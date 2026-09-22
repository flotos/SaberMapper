"""Build the studio's packaged research summaries from checked-in evidence."""
from pathlib import Path
import re
from sabermapper.profile import summarize_scores
from sabermapper.storage import read_json, write_json

ROOT = Path(__file__).resolve().parents[1]
resources = ROOT / "sabermapper" / "resources"
summary = summarize_scores(read_json(ROOT / "planning/research/scoresaber-snapshot.json"))
write_json(resources / "profile.json", {
    "schema_version": "1.0",
    "summary": "Nine unmodified ranked Standard results since 2024 average 7.43 ScoreSaber stars and 80.50% base-score accuracy. Eight cluster in January 2025. These historical scores do not establish current taste or comfort.",
    "statistics": summary["since_2024"],
    "provenance": "planning/research/scoresaber-snapshot.json",
    "uncertainty": "Saved best results are not all attempts. Named references and current playtests remain necessary.",
})
notes = [
    ("Timing and rhythm", "Check alignment at the start, middle and end. Preserve intentional syncopation; correct source alignment before shifting notes.", "basic-mapping.html#timing-rhythm"),
    ("Musical emphasis", "Let movement reflect the sound: doubles, space and wider strokes should have an audible reason.", "basic-mapping.html#emphasis-consistency"),
    ("Parity and recovery", "Inspect each hand's entry and exit. Rapid repeated cuts merit review, but a reset after a rest can be deliberate.", "intermediate-mapping.html#parity"),
    ("Repetition with variation", "Recurring music can retain a recognizable phrase while changed instrumentation motivates a different accent or exit.", "intermediate-mapping.html#consistency"),
    ("Visibility and jumps", "Consider clutter, jump settings and neighboring patterns together. A warning remains a hypothesis until reviewed.", "intermediate-mapping.html#note-jump-speed"),
    ("Functional lighting", "Keep the environment readable and mark structure. A playable map does not require rich animation.", "basic-lighting.html"),
    ("Technical intent", "Unusual movement is not automatically defective. Record setup, readability, intent and recovery before revising it.", "intermediate-mapping.html"),
]
write_json(resources / "knowledge.json", {"schema_version": "1.0", "retrieved_at": "2026-09-22", "notes": [
    {"title": title, "summary": text, "source": "https://bsmg.wiki/mapping/" + source}
    for title, text, source in notes]})
write_json(resources / "protocol.json", {
    "schema_version": "1.0",
    "summary": "Freeze song-family splits before tuning. Keep exact versions and audio aliases together, quarantine cross-split merges, and treat inspected pilot material as development data. Compare a rules baseline and an authored map with order-balanced review. Log timing, technical interest, enjoyment, fatigue and review time separately.",
    "human_validation": "Synthetic ratings are never user preference labels. Sparse or unsuccessful ranker experiments return no-go.",
    "timing_references_target": 3, "qualitative_songs_target": [3, 5],
})
evidence = {
    1: "docs/architecture.md", 2: "sabermapper/profile.py", 3: "docs/mapping-knowledge.md",
    4: "sabermapper/corpus.py", 5: "sabermapper/__main__.py", 6: "sabermapper/corpus.py",
    7: "sabermapper/mapio.py", 8: "sabermapper/corpus.py", 9: "sabermapper/patterns.py",
    10: "sabermapper/patterns.py", 11: "sabermapper/learning.py", 12: "sabermapper/learning.py",
    13: "sabermapper/patterns.py", 14: "sabermapper/audio.py", 15: "sabermapper/timing.py",
    16: "sabermapper/structure.py", 17: "sabermapper/arrangement.py", 18: "sabermapper/arrangement.py",
    19: "sabermapper/validation.py", 20: "sabermapper/static/app.js", 21: "sabermapper/projects.py",
    22: "skills/sabermapper-map/SKILL.md", 23: "skills/sabermapper-research/SKILL.md",
    24: "skills/sabermapper-review/SKILL.md", 25: "sabermapper/export.py",
    26: "docs/evaluation-protocol.md", 27: "Start-SaberMapper.ps1", 28: "sabermapper/evaluation.py",
    29: "docs/experiment-workflow.md", 30: "sabermapper/movement.py", 31: "docs/external-audit.md",
}
qualifications = {
    2: "Current player calibration pending", 4: "Human phrase curation pending",
    8: "Measured pilot report available", 11: "Human labels not fabricated",
    12: "No preference claim without labels", 15: "Listening review required",
    16: "Section labels need musical review", 20: "VR playtest remains separate",
    22: "Musical quality requires player feedback", 25: "In-game compatibility needs playtest",
    26: "Human playtest observations pending", 28: "Manual timing anchors pending",
    29: "Replay decision belongs to user", 30: "Heuristic; not biomechanics",
}
tickets = []
for number, source in evidence.items():
    ticket = next((ROOT / "planning/tickets").glob(f"SM-{number:03}-*.md"))
    title = ticket.read_text(encoding="utf-8").splitlines()[0].split(": ", 1)[1]
    assert (ROOT / source).is_file(), source
    tickets.append({"id": f"SM-{number:03}", "title": title, "evidence": source,
                    "status": "Implemented" + (" · " + qualifications[number] if number in qualifications else " · local evidence available")})
payload = {"schema_version": "1.0", "scope": "Software capability and external acceptance evidence are separate.", "tickets": tickets}
write_json(resources / "ticket-status.json", payload)
write_json(ROOT / "docs/ticket-coverage.json", payload)
print(f"Built {len(tickets)} ticket records and research summaries")

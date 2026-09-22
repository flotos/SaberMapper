"""Transparent deterministic starting arrangements, never presented as AI output."""
from __future__ import annotations

import math


def starting_arrangement(title: str, artist: str, bpm: float, duration_seconds: float,
                         *, difficulty: str = "Expert", demo: bool = False) -> dict:
    ranks = {"Easy": 1, "Normal": 3, "Hard": 5, "Expert": 7, "ExpertPlus": 9}
    if difficulty not in ranks:
        raise ValueError("Unknown Standard difficulty")
    if not math.isfinite(bpm) or not 20 <= bpm <= 400:
        raise ValueError("BPM must be between 20 and 400 for the starting arrangement")
    total = max(0, math.floor(duration_seconds * bpm / 60) - 2)
    if total < 8:
        raise ValueError("Use at least eight beats of audio to create a map")
    sections = []
    motifs = {}
    intents = ["Establish the pulse with space to settle in", "Answer the melody with alternating diagonals",
               "Open up the accents; retain a clear recurring phrase", "Vary the rhythm and release into the ending"]
    for number, start in enumerate(range(4, total, 16)):
        length = min(16, total - start)
        notes = []
        step = 2 if difficulty in ("Easy", "Normal") else 1
        # Intentional, audible rhythm variations in the original demonstration.
        positions = [float(b) for b in range(0, length, step)]
        if demo and number % 4 in (1, 2) and difficulty in ("Expert", "ExpertPlus"):
            positions += [b + 0.5 for b in range(2, length - 1, 4)]
        positions.sort()
        count = {0: 0, 1: 0}
        for index, beat in enumerate(positions):
            hand = index % 2
            down = count[hand] % 2 == 0
            count[hand] += 1
            direction = (1 if down else 0)
            if demo and number % 4 == 1:
                direction = (6 if hand == 0 else 7) if down else (5 if hand == 0 else 4)
            notes.append({"id": f"n{index:03}", "beat": beat, "x": 1 if hand == 0 else 2,
                          "y": 1 if down else 0, "color": hand, "direction": direction})
        sections.append({"id": f"section-{number + 1:02}", "start_beat": start,
                         "length_beats": length, "intent": intents[number % 4] if demo else "Rules baseline: review and author musical intent",
                         "locked": False, "resolved": True, "notes": notes, "patterns": []})
    return {"schema_version": "0.1", "song": {"title": title, "artist": artist,
            "bpm": bpm, "audio_offset_seconds": 0},
            "difficulty": {"name": difficulty, "rank": ranks[difficulty], "njs": 14,
                           "spawn_offset_beats": 0}, "motifs": motifs, "sections": sections}


def make_cover(path, title="SaberMapper"):
    """Create an original, deterministic export cover using vector-like primitives."""
    from PIL import Image, ImageDraw
    image = Image.new("RGB", (512, 512), "#10151e")
    draw = ImageDraw.Draw(image)
    for y in range(512):
        draw.line((0, y, 512, y), fill=(16 + y // 50, 21 + y // 35, 30 + y // 22))
    draw.line((110, 350, 270, 120), fill="#ff6685", width=24)
    draw.line((240, 350, 400, 120), fill="#53c9e9", width=24)
    draw.text((35, 445), title[:50], fill="#eaf3f6", font_size=24)
    image.save(path, format="PNG")

"""A recurring part of the song is played as a recurring pattern (themes), and project check reports one that is not."""
import copy
from fractions import Fraction
import unittest

from sabermapper.arrangement import expanded_notes
from sabermapper.check import apply_suggestion, check_arrangement
from sabermapper.critique import critique_arrangement
from sabermapper.placement import place_arrangement
from sabermapper.recurrence import (add_theme, audio_repeats, echo_score, propose_themes, rhythm_stems,
                                    theme_links)
from sabermapper.validation import validate_arrangement

FIGURE = (0, 0.5, 1, 2, 2.5, 3.5)
PLAIN = (0, 1, 2, 3)
HOOK = {"id": "hook", "intent": "the hook", "spans": [{"start_beat": 0, "end_beat": 16},
                                                      {"start_beat": 32, "end_beat": 48}]}


def arrangement(*, locked=()):
    """A hook (0-16), a plain bar run, the hook again (32-48), then the plain run again."""
    sections = []
    for sid, start, figure in (("a", 0, FIGURE), ("b", 16, PLAIN), ("c", 32, FIGURE), ("d", 48, PLAIN)):
        notes = [{"id": f"{sid}{i:02d}", "beat": bar + b}
                 for i, (bar, b) in enumerate((bar, b) for bar in range(0, 16, 4) for b in figure)]
        sections.append({"id": sid, "start_beat": start, "length_beats": 16, "intent": sid,
                         "locked": sid in locked, "resolved": True, "notes": notes, "patterns": []})
    return {"schema_version": "0.1", "song": {"title": "F", "artist": "T", "bpm": 120, "audio_offset_seconds": 0},
            "difficulty": {"name": "Expert", "rank": 7, "njs": 16, "spawn_offset_beats": 0}, "motifs": {},
            "sections": sections}


def with_theme(theme=HOOK, **options):
    return add_theme(arrangement(**options), theme)


def score(placed, mirror=False):
    return echo_score(expanded_notes(placed), (Fraction(0), Fraction(16)), (Fraction(32), Fraction(48)), mirror)


def listen_sections():
    return [{"id": "sec-01", "start_beat": 0.0, "end_beat": 16.0, "repeats": []},
            {"id": "sec-02", "start_beat": 16.0, "end_beat": 32.0, "repeats": []},
            {"id": "sec-03", "start_beat": 32.0, "end_beat": 48.0,
             "repeats": [{"section_id": "sec-01", "similarity": 0.9, "transposed_semitones": 0}]},
            {"id": "sec-04", "start_beat": 48.0, "end_beat": 64.0, "repeats": []}]


class EchoScoreTests(unittest.TestCase):
    def test_echo_score_aligns_by_relative_beat_and_is_mirror_aware(self):
        statement = [{"id": "s1", "beat": Fraction(0), "x": 1, "y": 0, "color": 0, "direction": 1},
                     {"id": "s2", "beat": Fraction(1), "x": 2, "y": 1, "color": 1, "direction": 6}]
        echo = [{"id": "e1", "beat": Fraction(16), "x": 2, "y": 0, "color": 1, "direction": 1},
                {"id": "e2", "beat": Fraction(17) + Fraction(1, 10), "x": 1, "y": 1, "color": 0, "direction": 7},
                {"id": "e3", "beat": Fraction(18), "x": 0, "y": 0, "color": 0, "direction": 1}]
        found = echo_score(statement + echo, (Fraction(0), Fraction(4)), (Fraction(16), Fraction(20)))
        self.assertEqual(found["matched"], 2)
        self.assertEqual(found["rhythm"], round(2 / 3, 3))
        self.assertEqual(found["placement"], 1.0)
        self.assertTrue(found["mirror"])
        self.assertEqual(echo_score(statement + echo, (Fraction(0), Fraction(4)), (Fraction(16), Fraction(20)),
                                    mirror=False)["placement"], 0.0)


class ThemedPlacementTests(unittest.TestCase):
    def test_an_unthemed_repeat_is_placed_as_a_different_pattern(self):
        self.assertLess(score(place_arrangement(arrangement())["arrangement"])["placement"], 0.35)

    def test_a_declared_echo_is_placed_like_its_statement(self):
        result = place_arrangement(with_theme())
        self.assertEqual(result["errors"], [])
        self.assertGreaterEqual(score(result["arrangement"])["placement"], 0.9)
        self.assertEqual([d for d in validate_arrangement(result["arrangement"]) if d["severity"] == "error"], [])
        self.assertEqual(result["report"]["themes"][0]["theme"], "hook")

    def test_a_mirrored_echo_swaps_hands_and_lanes(self):
        theme = copy.deepcopy(HOOK)
        theme["spans"][1]["mirror"] = True
        placed = place_arrangement(with_theme(theme))["arrangement"]
        self.assertGreaterEqual(score(placed, mirror=True)["placement"], 0.9)
        self.assertLess(score(placed, mirror=False)["placement"], 0.5)

    def test_an_echo_double_where_the_statement_has_a_single_keeps_both_hands(self):
        draft = with_theme()
        draft["sections"][2]["notes"].append({"id": "c-double", "beat": 5})  # beat 37 echoes a single at 5
        placed = place_arrangement(draft)["arrangement"]
        pair = [n for n in expanded_notes(placed) if n["beat"] == 37]
        self.assertEqual(sorted(n["color"] for n in pair), [0, 1])

    def test_stored_placements_outrank_the_echo(self):
        stored = place_arrangement(arrangement())["arrangement"]
        themed = copy.deepcopy(stored)
        themed["themes"] = [copy.deepcopy(HOOK)]
        placed = place_arrangement(themed)["arrangement"]
        self.assertEqual(placed["sections"][2]["notes"], stored["sections"][2]["notes"])

    def test_a_locked_echo_span_is_left_alone(self):
        stored = place_arrangement(arrangement())["arrangement"]
        stored["sections"][2]["locked"] = True
        themed = add_theme(stored, HOOK)
        self.assertEqual(themed["sections"][2]["notes"], stored["sections"][2]["notes"])
        placed = place_arrangement(themed)["arrangement"]
        self.assertEqual(placed["sections"][2]["notes"], stored["sections"][2]["notes"])

    def test_placement_with_themes_is_deterministic(self):
        self.assertEqual(place_arrangement(with_theme())["arrangement"],
                         place_arrangement(with_theme())["arrangement"])

    def test_the_echo_preference_never_breaks_a_rule(self):
        # The echo's first note is pinned against the statement: the flow into the rest still holds.
        draft = with_theme()
        draft["sections"][2]["notes"][0].update(color=1, direction=0)
        result = place_arrangement(draft)
        self.assertEqual(result["errors"], [])


class ValidationTests(unittest.TestCase):
    def assert_invalid(self, themes):
        draft = arrangement()
        draft["themes"] = themes
        self.assertIn("invalid_theme", {d["code"] for d in validate_arrangement(draft)}, themes)

    def test_validation_accepts_a_theme_and_rejects_malformed_ones(self):
        draft = with_theme()
        self.assertNotIn("invalid_theme", {d["code"] for d in validate_arrangement(draft)})
        self.assert_invalid({"id": "x"})
        self.assert_invalid([{"id": "Bad Id", "intent": "x", "spans": HOOK["spans"]}])
        self.assert_invalid([{"id": "x", "intent": "", "spans": HOOK["spans"]}])
        self.assert_invalid([{"id": "x", "intent": "x", "spans": HOOK["spans"][:1]}])
        self.assert_invalid([{"id": "x", "intent": "x", "spans": [{"start_beat": 0, "end_beat": 8},
                                                                    {"start_beat": 32, "end_beat": 48}]}])
        self.assert_invalid([{"id": "x", "intent": "x", "spans": [{"start_beat": 0, "end_beat": 16},
                                                                    {"start_beat": 8, "end_beat": 24}]}])
        self.assert_invalid([{"id": "x", "intent": "x", "spans": [{"start_beat": 0, "end_beat": 16, "mirror": True},
                                                                    {"start_beat": 32, "end_beat": 48}]}])
        self.assert_invalid([HOOK, {**HOOK, "id": "again"}])

    def test_theme_links_cover_an_echo_shorter_than_its_statement(self):
        draft = arrangement()
        draft["themes"] = [{"id": "x", "intent": "x", "spans": [{"start_beat": 0, "end_beat": 16},
                                                                  {"start_beat": 32, "end_beat": 40}]}]
        link, = theme_links(draft)
        self.assertEqual((link["statement"], link["echo"]), ((0, 8), (32, 40)))


class CheckTests(unittest.TestCase):
    def test_repeat_unechoed_fires_for_a_listen_repeat_mapped_differently_and_clears_with_a_theme(self):
        placed = place_arrangement(arrangement())["arrangement"]
        warnings = critique_arrangement(placed, None, listen=listen_sections())["warnings"]
        found = [w for w in warnings if w["code"] == "repeat_unechoed"]
        self.assertEqual(len(found), 1, warnings)
        self.assertEqual(found[0]["beats"], [32, 48])
        suggestion, = found[0]["suggestions"]
        self.assertEqual(suggestion["op"], "add_theme")
        fixed = apply_suggestion(placed, suggestion)
        report = check_arrangement(fixed, None, listen=listen_sections())
        self.assertEqual(report["blocking_count"], 0)
        self.assertFalse({"repeat_unechoed", "theme_unechoed"} & set(report["counts"]), report["counts"])

    def test_theme_unechoed_fires_when_pins_break_a_declared_theme(self):
        placed = place_arrangement(arrangement())["arrangement"]
        for section in placed["sections"]:
            for note in section["notes"]:
                note.pop("placed", None)  # every value is now the agent's pin
        placed["themes"] = [copy.deepcopy(HOOK)]
        codes = [w["code"] for w in critique_arrangement(placed, None)["warnings"]]
        self.assertIn("theme_unechoed", codes)


class RecurringAudioTests(unittest.TestCase):
    def test_listen_repeats_pair_with_the_earliest_matching_section_on_whole_bars(self):
        sections = listen_sections()
        sections[3]["repeats"] = [{"section_id": "sec-03", "similarity": 0.7, "transposed_semitones": 5},
                                  {"section_id": "sec-02", "similarity": 0.6, "transposed_semitones": 0}]
        sections[3]["start_beat"] = 48.2
        found = audio_repeats(arrangement(), None, sections)
        self.assertEqual([(r["statement"], r["echo"]) for r in found], [([0, 16], [32, 48]), ([16, 32], [48, 64])])

    def test_rhythm_repeats_follow_the_drums_and_the_busiest_instrument(self):
        from test_rhythm_proposal import song, song_arrangement
        evidence = song()
        self.assertEqual(rhythm_stems(evidence), ["drums", "guitar"])
        found = [r for r in audio_repeats(song_arrangement(), evidence) if r["source"] == "rhythm"]
        self.assertTrue(found)
        self.assertTrue(all(r["echo"][0] - r["statement"][0] >= 32 for r in found))

    def test_proposed_themes_mirror_a_transposed_return_and_skip_declared_spans(self):
        sections = listen_sections()
        sections[2]["repeats"][0]["transposed_semitones"] = 5
        theme, = propose_themes(arrangement(), None, sections)
        self.assertEqual(theme["spans"], [{"start_beat": 0, "end_beat": 16},
                                          {"start_beat": 32, "end_beat": 48, "mirror": True}])
        self.assertEqual(propose_themes(with_theme(), None, sections), [])

    def test_a_repeat_of_part_of_a_statement_joins_its_theme_from_that_beat(self):
        import sabermapper.recurrence as recurrence
        repeats = [{"statement": [0, 32], "echo": [64, 96], "source": "listen", "similarity": 0.9,
                    "transposed_semitones": 0, "sections": []},
                   {"statement": [16, 48], "echo": [128, 160], "source": "rhythm", "similarity": 0.9,
                    "transposed_semitones": 0, "sections": []},   # runs past the statement: it grows to 48
                   {"statement": [80, 96], "echo": [176, 192], "source": "rhythm", "similarity": 0.9,
                    "transposed_semitones": 0, "sections": []}]   # repeats the echo 64-96: statement beat 16
        original = recurrence.audio_repeats
        recurrence.audio_repeats = lambda *args: repeats
        try:
            theme, = propose_themes(arrangement(), None)
        finally:
            recurrence.audio_repeats = original
        self.assertEqual(theme["spans"], [{"start_beat": 0, "end_beat": 48},
                                          {"start_beat": 64, "end_beat": 96},
                                          {"start_beat": 128, "end_beat": 160, "from_beat": 16, "mirror": True},
                                          {"start_beat": 176, "end_beat": 192, "from_beat": 16}])

    def test_an_echo_from_inside_the_statement_links_to_that_part(self):
        draft = arrangement()
        draft["themes"] = [{"id": "x", "intent": "x", "spans": [{"start_beat": 0, "end_beat": 16},
                                                                  {"start_beat": 40, "end_beat": 48, "from_beat": 8}]}]
        self.assertNotIn("invalid_theme", {d["code"] for d in validate_arrangement(draft)})
        link, = theme_links(draft)
        self.assertEqual((link["statement"], link["echo"]), ((8, 16), (40, 48)))
        draft["themes"][0]["spans"][1]["from_beat"] = 12
        self.assertIn("invalid_theme", {d["code"] for d in validate_arrangement(draft)})

    def test_the_suggestion_extends_the_theme_whose_statement_covers_the_repeat(self):
        from sabermapper.recurrence import _theme_for
        declared = place_arrangement(with_theme({"id": "hook", "intent": "the hook",
                                                 "spans": [{"start_beat": 0, "end_beat": 32},
                                                           {"start_beat": 32, "end_beat": 48}]}))["arrangement"]
        repeat = {"statement": [4, 20], "echo": [48, 64], "transposed_semitones": 0}
        theme = _theme_for(declared, repeat)
        self.assertEqual(theme["id"], "hook")
        self.assertEqual(theme["spans"][-1], {"start_beat": 48, "end_beat": 64, "from_beat": 4})
        extended = add_theme(declared, theme)
        self.assertEqual(len(extended["themes"]), 1)
        self.assertEqual(extended["sections"][2]["notes"], declared["sections"][2]["notes"])  # 32-48 kept
        self.assertTrue(all("x" not in n for n in extended["sections"][3]["notes"]))  # 48-64 reopened
        self.assertIsNone(_theme_for(declared, {"statement": [0, 16], "echo": [40, 56], "transposed_semitones": 0}))

    def test_the_draft_declares_themes_for_the_recurring_parts_it_drafts(self):
        from test_rhythm_proposal import song, song_arrangement
        from sabermapper.rhythm_proposal import propose_rhythm
        result = propose_rhythm(song_arrangement(), song(), held=[36.0])
        self.assertTrue(result["themes"])
        self.assertEqual(result["draft"]["themes"], result["themes"])
        self.assertTrue(result["placement"]["themes"])


if __name__ == "__main__":
    unittest.main()

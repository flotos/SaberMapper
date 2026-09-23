"""Spectrogram images of the mix and its stems, for an agent that reads images but cannot listen.

Each panel is one layer on a log-frequency axis (30 Hz to 11 kHz, low at the bottom) with brightness
in dB against the mix: every layer shares one reference, so a stem that is absent or only bleed reads
dark instead of being stretched to full brightness. Over the panels the image draws bar and beat
lines from the arrangement's grid, section boundaries, each bar's salient layer, the mapped notes and
arcs (red and blue lanes, with faint lines through the panels), strong attacks per layer (white ticks)
and pitch, chord and melody changes (cyan ticks), and where each stem enters (green).
"""

from __future__ import annotations

import math
from fractions import Fraction
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy.signal import resample_poly, stft

from .audio import _decode

RATE = 22050
FFT = 2048
LOW_HZ, HIGH_HZ = 30.0, 11000.0
FLOOR_DB = 80.0
REFERENCE_PERCENTILE = 99.9
LABEL_WIDTH = 104
PANEL_HEIGHT = 128
OVERVIEW_PANEL_HEIGHT = 96
TICK_HEIGHT = 10
MAX_WIDTH = 2400
MIN_BEAT_PIXELS, MAX_BEAT_PIXELS = 8, 64
ATTACK_STRENGTH = 0.3
ATTACKS = ("spectral_flux",)
CHANGES = ("pitch_change", "chord_change", "melody_change")
# Anchors of a perceptually ordered dark-to-bright palette (magma).
PALETTE = np.array([(0, 0, 4), (28, 16, 68), (79, 18, 123), (129, 37, 129), (181, 54, 122),
                    (229, 80, 100), (251, 135, 97), (254, 194, 135), (252, 253, 191)], dtype=float)
COLORS = {"background": (12, 12, 16), "text": (230, 230, 235), "muted": (150, 150, 160),
          "bar": (255, 255, 255, 120), "beat": (255, 255, 255, 38), "section": (255, 214, 64),
          "red": (240, 60, 60), "blue": (70, 140, 255), "bomb": (170, 170, 170), "attack": (255, 255, 255),
          "change": (80, 230, 230), "entry": (90, 230, 120)}
LEGEND = {
    "panels": "One panel per layer: time left to right, log frequency 30 Hz-11 kHz bottom to top, brightness in "
              f"dB against the mix (0 to -{FLOOR_DB:g} dB); a dark stem is absent or bleed.",
    "grid": "Bold lines are bars (4 beats), faint lines beats; labels are absolute beats.",
    "notes": "Top lanes: red (left) and blue (right) notes as ticks, arcs as bars, bombs grey; faint colored lines "
             "carry each note time through the panels.",
    "ticks": f"Under each panel: white ticks are attacks (spectral_flux, strength {ATTACK_STRENGTH:g} or more, "
             "height = strength); cyan ticks are pitch, chord or melody changes.",
    "entries": "Green line and label: the stem becomes audible after silence (layer_entries).",
    "lead": "The lead row names each bar's salient layer: vocals, a declared lead, drums, or blank.",
}


def _font(size):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow before 10.1
        return ImageFont.load_default()


def _mono(path):
    samples, rate, _ = _decode(path)
    channel = int(np.argmax(np.mean(samples.astype(np.float64) ** 2, axis=0)))
    mono = samples[:, channel].astype(np.float32)
    if rate != RATE:
        divisor = math.gcd(rate, RATE)
        mono = resample_poly(mono, RATE // divisor, rate // divisor).astype(np.float32)
    return mono


def _magnitudes(samples, start, end, width):
    """(rows x width) maximum STFT magnitude per log-frequency row and pixel column."""
    first, last = max(0, int(start * RATE)), max(0, int(end * RATE))
    chunk = samples[first:last]
    if len(chunk) < FFT:
        chunk = np.pad(chunk, (0, FFT - len(chunk)))
    hop = max(32, min(FFT // 2, int(len(chunk) / (2 * width))))
    frequencies, times, spectrum = stft(chunk, fs=RATE, nperseg=FFT, noverlap=FFT - hop, boundary=None, padded=True)
    magnitude = np.abs(spectrum)
    edges = np.minimum(np.searchsorted(times, np.linspace(0, len(chunk) / RATE, width + 1)[:-1]),
                       magnitude.shape[1] - 1)
    columns = np.maximum.reduceat(magnitude, edges, axis=1)
    return frequencies, columns


def _rows(frequencies, height):
    """Frequency bin ranges for each image row, top row first."""
    bounds = np.geomspace(LOW_HZ, HIGH_HZ, height + 1)
    rows = []
    for low, high in zip(bounds[:-1], bounds[1:]):
        inside = np.flatnonzero((frequencies >= low) & (frequencies < high))
        rows.append(inside if len(inside) else [int(np.argmin(np.abs(frequencies - (low + high) / 2)))])
    return rows[::-1]


def _panel(columns, frequencies, height, reference):
    image = np.stack([columns[row].max(axis=0) for row in _rows(frequencies, height)])
    level = np.clip(20 * np.log10(np.maximum(image, 1e-12) / reference) / FLOOR_DB + 1, 0, 1)
    position = level * (len(PALETTE) - 1)
    index = np.minimum(position.astype(int), len(PALETTE) - 2)
    fraction = (position - index)[..., None]
    return (PALETTE[index] * (1 - fraction) + PALETTE[index + 1] * fraction).astype(np.uint8)


class _Axis:
    """Seconds to pixels, and beats to seconds when an arrangement gives the grid."""

    def __init__(self, start, end, left, width, arrangement=None):
        self.start, self.end, self.left, self.width, self.arrangement = start, end, left, width, arrangement

    def x(self, seconds):
        return self.left + (seconds - self.start) / (self.end - self.start) * self.width

    def seconds(self, beat):
        from .critique import beat_to_seconds
        return beat_to_seconds(beat, self.arrangement)

    def beat(self, seconds):
        from .musical import seconds_to_beat
        return seconds_to_beat(seconds, self.arrangement)


def _grid(draw, axis, top, bottom, font, label_y):
    """Bar and beat lines from ``top`` to ``bottom``, labelled at ``label_y``; seconds without an arrangement."""
    if axis.arrangement is None:
        step = next(s for s in (1, 2, 5, 10, 15, 30, 60) if (axis.end - axis.start) / s <= 24)
        for second in range(math.ceil(axis.start / step) * step, int(axis.end) + 1, step):
            x = axis.x(second)
            draw.line([(x, top), (x, bottom)], fill=COLORS["beat"])
            draw.text((x + 2, label_y), f"{second // 60}:{second % 60:02d}", fill=COLORS["muted"], font=font)
        return
    first, last = math.ceil(axis.beat(axis.start)), math.floor(axis.beat(axis.end))
    pixels = axis.width / max(1e-9, axis.beat(axis.end) - axis.beat(axis.start))
    label_every = next((k for k in (4, 8, 16, 32, 64, 128) if k * pixels >= 90), 256)
    for beat in range(first, last + 1):
        bar = beat % 4 == 0
        if not bar and pixels < 6 or bar and beat % (4 if pixels * 4 >= 24 else 16):
            continue
        x = axis.x(axis.seconds(beat))
        draw.line([(x, top), (x, bottom)], fill=COLORS["bar" if bar else "beat"], width=1)
        if beat % label_every == 0:
            seconds = axis.seconds(beat)
            draw.text((x + 2, label_y), f"{beat}  {int(seconds // 60)}:{seconds % 60:04.1f}",
                      fill=COLORS["muted"], font=font)


def _notes(draw, overlay, axis, arrangement, top, panels_top, bottom, font, through):
    """Red/blue note lanes and arcs from ``top``; faint note lines through the panels when ``through``."""
    from .arrangement import expanded_notes
    from .critique import _sections
    lane = 13
    draw.text((6, top), "notes L", fill=COLORS["red"], font=font)
    draw.text((6, top + lane), "notes R", fill=COLORS["blue"], font=font)
    for span in _sections(arrangement):
        for arc in span["section"].get("arcs") or []:
            head = axis.x(axis.seconds(span["start_beat"] + float(Fraction(str(arc["beat"])))))
            tail = axis.x(axis.seconds(span["start_beat"] + float(Fraction(str(arc["tail_beat"])))))
            y = top + lane * arc["color"] + lane // 2
            draw.line([(head, y), (tail, y)], fill=COLORS["red" if arc["color"] == 0 else "blue"], width=3)
    for note in expanded_notes(arrangement):
        seconds = axis.seconds(float(note["beat"]))
        if not axis.start <= seconds <= axis.end:
            continue
        x = axis.x(seconds)
        color = COLORS["bomb"] if note.get("type") == "bomb" else COLORS["red" if note.get("color") == 0 else "blue"]
        y = top + lane * (1 if note.get("color") == 1 else 0)
        draw.rectangle([x - 1, y + 1, x + 1, y + lane - 2], fill=color)
        if through:
            overlay.line([(x, panels_top), (x, bottom)], fill=(*color[:3], 70), width=1)


def _lanes(draw, axis, arrangement, report, top, font):
    """Section and salient-layer rows."""
    from .critique import _sections, critique_arrangement
    draw.text((6, top), "section", fill=COLORS["section"], font=font)
    for span in _sections(arrangement):
        x = axis.x(axis.seconds(span["start_beat"]))
        if axis.left <= x <= axis.left + axis.width:
            draw.line([(x, top), (x, top + 12)], fill=COLORS["section"], width=2)
            draw.text((x + 3, top), span["id"], fill=COLORS["section"], font=font)
    draw.text((6, top + 14), "lead", fill=COLORS["text"], font=font)
    bars = critique_arrangement(arrangement, report)["metrics"]["salience"].get("bars", [])
    previous = None
    for bar in bars:
        x = axis.x(axis.seconds(bar["start_beat"]))
        if not axis.left - 1 <= x <= axis.left + axis.width or bar["salient"] == previous:
            continue
        previous = bar["salient"]
        draw.line([(x, top + 14), (x, top + 26)], fill=COLORS["muted"])
        draw.text((x + 3, top + 14), bar["salient"] or "-", fill=COLORS["text"], font=font)


def render(report, run_directory, song, output, *, arrangement=None, start_seconds=None, end_seconds=None,
           layers=None, title="", overview=False):
    """Draw the image; returns its geometry for the caller to read against."""
    run_directory, output = Path(run_directory), Path(output)
    available = report.get("layers") or {}
    duration = float(report["source"]["duration_seconds"])
    start = max(0.0, 0.0 if start_seconds is None else float(start_seconds))
    end = min(duration, duration if end_seconds is None else float(end_seconds))
    if not end > start:
        raise ValueError("Choose a range inside the song")
    names = list(layers) if layers else ["mix"] + [n for n, layer in available.items()
                                                   if n != "mix" and layer.get("audio_file")]
    unknown = [n for n in names if n not in available or (n != "mix" and not available[n].get("audio_file"))]
    if unknown:
        raise ValueError(f"No audio to draw for {', '.join(unknown)}; drawable layers: mix, "
                         + ", ".join(n for n, l in available.items() if l.get("audio_file")))
    if arrangement is not None and not overview:
        from .musical import seconds_to_beat
        beats = seconds_to_beat(end, arrangement) - seconds_to_beat(start, arrangement)
        width = int(min(MAX_WIDTH, max(MIN_BEAT_PIXELS, min(MAX_BEAT_PIXELS, MAX_WIDTH / max(beats, 1e-9))) * beats))
    else:
        width = MAX_WIDTH
    width = max(200, width)
    height = OVERVIEW_PANEL_HEIGHT if overview else PANEL_HEIGHT
    font, small = _font(12), _font(10)
    header = 22 + 16 + (30 if arrangement is not None else 0) + (28 if arrangement is not None else 0)
    total = header + len(names) * (height + TICK_HEIGHT + 6) + 4
    canvas = Image.new("RGB", (LABEL_WIDTH + width + 8, total), COLORS["background"])
    draw = ImageDraw.Draw(canvas)
    overlay_image = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    overlay = ImageDraw.Draw(overlay_image)
    axis = _Axis(start, end, LABEL_WIDTH, width, arrangement)

    signals = {name: _mono(Path(song) if name == "mix" else run_directory / available[name]["audio_file"])
               for name in names}
    mix = signals.get("mix")
    if mix is None:
        mix = _mono(song)
    frequencies, mix_columns = _magnitudes(mix, start, end, width)
    reference = float(np.percentile(mix_columns, REFERENCE_PERCENTILE)) or 1.0

    top = 22 + 16
    if arrangement is not None:
        _notes(draw, overlay, axis, arrangement, top, header, total, small, through=width / max(
            1e-9, (end - start)) * 60 / float(arrangement["song"]["bpm"]) >= 12)
        _lanes(draw, axis, arrangement, report, top + 30, small)
    entries = {}
    from .musical import layer_entries
    for entry in report.get("layer_entries") or layer_entries(report):
        entries.setdefault(entry["layer"], []).append(entry["seconds"])
    panels, y = [], header
    for name in names:
        columns = mix_columns if name == "mix" else _magnitudes(signals[name], start, end, width)[1]
        canvas.paste(Image.fromarray(_panel(columns, frequencies, height, reference)), (LABEL_WIDTH, y))
        level = float(20 * np.log10(max(np.sqrt(np.mean(columns ** 2)), 1e-12)
                                    / max(np.sqrt(np.mean(mix_columns ** 2)), 1e-12)))
        draw.text((6, y + 2), name, fill=COLORS["text"], font=font)
        draw.text((6, y + 18), "mix ref" if name == "mix" else f"{level:+.0f} dB vs mix", fill=COLORS["muted"],
                  font=small)
        gate = (available.get(name) or {}).get("bleed_gate")
        if gate and gate["removed_events"]:
            draw.text((6, y + 32), f"{gate['removed_events']} bleed ev. cut", fill=COLORS["muted"], font=small)
        for hertz in (100, 1000, 5000):
            row = y + height * (1 - math.log(hertz / LOW_HZ) / math.log(HIGH_HZ / LOW_HZ))
            draw.text((LABEL_WIDTH - 34, row - 6), f"{hertz // 1000}k" if hertz >= 1000 else str(hertz),
                      fill=COLORS["muted"], font=small)
        base = y + height + TICK_HEIGHT
        for event in (available.get(name) or {}).get("events", []):
            if not start <= event["seconds"] <= end:
                continue
            x = axis.x(event["seconds"])
            if event.get("method") in ATTACKS and event.get("strength", 0) >= ATTACK_STRENGTH:
                draw.line([(x, base), (x, base - max(2, round(TICK_HEIGHT * event["strength"])))],
                          fill=COLORS["attack"])
            elif event.get("method") in CHANGES and event.get("strength", 0) >= ATTACK_STRENGTH:
                draw.line([(x, base - TICK_HEIGHT), (x, base - TICK_HEIGHT + 3)], fill=COLORS["change"])
        for seconds in entries.get(name, []):
            if start <= seconds <= end:
                x = axis.x(seconds)
                overlay.line([(x, y), (x, y + height)], fill=(*COLORS["entry"], 230), width=2)
                draw.text((x + 3, y + 2), f"{name} enters", fill=COLORS["entry"], font=small)
        panels.append({"layer": name, "top": y, "bottom": y + height, "level_db_vs_mix": round(level, 1)})
        y += height + TICK_HEIGHT + 6
    _grid(overlay, axis, header, total - 4, small, label_y=24)
    canvas = Image.alpha_composite(canvas.convert("RGBA"), overlay_image).convert("RGB")
    draw = ImageDraw.Draw(canvas)
    draw.text((6, 4), title or f"{start:.1f}-{end:.1f} s", fill=COLORS["text"], font=font)
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output, optimize=True)
    geometry = {"image": str(output), "width": canvas.width, "height": canvas.height, "plot_left": LABEL_WIDTH,
                "plot_width": width, "start_seconds": round(start, 3), "end_seconds": round(end, 3),
                "seconds_per_pixel": round((end - start) / width, 6), "panels": panels, "legend": LEGEND}
    if arrangement is not None:
        from .musical import seconds_to_beat
        geometry.update(start_beat=round(seconds_to_beat(start, arrangement), 4),
                        end_beat=round(seconds_to_beat(end, arrangement), 4))
    return geometry


def render_overview(report, run_directory, song, arrangement=None):
    """The whole song with every stem, written beside a run's report; returns the image path."""
    path = Path(run_directory) / "overview.png"
    render(report, run_directory, song, path, arrangement=arrangement, overview=True,
           title=f"Overview, {report['backend']} run, {report['source']['duration_seconds']:.0f} s")
    return path


def project_view(directory, arrangement, report, run_id, *, start_beat=None, end_beat=None, layers=None,
                 output=None, difficulty=None):
    """A beat range (or the whole song) of a project's evidence run with its current notes."""
    from .critique import beat_to_seconds
    directory = Path(directory)
    if (start_beat is None) != (end_beat is None):
        raise ValueError("Pass both --start and --end, or neither for the whole song")
    if start_beat is not None and not (math.isfinite(start_beat) and math.isfinite(end_beat)
                                       and 0 <= start_beat < end_beat):
        raise ValueError("Choose a finite increasing beat range")
    start = None if start_beat is None else beat_to_seconds(start_beat, arrangement)
    end = None if end_beat is None else beat_to_seconds(end_beat, arrangement)
    label = "song" if start_beat is None else f"b{start_beat:g}-{end_beat:g}"
    suffix = f"-{difficulty}" if difficulty else ""
    output = Path(output) if output else directory / "views" / f"spectrogram-{run_id[:8]}-{label}{suffix}.png"
    title = (f'{arrangement["song"].get("title", "")} - beats {label[1:] if start_beat is not None else "all"}, '
             f"run {run_id[:8]}")
    geometry = render(report, directory / "musical" / run_id, directory / "song.ogg", output,
                      arrangement=arrangement, start_seconds=start, end_seconds=end, layers=layers,
                      title=title, overview=start_beat is None)
    return {"run_id": run_id, **geometry,
            "next": "Read the image. Check that notes sit on the bright attacks of the layer that leads each "
                    "bar, that stem entries and drops get a note, and that dark (absent) stems are not followed."}

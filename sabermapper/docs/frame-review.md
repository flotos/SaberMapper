# Frame review: contact sheets and frame metrics

Ticket M2 (agent verification in the game), agent side. `game capture` writes a directory of PNG frames
from the running game; these commands turn it into images the agent reads and findings the pipeline
can gate on. They work purely from files and never open the game.

Code: `sabermapper/frames.py` (loading, contact sheets), `sabermapper/frame_metrics.py` (metrics and
findings), `sabermapper/frames_cli.py` (CLI). Tests: `tests/test_frames.py` (synthetic frames).

## Input

`DIR/capture.json`, schema version 1:

```json
{"schema_version": 1, "project": "...", "revision": "...", "difficulty": "ExpertPlus",
 "camera": "player", "width": 1920, "height": 1080, "game_version": "...", "level_path": "...",
 "created_at": "...",
 "frames": [{"file": "t0012.500.png", "requested_time": 12.5, "song_time": 12.503, "beat": 25.0,
             "section_id": "verse-1", "reason": "section_start"}],
 "log_diagnostics": []}
```

`reason` is `section_start`, `moment`, `grid`, `requested` or `probe`. Probe frames are a dense run
(20-30 fps over a few seconds) for the flash check. A directory without `capture.json` is also read:
PNGs named `tSSSS.mmm.png` (song seconds) become frames, and other PNGs are skipped with a
`frame_name_unparsed` warning. With `--project`, frames lacking a beat or section get them from the
arrangement's tempo and sections.

## Commands

```
sabermapper frames sheet DIR [--out OUTDIR] [--no-per-section] [--columns 4] [--thumb-width 420] [--include-probe]
sabermapper frames metrics DIR [--project ID --workspace W] [--difficulty D] [--concept FILE] [--corridor x0,y0,x1,y1] [--output F]
sabermapper frames summary DIR [same options as metrics]
```

- `sheet` writes `OUTDIR/sheet-NNN-<section>[-pK].png` (default `DIR/sheets/`) and `sheets.json`.
  Each thumbnail is labelled with song time (m:ss.mmm), beat, section and reason; the header names
  project, revision, difficulty, camera and the section's time span. Sheets stay at most 2000 px
  wide and 4 rows tall (about 1200 px at the default thumb width); a long section splits into parts.
  Probe frames are left out unless `--include-probe`. Read the PNGs with the image viewer.
- `metrics` returns `{capture, metrics, findings, summary}`. `summary.blocking` is true when any
  finding has severity `error`.
- `summary` returns per-section stats: mean luminance, corridor median luminance and minimum note
  contrast, corridor edge density, dominant palette, palette distance, mean/max change score, peak
  flash rate, finding codes, plus the capture's `log_diagnostics`.

The palette, note colours and moments come from `--concept FILE`, else the project's `concept.json`
(or `show.json`), else the arrangement's `presentation`. Accepted shapes: `palette: ["#rrggbb", ...]`
at the top level, under `presentation`, `selected`, `concept`, or the selected entry of `treatments`;
note colours as `note_colors`/`colors`/`color_scheme` with `left`/`right` (or `saberA`/`saberB`)
in hex, `[r, g, b]` or `{r, g, b}`; moments as `moments: [{song_time|seconds|time|beat}]`. All are
optional.

For `project critique` integration, `frame_metrics.frame_findings(capture_dir, arrangement=None,
concept=None)` returns the findings list alone.

## Findings

Findings use the critique shape `{severity, code, section_id, object_ids, value, threshold, message}`
plus `time` (song seconds of the first triggering frame) and `frames` (capture file names). Each
message says what triggered it and how to fix it.

| Code | Severity | Meaning |
|---|---|---|
| `flash_rate_exceeded` | error | more than 3 general flashes in some 1 s window |
| `flash_rate_high` | warning | 2 to 3 general flashes in some 1 s window |
| `red_flash_rate_exceeded` / `red_flash_rate_high` | error / warning | same for saturated-red flashes |
| `flash_check_insufficient_sampling` | info | no dense run (>= 20 fps for >= 1 s); flashes not checked |
| `note_contrast_low` | warning | notes blend into the corridor background, arrows wash out, or the background is busy |
| `palette_drift` | warning | a section's lit colours are far from the concept palette |
| `palette_observed` | info | no concept palette: the observed palette per section |
| `visual_change_unaligned` | info | a large visual change with no boundary or moment near it |
| `section_boundary_static` | warning | nothing visibly changes at a section boundary |
| `section_boundary_unsampled` | info | boundaries without frames just before and after |
| `capture_revision_stale` | warning | frames come from another revision than the arrangement |

### 1. Photosensitive flashes

Source: WCAG 2.2 SC 2.3.1 "Three Flashes or Below Threshold" and its definition of the general and
red flash thresholds, and ITU-R BT.1702 (the broadcast guideline behind Ofcom's rules).

- Relative luminance per pixel: sRGB decoded to linear, `Y = 0.2126 R + 0.7152 G + 0.0722 B`.
- A **transition** is a change of at least 0.10 in relative luminance (10% of the maximum, 1.0)
  where the darker state is below 0.80. A **flash** is a pair of opposing transitions.
- Area: the frame is split into 8x8 tiles; a tile's transition is found with a turning-point
  hysteresis on its mean luminance, so a ramp over several frames counts once. Tile transitions in
  the same direction within 2 frames are concurrent; a frame-level transition needs concurrent tiles
  covering at least 25% of the frame. This is BT.1702's screen-area criterion. WCAG instead uses 25%
  of any 10-degree visual field, which is a smaller patch; the capture shows only the desktop view,
  so this check targets large-area flashing. A smaller area can be passed to `analyze_frames(...,
  flash_area=...)`.
- Red flash (WCAG): a transition to or from a state where `R / (R + G + B) >= 0.8` (linear) with a
  change of more than 20 in `max(0, R - G - B) * 320`.
- Rate: the most transitions inside any 1 s window, divided by 2. Above 3 flashes/s blocks
  (`error`); 2 or more warns.
- Sampling: a 5 Hz strobe has 10 transitions per second, which needs at least 20 fps to be resolved.
  Only runs of frames spaced <= 62.5 ms and lasting >= 1 s are checked (usually `reason: "probe"`);
  `metrics.flash.windows` lists them with fps and peak rates. Sparse captures produce
  `flash_check_insufficient_sampling` rather than a guess.

### 2. Note contrast along the note corridor

The corridor is the normalized screen rectangle `x 0.25-0.75, y 0.35-0.90` (y down) of the player
camera, where notes travel from the horizon to the player's hit zone. No real Beat Saber capture
existed in the workspace to calibrate it, so the default comes from the note paths in local
ArcViewer screenshots (`artifacts/arcviewer*.png`, same forward-facing perspective) widened to stay
conservative. Override it with `--corridor`, and recalibrate it once real FPFC captures exist.
Frames from `camera: "wide"` are not checked.

Per corridor pixel (at 192 px analysis width), for each note colour:

- **Body camouflage**: the pixel fails when the note colour's WCAG contrast ratio against it is
  below 3:1 (SC 1.4.11 non-text contrast) **and** its CIEDE2000 difference is below 20 (the colour
  does not stand out by hue either). Luminance alone would flag red notes on any dark scene, since
  default red on black is only 3.6:1, yet hue keeps them readable.
- **Arrow washout**: the white arrow falls below 3:1 once the background luminance exceeds 0.30.
- **Busy background**: edge density is the share of pixels whose L* differs from a neighbour by
  more than 10.

A frame warns when either note colour blends into at least 50% of the corridor, arrows wash out
over at least 50%, or edge density is at least 0.30. Consecutive warning frames in one section
become one finding. The default note colours are Beat Saber's default scheme, saberA `#c81414` and
saberB `#288ed2`. The per-frame values (median luminance, median contrast per colour, camouflage,
washout, edge density) are in `metrics.corridor.frames`. The 20 ΔE, 50% and 0.30 values are
heuristics; the 3:1 ratios come from WCAG.

### 3. Palette drift

Pixels are converted to CIELAB (D65). Pixels with L* < 12 count as neutral darkness and are left out,
since Beat Saber scenes are mostly dark and black is rarely a palette entry; `dark_share` reports
them. Deterministic k-means (k = 5, k-means++ seeded) runs on up to 6000 pooled pixels per section.
Clusters under 5% share are dropped. Each cluster's CIEDE2000 distance to the nearest palette colour
uses `kL = 2`, so lighting-driven lightness shifts weigh half as much as hue and chroma changes. The
section value is the share-weighted median of those distances; above 15 warns `palette_drift` and
lists the off-palette colours (share >= 10%) and the frames that drift on their own. Without a
palette, each section's observed palette is reported as info.

### 4. Visual change and section boundaries

The change score between two frames is the mean per-pixel CIE76 ΔE on a 48 px wide version.
2.3 is one just-noticeable difference; 20 means most of the view changed colour.

- Consecutive review frames (non-probe frames, plus probe frames at most every 0.5 s) whose score is
  at least 20, with no section boundary or moment within 0.5 s of their interval, give
  `visual_change_unaligned` (info: a lyric or sound may justify it; record it as a concept moment).
- At each boundary (arrangement sections, else section changes in the manifest), the last frame up
  to 4 s before is compared with every frame up to 2 s after. A best score under 2.3 gives
  `section_boundary_static` (warning).
- Moments are frames with `reason: "moment"` plus concept moments.

## Limits

2D desktop captures show the rendered picture only. They do not establish VR scale, stereo
correctness, comfort, motion sickness or frame-time performance, and the flash check covers only the
captured windows (`metrics.flash.checked_seconds`). The user's own headset playtest remains the
ground truth. Frames can come from an older revision than the arrangement; `capture_revision_stale`
says so.

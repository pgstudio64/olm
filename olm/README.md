# OLM — Office Layout Matching

> Local tool for matching office desk layout patterns to floor plan rooms.

**Alpha version** — functional core, not yet production-ready.

OLM takes a floor plan (raster image or room definitions) and a catalogue of desk layout patterns, then proposes optimized desk arrangements room by room. No AI, no internet — 100% local processing.

## Features

- **Pattern catalogue** — define reusable desk layout patterns with a visual editor
- **Automatic matching** — 7-step pipeline: Pareto selection, E-W mirror, wall clamping, homothety, desk suppression, circulation scoring, best selection
- **Configurable spacing standards** — define your own standards with 11 spacing parameters each (chair clearance, passage widths, door exclusions, etc.)
- **Circulation analysis** — Dijkstra-based path quality grading from door to each desk
- **Floor plan ingestion** — extract rooms from raster images via adaptive comb ray-casting (experimental)
- **Interactive web UI** — Flask-based interface with SVG rendering, pan/zoom, settings panel

## Quick start

### Requirements

- Python 3.10+
- No admin rights needed (works with user-level pip/conda)

### Install

```bash
# Clone the repository
git clone https://github.com/<your-username>/olm.git
cd olm

# Create virtual environment and install dependencies
python -m venv venv
source venv/bin/activate   # Linux/macOS
# venv\Scripts\activate    # Windows

pip install -r requirements.txt
```

On Windows, you can also double-click `install.bat`.

### Run

```bash
python -m olm.server.app
# Open http://localhost:5051
```

On Windows, double-click `launch.bat`.

### Configure

OLM expects a `project/` directory next to the `olm/` package:

```
your-project/
├── olm/                  ← this repository
├── project/
│   ├── config.json       ← settings (desk size, spacing standards, matching weights)
│   ├── catalogue/
│   │   └── patterns.json ← your pattern catalogue
│   ├── plans/            ← floor plan images
│   └── test_rooms.json   ← room definitions for testing
├── requirements.txt
├── install.bat
└── launch.bat
```

If `project/config.json` is absent, OLM starts with generic defaults (no spacing standards loaded — you must define your own).

## Spacing standards

OLM supports multiple spacing standards, each defining 11 parameters:

| Code | Parameter | Description |
|------|-----------|-------------|
| ES-01 | `chair_clearance_cm` | Chair clearance zone |
| ES-02 | `front_access_cm` | Front access (sit/stand) |
| ES-03 | `access_single_desk_cm` | Single desk against wall |
| ES-04 | `passage_behind_one_row_cm` | Clearance behind one row |
| ES-05 | `passage_between_back_to_back_cm` | Between back-to-back rows |
| ES-06 | `passage_cm` | Inter-block passage |
| ES-08 | `door_exclusion_depth_cm` | Clear zone in front of door |
| ES-09 | `desk_to_wall_cm` | Lateral desk-to-wall distance |
| ES-10 | `max_island_size` | Maximum block size (desks) |
| ES-11 | `min_block_separation_cm` | Minimum block separation |
| PS-04 | `main_corridor_cm` | Main corridor width |

Standards are defined in `project/config.json` under the `spacing` key. You can create as many standards as needed.

## Architecture

```
olm/
├── core/                 ← business logic (pure Python)
│   ├── pattern_generator.py    # canonical blocks, geometry, rotations
│   ├── catalogue_matcher.py    # 7-step matching pipeline
│   ├── circulation_analysis.py # Dijkstra circulation grading
│   ├── coverage_analysis.py    # catalogue coverage reporting
│   ├── spacing_config.py       # spacing standard registry
│   ├── room_model.py           # RoomSpec dataclass
│   ├── pattern_dsl.py          # pattern DSL (parse + export)
│   └── room_dsl.py             # room DSL (parse + export)
├── server/
│   └── app.py            ← Flask server + REST API
├── ingestion/
│   └── extract.py        ← raster floor plan extraction (experimental)
├── static/               ← JavaScript modules
├── templates/            ← HTML templates
└── tests/                ← pytest test suite
```

## Dependencies

| Package | Role |
|---------|------|
| `flask` | Web server |
| `numpy` | Computation (circulation grid) |
| `opencv-python` | Image processing (ingestion) |
| `Pillow` | Image I/O (ingestion) |

## Status

**Alpha** — the core matching pipeline works but:

- Limited test coverage on real floor plans
- Ingestion module is experimental (known edge cases with door arcs, OCR)
- UI has structural bugs (shared canvas between views)
- No packaging beyond pip

## License

MIT — see [LICENSE](LICENSE).

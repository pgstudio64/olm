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
git clone https://github.com/pgstudio64/olm.git
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

For detailed usage instructions, see the [User Guide](docs/USER_GUIDE.md).

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

**Quickstart for v0.5.20+**: this release ships a ready-to-use `config.json` at the repo root with three standards pre-defined (AFNOR, Kardham, Site) following the D-229 spacing model (6 parameters per standard). Copy it into your `project/` directory:

```bash
mv config.json project/config.json
```

This bundled file is provided temporarily for migration convenience and may be removed in a future release.

## Spacing standards

OLM supports multiple spacing standards, each defining 6 parameters (D-229 model, v0.5.19+):

| Code | Parameter | Description |
|------|-----------|-------------|
| ES-01 | `chair_clearance_cm` | Chair pushback zone (primitive) |
| ES-02 | `walking_margin_cm` | Walking margin beyond chair (primitive) |
| ES-03 | `slip_in_margin_cm` | Standing margin for isolated desk access (primitive) |
| ES-04 | `main_corridor_cm` | Main corridor width |
| ES-05 | `door_exclusion_depth_cm` | Clear zone in front of door |
| ES-06 | `max_island_size` | Maximum block size (desks) |

The four practical circulation distances are **derived** from these primitives, not stored:

| Derived distance | Formula |
|---|---|
| Access to a single desk | `chair + slip_in` |
| Passage behind one person | `chair + walking` |
| Passage between two persons | `chair + walking + chair` |
| Passage between two desks | `walking` |

Decomposition mirrors AFNOR NF X35-102 figures 7-9. Standards are defined in `project/config.json` under the `standards` key (`standards.<slot>.spacing.<field>`). You can rename, edit, or add standards in the Settings panel.

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

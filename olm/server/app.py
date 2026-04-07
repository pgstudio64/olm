"""Flask server for the pattern management and creation tool.

Entry point: python pattern_server.py → http://localhost:5051
Storage: catalogue/patterns.json
"""
from __future__ import annotations

import json
import logging
import os
import traceback
from io import StringIO

from flask import Flask, jsonify, request, send_from_directory

from olm.core.catalogue_matcher import generate_auto_name, compact_catalogue_names
from olm.core.pattern_dsl import parse_dsl, to_dsl, DSLError
from olm.core.room_dsl import parse_room_dsl, to_room_dsl, RoomDSLError
from olm.core.pattern_generator import (
    DESK_W_CM, DESK_D_CM, CHAIR_CLEARANCE_CM, PASSAGE_CM, PASSAGE_SINGLE_CM,
    BLOCK_1, BLOCK_2_FACE, BLOCK_2_SIDE, BLOCK_3_SIDE, BLOCK_4_FACE, BLOCK_6_FACE,
    BLOCK_2_ORTHO_L, BLOCK_2_ORTHO_R,
)
from olm.core.spacing_config import ALL_CONFIGS

app = Flask(__name__, static_folder=None)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CATALOGUE_DIR = os.path.join(os.path.dirname(BASE_DIR), "project", "catalogue")
CATALOGUE_PATH = os.path.join(CATALOGUE_DIR, "patterns.json")


@app.route("/static/<path:filename>")
def serve_static(filename: str):
    """Serve static files from the static/ folder."""
    return send_from_directory(os.path.join(BASE_DIR, "static"), filename)


def _load_catalogue() -> list[dict]:
    """Load the catalogue from the JSON file."""
    if not os.path.exists(CATALOGUE_PATH):
        return []
    with open(CATALOGUE_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("patterns", [])


def _save_catalogue(patterns: list[dict]) -> None:
    """Save the catalogue to the JSON file."""
    os.makedirs(CATALOGUE_DIR, exist_ok=True)
    with open(CATALOGUE_PATH, "w", encoding="utf-8") as f:
        json.dump({"patterns": patterns}, f, indent=2, ensure_ascii=False)


def _find_pattern(patterns: list[dict], name: str) -> int:
    """Return the pattern index by name, or -1 if not found."""
    for i, p in enumerate(patterns):
        if p["name"] == name:
            return i
    return -1


_BASE_BLOCKS = [BLOCK_1, BLOCK_2_FACE, BLOCK_2_SIDE, BLOCK_3_SIDE, BLOCK_4_FACE, BLOCK_6_FACE,
                BLOCK_2_ORTHO_L, BLOCK_2_ORTHO_R]

# Face-to-face blocks: E/W zones = chair + passage (ES-06)
_FACE_TO_FACE_BLOCKS = {"BLOCK_2_FACE", "BLOCK_4_FACE", "BLOCK_6_FACE"}

# Orthogonal blocks: chair + passage_single zones on the chair faces
_ORTHO_BLOCKS = {
    "BLOCK_2_ORTHO_R": {"north", "east"},   # chairs desk1=N, desk2=E (L bottom-left)
    "BLOCK_2_ORTHO_L": {"north", "west"},   # chairs desk1=N, desk2=W (L bottom-right)
}


# Block dimension formulas: (eo_factor_w, eo_factor_d, ns_factor_w, ns_factor_d)
# eo_cm = fw * DESK_W + fd * DESK_D, ns_cm = gw * DESK_W + gd * DESK_D
# DESK_W = width (180, wide side), DESK_D = depth (80, front-to-back)
_BLOCK_DESK_FACTORS = {
    "BLOCK_1":          (0, 1, 1, 0),   # eo=D,  ns=W
    "BLOCK_2_FACE":     (0, 2, 1, 0),   # eo=2D, ns=W
    "BLOCK_2_SIDE":     (0, 1, 2, 0),   # eo=D,  ns=2W
    "BLOCK_3_SIDE":     (0, 1, 3, 0),   # eo=D,  ns=3W
    "BLOCK_4_FACE":     (0, 2, 2, 0),   # eo=2D, ns=2W
    "BLOCK_6_FACE":     (0, 2, 3, 0),   # eo=2D, ns=3W
    "BLOCK_2_ORTHO_R":  (1, 0, 1, 1),   # eo=W,  ns=W+D
    "BLOCK_2_ORTHO_L":  (1, 0, 1, 1),   # eo=W,  ns=W+D
}


def _block_def_to_json(block) -> dict:
    """Convert a Block to a JSON dict, recomputing dimensions from config."""
    from olm.core.pattern_generator import DESK_W_CM, DESK_D_CM
    factors = _BLOCK_DESK_FACTORS.get(block.name)
    if factors:
        fw, fd, gw, gd = factors
        eo = fw * DESK_W_CM + fd * DESK_D_CM
        ns = gw * DESK_W_CM + gd * DESK_D_CM
    else:
        eo = block.eo_cm
        ns = block.ns_cm
    return {
        "name": block.name,
        "eo_cm": eo,
        "ns_cm": ns,
        "n_desks": block.n_desks,
        "derogatory": block.derogatory,
        "faces": {
            "north": {"non_superposable_cm": block.faces.north.non_superposable_cm,
                       "candidate_cm": block.faces.north.candidate_cm},
            "south": {"non_superposable_cm": block.faces.south.non_superposable_cm,
                       "candidate_cm": block.faces.south.candidate_cm},
            "east":  {"non_superposable_cm": block.faces.east.non_superposable_cm,
                       "candidate_cm": block.faces.east.candidate_cm},
            "west":  {"non_superposable_cm": block.faces.west.non_superposable_cm,
                       "candidate_cm": block.faces.west.candidate_cm},
        },
    }


def _build_block_defs(cfg) -> dict:
    """Build block definitions for a given standard.

    Fixed zones (chair clearance) and circulation zones vary
    according to the layout standard.
    """
    chair = cfg.chair_clearance_cm      # ES-01
    passage = cfg.passage_cm            # ES-06
    passage_single = cfg.access_single_desk_cm - chair  # ES-03 - ES-01

    defs = {}
    for block in _BASE_BLOCKS:
        d = _block_def_to_json(block)
        if block.name in _FACE_TO_FACE_BLOCKS:
            # Face-to-face: E/W = chair + passage
            for face in ("east", "west"):
                d["faces"][face] = {
                    "non_superposable_cm": chair,
                    "candidate_cm": passage,
                }
        elif block.name in _ORTHO_BLOCKS:
            # Ortho: chair + passage_single on the chair faces
            chair_faces = _ORTHO_BLOCKS[block.name]
            for face in ("north", "south", "east", "west"):
                if face in chair_faces:
                    d["faces"][face] = {
                        "non_superposable_cm": chair,
                        "candidate_cm": passage_single,
                    }
                else:
                    d["faces"][face] = {
                        "non_superposable_cm": 0,
                        "candidate_cm": 0,
                    }
        else:
            # Single/side: W = chair + passage_single
            d["faces"]["west"] = {
                "non_superposable_cm": chair,
                "candidate_cm": passage_single,
            }
        defs[block.name] = d
    return defs


# Cache by standard
_BLOCK_DEFS_CACHE: dict[str, dict] = {}


def _get_block_defs(standard_name: str) -> dict:
    """Return block defs for a standard (with cache)."""
    if standard_name not in _BLOCK_DEFS_CACHE:
        cfg = ALL_CONFIGS.get(standard_name)
        if cfg is None:
            from olm.core.spacing_config import get_default
            cfg = get_default()
        _BLOCK_DEFS_CACHE[standard_name] = _build_block_defs(cfg)
    return _BLOCK_DEFS_CACHE[standard_name]


@app.route("/")
def index():
    """Serve the pattern editor page."""
    return send_from_directory(os.path.join(BASE_DIR, "templates"), "pattern_editor.html")


@app.route("/test_rooms.json")
def serve_test_rooms():
    """DEV: serve test_rooms.json from project/ for auto-load."""
    project_dir = os.path.join(os.path.dirname(BASE_DIR), "project")
    path = os.path.join(project_dir, "test_rooms.json")
    if not os.path.exists(path):
        return jsonify({"rooms": []})
    return send_from_directory(project_dir, "test_rooms.json")


@app.route("/test_floor_plan.png")
def serve_test_floor_plan():
    """DEV: serve test floor plan from project/plans/."""
    plans_dir = os.path.join(os.path.dirname(BASE_DIR), "project", "plans")
    # Try available test plans in order of preference
    for name in ("test_floorplan3.png", "test_floorplan.png", "test_floor_plan.png"):
        if os.path.exists(os.path.join(plans_dir, name)):
            return send_from_directory(plans_dir, name)
    return "", 404


@app.route("/api/ingestion/extract", methods=["POST"])
def api_ingestion_extract():
    """Extract rooms from a raster floor plan image.

    Accepts multipart form with:
      - 'image': the floor plan image file
      - 'scale' (optional): cm per pixel (default 0.5)
      - 'threshold' (optional): binarization threshold (default 110)

    Returns JSON with detected rooms (bbox, doors, windows, openings, hits).
    """
    import tempfile
    try:
        # Get image from upload or from a plan path
        plan_path = request.form.get('plan_path', '')
        scale_str = request.form.get('scale', '')
        scale = float(scale_str) if scale_str else None
        threshold = int(request.form.get('threshold', 110))

        if 'image' in request.files:
            f = request.files['image']
            fd, plan_path = tempfile.mkstemp(suffix='.png')
            os.close(fd)
            f.save(plan_path)
        elif plan_path:
            # Resolve relative plan names to project/plans/ directory
            if not os.path.isabs(plan_path):
                plans_dir = os.path.join(
                    os.path.dirname(BASE_DIR), "project", "plans")
                plan_path = os.path.join(plans_dir, plan_path)
            if not os.path.exists(plan_path):
                return jsonify({"error": f"Plan not found: {plan_path}"}), 404
        else:
            return jsonify({"error": "No image provided"}), 400

        import sys
        sys.path.insert(0, os.path.join(BASE_DIR, 'ingestion'))
        from test_comb import extract_all_rooms

        result = extract_all_rooms(plan_path, scale_cm_per_px=scale,
                                   threshold=threshold)

        # Clean up temp file if created
        if 'image' in request.files:
            os.unlink(plan_path)

        return jsonify(result)
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/ingestion/debug", methods=["POST"])
def api_ingestion_debug():
    """Extract rooms with detailed debug logs.

    Same parameters as /api/ingestion/extract, but returns:
    {
      'rooms': [...],
      'image_size': [w, h],
      'scale_cm_per_px': float,
      'threshold': int,
      'logs': ['[INFO] message', '[DEBUG] message', ...]
    }
    """
    import tempfile
    try:
        # Capture logging to a StringIO
        log_capture = StringIO()
        handler = logging.StreamHandler(log_capture)
        handler.setLevel(logging.DEBUG)
        formatter = logging.Formatter('[%(levelname)s] %(message)s')
        handler.setFormatter(formatter)

        # Add handler to all relevant loggers
        ingestion_logger = logging.getLogger('olm.ingestion.test_comb')
        ingestion_logger.addHandler(handler)
        ingestion_logger.setLevel(logging.DEBUG)

        try:
            # Get image from upload or from a plan path
            plan_path = request.form.get('plan_path', '')
            scale_str = request.form.get('scale', '')
            scale = float(scale_str) if scale_str else None
            threshold = int(request.form.get('threshold', 110))

            if 'image' in request.files:
                f = request.files['image']
                fd, plan_path = tempfile.mkstemp(suffix='.png')
                os.close(fd)
                f.save(plan_path)
            elif plan_path:
                # Resolve relative plan names to project/plans/ directory
                if not os.path.isabs(plan_path):
                    plans_dir = os.path.join(
                        os.path.dirname(BASE_DIR), "project", "plans")
                    plan_path = os.path.join(plans_dir, plan_path)
                if not os.path.exists(plan_path):
                    return jsonify({"error": f"Plan not found: {plan_path}"}), 404
            else:
                return jsonify({"error": "No image provided"}), 400

            import sys
            sys.path.insert(0, os.path.join(BASE_DIR, 'ingestion'))
            from test_comb import extract_all_rooms

            result = extract_all_rooms(plan_path, scale_cm_per_px=scale,
                                       threshold=threshold)

            # Clean up temp file if created
            if 'image' in request.files:
                os.unlink(plan_path)

            # Capture logs and add to result
            log_text = log_capture.getvalue()
            logs = [line.strip() for line in log_text.split('\n') if line.strip()]
            result['logs'] = logs

            return jsonify(result)
        finally:
            ingestion_logger.removeHandler(handler)
            handler.close()

    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/ingestion/plans", methods=["GET"])
def api_ingestion_plans():
    """List available plan images in project/plans/."""
    plans_dir = os.path.join(os.path.dirname(BASE_DIR), "project", "plans")
    if not os.path.isdir(plans_dir):
        return jsonify({"plans": []})
    plans = [f for f in os.listdir(plans_dir)
             if f.lower().endswith(('.png', '.jpg', '.jpeg', '.tiff'))]
    return jsonify({"plans": sorted(plans)})


@app.route("/api/ingestion/plan/<filename>")
def api_ingestion_plan_image(filename):
    """Serve a plan image from project/plans/."""
    plans_dir = os.path.join(os.path.dirname(BASE_DIR), "project", "plans")
    return send_from_directory(plans_dir, filename)


@app.route("/api/ingestion/binarize", methods=["POST"])
def api_ingestion_binarize():
    """Return the binarized version of a plan image (for visualization).

    Accepts: plan_path or uploaded image + threshold.
    Returns: PNG image of the binarized plan.
    """
    import io
    from PIL import Image as PILImage
    try:
        plan_path = request.form.get('plan_path', '')
        threshold = int(request.form.get('threshold', 110))

        if 'image' in request.files:
            import tempfile
            f = request.files['image']
            fd, plan_path = tempfile.mkstemp(suffix='.png')
            os.close(fd)
            f.save(plan_path)

        if not plan_path or not os.path.exists(plan_path):
            return jsonify({"error": "No image"}), 400

        import numpy as np
        img = PILImage.open(plan_path).convert("L")
        gray = np.array(img)
        binary = gray < threshold
        bin_img = PILImage.fromarray((~binary * 255).astype(np.uint8))

        buf = io.BytesIO()
        bin_img.save(buf, format='PNG')
        buf.seek(0)

        if 'image' in request.files:
            os.unlink(plan_path)

        from flask import send_file
        return send_file(buf, mimetype='image/png')
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/specs/<path:filename>")
def serve_specs(filename: str):
    """Serve spec files."""
    return send_from_directory(os.path.join(os.path.dirname(BASE_DIR), "docs", "specs"), filename)


@app.route("/matching")
def matching_viewer():
    """Serve the matching viewer page."""
    return send_from_directory(os.path.join(BASE_DIR, "templates"), "matching_viewer.html")


@app.route("/api/blocks", methods=["GET"])
def api_blocks():
    """Return block definitions for the requested standard.

    Query param: ?standard=<name> (defaults to first available standard).
    """
    from olm.core.spacing_config import get_default_name, get_default
    default_name = get_default_name() or ""
    standard = request.args.get("standard", default_name)
    cfg = ALL_CONFIGS.get(standard, get_default())
    block_defs = _get_block_defs(standard)
    import olm.core.pattern_generator as pg
    return jsonify({
        "blocks": block_defs,
        "standard": standard,
        "constants": {
            "DESK_W_CM": pg.DESK_W_CM,
            "DESK_D_CM": pg.DESK_D_CM,
            "CHAIR_CLEARANCE_CM": cfg.chair_clearance_cm,
            "PASSAGE_CM": cfg.passage_cm,
            "PASSAGE_SINGLE_CM": cfg.access_single_desk_cm - cfg.chair_clearance_cm,
        },
    })


@app.route("/api/spacing", methods=["GET", "POST"])
def api_spacing():
    """GET: return the 3 spacing configurations.
    POST: update a standard. Body: {"standard": "SITE", "values": {...}}.
    """
    if request.method == "POST":
        from olm.core.spacing_config import update_config
        from olm.core.spacing_config import update_config, reset_config
        data = request.json
        name = data.get("standard")
        values = data.get("values", {})
        if not name:
            return jsonify({"error": "Required field: standard"}), 400
        try:
            if data.get("reset"):
                updated = reset_config(name)
            else:
                updated = update_config(name, values)
            # Invalidate block defs cache for this standard
            _BLOCK_DEFS_CACHE.pop(name, None)
            return jsonify({"ok": True, "config": updated.to_dict()})
        except Exception as e:
            return jsonify({"error": str(e)}), 400

    configs = {}
    for name, cfg in ALL_CONFIGS.items():
        configs[name] = cfg.to_dict()
    return jsonify(configs)


@app.route("/api/config", methods=["GET"])
def api_config_get():
    """Return the full configuration."""
    from olm.core import app_config
    return jsonify(app_config._cfg)


@app.route("/api/config", methods=["POST"])
def api_config_post():
    """Update configuration keys and persist.

    Body: {"key": "room_code", "value": "15"}
    or:   {"path": ["matching", "w_density"], "value": 0.7}
    """
    from olm.core import app_config
    data = request.json
    if "path" in data:
        app_config.update_nested(data["path"], data["value"])
    elif "key" in data:
        app_config.update(data["key"], data["value"])
    else:
        return jsonify({"error": "Missing 'key' or 'path'"}), 400
    # Invalidate block defs cache when desk dimensions change
    key = data.get("key", "")
    if key in ("desk_width_cm", "desk_depth_cm"):
        import olm.core.pattern_generator as pg
        pg.DESK_W_CM = app_config.get("desk_width_cm", 180)
        pg.DESK_D_CM = app_config.get("desk_depth_cm", 80)
        _BLOCK_DEFS_CACHE.clear()
    return jsonify({"ok": True})


@app.route("/api/patterns", methods=["GET"])
def api_patterns_list():
    """List all patterns in the catalogue."""
    patterns = _load_catalogue()
    return jsonify({"patterns": patterns, "count": len(patterns)})


@app.route("/api/catalogue/export", methods=["GET"])
def api_catalogue_export():
    """Export the full catalogue as JSON (download)."""
    patterns = _load_catalogue()
    response = jsonify({"patterns": patterns})
    response.headers["Content-Disposition"] = "attachment; filename=patterns.json"
    response.headers["Content-Type"] = "application/json"
    return response


@app.route("/api/catalogue/import", methods=["POST"])
def api_catalogue_import():
    """Import patterns into the catalogue (merge).

    JSON body: {"patterns": [...]} in catalogue format.
    Imported patterns are appended. Name conflicts are resolved by
    automatic renumbering (compact names).
    """
    try:
        data = request.json
        if not data or "patterns" not in data:
            return jsonify({"error": "Required field: patterns"}), 400

        imported = data["patterns"]
        if not isinstance(imported, list):
            return jsonify({"error": "patterns must be a list"}), 400

        # Minimal schema validation
        required_fields = {"rows", "room_width_cm", "room_depth_cm", "standard"}
        for i, p in enumerate(imported):
            missing = required_fields - set(p.keys())
            if missing:
                return jsonify({
                    "error": f"Pattern #{i}: missing fields: {missing}",
                }), 400

        catalogue = _load_catalogue()
        n_before = len(catalogue)

        # Merge: append imported patterns
        for p in imported:
            catalogue.append(p)

        # Compact names (renumber) — resolves name conflicts
        compact_catalogue_names(catalogue)
        _save_catalogue(catalogue)

        n_added = len(catalogue) - n_before
        return jsonify({
            "ok": True,
            "imported": n_added,
            "total": len(catalogue),
        })
    except Exception as e:
        return jsonify({"error": str(e), "trace": traceback.format_exc()}), 500


@app.route("/api/patterns", methods=["POST"])
def api_patterns_create():
    """Create or update a pattern.

    JSON body: a pattern in PATTERN_DSL_SPEC.md format.
    If a pattern with the same name exists, it is replaced.
    If auto_name=true in the body, the name is auto-generated.
    After each save, name increments are compacted by group.
    """
    try:
        data = request.json
        if not data or "rows" not in data:
            return jsonify({"error": "Required field: rows"}), 400

        patterns = _load_catalogue()

        # Auto-name if requested or if no name provided
        auto_name = data.pop("auto_name", False)
        if auto_name or "name" not in data:
            data["name"] = generate_auto_name(data, patterns)

        idx = _find_pattern(patterns, data["name"])
        if idx >= 0:
            patterns[idx] = data
        else:
            patterns.append(data)

        # Compact name increments by group
        compact_catalogue_names(patterns)

        _save_catalogue(patterns)
        return jsonify({"ok": True, "name": data["name"], "count": len(patterns)})
    except Exception as e:
        return jsonify({"error": str(e), "trace": traceback.format_exc()}), 500


@app.route("/api/patterns/<name>", methods=["GET"])
def api_pattern_get(name: str):
    """Return a pattern by name."""
    patterns = _load_catalogue()
    idx = _find_pattern(patterns, name)
    if idx < 0:
        return jsonify({"error": f"Pattern not found: {name}"}), 404
    return jsonify(patterns[idx])


@app.route("/api/patterns/<name>", methods=["DELETE"])
def api_pattern_delete(name: str):
    """Delete a pattern by name and compact name increments."""
    patterns = _load_catalogue()
    idx = _find_pattern(patterns, name)
    if idx < 0:
        return jsonify({"error": f"Pattern not found: {name}"}), 404
    patterns.pop(idx)
    compact_catalogue_names(patterns)
    _save_catalogue(patterns)
    return jsonify({"ok": True, "name": name, "count": len(patterns)})


@app.route("/api/patterns/<name>/duplicate", methods=["POST"])
def api_pattern_duplicate(name: str):
    """Duplicate a pattern with a new name.

    Optional JSON body: {"new_name": "P_COPY"}.
    If absent, _copy suffix is added.
    """
    try:
        patterns = _load_catalogue()
        idx = _find_pattern(patterns, name)
        if idx < 0:
            return jsonify({"error": f"Pattern not found: {name}"}), 404

        data = request.json or {}
        new_name = data.get("new_name", name + "_copy")
        if _find_pattern(patterns, new_name) >= 0:
            return jsonify({"error": f"Name already in use: {new_name}"}), 409

        import copy
        new_pattern = copy.deepcopy(patterns[idx])
        new_pattern["name"] = new_name
        patterns.append(new_pattern)
        _save_catalogue(patterns)
        return jsonify({"ok": True, "name": new_name, "count": len(patterns)})
    except Exception as e:
        return jsonify({"error": str(e), "trace": traceback.format_exc()}), 500


@app.route("/api/dsl/parse", methods=["POST"])
def api_dsl_parse():
    """Parse DSL text to JSON.

    JSON body: {"dsl": "P_B4: BLOCK_4_FACE, 180, BLOCK_2_FACE"}
    """
    try:
        data = request.json
        if not data or "dsl" not in data:
            return jsonify({"error": "Required field: dsl"}), 400
        result = parse_dsl(data["dsl"])
        return jsonify(result)
    except DSLError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e), "trace": traceback.format_exc()}), 500


@app.route("/api/dsl/export", methods=["POST"])
def api_dsl_export():
    """Export a JSON pattern to DSL text.

    JSON body: a pattern in PATTERN_DSL_SPEC.md format.
    """
    try:
        data = request.json
        if not data or "name" not in data:
            return jsonify({"error": "Required field: name"}), 400
        dsl_text = to_dsl(data)
        return jsonify({"dsl": dsl_text})
    except Exception as e:
        return jsonify({"error": str(e), "trace": traceback.format_exc()}), 500


@app.route("/api/room-dsl/parse", methods=["POST"])
def api_room_dsl_parse():
    """Parse room DSL text to JSON.

    JSON body: {"dsl": "ROOM 300x480\\nWINDOW N 0 300\\nDOOR S 0 90 INT L"}
    Returns parsed fields for updating the editor.
    """
    try:
        data = request.json
        if not data or "dsl" not in data:
            return jsonify({"error": "Required field: dsl"}), 400
        room = parse_room_dsl(data["dsl"])
        return jsonify({
            "width_cm": room.width_cm,
            "depth_cm": room.depth_cm,
            "windows": [
                {"face": w.face.value, "offset_cm": w.offset_cm,
                 "width_cm": w.width_cm}
                for w in room.windows
            ],
            "openings": [
                {"face": o.face.value, "offset_cm": o.offset_cm,
                 "width_cm": o.width_cm, "has_door": o.has_door,
                 "opens_inward": o.opens_inward,
                 "hinge_side": o.hinge_side.value}
                for o in room.openings
            ],
            "exclusion_zones": [
                {"x_cm": z.x_cm, "y_cm": z.y_cm,
                 "width_cm": z.width_cm, "depth_cm": z.depth_cm}
                for z in room.exclusion_zones
            ],
        })
    except RoomDSLError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e), "trace": traceback.format_exc()}), 500


MOCK_ROOM = {
    "eo_cm": 300,
    "ns_cm": 480,
    "doors": [{"wall": "south", "position_cm": 0, "width_cm": 90, "swing": "right"}],
    "windows": [{"wall": "north", "position_cm": 0, "width_cm": 300}],
    "obstacles": [],
}


def _pattern_emprise_eo(pattern: dict) -> float:
    """Compute the EO footprint (width) of the first row of a pattern."""
    rows = pattern.get("rows", [])
    if not rows:
        return 0.0
    total = 0.0
    for block in rows[0].get("blocks", []):
        total += block.get("gap_cm", 0)
        btype = block.get("type", "")
        orient = block.get("orientation", 0)
        bdef = BLOCK_DEFS.get(btype, {})
        eo = bdef.get("eo_cm", 0)
        ns = bdef.get("ns_cm", 0)
        if orient in (90, 270):
            total += ns
        else:
            total += eo
    return total


def _pattern_total_desks(pattern: dict) -> int:
    """Count the total number of desks in a pattern."""
    total = 0
    for row in pattern.get("rows", []):
        for block in row.get("blocks", []):
            bdef = BLOCK_DEFS.get(block.get("type", ""), {})
            total += bdef.get("n_desks", 0)
    return total


@app.route("/api/mock-candidates", methods=["GET"])
def api_mock_candidates():
    """Generate mock candidate solutions for the reference room."""
    patterns = _load_catalogue()
    candidates = []
    cid = 1
    room_eo = MOCK_ROOM["eo_cm"]

    for pattern in patterns:
        emprise = _pattern_emprise_eo(pattern)
        desks = _pattern_total_desks(pattern)
        rows_copy = pattern.get("rows", [])
        gaps_copy = pattern.get("row_gaps_cm", [])

        anchors = [
            {"anchor_x_cm": 0, "anchor_y_cm": 0},
            {"anchor_x_cm": max(0.0, (room_eo - emprise) / 2.0), "anchor_y_cm": 50},
            {"anchor_x_cm": max(0.0, room_eo - emprise), "anchor_y_cm": 0},
        ]
        for anchor in anchors:
            candidates.append({
                "id": cid,
                "label": "Sol. " + str(cid),
                "pattern_name": pattern["name"],
                "anchor_x_cm": round(anchor["anchor_x_cm"], 1),
                "anchor_y_cm": anchor["anchor_y_cm"],
                "rotation": 0,
                "desks": desks,
                "score": None,
                "sqm_per_desk": None,
                "circulation_grade": None,
                "rows": rows_copy,
                "row_gaps_cm": gaps_copy,
            })
            cid += 1

    return jsonify({"room": MOCK_ROOM, "candidates": candidates, "pipelineStep": 0})


@app.route("/api/match", methods=["GET"])
def api_match():
    """Deprecated matching endpoint. Redirects to /api/floor-plan/match."""
    return jsonify({"error": "Deprecated. Use POST /api/floor-plan/match instead."}), 410


@app.route("/api/floor-plan/match", methods=["POST"])
def api_floor_plan_match():
    """Run catalogue matching on a set of rooms for the floor plan viewer.

    JSON body: {"rooms": [...]} in load_rooms_json format.
    Returns matching results per room with all scored candidates.
    """
    try:
        from olm.core.catalogue_matcher import (
            match_room, select_candidates, generate_mirrors,
            adapt_to_room, remove_conflicting_desks, score_candidate,
            compute_desk_positions, count_desks,
        )
        from olm.core.room_model import (
            ExclusionZone, Face, HingeSide, OpeningSpec, RoomSpec, WindowSpec,
        )

        data = request.json
        if not data or "rooms" not in data:
            return jsonify({"error": "Required field: rooms"}), 400

        catalogue = _load_catalogue()
        results = []

        for r in data["rooms"]:
            windows = [
                WindowSpec(Face(w["face"]), w["offset_cm"], w["width_cm"])
                for w in r.get("windows", [])
            ]
            openings = [
                OpeningSpec(
                    Face(o["face"]), o["offset_cm"],
                    o.get("width_cm", 90),
                    o.get("has_door", True),
                    o.get("opens_inward", True),
                    HingeSide(o.get("hinge_side", "left")),
                )
                for o in r.get("openings", [])
            ]
            exclusions = [
                ExclusionZone(
                    z["x_cm"], z["y_cm"], z["width_cm"], z["depth_cm"],
                )
                for z in r.get("exclusion_zones", [])
            ]
            room = RoomSpec(
                width_cm=r["width_cm"], depth_cm=r["depth_cm"],
                windows=windows, openings=openings,
                exclusion_zones=exclusions, name=r.get("name", ""),
            )

            match_result = match_room(catalogue, room)

            # Build the response for this room
            room_result = {
                "name": room.name,
                "width_cm": room.width_cm,
                "depth_cm": room.depth_cm,
                "windows": [
                    {"face": w.face.value, "offset_cm": w.offset_cm,
                     "width_cm": w.width_cm}
                    for w in room.windows
                ],
                "openings": [
                    {"face": o.face.value, "offset_cm": o.offset_cm,
                     "width_cm": o.width_cm, "has_door": o.has_door,
                     "opens_inward": o.opens_inward,
                     "hinge_side": o.hinge_side.value}
                    for o in room.openings
                ],
                "exclusion_zones": [
                    {"x_cm": z.x_cm, "y_cm": z.y_cm,
                     "width_cm": z.width_cm, "depth_cm": z.depth_cm}
                    for z in room.exclusion_zones
                ],
                "by_standard": {},
                "all_candidates": [],
            }

            for score in match_result.all_scores:
                # Compute desk positions for rendering
                desks = compute_desk_positions(score.adapted_pattern)
                removed_set = set()
                for rd in score.adapted_pattern.get("_removed_desks", []):
                    removed_set.add((rd["row"], rd["block"], rd["desk"]))

                desk_list = [
                    {
                        "x_cm": d.x_cm, "y_cm": d.y_cm,
                        "width_cm": d.width_cm, "depth_cm": d.depth_cm,
                        "removed": (d.row_idx, d.block_idx, d.desk_idx)
                                   in removed_set,
                    }
                    for d in desks
                ]

                candidate = {
                    "pattern_name": score.pattern_name,
                    "standard": score.standard,
                    "n_desks": score.n_desks,
                    "m2_per_desk": score.m2_per_desk,
                    "circulation_grade": score.circulation_grade,
                    "connectivity_pct": score.connectivity_pct,
                    "min_passage_cm": score.min_passage_cm,
                    "worst_detour": score.worst_detour,
                    "largest_free_rect_m2": score.largest_free_rect_m2,
                    "desks": desk_list,
                    "pattern": score.adapted_pattern,
                }
                room_result["all_candidates"].append(candidate)

            for std, best in match_result.by_standard.items():
                if best:
                    room_result["by_standard"][std] = best.pattern_name
                else:
                    room_result["by_standard"][std] = None

            results.append(room_result)

        return jsonify({"rooms": results})

    except Exception as e:
        return jsonify({"error": str(e), "trace": traceback.format_exc()}), 500


@app.route("/api/coverage", methods=["POST"])
def api_coverage():
    """Catalogue coverage analysis on a set of rooms.

    JSON body: {"rooms": [...]} in load_rooms_json format.
    Returns the coverage report with backlog.
    """
    try:
        from olm.core.coverage_analysis import (
            analyse_coverage, load_rooms_json, report_to_dict,
        )
        from olm.core.room_model import (
            ExclusionZone, Face, HingeSide, OpeningSpec, RoomSpec, WindowSpec,
        )

        data = request.json
        if not data or "rooms" not in data:
            return jsonify({"error": "Required field: rooms"}), 400

        # Build RoomSpec objects from JSON
        rooms = []
        for r in data["rooms"]:
            windows = [
                WindowSpec(
                    face=Face(w["face"]),
                    offset_cm=w["offset_cm"],
                    width_cm=w["width_cm"],
                )
                for w in r.get("windows", [])
            ]
            openings = [
                OpeningSpec(
                    face=Face(o["face"]),
                    offset_cm=o["offset_cm"],
                    width_cm=o.get("width_cm", 90),
                    has_door=o.get("has_door", True),
                    opens_inward=o.get("opens_inward", True),
                    hinge_side=HingeSide(o.get("hinge_side", "left")),
                )
                for o in r.get("openings", [])
            ]
            exclusions = [
                ExclusionZone(
                    x_cm=z["x_cm"], y_cm=z["y_cm"],
                    width_cm=z["width_cm"], depth_cm=z["depth_cm"],
                )
                for z in r.get("exclusion_zones", [])
            ]
            rooms.append(RoomSpec(
                width_cm=r["width_cm"],
                depth_cm=r["depth_cm"],
                windows=windows,
                openings=openings,
                exclusion_zones=exclusions,
                name=r.get("name", ""),
            ))

        catalogue = _load_catalogue()
        report = analyse_coverage(rooms, catalogue)
        return jsonify(report_to_dict(report))

    except Exception as e:
        return jsonify({"error": str(e), "trace": traceback.format_exc()}), 500


if __name__ == "__main__":
    print("Pattern editor — http://localhost:5051")
    print(f"Catalogue: {CATALOGUE_PATH}")
    app.run(debug=True, port=5051)

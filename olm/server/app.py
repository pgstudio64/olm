"""Flask server for the pattern management and creation tool.

Entry point: python -m olm.server.app [--dev]
Routes only — all business logic is delegated to olm.server.services.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import tempfile

DEV_MODE: bool = False

from flask import Flask, jsonify, request, send_file, send_from_directory

from olm.core.pattern_dsl import DSLError
from olm.core.room_dsl import RoomDSLError
from olm.server.services.config_service import (
    BASE_DIR, PROJECT_ROOT, get_plans_dir,
)

logger = logging.getLogger(__name__)

app = Flask(
    __name__,
    static_folder=None,
    template_folder=os.path.join(BASE_DIR, "templates"),
)
PLANS_DIR = get_plans_dir()


# ===================================================================
# A — Static & pages
# ===================================================================


@app.route("/static/<path:filename>")
def serve_static(filename: str):
    """Serve static files from the static/ folder."""
    return send_from_directory(os.path.join(BASE_DIR, "static"), filename)


@app.route("/")
def index():
    """Serve the pattern editor page with cache-bust version."""
    from flask import render_template
    import time
    from olm import __version__
    return render_template("pattern_editor.html",
                           v=__version__ + '.' + str(int(time.time())))


@app.route("/test_rooms.json")
def serve_test_rooms():
    """DEV: serve test_rooms.json from project/ for auto-load."""
    project_dir = os.path.join(PROJECT_ROOT, "project")
    path = os.path.join(project_dir, "test_rooms.json")
    if not os.path.exists(path):
        return "", 404
    return send_from_directory(project_dir, "test_rooms.json")


@app.route("/test_floor_plan.png")
def serve_test_floor_plan():
    """DEV: serve test floor plan from project/plans/."""
    plans_dir = get_plans_dir()
    for name in ("test_floorplan3.png", "test_floorplan.png",
                 "test_floor_plan.png"):
        if os.path.exists(os.path.join(plans_dir, name)):
            return send_from_directory(plans_dir, name)
    return "", 404


@app.route("/api/image")
def api_serve_image():
    """Serve a plan/overlay PNG from allowed directories only."""
    path = request.args.get("path", "")
    if not path or not os.path.isfile(path):
        return jsonify({"error": "File not found"}), 404
    real = os.path.realpath(path)
    allowed = [
        os.path.realpath(
            os.path.join(tempfile.gettempdir(), "olm_overlays")),
        os.path.realpath(PLANS_DIR),
    ]
    if not any(real.startswith(d + os.sep) or real == d for d in allowed):
        return jsonify({"error": "Access denied"}), 403
    return send_file(real, mimetype="image/png")


@app.route("/specs/<path:filename>")
def serve_specs(filename: str):
    """Serve spec files."""
    return send_from_directory(
        os.path.join(PROJECT_ROOT, "docs", "specs"), filename)


# ===================================================================
# B — Plans & ingestion
# ===================================================================


@app.route("/api/plans", methods=["GET"])
def api_plans():
    """List available plans (grouped by stem)."""
    from olm.server.services.ingestion_service import list_plans
    return jsonify(list_plans())


@app.route("/api/ingestion/plans", methods=["GET"])
def api_ingestion_plans():
    """List available plan images in project/plans/."""
    from olm.server.services.ingestion_service import list_ingestion_plans
    return jsonify(list_ingestion_plans())


@app.route("/api/ingestion/plan/<filename>")
def api_ingestion_plan_image(filename):
    """Serve a plan image from project/plans/."""
    return send_from_directory(get_plans_dir(), filename)


@app.route("/api/plans/<plan_id>/metadata")
def api_plan_metadata(plan_id):
    """Return lightweight metadata from the plan JSON."""
    from olm.server.services.ingestion_service import get_plan_metadata
    try:
        return jsonify(get_plan_metadata(plan_id))
    except FileNotFoundError:
        return jsonify({"error": "JSON not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/plans/<plan_id>/save", methods=["POST"])
def api_plan_save(plan_id):
    """Save the full plan JSON to disk."""
    from olm.server.services.ingestion_service import save_plan
    try:
        return jsonify(save_plan(plan_id, request.json))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.exception("plan save failed")
        return jsonify({"error": str(e)}), 500


@app.route("/api/plans/<plan_id>/reinit", methods=["POST"])
def api_plan_reinit(plan_id):
    """Strip a plan JSON to preprocessing-only data and save."""
    from olm.server.services.ingestion_service import reinit_plan
    try:
        return jsonify(reinit_plan(plan_id))
    except FileNotFoundError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.exception("plan reinit failed")
        return jsonify({"error": str(e)}), 500


def _resolve_plan_upload() -> tuple[str, bool]:
    """Resolve plan path from form upload or plan_path field.

    Returns:
        (plan_path, is_temp) — is_temp True if file was uploaded to a
        temp location and must be cleaned up by the caller.

    Raises:
        ValueError: if no image source is provided.
        FileNotFoundError: if plan_path does not exist.
    """
    plan_path = request.form.get('plan_path', '')
    if 'image' in request.files:
        f = request.files['image']
        fd, plan_path = tempfile.mkstemp(suffix='.png')
        os.close(fd)
        f.save(plan_path)
        return plan_path, True
    if plan_path:
        if not os.path.isabs(plan_path):
            plan_path = os.path.join(get_plans_dir(), plan_path)
        if not os.path.exists(plan_path):
            raise FileNotFoundError(f"Plan not found: {plan_path}")
        return plan_path, False
    raise ValueError("No image provided")


@app.route("/api/ingestion/extract", methods=["POST"])
def api_ingestion_extract():
    """Extract rooms from a raster floor plan image."""
    from olm.server.services.ingestion_service import extract_rooms
    from olm.server.services.config_service import get_default_threshold
    try:
        plan_path, is_temp = _resolve_plan_upload()
        scale_str = request.form.get('scale', '')
        scale = float(scale_str) if scale_str else None
        threshold = int(
            request.form.get('threshold', get_default_threshold()))
        result = extract_rooms(plan_path, scale, threshold)
        if is_temp:
            os.unlink(plan_path)
        return jsonify(result)
    except FileNotFoundError as e:
        return jsonify({"error": str(e)}), 404
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.exception("ingestion extract failed")
        return jsonify({"error": str(e)}), 500


@app.route("/api/ingestion/debug", methods=["POST"])
def api_ingestion_debug():
    """Extract rooms with detailed debug logs."""
    from olm.server.services.ingestion_service import extract_rooms_debug
    from olm.server.services.config_service import get_default_threshold
    try:
        plan_path, is_temp = _resolve_plan_upload()
        scale_str = request.form.get('scale', '')
        scale = float(scale_str) if scale_str else None
        threshold = int(
            request.form.get('threshold', get_default_threshold()))
        result = extract_rooms_debug(plan_path, scale, threshold)
        if is_temp:
            os.unlink(plan_path)
        return jsonify(result)
    except FileNotFoundError as e:
        return jsonify({"error": str(e)}), 404
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.exception("ingestion debug failed")
        return jsonify({"error": str(e)}), 500


@app.route("/api/ingestion/binarize", methods=["POST"])
def api_ingestion_binarize():
    """Return the binarized version of a plan image."""
    from olm.server.services.ingestion_service import binarize_image
    from olm.server.services.config_service import get_default_threshold
    try:
        plan_path, is_temp = _resolve_plan_upload()
        threshold = int(
            request.form.get('threshold', get_default_threshold()))
        buf = binarize_image(plan_path, threshold)
        if is_temp:
            os.unlink(plan_path)
        return send_file(buf, mimetype='image/png')
    except (FileNotFoundError, ValueError) as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.exception("binarize failed")
        return jsonify({"error": str(e)}), 500


@app.route("/api/import/ocr", methods=["POST"])
def api_import_ocr():
    """Mode OCR: upload image (PNG/JPEG/PDF)."""
    from olm.server.services.ingestion_service import (
        import_ocr, cleanup_old_overlays, drawing_scale_to_cm_per_px,
        resolve_plan_id_image,
    )
    from olm.server.services.config_service import (
        get_default_threshold, load_project_config,
    )
    cleanup_old_overlays()
    _ing_cfg = load_project_config().get("ingestion", {})
    _pdf_render_dpi: int = int(_ing_cfg.get("pdf_render_dpi", 200))
    try:
        drawing_scale_str = request.form.get("drawing_scale", "").strip()
        render_dpi = int(request.form.get("render_dpi") or 300)
        scale: float | None = None
        if drawing_scale_str:
            scale = drawing_scale_to_cm_per_px(
                drawing_scale_str, render_dpi)
        if scale is None:
            s = request.form.get("scale_cm_per_px", "")
            scale = float(s) if s else None
        threshold = int(
            request.form.get("threshold") or get_default_threshold())
        plan_id = request.form.get("plan_id", "").strip()
        use_temp = False
        if plan_id:
            plan_path = resolve_plan_id_image(plan_id)
        elif "floorplan_image" in request.files:
            f = request.files["floorplan_image"]
            fn = (f.filename or "").lower()
            is_pdf = fn.endswith(".pdf") or f.mimetype == "application/pdf"
            use_temp = True
            if is_pdf:
                import fitz  # type: ignore[import]
                doc = fitz.open(stream=f.read(), filetype="pdf")
                pix = doc[0].get_pixmap(dpi=_pdf_render_dpi)
                fd, plan_path = tempfile.mkstemp(suffix=".png")
                os.close(fd)
                pix.save(plan_path)
            else:
                fd, plan_path = tempfile.mkstemp(suffix=".png")
                os.close(fd)
                f.save(plan_path)
        else:
            return jsonify({"error": "plan_id ou floorplan_image requis"}), 400
        return jsonify(import_ocr(plan_path, scale, threshold, use_temp))
    except FileNotFoundError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.exception("import OCR failed")
        return jsonify({"error": str(e)}), 500


@app.route("/api/import/preprocessed", methods=["POST"])
def api_import_preprocessed():
    """Mode Preprocessed: import from plan_id or uploaded files."""
    from olm.server.services.ingestion_service import (
        import_preprocessed, resolve_preprocessed_files,
    )
    _temp_paths: list[str] = []
    try:
        plan_id = request.form.get("plan_id", "").strip()
        if plan_id:
            json_data, enhanced_path, overlay_path = (
                resolve_preprocessed_files(plan_id))
        else:
            json_data = None
            if "rooms_json" in request.files:
                raw = request.files["rooms_json"].read().decode("utf-8")
                json_data = json.loads(raw)
            elif "rooms_json" in request.form:
                json_data = json.loads(request.form["rooms_json"])
            else:
                return jsonify({"error": "rooms_json manquant"}), 400
            for field in ("enhanced_png", "overlay_png"):
                if field not in request.files:
                    return jsonify({"error": f"{field} manquant"}), 400
            fd, enhanced_path = tempfile.mkstemp(suffix="_enhanced.png")
            os.close(fd)
            request.files["enhanced_png"].save(enhanced_path)
            _temp_paths.append(enhanced_path)
            fd, overlay_path = tempfile.mkstemp(suffix="_overlay.png")
            os.close(fd)
            request.files["overlay_png"].save(overlay_path)
            _temp_paths.append(overlay_path)
        result = import_preprocessed(
            json_data, enhanced_path, overlay_path,
            drawing_scale_str=request.form.get(
                "drawing_scale", "").strip(),
            render_dpi_form=int(request.form.get("render_dpi") or 0)
            or None,
            scale_source=request.form.get("scale_source", "").strip(),
            window_mode=request.form.get("window_mode", "simple"),
        )
        return jsonify(result)
    except (json.JSONDecodeError, ValueError, FileNotFoundError) as e:
        for p in _temp_paths:
            if p and os.path.exists(p):
                os.unlink(p)
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.exception("import preprocessed failed")
        for p in _temp_paths:
            if p and os.path.exists(p):
                os.unlink(p)
        return jsonify({"error": str(e)}), 500


# ===================================================================
# C — Rooms
# ===================================================================


@app.route("/api/room/reanalyze", methods=["POST"])
def api_room_reanalyze():
    """Re-analyze windows and openings for a single room."""
    from olm.server.services.ingestion_service import reanalyze_room
    try:
        return jsonify(reanalyze_room(request.json or {}))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.exception("room reanalyze failed")
        return jsonify({"error": str(e)}), 500


@app.route("/api/room/reanalyze_batch", methods=["POST"])
def api_room_reanalyze_batch():
    """Batch re-analyze N rooms sharing image load."""
    from olm.server.services.ingestion_service import reanalyze_batch
    try:
        return jsonify(reanalyze_batch(request.json or {}))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.exception("batch reanalyze failed")
        return jsonify({"error": str(e)}), 500


@app.route("/api/debug/room-diagnostic", methods=["POST"])
def api_debug_room_diagnostic():
    """Diagnostic: re-runs detection with full debug info."""
    from olm.server.services.ingestion_service import room_diagnostic
    try:
        return jsonify(room_diagnostic(request.json or {}))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.exception("room diagnostic failed")
        return jsonify({"error": str(e)}), 500


@app.route("/api/room/orientation-check", methods=["POST"])
def api_room_orientation_check():
    """Check canonical orientation of a single room."""
    from olm.server.services.ingestion_service import orientation_check
    try:
        return jsonify(orientation_check(request.json or {}))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.exception("orientation check failed")
        return jsonify({"error": str(e)}), 500


@app.route("/api/floor-plan/orientation-report", methods=["POST"])
def api_floor_plan_orientation_report():
    """Batch orientation report for all rooms in a plan."""
    from olm.server.services.ingestion_service import orientation_report
    try:
        return jsonify(orientation_report(request.json or {}))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.exception("orientation report failed")
        return jsonify({"error": str(e)}), 500


@app.route("/api/room-dsl/parse", methods=["POST"])
def api_room_dsl_parse():
    """Parse room DSL text to JSON."""
    from olm.server.services.catalogue_service import room_dsl_parse
    data = request.json
    if not data or "dsl" not in data:
        return jsonify({"error": "Required field: dsl"}), 400
    try:
        return jsonify(room_dsl_parse(data["dsl"]))
    except RoomDSLError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.exception("Room DSL parse failed")
        return jsonify({"error": str(e)}), 500


# ===================================================================
# D — Catalogue
# ===================================================================


@app.route("/api/patterns", methods=["GET"])
def api_patterns_list():
    """List all patterns in the catalogue."""
    from olm.server.services.catalogue_service import list_patterns
    return jsonify(list_patterns())


@app.route("/api/catalogue/export", methods=["GET"])
def api_catalogue_export():
    """Export the full catalogue as JSON (download)."""
    from olm.server.services.catalogue_service import export_catalogue
    response = jsonify(export_catalogue())
    response.headers["Content-Disposition"] = (
        "attachment; filename=patterns.json")
    response.headers["Content-Type"] = "application/json"
    return response


@app.route("/api/catalogue/import", methods=["POST"])
def api_catalogue_import():
    """Import patterns into the catalogue (merge)."""
    from olm.server.services.catalogue_service import import_catalogue
    try:
        return jsonify(import_catalogue(request.json))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.exception("catalogue import failed")
        return jsonify({"error": str(e)}), 500


@app.route("/api/patterns", methods=["POST"])
def api_patterns_create():
    """Create or update a pattern."""
    from olm.server.services.catalogue_service import create_pattern
    try:
        return jsonify(create_pattern(request.json))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.exception("pattern create failed")
        return jsonify({"error": str(e)}), 500


@app.route("/api/patterns/<name>", methods=["GET"])
def api_pattern_get(name: str):
    """Return a pattern by name."""
    from olm.server.services.catalogue_service import get_pattern
    result = get_pattern(name)
    if result is None:
        return jsonify({"error": f"Pattern not found: {name}"}), 404
    return jsonify(result)


@app.route("/api/patterns/<name>", methods=["DELETE"])
def api_pattern_delete(name: str):
    """Delete a pattern by name."""
    from olm.server.services.catalogue_service import delete_pattern
    result = delete_pattern(name)
    if result is None:
        return jsonify({"error": f"Pattern not found: {name}"}), 404
    return jsonify(result)


@app.route("/api/patterns/<name>/duplicate", methods=["POST"])
def api_pattern_duplicate(name: str):
    """Duplicate a pattern with a new name."""
    from olm.server.services.catalogue_service import duplicate_pattern
    data = request.json or {}
    try:
        return jsonify(duplicate_pattern(name, data.get("new_name")))
    except KeyError as e:
        return jsonify({"error": str(e)}), 404
    except ValueError as e:
        return jsonify({"error": str(e)}), 409
    except Exception as e:
        logger.exception("pattern duplicate failed")
        return jsonify({"error": str(e)}), 500


@app.route("/api/dsl/parse", methods=["POST"])
def api_dsl_parse():
    """Parse DSL text to JSON."""
    from olm.server.services.catalogue_service import dsl_parse
    data = request.json
    if not data or "dsl" not in data:
        return jsonify({"error": "Required field: dsl"}), 400
    try:
        return jsonify(dsl_parse(data["dsl"]))
    except DSLError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.exception("DSL parse failed")
        return jsonify({"error": str(e)}), 500


@app.route("/api/dsl/export", methods=["POST"])
def api_dsl_export():
    """Export a JSON pattern to DSL text."""
    from olm.server.services.catalogue_service import dsl_export
    try:
        return jsonify(dsl_export(request.json))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.exception("DSL export failed")
        return jsonify({"error": str(e)}), 500


# ===================================================================
# E — Matching
# ===================================================================


@app.route("/api/mock-candidates", methods=["GET"])
def api_mock_candidates():
    """Generate mock candidate solutions for the reference room."""
    from olm.server.services.matching_service import get_mock_candidates
    return jsonify(get_mock_candidates())


@app.route("/api/match", methods=["GET"])
def api_match():
    """Deprecated matching endpoint."""
    return jsonify({
        "error": "Deprecated. Use POST /api/floor-plan/match instead.",
    }), 410


@app.route("/api/floor-plan/match", methods=["POST"])
def api_floor_plan_match():
    """Run catalogue matching on rooms (canonical coordinates)."""
    from olm.server.services.matching_service import floor_plan_match
    try:
        return jsonify(floor_plan_match(request.json))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.exception("floor-plan match failed")
        return jsonify({"error": str(e)}), 500


@app.route("/api/coverage", methods=["POST"])
def api_coverage():
    """Catalogue coverage analysis on a set of rooms."""
    from olm.server.services.matching_service import coverage_report
    try:
        return jsonify(coverage_report(request.json))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.exception("coverage analysis failed")
        return jsonify({"error": str(e)}), 500


# ===================================================================
# F — Configuration
# ===================================================================


@app.route("/api/blocks", methods=["GET"])
def api_blocks():
    """Return block definitions for the requested standard."""
    from olm.server.services.config_service import get_blocks
    standard = request.args.get("standard")
    return jsonify(get_blocks(standard))


@app.route("/api/spacing", methods=["GET", "POST"])
def api_spacing():
    """GET: return spacing configs. POST: update a standard."""
    from olm.server.services.config_service import (
        get_spacing, update_spacing,
    )
    if request.method == "POST":
        try:
            return jsonify(update_spacing(request.json))
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            return jsonify({"error": str(e)}), 400
    return jsonify(get_spacing())


@app.route("/api/config", methods=["GET"])
def api_config_get():
    """Return the full configuration (+ OLM version + dev_mode)."""
    from olm.server.services.config_service import get_config
    return jsonify(get_config())


@app.route("/api/config", methods=["POST"])
def api_config_post():
    """Update configuration keys and persist."""
    from olm.server.services.config_service import update_config
    try:
        return jsonify(update_config(request.json))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


# ===================================================================
# Main
# ===================================================================


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="OLM server")
    parser.add_argument("--dev", action="store_true",
                        help="Enable developer mode (shows debug tools)")
    args = parser.parse_args()
    DEV_MODE = args.dev
    mode_label = " [DEV]" if DEV_MODE else ""
    from olm.server.services.catalogue_service import CATALOGUE_PATH
    print(f"Pattern editor{mode_label} — http://localhost:5051")
    print(f"Catalogue: {CATALOGUE_PATH}")
    app.run(debug=True, port=5051)

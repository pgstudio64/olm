"""Flask server for the pattern management and creation tool.

Entry point: python -m olm.server.app [--dev]
Routes only — all business logic is delegated to olm.server.services.
"""
from __future__ import annotations

import argparse
import json
import logging
import logging.handlers
import os
import tempfile
import threading
import time
import uuid

DEV_MODE: bool = False
_START_TIME: float = time.monotonic()

# -- P2.5: mono-user session lock (D-188) --
IDLE_TIMEOUT_SECONDS: int = 30 * 60  # 30 min
_active_session: dict[str, str | float] | None = None

from flask import Flask, g, jsonify, make_response, request, send_file, send_from_directory
from werkzeug.exceptions import RequestEntityTooLarge

from olm.core.pattern_dsl import DSLError
from olm.core.room_dsl import RoomDSLError
from olm.server.services.config_service import (
    BASE_DIR,
    PROJECT_ROOT,
    _validate_upload,
    get_plans_dir,
    set_dev_mode,
)

LOG_FORMAT = '%(asctime)s [%(levelname)s] %(request_id)s%(name)s: %(message)s'
LOG_DIR = os.path.join(PROJECT_ROOT, "logs")
LOG_FILE = os.path.join(LOG_DIR, "olm.log")
LOG_MAX_BYTES = 5 * 1024 * 1024  # 5 MB
LOG_BACKUP_COUNT = 5

_request_local = threading.local()


class _RequestIdFilter(logging.Filter):
    """Inject request_id into every LogRecord."""

    def filter(self, record: logging.LogRecord) -> bool:
        rid = getattr(_request_local, 'request_id', None)
        record.request_id = f'[req-{rid}] ' if rid else ''  # type: ignore[attr-defined]
        return True


def configure_logging(*, dev: bool = False) -> None:
    """Set up the 'olm' root logger with stderr + rotating file handlers.

    Idempotent: clears existing handlers then rebuilds. Safe to call
    multiple times (import-time + __main__ reconfigure for --dev,
    Flask reloader child process, etc.).
    """
    level = logging.DEBUG if dev else logging.INFO
    olm_logger = logging.getLogger("olm")
    olm_logger.setLevel(level)

    # Close existing handlers before clearing (avoids leaked file descriptors)
    for h in olm_logger.handlers:
        h.close()
    olm_logger.handlers.clear()

    formatter = logging.Formatter(LOG_FORMAT)
    req_filter = _RequestIdFilter()

    # Handler 1: stderr
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    stream_handler.addFilter(req_filter)
    olm_logger.addHandler(stream_handler)

    # Handler 2: rotating file
    os.makedirs(LOG_DIR, exist_ok=True)
    file_handler = logging.handlers.RotatingFileHandler(
        LOG_FILE, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT,
    )
    file_handler.setFormatter(formatter)
    file_handler.addFilter(req_filter)
    olm_logger.addHandler(file_handler)

    # Silence Werkzeug's duplicate request log (OLM after_request handles it)
    logging.getLogger("werkzeug").setLevel(logging.WARNING)


# Configure logging at import time (INFO by default, reconfigured in __main__)
configure_logging(dev=False)

# Hardcoded name: when run via `python -m olm.server.app`, __name__ is
# "__main__" which is NOT a child of the "olm" logger hierarchy.
logger = logging.getLogger("olm.server.app")

app = Flask(
    __name__,
    static_folder=None,
    template_folder=os.path.join(BASE_DIR, "templates"),
)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50 MB
PLANS_DIR = get_plans_dir()


# Paths excluded from the mono-user session lock (P2.5).
_SESSION_LOCK_EXEMPT_PREFIXES = (
    "/health",
    "/static/",
    "/specs/",
    "/api/session/takeover",
)


@app.before_request
def _before_request():
    """Attach request_id, enforce mono-user lock (P2.5)."""
    global _active_session  # noqa: PLW0603
    g.request_id = uuid.uuid4().hex[:8]
    g.start_time = time.monotonic()
    _request_local.request_id = g.request_id

    # Skip lock check for exempt paths
    path = request.path
    if any(path == p or path.startswith(p) for p in _SESSION_LOCK_EXEMPT_PREFIXES):
        return None

    session_id = request.cookies.get("olm_session")
    now = time.time()

    if _active_session is None:
        # No active session — claim it
        if not session_id:
            session_id = uuid.uuid4().hex
        _active_session = {"id": session_id, "last_activity": now}
        g.set_session_cookie = session_id
        return None

    if session_id and session_id == _active_session["id"]:
        # Same session — refresh activity
        _active_session["last_activity"] = now
        return None

    # Different session — check idle timeout
    elapsed = now - float(_active_session["last_activity"])
    if elapsed >= IDLE_TIMEOUT_SECONDS:
        # Timeout expired — new session takes over
        if not session_id:
            session_id = uuid.uuid4().hex
        _active_session = {"id": session_id, "last_activity": now}
        g.set_session_cookie = session_id
        return None

    # Locked — refuse with 423
    return make_response(
        jsonify({"error": "OLM est deja utilise par une autre session.",
                 "locked_page": "/api/session/locked-page"}),
        423,
    )


@app.after_request
def _after_request(response):
    """Log HTTP request + set session cookie if needed (P2.5)."""
    # Set session cookie when a new session is claimed
    cookie_id = getattr(g, 'set_session_cookie', None)
    if cookie_id:
        response.set_cookie(
            "olm_session", cookie_id,
            httponly=True, samesite="Lax",
        )
    start = getattr(g, 'start_time', None)
    if start is not None:
        duration_ms = (time.monotonic() - start) * 1000
        # Static files, images, init endpoints, favicon → DEBUG
        path = request.path
        is_quiet = (
            path.startswith("/static/")
            or path.startswith("/api/ingestion/plan/")
            or path.startswith("/api/image")
            or path.startswith("/api/blocks")
            or path.startswith("/api/room-dsl/")
            or path == "/api/config"
            or path == "/api/spacing"
            or path == "/api/patterns"
            or path == "/favicon.ico"
            or path == "/test_rooms.json"
            or path == "/test_floor_plan.png"
        )
        log_fn = logger.debug if is_quiet else logger.info
        log_fn(
            "%d %s %s in %.0f ms",
            response.status_code, request.method, path, duration_ms,
        )
    return response


@app.teardown_request
def _teardown_request(exc=None) -> None:
    """Clean up thread-local request_id."""
    _request_local.request_id = None


@app.route("/health")
def health():
    """Diagnostic endpoint — returns system health checks."""
    from olm.server.services.config_service import get_health_status
    uptime = time.monotonic() - _START_TIME
    result, ok = get_health_status(uptime)
    return jsonify(result), 200 if ok else 503


@app.errorhandler(413)
def handle_request_too_large(e):
    """Return JSON error when upload exceeds size limit."""
    return jsonify({"error": "Fichier trop volumineux (limite : 50 MB)"}), 413


# ===================================================================
# Session lock (P2.5)
# ===================================================================


@app.route("/api/session/takeover", methods=["POST"])
def api_session_takeover():
    """Force-claim the active session for the current client."""
    global _active_session  # noqa: PLW0603
    new_id = uuid.uuid4().hex
    _active_session = {"id": new_id, "last_activity": time.time()}
    resp = make_response(jsonify({"ok": True}), 200)
    resp.set_cookie("olm_session", new_id, httponly=True, samesite="Lax")
    return resp


@app.route("/api/session/locked-page")
def api_session_locked_page():
    """HTML page shown when another session holds the lock."""
    html = """<!DOCTYPE html>
<html lang="fr">
<head><meta charset="utf-8"><title>OLM — Session verrouill\u00e9e</title>
<style>
body{font-family:system-ui,sans-serif;display:flex;justify-content:center;
align-items:center;height:100vh;margin:0;background:#f5f5f5}
.card{background:#fff;border-radius:8px;padding:2rem 3rem;
box-shadow:0 2px 8px rgba(0,0,0,.12);text-align:center;max-width:480px}
h1{font-size:1.4rem;margin-bottom:1rem}
p{color:#555;margin-bottom:1.5rem}
button{background:#2563eb;color:#fff;border:none;padding:.75rem 1.5rem;
border-radius:6px;font-size:1rem;cursor:pointer}
button:hover{background:#1d4ed8}
.ok{color:#16a34a;font-weight:bold}
</style></head>
<body><div class="card">
<h1>OLM est d\u00e9j\u00e0 en cours d\u2019utilisation</h1>
<p>Une autre session est active. Si vous \u00eates s\u00fbr de vouloir
prendre le contr\u00f4le, cliquez ci-dessous.</p>
<button id="btn">Prendre le contr\u00f4le</button>
<p id="msg"></p>
</div>
<script>
document.getElementById("btn").addEventListener("click",function(){
fetch("/api/session/takeover",{method:"POST",credentials:"same-origin"})
.then(function(r){if(r.ok){
document.getElementById("msg").className="ok";
document.getElementById("msg").textContent="Session prise. Rechargement...";
setTimeout(function(){window.location.href="/";},500);
}else{document.getElementById("msg").textContent="Erreur: "+r.status;}});
});
</script></body></html>"""
    return make_response(html, 200)


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
    import time

    from flask import render_template

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
    from olm.server.services.config_service import get_default_threshold
    from olm.server.services.ingestion_service import extract_rooms
    if 'image' in request.files:
        ok, err = _validate_upload(request.files['image'])
        if not ok:
            return jsonify({"error": err}), 415
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
    except RequestEntityTooLarge:
        raise
    except Exception as e:
        logger.exception("ingestion extract failed")
        return jsonify({"error": str(e)}), 500


@app.route("/api/ingestion/debug", methods=["POST"])
def api_ingestion_debug():
    """Extract rooms with detailed debug logs."""
    from olm.server.services.config_service import get_default_threshold
    from olm.server.services.ingestion_service import extract_rooms_debug
    if 'image' in request.files:
        ok, err = _validate_upload(request.files['image'])
        if not ok:
            return jsonify({"error": err}), 415
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
    except RequestEntityTooLarge:
        raise
    except Exception as e:
        logger.exception("ingestion debug failed")
        return jsonify({"error": str(e)}), 500


@app.route("/api/ingestion/binarize", methods=["POST"])
def api_ingestion_binarize():
    """Return the binarized version of a plan image."""
    from olm.server.services.config_service import get_default_threshold
    from olm.server.services.ingestion_service import binarize_image
    if 'image' in request.files:
        ok, err = _validate_upload(request.files['image'])
        if not ok:
            return jsonify({"error": err}), 415
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
    except RequestEntityTooLarge:
        raise
    except Exception as e:
        logger.exception("binarize failed")
        return jsonify({"error": str(e)}), 500


@app.route("/api/import/ocr", methods=["POST"])
def api_import_ocr():
    """Mode OCR: upload image (PNG/JPEG/PDF)."""
    from olm.server.services.config_service import (
        get_default_threshold,
        load_project_config,
    )
    from olm.server.services.ingestion_service import (
        cleanup_old_overlays,
        drawing_scale_to_cm_per_px,
        import_ocr,
        resolve_plan_id_image,
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
            ok, err = _validate_upload(f)
            if not ok:
                return jsonify({"error": err}), 415
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
    except RequestEntityTooLarge:
        raise
    except Exception as e:
        logger.exception("import OCR failed")
        return jsonify({"error": str(e)}), 500


@app.route("/api/import/preprocessed", methods=["POST"])
def api_import_preprocessed():
    """Mode Preprocessed: import from plan_id or uploaded files."""
    from olm.server.services.ingestion_service import (
        import_preprocessed,
        resolve_preprocessed_files,
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
            from olm.core.json_v3_validator import validate_plan
            validate_plan(json_data)
            for field in ("enhanced_png", "overlay_png"):
                if field not in request.files:
                    return jsonify({"error": f"{field} manquant"}), 400
                ok, err = _validate_upload(request.files[field])
                if not ok:
                    return jsonify({"error": err}), 415
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
    except RequestEntityTooLarge:
        for p in _temp_paths:
            if p and os.path.exists(p):
                os.unlink(p)
        raise
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
        get_spacing,
        update_spacing,
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
    set_dev_mode(args.dev)
    # Reconfigure logging (idempotent — rebuilds handlers with correct level)
    configure_logging(dev=args.dev)
    mode_label = " [DEV]" if DEV_MODE else ""
    from olm.server.services.catalogue_service import CATALOGUE_PATH
    # Only show startup banner in the reloader parent (avoid duplicate)
    if os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        logger.info("Pattern editor%s — http://localhost:5051", mode_label)
        logger.info("Catalogue: %s", CATALOGUE_PATH)
    app.run(debug=True, port=5051)

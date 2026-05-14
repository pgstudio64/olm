"""Flask server for the pattern management and creation tool.

Entry point: python -m olm.server.app [--dev]
Storage: catalogue/patterns.json
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import traceback
from io import StringIO

DEV_MODE: bool = False

from flask import Flask, jsonify, request, send_from_directory

from olm.core.pattern_dsl import DSLError
from olm.core.room_dsl import RoomDSLError
from olm.server.services.config_service import (
    BASE_DIR, PROJECT_ROOT,
    get_plans_dir, get_detection_overrides, get_default_threshold,
    get_exterior_rgb, get_corridor_rgb,
    get_block_defs, invalidate_block_cache,
)
from olm.server.services.catalogue_service import load_catalogue

logger = logging.getLogger(__name__)

app = Flask(
    __name__,
    static_folder=None,
    template_folder=os.path.join(BASE_DIR, "templates"),
)
PLANS_DIR = get_plans_dir()


_INCH_TO_CM = 2.54


def _drawing_scale_to_cm_per_px(text: str, render_dpi: int) -> float | None:
    """Convertit un texte '1 : N' en cm/px via le DPI de rendu."""
    m = re.match(r"1\s*:\s*(\d+(?:\.\d+)?)", text.strip())
    if not m or render_dpi <= 0:
        return None
    return _INCH_TO_CM * float(m.group(1)) / render_dpi


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
    """DEV: serve test_rooms.json from project/ for auto-load.

    Renvoie 404 si le fichier est absent (ex. déploiement prod sans
    project/test_rooms.json) : le fetch frontend check `r.ok` et skip
    silencieusement. Retourner `{"rooms": []}` avec HTTP 200 déclenchait
    faussement l'alerte "No rooms found in JSON" à l'ouverture de la page.
    """
    project_dir = os.path.join(os.path.dirname(BASE_DIR), "project")
    path = os.path.join(project_dir, "test_rooms.json")
    if not os.path.exists(path):
        return "", 404
    return send_from_directory(project_dir, "test_rooms.json")


@app.route("/test_floor_plan.png")
def serve_test_floor_plan():
    """DEV: serve test floor plan from project/plans/."""
    plans_dir = get_plans_dir()
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
      - 'threshold' (optional): binarization threshold (default 140)

    Returns JSON with detected rooms (bbox, doors, windows, openings, hits).
    """
    import tempfile
    try:
        # Get image from upload or from a plan path
        plan_path = request.form.get('plan_path', '')
        scale_str = request.form.get('scale', '')
        scale = float(scale_str) if scale_str else None
        threshold = int(request.form.get('threshold', get_default_threshold()))

        if 'image' in request.files:
            f = request.files['image']
            fd, plan_path = tempfile.mkstemp(suffix='.png')
            os.close(fd)
            f.save(plan_path)
        elif plan_path:
            # Resolve relative plan names to project/plans/ directory
            if not os.path.isabs(plan_path):
                plan_path = os.path.join(get_plans_dir(), plan_path)
            if not os.path.exists(plan_path):
                return jsonify({"error": f"Plan not found: {plan_path}"}), 404
        else:
            return jsonify({"error": "No image provided"}), 400

        import sys
        sys.path.insert(0, os.path.join(BASE_DIR, 'ingestion'))
        from test_comb import extract_all_rooms

        result = extract_all_rooms(plan_path, scale_cm_per_px=scale,
                                   threshold=threshold,
                                   detection_overrides=get_detection_overrides())

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
        # Note: test_comb is imported as 'from test_comb import', so __name__ = 'test_comb'
        ingestion_logger = logging.getLogger('test_comb')
        ingestion_logger.addHandler(handler)
        ingestion_logger.setLevel(logging.DEBUG)
        ingestion_logger.propagate = True  # Ensure logs propagate

        try:
            # Get image from upload or from a plan path
            plan_path = request.form.get('plan_path', '')
            scale_str = request.form.get('scale', '')
            scale = float(scale_str) if scale_str else None
            threshold = int(request.form.get('threshold', get_default_threshold()))

            if 'image' in request.files:
                f = request.files['image']
                fd, plan_path = tempfile.mkstemp(suffix='.png')
                os.close(fd)
                f.save(plan_path)
            elif plan_path:
                # Resolve relative plan names to project/plans/ directory
                if not os.path.isabs(plan_path):
                    plan_path = os.path.join(get_plans_dir(), plan_path)
                if not os.path.exists(plan_path):
                    return jsonify({"error": f"Plan not found: {plan_path}"}), 404
            else:
                return jsonify({"error": "No image provided"}), 400

            import sys
            sys.path.insert(0, os.path.join(BASE_DIR, 'ingestion'))
            from test_comb import extract_all_rooms

            result = extract_all_rooms(plan_path, scale_cm_per_px=scale,
                                       threshold=threshold,
                                       detection_overrides=get_detection_overrides())

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


@app.route("/api/plans", methods=["GET"])
def api_plans():
    """List available plans in project/plans/ (grouped by stem).

    A plan is identified by its base stem. The naming convention for the
    preprocessed mode is <plan_id>.png (overlay with cartouches),
    <plan_id>-SD.png (sans description / cartouches removed) and
    <plan_id>.json (metadata). The -SD variant is NOT listed as a
    separate plan — it's a component of its parent plan.

    ``effective_mode`` is "preprocessed" when has_json is true, "ocr"
    otherwise (D-140 — le check mtime a été supprimé car non-robuste aux
    copies inter-machine / git checkout).

    Returns:
        { "plans": [{ "id": str, "has_png": bool, "has_json": bool,
                      "has_enhanced": bool,
                      "effective_mode": "ocr"|"preprocessed" }, ...] }
    """
    plans_dir = get_plans_dir()
    if not os.path.isdir(plans_dir):
        return jsonify({"plans": []})
    _entry_defaults: dict = {
        "has_png": False, "has_json": False, "has_enhanced": False,
        "png_mtime": 0.0, "json_mtime": 0.0,
    }
    stems: dict[str, dict] = {}
    for fname in os.listdir(plans_dir):
        name, ext = os.path.splitext(fname)
        ext_lower = ext.lower()
        fpath = os.path.join(plans_dir, fname)
        if name.endswith("-SD"):
            base = name[: -len("-SD")]
            entry = stems.setdefault(base, dict(_entry_defaults))
            if ext_lower in (".png", ".jpg", ".jpeg"):
                entry["has_enhanced"] = True
            continue
        if ext_lower in (".png", ".jpg", ".jpeg"):
            entry = stems.setdefault(name, dict(_entry_defaults))
            entry["has_png"] = True
            entry["png_mtime"] = os.path.getmtime(fpath)
        elif ext_lower == ".json":
            entry = stems.setdefault(name, dict(_entry_defaults))
            entry["has_json"] = True
            entry["json_mtime"] = os.path.getmtime(fpath)
    plans = []
    for stem, info in sorted(stems.items()):
        if not info["has_png"]:
            continue
        # effective_mode : "preprocessed" dès que le JSON existe (pour
        # le chargement), "ocr" sinon. Le mode source (ocr/preprocessed)
        # pour le rescan est lu depuis le champ "mode" du JSON par
        # /api/import/preprocessed et propagé au frontend (D-154).
        effective_mode = "preprocessed" if info["has_json"] else "ocr"
        plans.append({
            "id": stem,
            "has_png": info["has_png"],
            "has_json": info["has_json"],
            "has_enhanced": info["has_enhanced"],
            "effective_mode": effective_mode,
        })
    return jsonify({"plans": plans})


@app.route("/api/ingestion/plans", methods=["GET"])
def api_ingestion_plans():
    """List available plan images in project/plans/."""
    plans_dir = get_plans_dir()
    if not os.path.isdir(plans_dir):
        return jsonify({"plans": []})
    plans = [f for f in os.listdir(plans_dir)
             if f.lower().endswith(('.png', '.jpg', '.jpeg', '.tiff'))]
    return jsonify({"plans": sorted(plans)})


@app.route("/api/ingestion/plan/<filename>")
def api_ingestion_plan_image(filename):
    """Serve a plan image from project/plans/."""
    return send_from_directory(get_plans_dir(), filename)


@app.route("/api/plans/<plan_id>/metadata")
def api_plan_metadata(plan_id):
    """Return lightweight metadata from the plan JSON (no extraction).

    Used by the frontend to populate building/floor info and zoom to the
    rooms envelope while the full import runs in the background.
    """
    plans_dir = get_plans_dir()
    json_path = os.path.join(plans_dir, plan_id + ".json")
    if not os.path.exists(json_path):
        return jsonify({"error": "JSON not found"}), 404
    try:
        with open(json_path, encoding="utf-8") as f:
            data = json.load(f)
        rooms_summary = []
        for r in data.get("rooms", []):
            bbox = r.get("bbox_px")
            if bbox and len(bbox) == 4:
                rooms_summary.append({
                    "name": r.get("room_id", ""),
                    "bbox_px": [int(v) for v in bbox],
                })
        page_w = int(data.get("page_width_px") or 0)
        page_h = int(data.get("page_height_px") or 0)
        if page_w <= 0 or page_h <= 0:
            png_path = os.path.join(plans_dir, plan_id + ".png")
            if os.path.exists(png_path):
                from PIL import Image as _PilImg
                with _PilImg.open(png_path) as im:
                    page_w, page_h = im.size
        return jsonify({
            "building_id": str(data.get("building_id", "")),
            "floor_id": str(data.get("floor_id", "")),
            "north_angle_deg": float(data.get("north_angle_deg", 0) or 0),
            "drawing_scale_text": str(data.get("drawing_scale_text", "")),
            "mode": data.get("mode", "preprocessed"),
            "image_size": [page_w, page_h],
            "rooms_summary": rooms_summary,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/plans/<plan_id>/save", methods=["POST"])
def api_plan_save(plan_id):
    """Save the full plan JSON to disk (overwrites existing file)."""
    try:
        plans_dir = get_plans_dir()
        json_path = os.path.join(plans_dir, plan_id + ".json")
        data = request.json
        if not data:
            return jsonify({"error": "Empty payload"}), 400
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return jsonify({"ok": True, "path": json_path})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/plans/<plan_id>/reinit", methods=["POST"])
def api_plan_reinit(plan_id):
    """Strip a plan JSON to preprocessing-only data and save to disk.

    Keeps: file, page_width_px, page_height_px, drawing_scale_text,
           render_dpi, and per room: surface, seed_x, seed_y,
           seed-only doors ({seed_x, seed_y} without face).
    Removes: everything added by detection or user (bbox_px, windows,
             openings, enriched doors, exclusion_zones, etc.).
    """
    try:
        plans_dir = get_plans_dir()
        json_path = os.path.join(plans_dir, plan_id + ".json")
        if not os.path.exists(json_path):
            return jsonify({"error": f"JSON not found for '{plan_id}'"}), 404
        with open(json_path, encoding="utf-8") as f:
            data = json.load(f)

        # Preserve root-level preprocessing fields only
        clean = {}
        for key in ("file", "page_width_px", "page_height_px",
                     "drawing_scale_text", "render_dpi"):
            if key in data:
                clean[key] = data[key]

        # Clean each room: keep only preprocessing fields
        rooms_raw = data.get("rooms", {})
        clean_rooms = {}
        if isinstance(rooms_raw, dict):
            for room_id, r in rooms_raw.items():
                if not isinstance(r, dict):
                    continue
                room = {}
                for key in ("surface", "seed_x", "seed_y"):
                    if key in r:
                        room[key] = r[key]
                # Keep seed-only doors (no face = preprocessing)
                seed_doors = []
                for d in (r.get("doors") or []):
                    if isinstance(d, dict) and "seed_x" in d and not d.get("face"):
                        seed_doors.append({
                            "seed_x": d["seed_x"],
                            "seed_y": d["seed_y"],
                        })
                if seed_doors:
                    room["doors"] = seed_doors
                clean_rooms[room_id] = room
        clean["rooms"] = clean_rooms

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(clean, f, indent=2, ensure_ascii=False)
        return jsonify({"ok": True, "path": json_path})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


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
        threshold = int(request.form.get('threshold', get_default_threshold()))

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


@app.route("/api/import/ocr", methods=["POST"])
def api_import_ocr():
    """Mode OCR : upload image (PNG/JPEG/PDF).

    Accepte multipart form avec :
      - floorplan_image : fichier image du plan de sol (PNG, JPEG ou PDF)
      - scale_cm_per_px (optionnel) : cm par pixel ; défaut depuis config.json
      - threshold (optionnel) : seuil de binarisation ; défaut 140

    Retourne :
      {
        "rooms": [...],
        "mode": "ocr",
        "image_size": [w, h],
        "scale_cm_per_px": float,
        "image_path": ""
      }
    """
    import tempfile
    import shutil
    import time
    import uuid

    # Nettoyage best-effort des anciens overlays (> 1 heure)
    _overlay_dir = os.path.join(tempfile.gettempdir(), "olm_overlays")
    os.makedirs(_overlay_dir, exist_ok=True)
    _cutoff = time.time() - 3600
    try:
        for _f in os.listdir(_overlay_dir):
            _fp = os.path.join(_overlay_dir, _f)
            try:
                if os.path.getmtime(_fp) < _cutoff:
                    os.unlink(_fp)
            except OSError:
                pass
    except OSError:
        pass

    # Valeurs par défaut depuis config_service
    from olm.server.services.config_service import load_project_config
    _ing_cfg = load_project_config().get("ingestion", {})
    _default_scale: float = float(_ing_cfg.get("scale_cm_per_px", 0.5))
    _default_threshold = get_default_threshold()
    _pdf_render_dpi: int = int(_ing_cfg.get("pdf_render_dpi", 200))

    try:
        # Drawing scale (e.g. "1 : 100") takes priority over raw scale_cm_per_px
        drawing_scale_str = request.form.get("drawing_scale", "").strip()
        render_dpi = int(request.form.get("render_dpi") or 300)
        scale: float | None = None
        if drawing_scale_str:
            scale = _drawing_scale_to_cm_per_px(drawing_scale_str, render_dpi)
        if scale is None:
            scale_str = request.form.get("scale_cm_per_px", "")
            scale = float(scale_str) if scale_str else None
        threshold = int(request.form.get("threshold") or _default_threshold)

        plan_id = request.form.get("plan_id", "").strip()
        plan_path = ""
        pdf_tmp_path = ""
        use_temp = False

        if plan_id:
            # Résolution depuis project/plans/<plan_id>.png
            for ext in (".png", ".jpg", ".jpeg", ".PNG", ".JPG", ".JPEG"):
                candidate = os.path.join(PLANS_DIR, plan_id + ext)
                if os.path.exists(candidate):
                    plan_path = candidate
                    break
            if not plan_path:
                return jsonify({"error": f"Plan '{plan_id}' introuvable dans project/plans/"}), 400
        elif "floorplan_image" in request.files:
            f = request.files["floorplan_image"]
            filename_lower = (f.filename or "").lower()
            is_pdf = filename_lower.endswith(".pdf") or f.mimetype == "application/pdf"
            use_temp = True

            if is_pdf:
                import fitz  # type: ignore[import]
                pdf_data = f.read()
                doc = fitz.open(stream=pdf_data, filetype="pdf")
                page = doc[0]
                pix = page.get_pixmap(dpi=_pdf_render_dpi)
                fd, plan_path = tempfile.mkstemp(suffix=".png")
                os.close(fd)
                pix.save(plan_path)
                pdf_tmp_path = plan_path
            else:
                fd, plan_path = tempfile.mkstemp(suffix=".png")
                os.close(fd)
                f.save(plan_path)
        else:
            return jsonify({"error": "Paramètre 'plan_id' ou champ 'floorplan_image' requis"}), 400

        import sys
        sys.path.insert(0, os.path.join(BASE_DIR, "ingestion"))
        from test_comb import extract_all_rooms  # noqa: PLC0415

        result = extract_all_rooms(plan_path, scale_cm_per_px=scale,
                                   threshold=threshold,
                                   detection_overrides=get_detection_overrides())

        if use_temp:
            # Déplacer le PNG temporaire vers le dossier overlays persistant
            overlay_filename = "overlay_" + uuid.uuid4().hex + ".png"
            overlay_path = os.path.join(_overlay_dir, overlay_filename)
            shutil.move(plan_path, overlay_path)
            result["image_path"] = overlay_path
        else:
            # Plan fichier permanent — le servir directement via /api/ingestion/plan/
            result["image_path"] = plan_path

        result["mode"] = "ocr"
        return jsonify(result)
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/import/preprocessed", methods=["POST"])
def api_import_preprocessed():
    """Mode Préprocessé : upload JSON + PNG enhanced + PNG overlay.

    Accepte multipart form avec :
      - rooms_json : fichier JSON ou champ texte JSON brut
      - enhanced_png : fichier PNG "-SD" (sans description / cartouches supprimés)
      - overlay_png : fichier PNG overlay (plan officiel)

    Retourne :
      {
        "rooms": [...],
        "mode": "preprocessed",
        "overlay_path": "chemin PNG overlay temporaire",
        "enhanced_path": "chemin PNG enhanced temporaire"
      }
    """
    import tempfile
    enhanced_path = ""
    overlay_path = ""
    _temp_paths: list[str] = []
    try:
        plan_id = request.form.get("plan_id", "").strip()

        if plan_id:
            # --- Mode plan_id : résolution depuis project/plans/ ---
            json_path = os.path.join(PLANS_DIR, plan_id + ".json")
            if not os.path.exists(json_path):
                return jsonify({
                    "error": f"Preprocessed mode: JSON file missing for plan '{plan_id}'"
                }), 400
            with open(json_path, encoding="utf-8") as f:
                json_data = json.load(f)

            overlay_path = ""
            for ext in (".png", ".PNG"):
                candidate = os.path.join(PLANS_DIR, plan_id + ext)
                if os.path.exists(candidate):
                    overlay_path = candidate
                    break
            if not overlay_path:
                return jsonify({"error": f"Plan PNG manquant pour '{plan_id}'"}), 400

            sd_candidate = os.path.join(PLANS_DIR, plan_id + "-SD.png")
            enhanced_path = sd_candidate if os.path.exists(sd_candidate) else overlay_path
        else:
            # --- Mode upload fichiers (fallback) ---
            json_data = None
            if "rooms_json" in request.files:
                raw = request.files["rooms_json"].read().decode("utf-8")
                json_data = json.loads(raw)
            elif "rooms_json" in request.form:
                json_data = json.loads(request.form["rooms_json"])
            else:
                return jsonify({"error": "Champ 'rooms_json' manquant (fichier ou texte)"}), 400

            if "enhanced_png" not in request.files:
                return jsonify({"error": "Champ 'enhanced_png' manquant"}), 400
            if "overlay_png" not in request.files:
                return jsonify({"error": "Champ 'overlay_png' manquant"}), 400

            fd, enhanced_path = tempfile.mkstemp(suffix="_enhanced.png")
            os.close(fd)
            request.files["enhanced_png"].save(enhanced_path)
            _temp_paths.append(enhanced_path)

            fd, overlay_path = tempfile.mkstemp(suffix="_overlay.png")
            os.close(fd)
            request.files["overlay_png"].save(overlay_path)
            _temp_paths.append(overlay_path)

        # Inject semantic colors from config into json_data for face detection
        json_data.setdefault("corridor_rgb", list(get_corridor_rgb()))
        json_data.setdefault("exterior_rgb", list(get_exterior_rgb()))

        # --- Scale resolution ---
        # Priority: notation (text + dpi) > ruler (measured) > median
        # The frontend may send a manual override via drawing_scale form field.
        import math as _math
        render_dpi = int(
            json_data.get("render_dpi")
            or request.form.get("render_dpi")
            or 300
        )

        # 1) Notation Scale: drawing_scale_text from JSON + render_dpi
        dst_raw = str(json_data.get("drawing_scale_text", "")).strip()
        notation_scale = _drawing_scale_to_cm_per_px(
            dst_raw, render_dpi) if dst_raw else None

        # 2) Ruler Scale: drawing_scale_measured from JSON (cm/px)
        ruler_scale: float | None = None
        measured_str = str(
            json_data.get("drawing_scale_measured", "")
        ).strip()
        if measured_str:
            m_val = re.match(r"([\d.]+)\s*cm/px", measured_str)
            if m_val:
                ruler_scale = float(m_val.group(1))

        # 3) Manual Scale: drawing_scale from frontend UI
        drawing_scale_str = request.form.get("drawing_scale", "").strip()
        manual_scale = _drawing_scale_to_cm_per_px(
            drawing_scale_str, render_dpi) if drawing_scale_str else None

        # Frontend may specify which source to use (radio selection)
        scale_source = request.form.get("scale_source", "").strip()
        if scale_source == "notation" and notation_scale:
            explicit_scale = notation_scale
        elif scale_source == "ruler" and ruler_scale:
            explicit_scale = ruler_scale
        elif scale_source == "manual" and manual_scale:
            explicit_scale = manual_scale
        else:
            # Default cascade: notation > ruler > manual
            explicit_scale = notation_scale or ruler_scale or manual_scale

        # Pass explicit scale to extract function if available
        if explicit_scale is not None and explicit_scale > 0:
            json_data["_override_cm_per_px"] = explicit_scale

        # Pass detection overrides for color sampling widths
        _det_overrides = get_detection_overrides()
        if _det_overrides:
            json_data["_detection_overrides"] = _det_overrides

        # --- Extraction ---
        _window_mode = request.form.get("window_mode", "simple")
        from olm.ingestion.extract import extract_rooms_from_preprocessed
        rooms = extract_rooms_from_preprocessed(
            json_data, enhanced_path, overlay_path,
            window_mode=_window_mode)

        # Image size : lire depuis le JSON v3 si présent, sinon depuis le PNG
        page_w = int(json_data.get("page_width_px") or 0)
        page_h = int(json_data.get("page_height_px") or 0)
        if page_w <= 0 or page_h <= 0:
            try:
                from PIL import Image as _PilImage
                with _PilImage.open(overlay_path) as _im:
                    page_w, page_h = _im.size
            except Exception:
                page_w = page_h = 0

        # Scale cm/px : use explicit scale if provided, otherwise median
        if explicit_scale is not None and explicit_scale > 0:
            scale_cm_per_px = explicit_scale
        else:
            scale_samples = []
            for r in rooms:
                bb = r.get("bbox_px")
                surf = r.get("surface_m2", 0) or 0
                if bb and surf > 0 and bb[2] > bb[0] and bb[3] > bb[1]:
                    area_px = (bb[2] - bb[0]) * (bb[3] - bb[1])
                    if area_px > 0:
                        scale_samples.append(
                            _math.sqrt((surf * 10_000.0) / area_px)
                        )
            scale_samples.sort()
            scale_cm_per_px = (
                scale_samples[len(scale_samples) // 2]
                if scale_samples else 0.0
            )

        return jsonify({
            "rooms": rooms,
            "mode": json_data.get("mode", "preprocessed"),
            "overlay_path": overlay_path,
            "enhanced_path": enhanced_path,
            "image_size": [page_w, page_h],
            "image_path": overlay_path,
            "scale_cm_per_px": scale_cm_per_px,
            # Scale sources for the frontend selector
            "render_dpi": render_dpi,
            "drawing_scale_text": str(
                json_data.get("drawing_scale_text", "")),
            "notation_scale_cm_per_px": notation_scale or 0,
            "ruler_scale_cm_per_px": ruler_scale or 0,
            "scale_source": scale_source or "auto",
            "first_scan_done": bool(json_data.get("first_scan_done", False)),
            "building_id":  str(json_data.get("building_id", "")),
            "floor_id":     str(json_data.get("floor_id", "")),
            "north_angle_deg": float(
                json_data.get("north_angle_deg", 0) or 0),
        })
    except (json.JSONDecodeError, ValueError) as e:
        for p in _temp_paths:
            if p and os.path.exists(p):
                os.unlink(p)
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        traceback.print_exc()
        for p in _temp_paths:
            if p and os.path.exists(p):
                os.unlink(p)
        return jsonify({"error": str(e)}), 500


@app.route("/api/image")
def api_serve_image():
    """Serve a plan/overlay PNG from allowed directories only."""
    from flask import send_file
    import tempfile
    path = request.args.get("path", "")
    if not path or not os.path.isfile(path):
        return jsonify({"error": "File not found"}), 404
    real = os.path.realpath(path)
    allowed = [
        os.path.realpath(os.path.join(tempfile.gettempdir(), "olm_overlays")),
        os.path.realpath(PLANS_DIR),
    ]
    if not any(real.startswith(d + os.sep) or real == d for d in allowed):
        return jsonify({"error": "Access denied"}), 403
    return send_file(real, mimetype="image/png")


@app.route("/specs/<path:filename>")
def serve_specs(filename: str):
    """Serve spec files."""
    return send_from_directory(os.path.join(os.path.dirname(BASE_DIR), "docs", "specs"), filename)


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
        data = request.json
        try:
            result = update_spacing(data)
            return jsonify(result)
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
    data = request.json
    try:
        result = update_config(data)
        return jsonify(result)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


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


@app.route("/api/room/reanalyze", methods=["POST"])
def api_room_reanalyze():
    """Re-analyse les fenêtres et ouvertures d'une seule pièce (R-04 Review).

    Body JSON attendu :
        {
          "plan_path": "/chemin/vers/plan.png",  (-SD pour Mode Préprocessé)
          "bbox_px": [x0, y0, x1, y1],
          "scale_cm_per_px": 0.5,
          "transparent_zones": [{x_cm, y_cm, width_cm, depth_cm}, ...],
          "threshold": 140  (optionnel)
        }

    Retour :
        {
          "windows": [{face, offset_px, width_px, offset_cm, width_cm}],
          "openings": [...]
        }

    Les doors ne sont PAS redétectées (swing d'arc hors périmètre de la
    classification directe). Le frontend est responsable de les préserver.
    """
    try:
        data = request.json or {}
        plan_path = data.get("plan_path", "")
        seed_px = data.get("seed_px")
        bbox_px = data.get("bbox_px")
        scale = float(data.get("scale_cm_per_px", 0.5))
        transparents = data.get("transparent_zones", []) or []
        doors = data.get("doors", []) or []
        door_width_cm = int(data.get("door_width_cm", 90))
        threshold = int(data.get("threshold", get_default_threshold()))
        clip_to_bbox = bool(data.get("clip_to_bbox", False))
        mode = (data.get("mode") or "preprocessed").lower()
        window_mode = data.get("window_mode", "detailed") \
            if mode != "ocr" else "detailed"
        raw_other = data.get("other_seeds_px") or []
        other_seeds_px = [(int(s[0]), int(s[1]))
                          for s in raw_other if s and len(s) >= 2]
        corridor_face_abs = data.get("corridor_face", "") or ""

        if not plan_path or not os.path.exists(plan_path):
            return jsonify({"error": "plan_path missing or invalid"}), 400
        if not seed_px or len(seed_px) != 2:
            return jsonify({"error": "seed_px must be [x, y]"}), 400
        if bbox_px:
            try:
                bbox_px = [int(v) for v in bbox_px]
            except (TypeError, ValueError):
                return jsonify({"error": "bbox_px must contain integers"}), 400
            if bbox_px[2] <= bbox_px[0] or bbox_px[3] <= bbox_px[1]:
                bbox_px = None

        from PIL import Image as _PILImage
        from olm.ingestion.extract import extract_room_features
        img = _PILImage.open(plan_path).convert("L")

        # D-156 : image couleur pour filtrage fenêtres/extérieur.
        # En mode preprocessed, le -SD (plan_path) porte les zones colorées
        # (bleu extérieur, vert corridor). L'overlay est le plan officiel
        # (souvent grayscale). En OCR le plan_path n'a pas de zones colorées.
        color_img = None
        if mode != "ocr" and plan_path and os.path.exists(plan_path):
            color_img = _PILImage.open(plan_path)

        # D-156 : appliquer la config de détection quel que soit le mode.
        from olm.ingestion.comb_detection import _apply_detection_config
        _apply_detection_config(scale, get_detection_overrides())

        # Mode OCR : reproduire l'erase cartouches du scan initial
        # (test_comb.extract_all_rooms). Sans ça, les seeds tombent sur du
        # texte solide et les rays butent immédiatement.
        cart_bboxes_px: list = []
        if mode == "ocr":
            from olm.ingestion.comb_detection import find_seeds_by_ocr
            _seeds, cart_bboxes_px = find_seeds_by_ocr(img)

        result = extract_room_features(
            img,
            (int(seed_px[0]), int(seed_px[1])),
            tuple(bbox_px) if bbox_px else None,
            scale,
            transparent_zones_cm=transparents,
            doors_px=doors,
            door_width_cm=door_width_cm,
            threshold=threshold,
            clip_to_bbox=clip_to_bbox,
            cartouche_bboxes_px=cart_bboxes_px,
            color_image=color_img,
            exterior_rgb=get_exterior_rgb(),
            corridor_rgb=get_corridor_rgb(),
            other_seeds=other_seeds_px or None,
            detection_overrides=get_detection_overrides(),
            window_mode=window_mode,
            corridor_face=corridor_face_abs,
        )
        return jsonify(result)
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e), "trace": traceback.format_exc()}), 500


@app.route("/api/debug/room-diagnostic", methods=["POST"])
def api_debug_room_diagnostic():
    """Diagnostic endpoint: re-runs detection with full debug info.

    Body JSON: same as /api/room/reanalyze plus optional room_name.
    Returns: extract_room_features result + diag dict with coarse
    distances, seed_caps, hit counts, bbox info.
    """
    try:
        data = request.json or {}
        plan_path = data.get("plan_path", "")
        seed_px = data.get("seed_px")
        bbox_px = data.get("bbox_px")
        scale = float(data.get("scale_cm_per_px", 0.5))
        transparents = data.get("transparent_zones", []) or []
        doors = data.get("doors", []) or []
        door_width_cm = int(data.get("door_width_cm", 90))
        threshold = int(data.get("threshold", get_default_threshold()))
        clip_to_bbox = bool(data.get("clip_to_bbox", False))
        mode = (data.get("mode") or "preprocessed").lower()
        _wm = data.get("window_mode", "detailed")
        window_mode = _wm if mode != "ocr" else "detailed"
        raw_other = data.get("other_seeds_px") or []
        other_seeds_px = [(int(s[0]), int(s[1]))
                          for s in raw_other if s and len(s) >= 2]

        if not plan_path or not os.path.exists(plan_path):
            return jsonify({"error": "plan_path missing or invalid"}), 400
        if not seed_px or len(seed_px) != 2:
            return jsonify({"error": "seed_px must be [x, y]"}), 400
        if bbox_px:
            try:
                bbox_px = [int(v) for v in bbox_px]
            except (TypeError, ValueError):
                return jsonify({"error": "bbox_px must contain ints"}), 400
            if bbox_px[2] <= bbox_px[0] or bbox_px[3] <= bbox_px[1]:
                bbox_px = None

        from PIL import Image as _PILImage
        from olm.ingestion.extract import extract_room_features
        img = _PILImage.open(plan_path).convert("L")

        color_img = None
        if mode != "ocr" and plan_path and os.path.exists(plan_path):
            color_img = _PILImage.open(plan_path)

        from olm.ingestion.comb_detection import _apply_detection_config
        _apply_detection_config(scale, get_detection_overrides())

        cart_bboxes_px: list = []
        if mode == "ocr":
            from olm.ingestion.comb_detection import find_seeds_by_ocr
            _seeds, cart_bboxes_px = find_seeds_by_ocr(img)

        diag: dict = {}
        result = extract_room_features(
            img,
            (int(seed_px[0]), int(seed_px[1])),
            tuple(bbox_px) if bbox_px else None,
            scale,
            transparent_zones_cm=transparents,
            doors_px=doors,
            door_width_cm=door_width_cm,
            threshold=threshold,
            clip_to_bbox=clip_to_bbox,
            cartouche_bboxes_px=cart_bboxes_px,
            color_image=color_img,
            exterior_rgb=get_exterior_rgb(),
            corridor_rgb=get_corridor_rgb(),
            other_seeds=other_seeds_px or None,
            diag=diag,
            detection_overrides=get_detection_overrides(),
            window_mode=window_mode,
        )
        # Keep hits in the response so the frontend can display
        # rays after rescan (D-169b).
        diag['binarize_threshold'] = threshold
        diag['door_width_px'] = int(round(door_width_cm / scale))
        result["diag"] = diag
        result["other_seeds_count"] = len(other_seeds_px)

        # Color detection on detected bbox (orientation diagnostic)
        detected_bbox = result.get("bbox_px")
        if detected_bbox and color_img and mode != "ocr":
            try:
                import numpy as _np
                from olm.ingestion.extract import _detect_face_colors
                _rgb_arr = _np.array(color_img.convert("RGB"))
                colors = _detect_face_colors(
                    _rgb_arr, detected_bbox,
                    get_corridor_rgb(),
                    get_exterior_rgb(),
                )
                result["color_detection"] = {
                    "corridor_face": colors["corridor_face"],
                    "exterior_faces": colors["exterior_faces"],
                }
                result["corner_hits"] = colors.get("corner_hits", [])
                result["color_params"] = {
                    "corridor_rgb": list(get_corridor_rgb()),
                    "exterior_rgb": list(get_exterior_rgb()),
                    "image_path": plan_path,
                    "image_mode": color_img.mode,
                    "image_size": list(color_img.size),
                }
                _OPP = {"north": "south", "south": "north",
                         "east": "west", "west": "east"}
                deduced_cf = colors.get("corridor_face", "")
                if not deduced_cf and colors.get("exterior_faces"):
                    deduced_cf = ("(from blue) "
                                  + _OPP.get(
                                      colors["exterior_faces"][0], "?"))
                result["deduced_corridor_face"] = deduced_cf
            except Exception as e:
                result["color_detection_error"] = str(e)

        return jsonify(result)
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e), "trace": traceback.format_exc()}), 500


@app.route("/api/room/orientation-check", methods=["POST"])
def api_room_orientation_check():
    """Auto-test R-13 / D-119 — vérifie l'orientation canonique d'une pièce.

    Body JSON attendu :
        {
          "plan_path": "/chemin/vers/plan-SD.png",
          "bbox_px": [x0, y0, x1, y1],
          "corridor_face_abs": "east"   # "", "south", "north", "east", "west"
        }

    Retour : diagnostic complet pour les 4 faces canon + verdicts corridor
    (sud canon) et extérieur (nord canon).
    """
    try:
        data = request.json or {}
        plan_path = data.get("plan_path", "")
        bbox_px = data.get("bbox_px")
        ocf = data.get("corridor_face_abs", "") or ""

        if not plan_path or not os.path.exists(plan_path):
            return jsonify({"error": "plan_path missing or invalid"}), 400
        if not bbox_px or len(bbox_px) != 4:
            return jsonify({"error": "bbox_px must be [x0,y0,x1,y1]"}), 400

        from olm.ingestion.orientation_check import (
            check_all_faces, check_corridor_south, check_exterior_north,
            check_windows_exterior,
        )
        faces = check_all_faces(plan_path, bbox_px, ocf)
        corridor = check_corridor_south(plan_path, bbox_px, ocf)
        exterior = check_exterior_north(plan_path, bbox_px, ocf)
        windows = None
        windows_in = data.get("windows") or []
        scale = float(data.get("scale_cm_per_px", 0) or 0)
        if windows_in and scale > 0:
            windows = check_windows_exterior(
                plan_path, bbox_px, ocf, windows_in, scale)
        return jsonify({
            "corridor_face_abs": ocf,
            "faces": faces["faces"],
            "corridor_south": corridor,
            "exterior_north": exterior,
            "windows": windows,
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e), "trace": traceback.format_exc()}), 500


@app.route("/api/floor-plan/orientation-report", methods=["POST"])
def api_floor_plan_orientation_report():
    """Batch R-13 : rapport d'orientation pour toutes les pièces du plan.

    Body JSON attendu :
        {
          "plan_path": "/chemin/vers/plan-SD.png",
          "scale_cm_per_px": 0.5,
          "rooms": [
            {"name": "237", "bbox_px": [x0,y0,x1,y1],
             "corridor_face_abs": "east",
             "windows": [{face, offset_cm, width_cm}, ...]},
            ...
          ]
        }

    Retour :
        {
          "results": [{name, corridor_south, exterior_north, windows,
                       verdict}, ...],
          "summary": {n_ok, n_warn, n_total, failing: [name, ...]},
        }
    """
    try:
        data = request.json or {}
        plan_path = data.get("plan_path", "")
        rooms = data.get("rooms") or []
        scale = float(data.get("scale_cm_per_px", 0) or 0)

        if not plan_path or not os.path.exists(plan_path):
            return jsonify({"error": "plan_path missing or invalid"}), 400
        if not isinstance(rooms, list) or not rooms:
            return jsonify({"error": "rooms must be non-empty list"}), 400

        from olm.ingestion.orientation_check import (
            check_corridor_south, check_exterior_north,
            check_windows_exterior,
        )

        results = []
        failing = []
        n_ok = 0
        n_warn = 0
        for r in rooms:
            name = r.get("name", "")
            bbox = r.get("bbox_px")
            ocf = r.get("corridor_face_abs", "") or ""
            if not bbox or len(bbox) != 4:
                results.append({"name": name, "error": "invalid bbox_px"})
                continue
            try:
                corridor = check_corridor_south(plan_path, bbox, ocf)
                exterior = check_exterior_north(plan_path, bbox, ocf)
                windows_res = None
                win_list = r.get("windows") or []
                if win_list and scale > 0:
                    windows_res = check_windows_exterior(
                        plan_path, bbox, ocf, win_list, scale)

                # Verdict par pièce : ok si corridor OK + (extérieur ou
                # fenêtres indiquent une façade valide).
                corridor_ok = corridor.get("ok", False)
                windows_ok = (windows_res is None
                              or windows_res.get("verdict") in ("ok", ""))
                if corridor_ok and windows_ok:
                    verdict = "ok"
                    n_ok += 1
                elif not corridor_ok:
                    verdict = "corridor_fail"
                    failing.append(name)
                else:
                    verdict = "windows_warn"
                    n_warn += 1
                results.append({
                    "name": name,
                    "corridor_face_abs": ocf,
                    "corridor_south": corridor,
                    "exterior_north": exterior,
                    "windows": windows_res,
                    "verdict": verdict,
                })
            except Exception as e:
                results.append({"name": name, "error": str(e)})

        return jsonify({
            "results": results,
            "summary": {
                "n_total": len(rooms),
                "n_ok": n_ok,
                "n_warn": n_warn,
                "n_fail": len(failing),
                "failing": failing,
            },
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e), "trace": traceback.format_exc()}), 500


@app.route("/api/room/reanalyze_batch", methods=["POST"])
def api_room_reanalyze_batch():
    """Batch re-analyse : traite N pièces en partageant le chargement de l'image.

    Body JSON attendu :
        {
          "plan_path": "/chemin/vers/plan-SD.png",
          "scale_cm_per_px": 0.5,
          "threshold": 140,
          "rooms": [
            {"name": "237", "bbox_px": [x0,y0,x1,y1], "transparent_zones": [...]},
            ...
          ]
        }

    Retour :
        {"results": [{"name": "237", "windows": [...], "openings": [...]},
                     {"name": "238", "error": "..."}, ...]}
    """
    try:
        data = request.json or {}
        plan_path = data.get("plan_path", "")
        scale = float(data.get("scale_cm_per_px", 0.5))
        threshold = int(data.get("threshold", get_default_threshold()))
        door_width_cm = int(data.get("door_width_cm", 90))
        rooms = data.get("rooms") or []
        clip_to_bbox = bool(data.get("clip_to_bbox", False))
        mode = (data.get("mode") or "preprocessed").lower()
        window_mode = data.get("window_mode", "detailed") \
            if mode != "ocr" else "detailed"

        if not plan_path or not os.path.exists(plan_path):
            return jsonify({"error": "plan_path missing or invalid"}), 400
        if not isinstance(rooms, list) or not rooms:
            return jsonify({"error": "rooms must be non-empty list"}), 400

        from PIL import Image as _PILImage
        import numpy as _np
        from olm.ingestion.extract import (
            extract_room_features, remove_non_ortho,
        )

        # Chargement unique : l'image est partagée entre toutes les pièces.
        img = _PILImage.open(plan_path).convert("L")

        # D-156 : image couleur overlay pour filtrage fenêtres/extérieur.
        # Uniquement en mode preprocessed (cf. commentaire single reanalyze).
        # D-156 : image couleur pour filtrage fenêtres/extérieur.
        # En mode preprocessed, le -SD (plan_path) porte les zones colorées
        # (bleu extérieur, vert corridor). En OCR pas de zones colorées.
        color_img = None
        if mode != "ocr" and plan_path and os.path.exists(plan_path):
            color_img = _PILImage.open(plan_path)

        # D-123 perf : binarisation + remove_non_ortho partagées sur toute
        # l'image. ~200-300 ms × N pièces → 1 seule invocation. Les masques
        # room-locaux (zones transparentes) sont zéro-outés localement par
        # `extract_room_features` via `binary_precomputed`.
        # D-145 : on partage AUSSI la binaire pré-`remove_non_ortho`
        # (`binary_raw_precomputed`) pour la détection d'arcs de porte.
        _gray_global = _np.asarray(img)

        # D-156 : appliquer la config de détection quel que soit le mode.
        # Les constantes (ray margins, seuils portes…) doivent être
        # ajustées au scale du plan avant tout ray-cast.
        from olm.ingestion.comb_detection import _apply_detection_config
        _apply_detection_config(scale, get_detection_overrides())

        # Mode OCR : reproduire l'erase cartouches du scan initial
        # (test_comb.extract_all_rooms) AVANT la binarisation globale.
        # Sans ça, les cartouches survivent comme paquets de pixels solides
        # et les seeds tombent dessus → bbox réduite à des bandes étroites.
        if mode == "ocr":
            from olm.ingestion.comb_detection import (
                find_seeds_by_ocr, erase_cartouches,
            )
            _seeds, _cart_bboxes_px = find_seeds_by_ocr(img)
            _gray_global = erase_cartouches(_gray_global, _cart_bboxes_px)

        _binary_raw_global = _gray_global < threshold
        # DISABLED — see extract.py L877 comment.  Restore: uncomment.
        # _binary_global = remove_non_ortho(_binary_raw_global)  # disabled
        _binary_global = _binary_raw_global.copy()

        # Collect all seeds for inter-room ray limiting.
        all_seeds_px: list[tuple[int, int]] = []
        for r in rooms:
            sp = r.get("seed_px")
            if sp and len(sp) >= 2:
                all_seeds_px.append((int(sp[0]), int(sp[1])))

        results = []
        for r in rooms:
            name = r.get("name", "")
            bbox_px = r.get("bbox_px")
            seed_px = r.get("seed_px")
            if (not bbox_px or len(bbox_px) != 4
                or bbox_px[2] <= bbox_px[0] or bbox_px[3] <= bbox_px[1]):
                results.append({"name": name, "error": "invalid bbox_px"})
                continue
            if not seed_px or len(seed_px) != 2:
                results.append({"name": name, "error": "missing seed_px"})
                continue
            cur_seed = (int(seed_px[0]), int(seed_px[1]))
            other_seeds = [s for s in all_seeds_px if s != cur_seed]
            try:
                features = extract_room_features(
                    img,
                    cur_seed,
                    tuple(int(v) for v in bbox_px),
                    scale,
                    transparent_zones_cm=r.get("transparent_zones") or [],
                    doors_px=r.get("doors") or [],
                    door_width_cm=door_width_cm,
                    threshold=threshold,
                    binary_precomputed=_binary_global,
                    binary_raw_precomputed=_binary_raw_global,
                    clip_to_bbox=clip_to_bbox,
                    color_image=color_img,
                    exterior_rgb=get_exterior_rgb(),
                    corridor_rgb=get_corridor_rgb(),
                    other_seeds=other_seeds or None,
                    detection_overrides=get_detection_overrides(),
                    window_mode=window_mode,
                    corridor_face=r.get("corridor_face", "") or "",
                )
                results.append({"name": name, **features})
            except Exception as e:
                results.append({"name": name, "error": str(e)})

        return jsonify({"results": results})
    except Exception as e:
        traceback.print_exc()
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
    block_defs = get_block_defs("SITE")
    rows = pattern.get("rows", [])
    if not rows:
        return 0.0
    total = 0.0
    for block in rows[0].get("blocks", []):
        total += block.get("gap_cm", 0)
        btype = block.get("type", "")
        orient = block.get("orientation", 0)
        bdef = block_defs.get(btype, {})
        eo = bdef.get("eo_cm", 0)
        ns = bdef.get("ns_cm", 0)
        if orient in (90, 270):
            total += ns
        else:
            total += eo
    return total


def _pattern_total_desks(pattern: dict) -> int:
    """Count the total number of desks in a pattern."""
    block_defs = get_block_defs("SITE")
    total = 0
    for row in pattern.get("rows", []):
        for block in row.get("blocks", []):
            bdef = block_defs.get(block.get("type", ""), {})
            total += bdef.get("n_desks", 0)
    return total


@app.route("/api/mock-candidates", methods=["GET"])
def api_mock_candidates():
    """Generate mock candidate solutions for the reference room."""
    patterns = load_catalogue()
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

    JSON body: {"rooms": [...]}.
    Contract (D-122 P5) : les pièces sont envoyées en repère CANONIQUE
    (corridor_face = "south"). width_cm / depth_cm / faces d'openings
    sont déjà normalisés ; le champ `corridor_face_abs` (optionnel) indique
    le repère absolu d'origine pour traçabilité. Le matcher et le catalogue
    étant définis en canonique, aucune rotation n'est appliquée ici.

    Returns matching results per room with all scored candidates.
    """
    try:
        from olm.core.catalogue_matcher import (
            match_room, compute_desk_positions,
        )
        from olm.server.services.serialization import (
            room_from_json, room_to_json,
        )

        data = request.json
        if not data or "rooms" not in data:
            return jsonify({"error": "Required field: rooms"}), 400

        catalogue = load_catalogue()
        results = []

        for r in data["rooms"]:
            room = room_from_json(r)
            match_result = match_room(catalogue, room)

            room_result = room_to_json(room)
            room_result["by_standard"] = {}
            room_result["all_candidates"] = []

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
        from olm.server.services.serialization import room_from_json

        data = request.json
        if not data or "rooms" not in data:
            return jsonify({"error": "Required field: rooms"}), 400

        rooms = [room_from_json(r) for r in data["rooms"]]
        catalogue = load_catalogue()
        report = analyse_coverage(rooms, catalogue)
        return jsonify(report_to_dict(report))

    except Exception as e:
        return jsonify({"error": str(e), "trace": traceback.format_exc()}), 500


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="OLM server")
    parser.add_argument("--dev", action="store_true",
                        help="Enable developer mode (shows debug tools)")
    args = parser.parse_args()
    DEV_MODE = args.dev
    mode_label = " [DEV]" if DEV_MODE else ""
    print(f"Pattern editor{mode_label} — http://localhost:5051")
    from olm.server.services.catalogue_service import CATALOGUE_PATH
    print(f"Catalogue: {CATALOGUE_PATH}")
    app.run(debug=True, port=5051)

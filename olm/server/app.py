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


def _get_plans_dir() -> str:
    """Return the plans directory path from config.json, or the default.

    Reads ``ingestion.plans_dir`` from project/config.json. Relative paths are
    resolved against the project root (parent of BASE_DIR). Falls back to
    ``<root>/project/plans`` if the key is absent or the file unreadable.
    """
    _root = os.path.dirname(BASE_DIR)
    _default = os.path.join(_root, "project", "plans")
    _config_path = os.path.join(_root, "project", "config.json")
    if not os.path.exists(_config_path):
        return _default
    try:
        with open(_config_path, encoding="utf-8") as _f:
            _cfg = json.load(_f)
        _plans_dir = _cfg.get("ingestion", {}).get("plans_dir", "")
        if not _plans_dir:
            return _default
        if os.path.isabs(_plans_dir):
            return _plans_dir
        return os.path.join(_root, _plans_dir)
    except Exception:
        return _default


PLANS_DIR = _get_plans_dir()


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
    plans_dir = _get_plans_dir()
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
                plan_path = os.path.join(_get_plans_dir(), plan_path)
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
            threshold = int(request.form.get('threshold', 110))

            if 'image' in request.files:
                f = request.files['image']
                fd, plan_path = tempfile.mkstemp(suffix='.png')
                os.close(fd)
                f.save(plan_path)
            elif plan_path:
                # Resolve relative plan names to project/plans/ directory
                if not os.path.isabs(plan_path):
                    plan_path = os.path.join(_get_plans_dir(), plan_path)
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
    plans_dir = _get_plans_dir()
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
        # D-140 : `effective_mode = preprocessed` dès que le JSON existe.
        # L'heuristique `json_mtime > png_mtime` était fragile (copie entre
        # machines, git checkout, timezone) et déclenchait à tort le mode
        # OCR quand les fichiers étaient copiés tels quels en prod.
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
    plans_dir = _get_plans_dir()
    if not os.path.isdir(plans_dir):
        return jsonify({"plans": []})
    plans = [f for f in os.listdir(plans_dir)
             if f.lower().endswith(('.png', '.jpg', '.jpeg', '.tiff'))]
    return jsonify({"plans": sorted(plans)})


@app.route("/api/ingestion/plan/<filename>")
def api_ingestion_plan_image(filename):
    """Serve a plan image from project/plans/."""
    return send_from_directory(_get_plans_dir(), filename)


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


@app.route("/api/import/ocr", methods=["POST"])
def api_import_ocr():
    """Mode OCR : upload image (PNG/JPEG/PDF).

    Accepte multipart form avec :
      - floorplan_image : fichier image du plan de sol (PNG, JPEG ou PDF)
      - scale_cm_per_px (optionnel) : cm par pixel ; défaut depuis config.json
      - threshold (optionnel) : seuil de binarisation ; défaut 110

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

    # Valeurs par défaut depuis config.json
    _config_path = os.path.join(os.path.dirname(BASE_DIR), "project", "config.json")
    _default_scale: float = 0.5
    _default_threshold: int = 110
    _pdf_render_dpi: int = 200
    if os.path.exists(_config_path):
        with open(_config_path, encoding="utf-8") as _f:
            _cfg = json.load(_f)
        _ing = _cfg.get("ingestion", {})
        _default_scale = float(_ing.get("scale_cm_per_px", _default_scale))
        _default_threshold = int(_ing.get("threshold", _default_threshold))
        _pdf_render_dpi = int(_ing.get("pdf_render_dpi", _pdf_render_dpi))

    try:
        # Drawing scale (e.g. "1 : 100") takes priority over raw scale_cm_per_px
        import re as _re
        drawing_scale_str = request.form.get("drawing_scale", "").strip()
        render_dpi = int(request.form.get("render_dpi") or 300)
        scale: float | None = None
        if drawing_scale_str:
            m = _re.match(r"1\s*:\s*(\d+(?:\.\d+)?)", drawing_scale_str)
            if m:
                scale = 2.54 * float(m.group(1)) / render_dpi
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

        result = extract_all_rooms(plan_path, scale_cm_per_px=scale, threshold=threshold)

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
        _config_path_pp = os.path.join(os.path.dirname(BASE_DIR), "project", "config.json")
        if os.path.exists(_config_path_pp):
            with open(_config_path_pp, encoding="utf-8") as _fc:
                _cfg_pp = json.load(_fc)
            _ing_pp = _cfg_pp.get("ingestion", {})
            json_data.setdefault("corridor_rgb", _ing_pp.get("preprocessed_corridor_rgb", [193, 247, 179]))
            json_data.setdefault("exterior_rgb", _ing_pp.get("preprocessed_exterior_rgb", [135, 206, 235]))

        # --- Scale resolution: JSON measured > frontend drawing_scale > median ---
        import re as _re_pp
        import math as _math
        render_dpi = int(request.form.get("render_dpi") or 300)

        # 1) drawing_scale_measured from JSON (ruler-based, most reliable)
        measured_scale: float | None = None
        measured_str = str(json_data.get("drawing_scale_measured", "")).strip()
        if measured_str:
            m_val = _re_pp.match(r"([\d.]+)\s*cm/px", measured_str)
            if m_val:
                measured_scale = float(m_val.group(1))

        # 2) drawing_scale from frontend UI (text-based)
        drawing_scale_str = request.form.get("drawing_scale", "").strip()
        text_scale: float | None = None
        if drawing_scale_str:
            m_txt = _re_pp.match(r"1\s*:\s*(\d+(?:\.\d+)?)", drawing_scale_str)
            if m_txt:
                text_scale = 2.54 * float(m_txt.group(1)) / render_dpi

        # Cross-check: log if both sources diverge significantly
        if measured_scale and text_scale:
            ratio = measured_scale / text_scale if text_scale > 0 else 0
            if ratio < 0.8 or ratio > 1.2:
                app.logger.warning(
                    "Scale divergence: measured=%.4f cm/px vs text=%.4f cm/px "
                    "(ratio=%.2f) — using measured value",
                    measured_scale, text_scale, ratio,
                )

        explicit_scale = measured_scale or text_scale

        # Pass explicit scale to extract function if available
        if explicit_scale is not None and explicit_scale > 0:
            json_data["_override_cm_per_px"] = explicit_scale

        # --- Extraction ---
        from olm.ingestion.extract import extract_rooms_from_preprocessed
        rooms = extract_rooms_from_preprocessed(json_data, enhanced_path, overlay_path)

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

        # Scale cm/px : use explicit scale if provided, otherwise median from rooms
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
                        scale_samples.append(_math.sqrt((surf * 10_000.0) / area_px))
            scale_samples.sort()
            scale_cm_per_px = (
                scale_samples[len(scale_samples) // 2] if scale_samples else 0.5
            )

        return jsonify({
            "rooms": rooms,
            "mode": "preprocessed",
            "overlay_path": overlay_path,
            "enhanced_path": enhanced_path,
            "image_size": [page_w, page_h],
            "image_path": overlay_path,
            "scale_cm_per_px": scale_cm_per_px,
            "first_scan_done": bool(json_data.get("first_scan_done", False)),
            "building_id":  str(json_data.get("building_id", "")),
            "floor_id":     str(json_data.get("floor_id", "")),
            "north_angle_deg": float(json_data.get("north_angle_deg", 0) or 0),
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
            "transparent_zones": [
                {"x_cm": z.x_cm, "y_cm": z.y_cm,
                 "width_cm": z.width_cm, "depth_cm": z.depth_cm}
                for z in (room.transparent_zones or [])
            ],
        })
    except RoomDSLError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e), "trace": traceback.format_exc()}), 500


@app.route("/api/room/reanalyze", methods=["POST"])
def api_room_reanalyze():
    """Re-analyse les fenêtres et ouvertures d'une seule pièce (R-04 Review).

    Body JSON attendu :
        {
          "plan_path": "/chemin/vers/plan.png",  (-SD pour Mode Préprocessé)
          "bbox_px": [x0, y0, x1, y1],
          "scale_cm_per_px": 0.5,
          "transparent_zones": [{x_cm, y_cm, width_cm, depth_cm}, ...],
          "threshold": 110  (optionnel)
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
        threshold = int(data.get("threshold", 110))
        clip_to_bbox = bool(data.get("clip_to_bbox", False))

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
        )
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
          "threshold": 110,
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
        threshold = int(data.get("threshold", 110))
        door_width_cm = int(data.get("door_width_cm", 90))
        rooms = data.get("rooms") or []
        clip_to_bbox = bool(data.get("clip_to_bbox", False))

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

        # D-123 perf : binarisation + remove_non_ortho partagées sur toute
        # l'image. ~200-300 ms × N pièces → 1 seule invocation. Les masques
        # room-locaux (portes + zones transparentes) sont zéro-outés
        # localement par `extract_room_features` via `binary_precomputed`.
        _gray_global = _np.asarray(img)
        _binary_raw_global = _gray_global < threshold
        _binary_global = remove_non_ortho(_binary_raw_global)

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
            try:
                features = extract_room_features(
                    img,
                    (int(seed_px[0]), int(seed_px[1])),
                    tuple(int(v) for v in bbox_px),
                    scale,
                    transparent_zones_cm=r.get("transparent_zones") or [],
                    doors_px=[],
                    door_width_cm=door_width_cm,
                    threshold=threshold,
                    binary_precomputed=_binary_global,
                    clip_to_bbox=clip_to_bbox,
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
            # D-141 : skip silencieux des entries non-enrichies (pas de
            # "face"). Cas d'un JSON v3 Input minimal où le pipeline
            # d'enrichissement (ray-cast / détection) n'a pas tourné ou
            # n'a rien attaché. Sans ce filtre, un KeyError "face" casse
            # l'endpoint match (symptôme "Error: 'face'" côté UI).
            windows = [
                WindowSpec(
                    Face(w["face"]), w["offset_cm"], w["width_cm"],
                    origin=w.get("origin"),
                )
                for w in r.get("windows", [])
                if "face" in w and "offset_cm" in w and "width_cm" in w
            ]
            openings = [
                OpeningSpec(
                    Face(o["face"]), o["offset_cm"],
                    o.get("width_cm", 90),
                    o.get("has_door", True),
                    o.get("opens_inward", True),
                    HingeSide(o.get("hinge_side", "left")),
                    origin=o.get("origin"),
                )
                for o in r.get("openings", [])
                if "face" in o and "offset_cm" in o
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
                     "width_cm": w.width_cm,
                     **({"origin": w.origin} if w.origin else {})}
                    for w in room.windows
                ],
                "openings": [
                    {"face": o.face.value, "offset_cm": o.offset_cm,
                     "width_cm": o.width_cm, "has_door": o.has_door,
                     "opens_inward": o.opens_inward,
                     "hinge_side": o.hinge_side.value,
                     **({"origin": o.origin} if o.origin else {})}
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
            # D-141 : skip silencieux des entries non-enrichies (cf.
            # /api/floor-plan/match ci-dessus).
            windows = [
                WindowSpec(
                    face=Face(w["face"]),
                    offset_cm=w["offset_cm"],
                    width_cm=w["width_cm"],
                )
                for w in r.get("windows", [])
                if "face" in w and "offset_cm" in w and "width_cm" in w
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
                if "face" in o and "offset_cm" in o
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

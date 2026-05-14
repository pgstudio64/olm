"""Ingestion service — plans, extraction, reanalyze, diagnostics, orientation.

Handles groups B (plans & ingestion) and C (rooms) endpoints.
All functions accept pre-parsed parameters (no Flask objects).
"""
from __future__ import annotations

import io
import json
import logging
import math
import os
import re
import shutil
import tempfile
import time
import uuid

import numpy as np
from PIL import Image as PILImage

from olm.server.services.config_service import (
    get_corridor_rgb,
    get_default_threshold,
    get_detection_overrides,
    get_exterior_rgb,
    get_plans_dir,
)

logger = logging.getLogger(__name__)

_INCH_TO_CM = 2.54


def drawing_scale_to_cm_per_px(
    text: str, render_dpi: int,
) -> float | None:
    """Convert a '1 : N' text to cm/px via render DPI."""
    m = re.match(r"1\s*:\s*(\d+(?:\.\d+)?)", text.strip())
    if not m or render_dpi <= 0:
        return None
    return _INCH_TO_CM * float(m.group(1)) / render_dpi


# ---------------------------------------------------------------------------
# Plans listing
# ---------------------------------------------------------------------------


def list_plans() -> dict:
    """List available plans in project/plans/ (grouped by stem).

    Returns:
        ``{"plans": [{"id", "has_png", "has_json", "has_enhanced",
        "effective_mode"}, ...]}``.
    """
    plans_dir = get_plans_dir()
    if not os.path.isdir(plans_dir):
        return {"plans": []}
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
        effective_mode = "preprocessed" if info["has_json"] else "ocr"
        plans.append({
            "id": stem,
            "has_png": info["has_png"],
            "has_json": info["has_json"],
            "has_enhanced": info["has_enhanced"],
            "effective_mode": effective_mode,
        })
    return {"plans": plans}


def list_ingestion_plans() -> dict:
    """List available plan image files.

    Returns:
        ``{"plans": [filename, ...]}``.
    """
    plans_dir = get_plans_dir()
    if not os.path.isdir(plans_dir):
        return {"plans": []}
    plans = [
        f for f in os.listdir(plans_dir)
        if f.lower().endswith(('.png', '.jpg', '.jpeg', '.tiff'))
    ]
    return {"plans": sorted(plans)}


# ---------------------------------------------------------------------------
# Plan metadata / save / reinit
# ---------------------------------------------------------------------------


def get_plan_metadata(plan_id: str) -> dict:
    """Return lightweight metadata from a plan JSON.

    Raises:
        FileNotFoundError: if JSON is absent.
    """
    plans_dir = get_plans_dir()
    json_path = os.path.join(plans_dir, plan_id + ".json")
    if not os.path.exists(json_path):
        raise FileNotFoundError("JSON not found")
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)
    rooms_summary = []
    rooms = data.get("rooms", [])
    rooms_iter = (
        rooms.items() if isinstance(rooms, dict)
        else (("", r) for r in rooms)
    )
    for room_id, r in rooms_iter:
        bbox = r.get("bbox_px")
        if bbox and len(bbox) == 4:
            rooms_summary.append({
                "name": room_id or r.get("room_id", ""),
                "bbox_px": [int(v) for v in bbox],
            })
    page_w = int(data.get("page_width_px") or 0)
    page_h = int(data.get("page_height_px") or 0)
    if page_w <= 0 or page_h <= 0:
        png_path = os.path.join(plans_dir, plan_id + ".png")
        if os.path.exists(png_path):
            with PILImage.open(png_path) as im:
                page_w, page_h = im.size
    return {
        "building_id": str(data.get("building_id", "")),
        "floor_id": str(data.get("floor_id", "")),
        "north_angle_deg": float(data.get("north_angle_deg", 0) or 0),
        "drawing_scale_text": str(data.get("drawing_scale_text", "")),
        "mode": data.get("mode", "preprocessed"),
        "image_size": [page_w, page_h],
        "rooms_summary": rooms_summary,
    }


def save_plan(plan_id: str, data: dict) -> dict:
    """Save a full plan JSON to disk.

    Raises:
        ValueError: if payload is empty.
    """
    if not data:
        raise ValueError("Empty payload")
    plans_dir = get_plans_dir()
    json_path = os.path.join(plans_dir, plan_id + ".json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return {"ok": True, "path": json_path}


def reinit_plan(plan_id: str) -> dict:
    """Strip a plan JSON to preprocessing-only data and save.

    Raises:
        FileNotFoundError: if JSON is absent.
    """
    plans_dir = get_plans_dir()
    json_path = os.path.join(plans_dir, plan_id + ".json")
    if not os.path.exists(json_path):
        raise FileNotFoundError(f"JSON not found for '{plan_id}'")
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)

    clean = {}
    for key in ("file", "page_width_px", "page_height_px",
                "drawing_scale_text", "render_dpi"):
        if key in data:
            clean[key] = data[key]

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
            seed_doors = []
            for d in (r.get("doors") or []):
                if (isinstance(d, dict) and "seed_x" in d
                        and not d.get("face")):
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
    return {"ok": True, "path": json_path}


# ---------------------------------------------------------------------------
# Binarize
# ---------------------------------------------------------------------------


def binarize_image(plan_path: str, threshold: int) -> io.BytesIO:
    """Binarize a plan image and return PNG bytes.

    Args:
        plan_path: path to the image.
        threshold: binarization threshold.

    Returns:
        BytesIO with PNG data.
    """
    img = PILImage.open(plan_path).convert("L")
    gray = np.array(img)
    binary = gray < threshold
    bin_img = PILImage.fromarray((~binary * 255).astype(np.uint8))
    buf = io.BytesIO()
    bin_img.save(buf, format='PNG')
    buf.seek(0)
    return buf


# ---------------------------------------------------------------------------
# Extract (raw)
# ---------------------------------------------------------------------------


def extract_rooms(
    plan_path: str,
    scale: float | None,
    threshold: int,
) -> dict:
    """Run raw room extraction on a plan image.

    Returns:
        Extraction result dict.
    """
    from olm.ingestion.comb_detection import extract_all_rooms
    return extract_all_rooms(
        plan_path, scale_cm_per_px=scale, threshold=threshold,
        detection_overrides=get_detection_overrides(),
    )


def extract_rooms_debug(
    plan_path: str,
    scale: float | None,
    threshold: int,
) -> dict:
    """Run raw extraction with debug log capture.

    Returns:
        Extraction result dict with ``logs`` key added.
    """
    from io import StringIO
    log_capture = StringIO()
    handler = logging.StreamHandler(log_capture)
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(logging.Formatter('[%(levelname)s] %(message)s'))

    ingestion_logger = logging.getLogger('test_comb')
    ingestion_logger.addHandler(handler)
    ingestion_logger.setLevel(logging.DEBUG)
    ingestion_logger.propagate = True
    try:
        result = extract_rooms(plan_path, scale, threshold)
        log_text = log_capture.getvalue()
        result['logs'] = [
            line.strip()
            for line in log_text.split('\n') if line.strip()
        ]
        return result
    finally:
        ingestion_logger.removeHandler(handler)
        handler.close()


# ---------------------------------------------------------------------------
# Import OCR
# ---------------------------------------------------------------------------


def import_ocr(
    plan_path: str,
    scale: float | None,
    threshold: int,
    use_temp: bool,
) -> dict:
    """Core OCR import logic (after file handling).

    Args:
        plan_path: path to the plan PNG (temp or permanent).
        scale: cm/px override or None.
        threshold: binarization threshold.
        use_temp: whether plan_path is a temp file needing overlay move.

    Returns:
        Import result dict.
    """
    from olm.ingestion.comb_detection import extract_all_rooms

    result = extract_all_rooms(
        plan_path, scale_cm_per_px=scale, threshold=threshold,
        detection_overrides=get_detection_overrides(),
    )

    if use_temp:
        overlay_dir = os.path.join(tempfile.gettempdir(), "olm_overlays")
        os.makedirs(overlay_dir, exist_ok=True)
        overlay_filename = "overlay_" + uuid.uuid4().hex + ".png"
        overlay_path = os.path.join(overlay_dir, overlay_filename)
        shutil.move(plan_path, overlay_path)
        result["image_path"] = overlay_path
    else:
        result["image_path"] = plan_path

    result["mode"] = "ocr"
    return result


def resolve_plan_id_image(plan_id: str) -> str:
    """Resolve a plan_id to its image file path.

    Raises:
        FileNotFoundError: if no image found for plan_id.
    """
    plans_dir = get_plans_dir()
    for ext in (".png", ".jpg", ".jpeg", ".PNG", ".JPG", ".JPEG"):
        candidate = os.path.join(plans_dir, plan_id + ext)
        if os.path.exists(candidate):
            return candidate
    raise FileNotFoundError(
        f"Plan '{plan_id}' introuvable dans project/plans/")


def resolve_preprocessed_files(plan_id: str) -> tuple[dict, str, str]:
    """Resolve a plan_id to preprocessed files (JSON + overlay + enhanced).

    Returns:
        (json_data, enhanced_path, overlay_path).

    Raises:
        FileNotFoundError: if required files are missing.
    """
    plans_dir = get_plans_dir()
    json_path = os.path.join(plans_dir, plan_id + ".json")
    if not os.path.exists(json_path):
        raise FileNotFoundError(
            f"Preprocessed mode: JSON file missing for plan '{plan_id}'")
    with open(json_path, encoding="utf-8") as f:
        json_data = json.load(f)

    overlay_path = ""
    for ext in (".png", ".PNG"):
        candidate = os.path.join(plans_dir, plan_id + ext)
        if os.path.exists(candidate):
            overlay_path = candidate
            break
    if not overlay_path:
        raise FileNotFoundError(
            f"Plan PNG manquant pour '{plan_id}'")

    sd_candidate = os.path.join(plans_dir, plan_id + "-SD.png")
    enhanced_path = (
        sd_candidate if os.path.exists(sd_candidate) else overlay_path
    )
    return json_data, enhanced_path, overlay_path


def cleanup_old_overlays() -> None:
    """Best-effort cleanup of overlay temp files older than 1 hour."""
    overlay_dir = os.path.join(tempfile.gettempdir(), "olm_overlays")
    os.makedirs(overlay_dir, exist_ok=True)
    cutoff = time.time() - 3600
    try:
        for f in os.listdir(overlay_dir):
            fp = os.path.join(overlay_dir, f)
            try:
                if os.path.getmtime(fp) < cutoff:
                    os.unlink(fp)
            except OSError:
                pass
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Import preprocessed
# ---------------------------------------------------------------------------


def import_preprocessed(
    json_data: dict,
    enhanced_path: str,
    overlay_path: str,
    *,
    drawing_scale_str: str = "",
    render_dpi_form: int | None = None,
    scale_source: str = "",
    window_mode: str = "simple",
) -> dict:
    """Core preprocessed import logic.

    Args:
        json_data: parsed plan JSON.
        enhanced_path: path to -SD PNG.
        overlay_path: path to overlay PNG.
        drawing_scale_str: manual drawing scale from form.
        render_dpi_form: render DPI from form.
        scale_source: which scale source to use.
        window_mode: window detection mode.

    Returns:
        Import result dict.
    """
    # Inject semantic colors
    json_data.setdefault("corridor_rgb", list(get_corridor_rgb()))
    json_data.setdefault("exterior_rgb", list(get_exterior_rgb()))

    # --- Scale resolution ---
    render_dpi = int(
        json_data.get("render_dpi")
        or render_dpi_form
        or 300
    )

    dst_raw = str(json_data.get("drawing_scale_text", "")).strip()
    notation_scale = drawing_scale_to_cm_per_px(
        dst_raw, render_dpi) if dst_raw else None

    ruler_scale: float | None = None
    measured_str = str(
        json_data.get("drawing_scale_measured", "")
    ).strip()
    if measured_str:
        m_val = re.match(r"([\d.]+)\s*cm/px", measured_str)
        if m_val:
            ruler_scale = float(m_val.group(1))

    manual_scale = drawing_scale_to_cm_per_px(
        drawing_scale_str, render_dpi) if drawing_scale_str else None

    if scale_source == "notation" and notation_scale:
        explicit_scale = notation_scale
    elif scale_source == "ruler" and ruler_scale:
        explicit_scale = ruler_scale
    elif scale_source == "manual" and manual_scale:
        explicit_scale = manual_scale
    else:
        explicit_scale = notation_scale or ruler_scale or manual_scale

    if explicit_scale is not None and explicit_scale > 0:
        json_data["_override_cm_per_px"] = explicit_scale

    det_overrides = get_detection_overrides()
    if det_overrides:
        json_data["_detection_overrides"] = det_overrides

    # --- Extraction ---
    from olm.ingestion.extract import extract_rooms_from_preprocessed
    rooms = extract_rooms_from_preprocessed(
        json_data, enhanced_path, overlay_path,
        window_mode=window_mode,
    )

    # Image size
    page_w = int(json_data.get("page_width_px") or 0)
    page_h = int(json_data.get("page_height_px") or 0)
    if page_w <= 0 or page_h <= 0:
        try:
            with PILImage.open(overlay_path) as im:
                page_w, page_h = im.size
        except Exception:
            page_w = page_h = 0

    # Scale cm/px
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
                        math.sqrt((surf * 10_000.0) / area_px)
                    )
        scale_samples.sort()
        scale_cm_per_px = (
            scale_samples[len(scale_samples) // 2]
            if scale_samples else 0.0
        )

    return {
        "rooms": rooms,
        "mode": json_data.get("mode", "preprocessed"),
        "overlay_path": overlay_path,
        "enhanced_path": enhanced_path,
        "image_size": [page_w, page_h],
        "image_path": overlay_path,
        "scale_cm_per_px": scale_cm_per_px,
        "render_dpi": render_dpi,
        "drawing_scale_text": str(
            json_data.get("drawing_scale_text", "")),
        "notation_scale_cm_per_px": notation_scale or 0,
        "ruler_scale_cm_per_px": ruler_scale or 0,
        "scale_source": scale_source or "auto",
        "first_scan_done": bool(
            json_data.get("first_scan_done", False)),
        "building_id": str(json_data.get("building_id", "")),
        "floor_id": str(json_data.get("floor_id", "")),
        "north_angle_deg": float(
            json_data.get("north_angle_deg", 0) or 0),
    }


# ---------------------------------------------------------------------------
# Reanalyze (single room)
# ---------------------------------------------------------------------------


def reanalyze_room(data: dict) -> dict:
    """Re-analyze windows and openings for a single room.

    Args:
        data: parsed request body.

    Returns:
        Feature dict with ``windows``, ``openings``, etc.

    Raises:
        ValueError: if required fields are missing/invalid.
    """
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
    window_mode = (
        data.get("window_mode", "detailed")
        if mode != "ocr" else "detailed"
    )
    raw_other = data.get("other_seeds_px") or []
    other_seeds_px = [
        (int(s[0]), int(s[1]))
        for s in raw_other if s and len(s) >= 2
    ]
    corridor_face_abs = data.get("corridor_face", "") or ""

    if not plan_path or not os.path.exists(plan_path):
        raise ValueError("plan_path missing or invalid")
    if not seed_px or len(seed_px) != 2:
        raise ValueError("seed_px must be [x, y]")
    if bbox_px:
        try:
            bbox_px = [int(v) for v in bbox_px]
        except (TypeError, ValueError):
            raise ValueError("bbox_px must contain integers")
        if bbox_px[2] <= bbox_px[0] or bbox_px[3] <= bbox_px[1]:
            bbox_px = None

    from olm.ingestion.extract import extract_room_features
    img = PILImage.open(plan_path).convert("L")

    color_img = None
    if mode != "ocr" and plan_path and os.path.exists(plan_path):
        color_img = PILImage.open(plan_path)

    from olm.ingestion.comb_detection import _apply_detection_config
    _apply_detection_config(scale, get_detection_overrides())

    cart_bboxes_px: list = []
    if mode == "ocr":
        from olm.ingestion.comb_detection import find_seeds_by_ocr
        _seeds, cart_bboxes_px = find_seeds_by_ocr(img)

    return extract_room_features(
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


# ---------------------------------------------------------------------------
# Room diagnostic
# ---------------------------------------------------------------------------


def room_diagnostic(data: dict) -> dict:
    """Run detection with full debug info for a single room.

    Args:
        data: parsed request body (same as reanalyze + optional room_name).

    Returns:
        Feature dict augmented with ``diag``, ``color_detection``, etc.

    Raises:
        ValueError: if required fields are missing/invalid.
    """
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
    other_seeds_px = [
        (int(s[0]), int(s[1]))
        for s in raw_other if s and len(s) >= 2
    ]

    if not plan_path or not os.path.exists(plan_path):
        raise ValueError("plan_path missing or invalid")
    if not seed_px or len(seed_px) != 2:
        raise ValueError("seed_px must be [x, y]")
    if bbox_px:
        try:
            bbox_px = [int(v) for v in bbox_px]
        except (TypeError, ValueError):
            raise ValueError("bbox_px must contain ints")
        if bbox_px[2] <= bbox_px[0] or bbox_px[3] <= bbox_px[1]:
            bbox_px = None

    from olm.ingestion.extract import extract_room_features
    img = PILImage.open(plan_path).convert("L")

    color_img = None
    if mode != "ocr" and plan_path and os.path.exists(plan_path):
        color_img = PILImage.open(plan_path)

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
    diag['binarize_threshold'] = threshold
    diag['door_width_px'] = int(round(door_width_cm / scale))
    result["diag"] = diag
    result["other_seeds_count"] = len(other_seeds_px)

    # Color detection on detected bbox
    detected_bbox = result.get("bbox_px")
    if detected_bbox and color_img and mode != "ocr":
        try:
            from olm.ingestion.extract import _detect_face_colors
            rgb_arr = np.array(color_img.convert("RGB"))
            colors = _detect_face_colors(
                rgb_arr, detected_bbox,
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

    return result


# ---------------------------------------------------------------------------
# Orientation check / report
# ---------------------------------------------------------------------------


def orientation_check(data: dict) -> dict:
    """Check canonical orientation of a single room.

    Raises:
        ValueError: if required fields are missing.
    """
    plan_path = data.get("plan_path", "")
    bbox_px = data.get("bbox_px")
    ocf = data.get("corridor_face_abs", "") or ""

    if not plan_path or not os.path.exists(plan_path):
        raise ValueError("plan_path missing or invalid")
    if not bbox_px or len(bbox_px) != 4:
        raise ValueError("bbox_px must be [x0,y0,x1,y1]")

    from olm.ingestion.orientation_check import (
        check_all_faces,
        check_corridor_south,
        check_exterior_north,
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
    return {
        "corridor_face_abs": ocf,
        "faces": faces["faces"],
        "corridor_south": corridor,
        "exterior_north": exterior,
        "windows": windows,
    }


def orientation_report(data: dict) -> dict:
    """Batch orientation report for all rooms in a plan.

    Raises:
        ValueError: if required fields are missing.
    """
    plan_path = data.get("plan_path", "")
    rooms = data.get("rooms") or []
    scale = float(data.get("scale_cm_per_px", 0) or 0)

    if not plan_path or not os.path.exists(plan_path):
        raise ValueError("plan_path missing or invalid")
    if not isinstance(rooms, list) or not rooms:
        raise ValueError("rooms must be non-empty list")

    from olm.ingestion.orientation_check import (
        check_corridor_south,
        check_exterior_north,
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
            corridor_ok = corridor.get("ok", False)
            windows_ok = (
                windows_res is None
                or windows_res.get("verdict") in ("ok", "")
            )
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

    return {
        "results": results,
        "summary": {
            "n_total": len(rooms),
            "n_ok": n_ok,
            "n_warn": n_warn,
            "n_fail": len(failing),
            "failing": failing,
        },
    }


# ---------------------------------------------------------------------------
# Reanalyze batch
# ---------------------------------------------------------------------------


def reanalyze_batch(data: dict) -> dict:
    """Batch re-analyze N rooms sharing a single image load.

    Args:
        data: parsed request body.

    Returns:
        ``{"results": [...]}``.

    Raises:
        ValueError: if required fields are missing.
    """
    plan_path = data.get("plan_path", "")
    scale = float(data.get("scale_cm_per_px", 0.5))
    threshold = int(data.get("threshold", get_default_threshold()))
    door_width_cm = int(data.get("door_width_cm", 90))
    rooms = data.get("rooms") or []
    clip_to_bbox = bool(data.get("clip_to_bbox", False))
    mode = (data.get("mode") or "preprocessed").lower()
    window_mode = (
        data.get("window_mode", "detailed")
        if mode != "ocr" else "detailed"
    )

    if not plan_path or not os.path.exists(plan_path):
        raise ValueError("plan_path missing or invalid")
    if not isinstance(rooms, list) or not rooms:
        raise ValueError("rooms must be non-empty list")

    from olm.ingestion.extract import extract_room_features

    img = PILImage.open(plan_path).convert("L")

    color_img = None
    if mode != "ocr" and plan_path and os.path.exists(plan_path):
        color_img = PILImage.open(plan_path)

    from olm.ingestion.comb_detection import _apply_detection_config
    _apply_detection_config(scale, get_detection_overrides())

    gray_global = np.asarray(img)

    if mode == "ocr":
        from olm.ingestion.comb_detection import (
            erase_cartouches,
            find_seeds_by_ocr,
        )
        _seeds, _cart_bboxes_px = find_seeds_by_ocr(img)
        gray_global = erase_cartouches(gray_global, _cart_bboxes_px)

    binary_raw_global = gray_global < threshold
    binary_global = binary_raw_global.copy()

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
                or bbox_px[2] <= bbox_px[0]
                or bbox_px[3] <= bbox_px[1]):
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
                binary_precomputed=binary_global,
                binary_raw_precomputed=binary_raw_global,
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

    return {"results": results}

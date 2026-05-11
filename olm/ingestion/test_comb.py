"""
Test of the adaptive comb on test_floorplan2.png.

Full pipeline:
  1. OCR (pytesseract --psm 11, upscale x2) → find all "14" codes
  2. Syntactic parsing of label boxes → seed = geometric center, name = room number
  3. Binarize at threshold 80
  4. Erase label boxes → white
  5. Adaptive comb (dynamic stop condition) → grid of hit points
  6. Largest rectangle containing the seed
  7. Debug visualization

Usage:
  python /tmp/test_comb.py              # all rooms
  python /tmp/test_comb.py 916          # room 916 only
"""

import os
import re
import sys
import tempfile
import logging
from dataclasses import dataclass, field
import numpy as np
import cv2
from PIL import Image, ImageDraw
from collections import deque

logger = logging.getLogger(__name__)

_TMP = tempfile.gettempdir()

# Debug flag — set to True to save intermediate images to /tmp/
DEBUG_IMAGES = True

# Import config to get parameterizable room code
try:
    from olm.core.app_config import get_room_code
except ImportError:
    def get_room_code():
        return "14"  # fallback default

# --- Parameters ---
# Allow PLAN_PATH to be overridden via environment variable
if "PLAN_PATH" in os.environ:
    PLAN_PATH = os.environ["PLAN_PATH"]
else:
    PLAN_PATH = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "project", "plans", "test_floorplan3.png"
    )
BINARIZE_THRESHOLD = 140
COMB_STEP_PX = 5   # comb step in pixels
MAX_RAY_PX = 1500
CARTOUCHE_MARGIN_PX = 1
MIN_DOOR_ARC_HITS = 3   # min hits per direction to validate a door arc
MIN_OBSTACLE_WIDTH_PX = 15  # default ~30cm at 0.5 cm/px; updated by _apply
MIN_PILLAR_SIZE_PX = 8    # default ~15cm at 0.5 cm/px; updated by _apply
MAX_PILLAR_SIZE_PX = 60   # default ~30cm at 0.5 cm/px; updated by _apply

# --- Scale auto-calibration from OCR surfaces ---
# Minimum annotated surface (m²) for a room to be used in scale calibration.
# Rooms below this threshold are more likely to have incorrect bboxes.
MIN_CALIB_SURFACE_M2 = 8.0
# Minimum bbox dimension (px) for calibration eligibility.
MIN_CALIB_DIM_PX = 20
# Margin from image edge (px) — rooms touching the edge likely have a
# truncated bbox and should not be used for calibration.
CALIB_EDGE_MARGIN_PX = 5


def _apply_detection_config(scale_cm_per_px: float,
                            config_overrides: dict | None = None) -> None:
    """Met à jour les constantes px du module depuis la detection_config.

    À appeler au début d'une exécution quand le scale est connu. Modifie
    l'état module (acceptable en contexte outil local mono-thread).

    Args:
        scale_cm_per_px: Échelle cm par pixel.
        config_overrides: Dict partiel de valeurs cm écrasant les défauts
            (ex. ``{"cartouche_margin_cm": 5.0}``). Clés inconnues ignorées.
    """
    from olm.core.detection_config import (
        DEFAULT_DETECTION_CONFIG_CM, DetectionConfigCm,
    )
    base = (DetectionConfigCm.from_dict(config_overrides)
            if config_overrides else DEFAULT_DETECTION_CONFIG_CM)
    cfg = base.to_px(scale_cm_per_px)
    global BINARIZE_THRESHOLD, COMB_STEP_PX, MAX_RAY_PX, CARTOUCHE_MARGIN_PX
    global COARSE_STEP_PX, RAY_MARGIN_PX, SNAP_SEARCH_PX
    global DOOR_PROBE_PX, DOOR_GROUP_GAP_PX, WALL_MARGIN_PX
    global MIN_DOOR_ARC_HITS, MIN_OBSTACLE_WIDTH_PX
    global MIN_PILLAR_SIZE_PX, MAX_PILLAR_SIZE_PX
    BINARIZE_THRESHOLD = cfg.binarize_threshold
    COMB_STEP_PX = cfg.comb_step_px
    MAX_RAY_PX = cfg.max_ray_px
    CARTOUCHE_MARGIN_PX = cfg.cartouche_margin_px
    COARSE_STEP_PX = cfg.coarse_step_px
    RAY_MARGIN_PX = cfg.ray_margin_px
    SNAP_SEARCH_PX = cfg.snap_search_px
    DOOR_PROBE_PX = cfg.door_probe_depth_px
    DOOR_GROUP_GAP_PX = cfg.door_group_gap_px
    WALL_MARGIN_PX = cfg.door_wall_margin_px
    MIN_DOOR_ARC_HITS = cfg.min_door_arc_hits
    MIN_OBSTACLE_WIDTH_PX = cfg.min_obstacle_width_px
    MIN_PILLAR_SIZE_PX = cfg.min_pillar_size_px
    MAX_PILLAR_SIZE_PX = cfg.max_pillar_size_px

# --- Tesseract OCR parameters ---
# Upscale factor applied before OCR — small cartouche text (10-20 px) needs enlargement
TESSERACT_UPSCALE = 2
# Whitelist: characters expected in floor plan cartouches.
# Covers all three token types:
#   - room code   : 2 digits + optional letter     → "14", "14c", "12d"
#   - surface     : decimal number + " m2"         → "14.28 m2", "9.8 m2"
#   - room number : 1-3 digits, or 2d+letter,
#                   or 1d+2letters                 → "916", "12a", "1AB"
# Dictionaries are disabled explicitly via load_system_dawg/load_freq_dawg
# (whitelist alone is insufficient when letters are present).
TESSERACT_CHAR_WHITELIST = "0123456789.,abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ "

# Regex patterns for the three token types found in floor plan cartouches.
# Used to filter OCR output and classify detected words.
_RE_ROOM_CODE = re.compile(r"^\d{2}[a-zA-Z]?$")          # "14", "14c", "12d"
_RE_ROOM_NUMBER = re.compile(
    r"^\d{1,3}$"           # 1, 2 or 3 digits:      "5", "12", "916"
    r"|^\d{2}[a-zA-Z]$"   # 2 digits + 1 letter:   "12a"
    r"|^\d[a-zA-Z]{2}$"   # 1 digit  + 2 letters:  "1AB"
)
_RE_SURFACE = re.compile(r"^\d+\.\d+$")                   # "14.28", "9.8" (the "m2" is a separate token)
# Stragglers du cartouche que l'OCR détecte comme tokens séparés et
# qui tombent souvent juste hors du cluster (window_h trop étroit) :
# "m²" tokenisé à part de la surface. Cas observé : pièce 913 où
# "26.10" est dans le cluster mais "m²" reste 30 px à droite, hors
# window_h=25.
#
# Restriction stricte : ne JAMAIS y mettre des patterns qui matchent
# des codes ("\d{1,2}" capture "14"), des surfaces ou des fragments
# de lettres ("[a-zA-Z]{1,3}" capture "BU" du caption BULLE) — ces
# tokens existent dans les pièces voisines ou les annotations
# adjacentes et leur absorption fait déborder le bbox sur les murs
# limitrophes (régression observée 916 → mur nord effacé).
_RE_CARTOUCHE_STRAGGLER = re.compile(r"^(m2|m²|²)$")


def load_image(path):
    return Image.open(path).convert("L")


def find_seeds_by_ocr(image):
    import subprocess
    import json as json_lib

    room_code = get_room_code()
    logger.debug(f"OCR: searching for room code '{room_code}'")

    # Upscale the image before OCR: cartouche text is typically 10-20 px tall,
    # Tesseract performs significantly better at 20-40 px (≥ 300 DPI equivalent).
    w_orig, h_orig = image.size
    if TESSERACT_UPSCALE > 1:
        upscaled = image.resize(
            (w_orig * TESSERACT_UPSCALE, h_orig * TESSERACT_UPSCALE),
            Image.LANCZOS,
        )
        logger.debug(f"OCR: upscaled {w_orig}×{h_orig} → {upscaled.width}×{upscaled.height}")
    else:
        upscaled = image

    # Save image to temp file for tesseract
    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
        upscaled.save(tmp.name)
        tmp_path = tmp.name

    try:
        # Tesseract configuration:
        #   --psm 11  Sparse text — finds tokens that are isolated in whitespace,
        #             excellent when cartouche lines are clearly separated.
        #   --psm  6  Uniform block — reads text as a dense block, better when
        #             cartouche lines are packed tight (3-line format D-81).
        #   --oem 3   Default engine (LSTM + legacy fallback)
        #   tessedit_char_whitelist / load_*_dawg=0  See comments in older commits.
        # We run BOTH PSM 11 and PSM 6, then merge + deduplicate the tokens. The
        # two modes catch different cartouches on the same plan (PSM 11 misses
        # tight 3-line cartouches, PSM 6 handles them; PSM 11 catches isolated
        # cartouches that PSM 6 sometimes groups with neighbours).

        def _run_tesseract_pass(psm_mode):
            return subprocess.run(
                [
                    'tesseract', tmp_path, 'stdout',
                    '--psm', str(psm_mode),
                    '--oem', '3',
                    '-c', f'tessedit_char_whitelist={TESSERACT_CHAR_WHITELIST}',
                    '-c', 'load_system_dawg=0',
                    '-c', 'load_freq_dawg=0',
                    'tsv',
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )

        words = []
        seen_keys = set()  # dedupe by (text, rounded cx, rounded cy)
        skipped_lines = 0
        low_conf = 0

        for psm_mode in (11, 6):
            result = _run_tesseract_pass(psm_mode)
            if result.returncode != 0:
                logger.warning(f"tesseract PSM {psm_mode} failed: {result.stderr}")
                continue

            lines = result.stdout.split('\n')
            logger.debug(f"Tesseract PSM {psm_mode}: {len(lines)} lines")
            for i, line in enumerate(lines):
                if not line.strip() or line.startswith('level') or 'Estimating' in line:
                    continue
                parts = line.split('\t')
                if len(parts) < 12:
                    skipped_lines += 1
                    continue
                try:
                    text = parts[11].strip()
                    conf = float(parts[10]) if parts[10] else -1
                    x = int(parts[6])
                    y = int(parts[7])
                    w = int(parts[8])
                    h = int(parts[9])

                    if not text:
                        low_conf += 1
                        continue
                    if conf < 0:
                        low_conf += 1
                        continue

                    # Divide coordinates back to original image space (undo upscale)
                    scale = TESSERACT_UPSCALE
                    cx = (x + w // 2) // scale
                    cy = (y + h // 2) // scale

                    # Dedupe: same text within a 10-px radius across passes counts once
                    key = (text, cx // 10, cy // 10)
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)

                    words.append({
                        "text": text,
                        "cx": cx,
                        "cy": cy,
                        "x": x // scale,
                        "y": y // scale,
                        "w": w // scale,
                        "h": h // scale,
                    })
                except (ValueError, IndexError) as e:
                    low_conf += 1
                    logger.debug(f"    PSM {psm_mode} parse error on line {i}: {e}")
                    continue

    except FileNotFoundError:
        logger.warning("tesseract not installed: brew install tesseract (macOS) or apt-get install tesseract-ocr (Linux)")
        return {}, []
    except subprocess.TimeoutExpired:
        logger.warning("tesseract timeout")
        return {}, []
    finally:
        # Clean up temp file
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

        logger.debug(f"  Skipped {skipped_lines} lines (< 12 parts), {low_conf} low-conf items")

    words.sort(key=lambda w: (w["cy"], w["cx"]))
    logger.debug(f"OCR: detected {len(words)} text elements")
    if words:
        logger.debug(f"Words found: {[w['text'] for w in words[:10]]}...")  # show first 10
        # Report detected token types using the canonical regex patterns
        room_numbers = [w['text'] for w in words if _RE_ROOM_NUMBER.match(w['text'])]
        surfaces = [w['text'] for w in words if _RE_SURFACE.match(w['text'])]
        logger.debug(f"OCR: {len(room_numbers)} room number candidates: {room_numbers}")
        logger.debug(f"OCR: {len(surfaces)} surface candidates: {surfaces}")

    # Cluster-based cartouche detection (generic, font-agnostic).
    #
    # Rationale: anchoring on a specific room_code ("14") is fragile because
    # (a) Tesseract sometimes fails to segment the code line, and
    # (b) greedy 1:1 matching from code to id mis-pairs when a cartouche is
    #     partially unreadable (cascading mis-assignments).
    # Surfaces are a much more reliable anchor: the format "X.XX" (with or
    # without a " m²" suffix token) is near-universal across floor plans and
    # rarely appears outside cartouches.
    #
    # Algorithm:
    #   1. Compute h_med, the median text height → adaptive spatial window.
    #   2. For each surface token, collect all tokens within ±3·h_med vertical
    #      and ±1.5·h_med horizontal → the cartouche cluster.
    #   3. Identify the ID (longest _RE_ROOM_NUMBER token in the cluster).
    #   4. If room_code is configured, require one of its tokens in the
    #      cluster — filters out non-target cartouches (meeting rooms, etc.).
    #      If no room_code configured, accept every cluster.
    # Meeting-room labels like "93A" are naturally rejected: they have no
    # neighbouring surface, so no cluster forms around them.

    seeds = {}
    cartouche_bboxes = []

    # Median text height over tokens likely to belong to cartouches (digits or
    # the "m" unit token). Using all tokens would pull the median toward noise
    # (small garbled fragments) and undersize the clustering window.
    _cartouche_heights = [
        w["h"] for w in words
        if w["h"] > 0 and (w["text"].replace(".", "").replace(",", "").isdigit()
                            or w["text"] in ("m", "m2", "m²"))
    ]
    if _cartouche_heights:
        _cartouche_heights.sort()
        h_med = _cartouche_heights[len(_cartouche_heights) // 2]
    else:
        h_med = 15  # safe fallback (typical cartouche text height)

    # Vertical window must span the tallest cartouche (5 lines with gaps ≈ 7·h)
    window_v = max(int(h_med * 7.0), 70)
    window_h = int(h_med * 2.5)   # horizontal cluster extent (cartouche is ~narrow)
    logger.debug(f"OCR: h_med={h_med}, window_v={window_v}, window_h={window_h}")

    # Index surface tokens (the anchors)
    surface_tokens = [w for w in words if _RE_SURFACE.match(w["text"])]
    logger.debug(f"OCR: {len(surface_tokens)} surface anchor(s) found")

    used_surfaces = set()  # prevent double-anchoring when multiple surfaces overlap

    for anchor in surface_tokens:
        if id(anchor) in used_surfaces:
            continue
        used_surfaces.add(id(anchor))

        ax, ay = anchor["cx"], anchor["cy"]

        # Collect all tokens within the cluster window
        cluster = []
        for w in words:
            if abs(w["cx"] - ax) <= window_h and abs(w["cy"] - ay) <= window_v:
                cluster.append(w)

        # Room code filter (optional, from config.json)
        if room_code:
            if not any(w["text"] == room_code for w in cluster):
                logger.debug(
                    f"  cluster at ({ax},{ay}) surface={anchor['text']!r} "
                    f"rejected: no '{room_code}' token in {len(cluster)} neighbours"
                )
                continue

        # Parse the surface value (universal "X.XX" format with optional ",")
        room_surface = 0.0
        try:
            val = float(anchor["text"].replace(",", "."))
            if 0.5 < val < 2000.0:
                room_surface = val
        except ValueError:
            pass

        # Pick the room ID: longest _RE_ROOM_NUMBER token in the cluster,
        # excluding the anchor itself and tokens that happen to match the code.
        id_candidates = [
            w for w in cluster
            if w is not anchor
            and w["text"] != room_code
            and _RE_ROOM_NUMBER.match(w["text"])
        ]
        id_candidates.sort(
            key=lambda w: (
                -len(w["text"]),                                     # prefer longer IDs
                (w["cx"] - ax) ** 2 + (w["cy"] - ay) ** 2,          # then closest
            )
        )
        if id_candidates:
            room_name = id_candidates[0]["text"]
        else:
            room_name = f"room_{ax}_{ay}"
        logger.debug(
            f"  cluster at ({ax},{ay}) surface={anchor['text']!r} "
            f"→ room '{room_name}' ({len(cluster)} tokens)"
        )

        # Cartouche bbox = cluster bounding box with margin
        all_x0 = min(w["x"] for w in cluster)
        all_y0 = min(w["y"] for w in cluster)
        all_x1 = max(w["x"] + w["w"] for w in cluster)
        all_y1 = max(w["y"] + w["h"] for w in cluster)

        # B2 (D-148) : étendre le bbox aux stragglers OCR ("m²", "²",
        # surfaces avec virgule, codes orphelins) qui tombent hors du
        # cluster collecté (window_h trop étroit) mais juste à côté.
        # Fenêtre d'absorption verticale = celle du cluster (window_v) ;
        # horizontale = h_med × 5 autour du centre cluster — assez large
        # pour capter "m²" à droite de la surface, mais pas assez pour
        # déborder sur le cartouche voisin.
        absorb_h = h_med * 5
        for w in words:
            if w in cluster:
                continue
            wcx, wcy = w["cx"], w["cy"]
            if abs(wcx - ax) > absorb_h or abs(wcy - ay) > window_v:
                continue
            if not _RE_CARTOUCHE_STRAGGLER.match(w["text"]):
                continue
            wx0, wy0 = w["x"], w["y"]
            wx1, wy1 = w["x"] + w["w"], w["y"] + w["h"]
            if wx0 < all_x0: all_x0 = wx0
            if wy0 < all_y0: all_y0 = wy0
            if wx1 > all_x1: all_x1 = wx1
            if wy1 > all_y1: all_y1 = wy1

        cartouche_bboxes.append((
            all_x0 - CARTOUCHE_MARGIN_PX,
            all_y0 - CARTOUCHE_MARGIN_PX,
            all_x1 + CARTOUCHE_MARGIN_PX,
            all_y1 + CARTOUCHE_MARGIN_PX,
        ))

        seed_cx = (all_x0 + all_x1) // 2
        seed_cy = (all_y0 + all_y1) // 2

        # De-duplicate on room_name: if a cluster re-nominates an existing
        # room, keep the one with a non-zero surface.
        if room_name in seeds:
            prev_cx, prev_cy, prev_surf = seeds[room_name]
            if room_surface == 0.0 and prev_surf > 0.0:
                continue
        seeds[room_name] = (seed_cx, seed_cy, room_surface)

    if not seeds:
        logger.warning(
            f"No seeds found. Check the room_code setting ('{room_code}') "
            f"or cartouche text (surfaces must match '\\d+[.,]\\d+')."
        )
    else:
        logger.info(f"OCR: found {len(seeds)} room(s): {', '.join(seeds.keys())}")

    return seeds, cartouche_bboxes


def erase_cartouches(gray_arr, cartouche_bboxes):
    cleaned = gray_arr.copy()
    for x0, y0, x1, y1 in cartouche_bboxes:
        x0 = max(0, x0)
        y0 = max(0, y0)
        x1 = min(cleaned.shape[1], x1)
        y1 = min(cleaned.shape[0], y1)
        cleaned[y0:y1, x0:x1] = 255
    return cleaned


def binarize(gray_arr, threshold=BINARIZE_THRESHOLD):
    return gray_arr < threshold


def save_debug_image(binary, all_hits, rect, room_name, title):
    """Save debug visualization: binary image + hits (red) + rect (green).

    Args:
        binary: binarized image as numpy array (h×w, bool)
        all_hits: list of (hx, hy) hit points from comb
        rect: (x0, y0, x1, y1) detected rectangle
        room_name: room identifier for filename
        title: image title
    """
    if not DEBUG_IMAGES:
        return

    # Create RGB image from binary
    binary_u8 = (binary.astype(np.uint8) * 255)[:,:,np.newaxis]
    debug_img = np.concatenate([binary_u8, binary_u8, binary_u8], axis=2)
    debug_img = Image.fromarray(debug_img.astype(np.uint8), mode='RGB')
    draw = ImageDraw.Draw(debug_img)

    # Draw hits in red
    for hx, hy in all_hits:
        r = 3
        draw.ellipse([hx-r, hy-r, hx+r, hy+r], fill=(255, 0, 0), outline=(255, 0, 0))

    # Draw rect in green
    if rect:
        x0, y0, x1, y1 = rect
        draw.rectangle([x0, y0, x1, y1], outline=(0, 255, 0), width=2)

    # Save
    filepath = os.path.join(_TMP, f"debug_{room_name}_{title}.png")
    debug_img.save(filepath)
    logger.debug(f"  DEBUG image: {filepath}")


def remove_non_ortho(binary):
    """Remove non-orthogonal elements (door arcs, dimension lines).

    Analyses each connected component via minAreaRect. If the dominant
    orientation is neither ~0° nor ~90° (tolerance 5°), the component is removed.
    """
    binary_u8 = binary.astype(np.uint8) * 255
    num, labels = cv2.connectedComponents(binary_u8)

    for label_id in range(1, num):
        component = np.argwhere(labels == label_id)
        if len(component) < 5:
            continue
        rect = cv2.minAreaRect(component[:, ::-1].astype(np.float32))
        angle = rect[2] % 90
        if 5 < angle < 85:
            binary[labels == label_id] = False

    return binary


def ray_single(binary, x, y, dx, dy, max_dist=MAX_RAY_PX,
               stop_mask=None):
    """Return the distance to the last white pixel before the wall.

    Args:
        stop_mask: optional boolean array same shape as binary.
            When a ray hits stop_mask before binary, it stops but
            returns a **negative** distance (= opening, not wall).

    Returns:
        Positive distance: wall hit (distance to last white pixel).
        Negative distance: stopped on stop_mask at abs(distance).
        -1: start point is on a wall.
    """
    h, w = binary.shape
    if 0 <= x < w and 0 <= y < h and binary[y, x]:
        return -1
    px, py = x, y
    for d in range(1, max_dist + 1):
        px += dx
        py += dy
        if px < 0 or px >= w or py < 0 or py >= h:
            return d - 1
        if binary[py, px]:
            return d - 1
        if stop_mask is not None and stop_mask[py, px]:
            return -(d - 1)
    return max_dist


def ray_single_through(binary, x, y, dx, dy, max_dist, min_wall_px):
    """Ray that traverses obstacles narrower than min_wall_px.

    Returns:
        (distance, obstacles) where distance is the distance to the real
        wall (thick obstacle or image boundary), and obstacles is a list
        of (start_d, end_d) for each narrow obstacle traversed.
        Returns (-1, []) if start is on a wall.
    """
    h, w = binary.shape
    if 0 <= x < w and 0 <= y < h and binary[y, x]:
        return -1, []
    obstacles: list[tuple[int, int]] = []
    px, py = x, y
    in_obstacle = False
    obs_start = 0
    d = 0
    for d in range(1, max_dist + 1):
        px += dx
        py += dy
        if px < 0 or px >= w or py < 0 or py >= h:
            if in_obstacle:
                # Reached boundary inside an obstacle — it's a real wall
                return obs_start - 1, obstacles
            return d - 1, obstacles
        if binary[py, px]:
            if not in_obstacle:
                in_obstacle = True
                obs_start = d
        else:
            if in_obstacle:
                obs_width = d - obs_start
                if obs_width >= min_wall_px:
                    # Real wall — stop at last white before it
                    return obs_start - 1, obstacles
                # Narrow obstacle — record and continue
                obstacles.append((obs_start, d - 1))
                in_obstacle = False
    # Reached max_dist
    if in_obstacle:
        obs_width = d - obs_start + 1
        if obs_width >= min_wall_px:
            return obs_start - 1, obstacles
        # Narrow obstacle at the very end — treat as wall anyway
        return obs_start - 1, obstacles
    return max_dist, obstacles


COARSE_STEP_PX = 30  # phase 1: coarse scan to find room walls
RAY_MARGIN_PX = 10   # margin beyond coarse distance for fine rays


def comb_collect_hits(binary, cx, cy, step_px, other_seeds=None,
                      diag=None, stop_mask=None):
    """Adaptive two-pass comb.

    Phase 1 (coarse): rays at wide step (COARSE_STEP_PX) from the seed
    to detect the 4 immediate walls → distances by direction.

    Phase 2 (fine): rays at step_px, bounded in position (phase 1 bbox)
    AND in range (phase 1 distance + margin). No ray goes past the walls
    detected in phase 1.

    Args:
        diag: (OPT) dict — when provided, filled with diagnostic data
            (coarse distances, seed limits, hit counts before/after filter).

    Returns (all_hits, dir_hits):
      all_hits = flat list [(px, py), ...]
      dir_hits = {'north': [...], 'south': [...], 'east': [...], 'west': [...]}
    """
    # === Phase 1: coarse distances by direction (mode, not max) ===
    coarse_dists = {'north': [], 'south': [], 'west': [], 'east': []}
    coarse_hits: dict[str, list[tuple[int, int]]] = {
        'north': [], 'south': [], 'west': [], 'east': []}

    # Rays initiaux
    for name, dx, dy in [('north', 0, -1), ('south', 0, 1),
                          ('west', -1, 0), ('east', 1, 0)]:
        d = ray_single(binary, cx, cy, dx, dy)
        if d > 0:
            coarse_dists[name].append(d)
            coarse_hits[name].append((cx + dx * d, cy + dy * d))

    max_ns = max((coarse_dists['north'] + coarse_dists['south']) or [0])
    max_ew = max((coarse_dists['west'] + coarse_dists['east']) or [0])

    # Coarse vertical comb → collect north/south distances
    step = 1
    while True:
        offset = step * COARSE_STEP_PX
        if offset > max_ew:
            break
        for rx in (cx - offset, cx + offset):
            d = ray_single(binary, rx, cy, 0, -1)
            if d > 0:
                coarse_dists['north'].append(d)
                coarse_hits['north'].append((rx, cy - d))
                max_ns = max(max_ns, d)
            d = ray_single(binary, rx, cy, 0, 1)
            if d > 0:
                coarse_dists['south'].append(d)
                coarse_hits['south'].append((rx, cy + d))
                max_ns = max(max_ns, d)
        step += 1

    # Coarse horizontal comb → collect west/east distances
    step = 1
    while True:
        offset = step * COARSE_STEP_PX
        if offset > max_ns:
            break
        for ry in (cy - offset, cy + offset):
            d = ray_single(binary, cx, ry, -1, 0)
            if d > 0:
                coarse_dists['west'].append(d)
                coarse_hits['west'].append((cx - d, ry))
                max_ew = max(max_ew, d)
            d = ray_single(binary, cx, ry, 1, 0)
            if d > 0:
                coarse_dists['east'].append(d)
                coarse_hits['east'].append((cx + d, ry))
                max_ew = max(max_ew, d)
        step += 1

    # Mode per direction = dominant wall distance (outliers = door traversals)
    def _mode_dist(dists):
        if not dists:
            return 0
        vals, counts = np.unique(dists, return_counts=True)
        return int(vals[np.argmax(counts)])

    coarse_mode = {d: _mode_dist(coarse_dists[d]) for d in coarse_dists}
    coarse_max = {d: max(coarse_dists[d]) if coarse_dists[d] else 0
                  for d in coarse_dists}

    coarse_ns = max(coarse_mode['north'], coarse_mode['south'])
    coarse_ew = max(coarse_mode['west'], coarse_mode['east'])

    # Compute seed_caps: nearest neighbor seed on each axis.
    # Tolerance = room dimension on the perpendicular axis (coarse pass).
    # For E/W caps, only consider seeds within ±coarse_ns (room height).
    # For N/S caps, only consider seeds within ±coarse_ew (room width).
    # This prevents a distant seed on the perpendicular axis from
    # incorrectly capping the exploration range.
    seed_caps = {'north': None, 'south': None, 'east': None, 'west': None}
    if other_seeds:
        for ox, oy in other_seeds:
            dx_s = ox - cx
            dy_s = oy - cy
            # East/West caps (vertical comb): seed must be on same
            # horizontal band (within N/S extent of the room).
            if abs(dy_s) <= coarse_ns:
                if dx_s > 0 and (seed_caps['east'] is None
                                 or dx_s < seed_caps['east']):
                    seed_caps['east'] = dx_s
                if dx_s < 0 and (seed_caps['west'] is None
                                 or -dx_s < seed_caps['west']):
                    seed_caps['west'] = -dx_s
            # North/South caps (horizontal comb): only consider seeds
            # beyond the north or south wall — seeds within the N/S
            # extent are lateral neighbors, not N/S neighbors.
            if (dy_s < 0 and abs(dy_s) >= coarse_mode['north']
                    or dy_s > 0 and dy_s >= coarse_mode['south']):
                if dy_s > 0 and (seed_caps['south'] is None
                                 or dy_s < seed_caps['south']):
                    seed_caps['south'] = dy_s
                if dy_s < 0 and (seed_caps['north'] is None
                                 or -dy_s < seed_caps['north']):
                    seed_caps['north'] = -dy_s

    # Bbox (start positions) = symmetric, based on mode (dominant wall).
    # v0.4.7 behavior — seed assumed roughly centered.
    bbox_x0 = cx - coarse_ew
    bbox_x1 = cx + coarse_ew
    bbox_y0 = cy - coarse_ns
    bbox_y1 = cy + coarse_ns
    # D-169b: seed_caps limit exploration — rays must not scan
    # beyond a neighbor seed on the perpendicular axis.
    # For vertical rays (N/S), the scan range in x is capped at the
    # nearest neighbor seed's x.  For horizontal rays (E/W), capped
    # at the nearest neighbor seed's y.
    # D-165b extension is removed: it extended the bbox TO the
    # neighbor seed, causing rays to explore the neighbor's room.
    if seed_caps['west'] is not None:
        bbox_x0 = max(bbox_x0, cx - seed_caps['west'])
    if seed_caps['east'] is not None:
        bbox_x1 = min(bbox_x1, cx + seed_caps['east'])
    if seed_caps['north'] is not None:
        bbox_y0 = max(bbox_y0, cy - seed_caps['north'])
    if seed_caps['south'] is not None:
        bbox_y1 = min(bbox_y1, cy + seed_caps['south'])
    # Ray range = based on max (to traverse doors), capped by seed distance
    max_north = coarse_max['north'] + RAY_MARGIN_PX
    max_south = coarse_max['south'] + RAY_MARGIN_PX
    max_west = coarse_max['west'] + RAY_MARGIN_PX
    max_east = coarse_max['east'] + RAY_MARGIN_PX

    if diag is not None:
        diag['coarse_mode'] = dict(coarse_mode)
        diag['coarse_max'] = dict(coarse_max)
        diag['seed_caps'] = {k: int(v) if v is not None else None
                             for k, v in seed_caps.items()}
        diag['bbox_coarse'] = [int(bbox_x0), int(bbox_y0),
                               int(bbox_x1), int(bbox_y1)]
        diag['max_range'] = {'north': int(max_north), 'south': int(max_south),
                             'west': int(max_west), 'east': int(max_east)}

    # === Phase 2: fine comb, bounded in position AND range ===
    # D-160: ray_single_through exists but is DISABLED — min_obstacle_width_cm
    # (30 cm) traverses interior walls (~10-15 cm). Needs a dedicated
    # pillar_max_width_cm parameter before activation.
    dir_hits = {'north': [], 'south': [], 'east': [], 'west': []}
    all_obstacles: list[tuple[int, int, int, int]] = []

    # Vertical rays (N and S)
    # stop_mask hits (d < -1) are recorded at abs(d) — they represent
    # rays stopped by corridor/exterior color, revealing openings.
    rx = cx
    while rx >= bbox_x0:
        d = ray_single(binary, rx, cy, 0, -1, max_dist=max_north,
                       stop_mask=stop_mask)
        if d > 0:
            dir_hits['north'].append((rx, cy - d))
        elif d < -1:
            dir_hits['north'].append((rx, cy - abs(d)))
        d = ray_single(binary, rx, cy, 0, 1, max_dist=max_south,
                       stop_mask=stop_mask)
        if d > 0:
            dir_hits['south'].append((rx, cy + d))
        elif d < -1:
            dir_hits['south'].append((rx, cy + abs(d)))
        rx -= step_px
    rx = cx + step_px
    while rx <= bbox_x1:
        d = ray_single(binary, rx, cy, 0, -1, max_dist=max_north,
                       stop_mask=stop_mask)
        if d > 0:
            dir_hits['north'].append((rx, cy - d))
        elif d < -1:
            dir_hits['north'].append((rx, cy - abs(d)))
        d = ray_single(binary, rx, cy, 0, 1, max_dist=max_south,
                       stop_mask=stop_mask)
        if d > 0:
            dir_hits['south'].append((rx, cy + d))
        elif d < -1:
            dir_hits['south'].append((rx, cy + abs(d)))
        rx += step_px

    # Horizontal rays (E and W)
    ry = cy
    while ry >= bbox_y0:
        d = ray_single(binary, cx, ry, -1, 0, max_dist=max_west,
                       stop_mask=stop_mask)
        if d > 0:
            dir_hits['west'].append((cx - d, ry))
        elif d < -1:
            dir_hits['west'].append((cx - abs(d), ry))
        d = ray_single(binary, cx, ry, 1, 0, max_dist=max_east,
                       stop_mask=stop_mask)
        if d > 0:
            dir_hits['east'].append((cx + d, ry))
        elif d < -1:
            dir_hits['east'].append((cx + abs(d), ry))
        ry -= step_px
    ry = cy + step_px
    while ry <= bbox_y1:
        d = ray_single(binary, cx, ry, -1, 0, max_dist=max_west,
                       stop_mask=stop_mask)
        if d > 0:
            dir_hits['west'].append((cx - d, ry))
        elif d < -1:
            dir_hits['west'].append((cx - abs(d), ry))
        d = ray_single(binary, cx, ry, 1, 0, max_dist=max_east,
                       stop_mask=stop_mask)
        if d > 0:
            dir_hits['east'].append((cx + d, ry))
        elif d < -1:
            dir_hits['east'].append((cx + abs(d), ry))
        ry += step_px

    raw_counts = {d: len(dir_hits[d]) for d in dir_hits}

    # D-169b: the post-hoc _not_past_seed filter is removed.
    # Exploration is now bounded by seed_caps (bbox capped at the
    # nearest neighbor seed on each axis) so rays never reach
    # another room's territory.
    seed_filter_detail: dict = {}

    # Deduplicate obstacle bboxes (multiple rays may hit same pillar)
    unique_obs = list(set(all_obstacles)) if all_obstacles else []

    if diag is not None:
        filtered_counts = {d: len(dir_hits[d]) for d in dir_hits}
        diag['hits_raw'] = raw_counts
        diag['hits_filtered'] = filtered_counts
        diag['seed_filter'] = seed_filter_detail
        diag['other_seeds_count'] = len(other_seeds) if other_seeds else 0
        diag['obstacles_px'] = [[x0, y0, x1, y1]
                                for x0, y0, x1, y1 in unique_obs]
        # South hits detail: coordinates of all south hits after filter
        diag['south_hits'] = [
            [int(hx), int(hy)] for hx, hy in dir_hits.get('south', [])
        ]

    all_hits = [h for hits in dir_hits.values() for h in hits]
    return all_hits, dir_hits, coarse_hits


def _filter_pillar_hits(dir_hits, cx, cy, min_obstacle_width_px,
                        min_pillar_size_px=8, max_pillar_size_px=60,
                        door_seeds=None, min_door_width_px=0,
                        step_px=10):
    """Filter out hits caused by narrow pillars (< min_obstacle_width_px).

    For each face, the dominant wall position is the mode of the hit
    coordinates perpendicular to the face. Hits that are closer to the
    seed than the mode form candidate pillar groups. A contiguous group
    whose width (along the face) is < min_obstacle_width_px is classified
    as a pillar: its hits are removed from dir_hits and the pillar
    geometry is recorded.

    Groups whose centre falls inside the exclusion square of a known
    door seed (side = min_door_width_px, centred on the seed) are
    rejected — they are arc fragments, not pillars.

    Args:
        dir_hits: dict {face: [(hx, hy), ...]} — modified in place.
        cx, cy: seed position.
        min_obstacle_width_px: max width for an obstacle to be a pillar.
        min_pillar_size_px: min protrusion to qualify as pillar.
        door_seeds: list of {face, seed_x, seed_y} or None.
        min_door_width_px: side of the exclusion square around each
            door seed.

    Returns:
        tuple (pillars, pillar_hit_coords):
        - pillars: list of pillar dicts {face, pos_along_px, width_px,
          depth_px, hit_coord_px, mode_coord_px}.
        - pillar_hit_coords: list of (x, y) hit coordinates removed.
    """
    pillars = []
    pillar_hit_coords: list[tuple[int, int]] = []
    if min_obstacle_width_px <= 0:
        return pillars, pillar_hit_coords

    for face in ('north', 'south', 'east', 'west'):
        hits = dir_hits.get(face, [])
        if len(hits) < 3:
            continue

        # Perpendicular coordinate = wall position (Y for N/S, X for E/W).
        # Along coordinate = position along the face (X for N/S, Y for E/W).
        if face in ('north', 'south'):
            perp = [hy for _, hy in hits]
            along = [hx for hx, _ in hits]
        else:
            perp = [hx for hx, _ in hits]
            along = [hy for hx, hy in hits]

        # Mode = dominant wall position.
        vals, counts = np.unique(perp, return_counts=True)
        mode_perp = int(vals[np.argmax(counts)])

        # Identify hits closer to seed than the mode (= in front of the
        # wall, toward the room interior).
        # North: wall is at small Y, closer to seed = larger Y.
        # South: wall is at large Y, closer to seed = smaller Y.
        # West: wall is at small X, closer to seed = larger X.
        # East: wall is at large X, closer to seed = smaller X.
        if face == 'north':
            is_inward = lambda p: p > mode_perp
        elif face == 'south':
            is_inward = lambda p: p < mode_perp
        elif face == 'west':
            is_inward = lambda p: p > mode_perp
        else:  # east
            is_inward = lambda p: p < mode_perp

        # Collect inward hits with their indices, filtering by max
        # displacement < min_obstacle_width_px.
        inward_indices = []
        for i, (p, a) in enumerate(zip(perp, along)):
            displacement = abs(p - mode_perp)
            if is_inward(p) and displacement >= min_pillar_size_px:
                inward_indices.append(i)

        if not inward_indices:
            continue

        # Sort inward hits by along-coordinate to find contiguous groups.
        inward_sorted = sorted(inward_indices, key=lambda i: along[i])

        # Group contiguous hits (gap < 2 * step between rays).
        # Use a generous gap threshold: hits from adjacent rays are
        # spaced by step_px (~10-20 px). Allow 3× step as gap tolerance.
        gap_threshold = 3 * step_px
        groups: list[list[int]] = []
        current_group = [inward_sorted[0]]
        for k in range(1, len(inward_sorted)):
            if along[inward_sorted[k]] - along[inward_sorted[k - 1]] \
                    <= gap_threshold:
                current_group.append(inward_sorted[k])
            else:
                groups.append(current_group)
                current_group = [inward_sorted[k]]
        groups.append(current_group)

        # Evaluate each group: pillar if width <= max_pillar_size_px
        # and displacement pattern is constant (not progressive like an arc).
        indices_to_remove: set[int] = set()
        for group in groups:
            if len(group) < 3:
                continue  # Too few hits to be a reliable pillar.
            along_vals = [along[i] for i in group]
            group_width = max(along_vals) - min(along_vals)
            if group_width > max_pillar_size_px:
                continue  # Too wide to be a pillar.

            # Distinguish pillar (constant depth) from door arc
            # (progressive depth). Sort by along-coordinate and check
            # if displacements are monotonically increasing/decreasing.
            sorted_group = sorted(group, key=lambda i: along[i])
            disps = [abs(perp[i] - mode_perp) for i in sorted_group]
            if len(disps) >= 3:
                diffs = [disps[j+1] - disps[j] for j in range(len(disps)-1)]
                # Arc: diffs are mostly same sign (monotonic).
                # Pillar: diffs are near zero or mixed sign.
                positive = sum(1 for d in diffs if d > 0)
                negative = sum(1 for d in diffs if d < 0)
                n = len(diffs)
                # If > 70% of diffs are same sign → monotonic → arc.
                if positive > 0.7 * n or negative > 0.7 * n:
                    continue  # Progressive displacement → door arc.

            # Reject if group centre falls near a door seed (any face).
            # Door arcs in corners generate hits on the adjacent face,
            # so we compare in absolute image coordinates, not per-face.
            group_center_along = (min(along_vals) + max(along_vals)) / 2
            group_center_perp = sum(perp[i] for i in group) / len(group)
            if face in ('north', 'south'):
                gc_x = group_center_along
                gc_y = group_center_perp
            else:
                gc_x = group_center_perp
                gc_y = group_center_along
            if door_seeds and min_door_width_px > 0:
                half = min_door_width_px / 2
                in_door_zone = False
                for ds in door_seeds:
                    ds_x = ds.get('seed_x', 0)
                    ds_y = ds.get('seed_y', 0)
                    if abs(gc_x - ds_x) <= half and abs(gc_y - ds_y) <= half:
                        in_door_zone = True
                        break
                if in_door_zone:
                    continue

            # Max depth: a pillar cannot protrude more than its max width.
            perp_vals = [perp[i] for i in group]
            depth = max(abs(p - mode_perp) for p in perp_vals)
            if depth > max_pillar_size_px:
                continue  # Too deep — wall bleed-through, not a pillar.

            # Pillar detected — record geometry.
            pos_along = min(along_vals)
            width = group_width if group_width > 0 else 1

            # hit_coord = the perpendicular position of the pillar hits
            # (average). Needed to place the exclusion zone.
            avg_perp = int(round(sum(perp_vals) / len(perp_vals)))

            pillars.append({
                'face': face,
                'pos_along_px': pos_along,
                'width_px': width,
                'depth_px': depth,
                'hit_coord_px': avg_perp,
                'mode_coord_px': mode_perp,
            })
            indices_to_remove.update(group)

        # Remove pillar hits from dir_hits and record their coords.
        if indices_to_remove:
            for i in indices_to_remove:
                pillar_hit_coords.append(hits[i])
            dir_hits[face] = [h for i, h in enumerate(hits)
                              if i not in indices_to_remove]

    # Remove perpendicular hits that fall inside pillar zones.
    # E.g. a pillar on north face (Y range mode..hit) also blocks
    # east/west hits at the same Y and X range → remove them so the
    # bbox can expand to the real wall.
    for p in pillars:
        pf = p['face']
        mode_c = p['mode_coord_px']
        hit_c = p['hit_coord_px']
        pos = p['pos_along_px']
        width = p['width_px']
        if pf in ('north', 'south'):
            y_lo = min(mode_c, hit_c)
            y_hi = max(mode_c, hit_c)
            x_lo = pos
            x_hi = pos + width
            for perp_face in ('east', 'west'):
                before = len(dir_hits[perp_face])
                dir_hits[perp_face] = [
                    (hx, hy) for hx, hy in dir_hits[perp_face]
                    if not (y_lo <= hy <= y_hi and x_lo <= hx <= x_hi)
                ]
        else:  # east / west
            x_lo = min(mode_c, hit_c)
            x_hi = max(mode_c, hit_c)
            y_lo = pos
            y_hi = pos + width
            for perp_face in ('north', 'south'):
                before = len(dir_hits[perp_face])
                dir_hits[perp_face] = [
                    (hx, hy) for hx, hy in dir_hits[perp_face]
                    if not (x_lo <= hx <= x_hi and y_lo <= hy <= y_hi)
                ]

    return pillars, pillar_hit_coords


def _innermost_with_support(coords, direction, min_support=3, tolerance=2):
    """Find the innermost coordinate with sufficient ray support.

    Scans from the room interior outward. Returns the first coordinate
    where at least min_support rays hit within ±tolerance pixels.

    Args:
        coords: list of wall coordinates (y for N/S, x for E/W)
        direction: 'max' for N/W faces (innermost = largest value),
                   'min' for S/E faces (innermost = smallest value)
        min_support: minimum number of rays for a valid wall
        tolerance: max distance in px for hits to be grouped

    Returns:
        Wall coordinate, or None if no supported value found.
    """
    if not coords:
        return None
    if direction == 'max':
        sorted_c = sorted(coords, reverse=True)
    else:
        sorted_c = sorted(coords)

    for c in sorted_c:
        support = sum(1 for other in coords if abs(other - c) <= tolerance)
        if support >= min_support:
            return c

    # Fallback: mode
    vals, counts = np.unique(coords, return_counts=True)
    return int(vals[np.argmax(counts)])


def rect_from_directional_hits(dir_hits, cx, cy):
    """Compute rectangle from directional hits.

    For each face, find the innermost wall position with sufficient
    support. This aligns the rectangle with window lines (innermost
    feature) and is robust to outlier hits.

    The innermost wall for each face is:
      north: largest hy (closest to seed from above)
      south: smallest hy (closest to seed from below)
      west:  largest hx (closest to seed from left)
      east:  smallest hx (closest to seed from right)
    """
    north_ys = [hy for _, hy in dir_hits['north']]
    south_ys = [hy for _, hy in dir_hits['south']]
    west_xs = [hx for hx, _ in dir_hits['west']]
    east_xs = [hx for hx, _ in dir_hits['east']]

    y0 = _innermost_with_support(north_ys, 'max')
    y1 = _innermost_with_support(south_ys, 'min')
    x0 = _innermost_with_support(west_xs, 'max')
    x1 = _innermost_with_support(east_xs, 'min')

    # Fallbacks
    if y0 is None: y0 = cy - 1
    if y1 is None: y1 = cy + 1
    if x0 is None: x0 = cx - 1
    if x1 is None: x1 = cx + 1

    return (x0, y0, x1, y1)


def largest_rect_no_hits(hits, cx, cy, return_all=False):
    """Largest rectangle containing (cx,cy) with no hits strictly inside.

    Hits may lie on the rectangle edges.
    Approach: for each pair of y bounds (top, bottom) defined by
    the hits, find the widest x bounds such that no hit is strictly
    inside.

    Args:
        return_all: if True, return (best_rect, all_candidates) where
            all_candidates is a list of (rect, area) sorted by area desc.
    """
    if not hits:
        r = (cx - 1, cy - 1, cx + 1, cy + 1)
        return (r, [(r, 4)]) if return_all else r

    # Collect all unique y coordinates of hits
    ys = sorted(set(h[1] for h in hits))

    best_area = 0
    best_rect = None
    all_candidates = [] if return_all else None

    # For each pair (y_top, y_bottom) containing cy
    for i, y_top in enumerate(ys):
        if y_top > cy:
            break
        for j in range(len(ys) - 1, -1, -1):
            y_bot = ys[j]
            if y_bot < cy:
                break
            h = y_bot - y_top
            if h <= 0:
                continue

            # Find x bounds: hits within the band
            # y_top <= hit_y <= y_bot constrain x
            x_left = -999999
            x_right = 999999

            for hx, hy in hits:
                if y_top <= hy <= y_bot:
                    # This hit is in the band (edges included)
                    if hx <= cx:
                        x_left = max(x_left, hx)
                    if hx >= cx:
                        x_right = min(x_right, hx)

            if x_left == -999999 or x_right == 999999:
                continue
            w = x_right - x_left
            if w <= 0:
                continue

            area = w * h
            rect = (x_left, y_top, x_right, y_bot)
            if return_all:
                all_candidates.append((rect, area))
            if area > best_area:
                best_area = area
                best_rect = rect

    if return_all:
        all_candidates.sort(key=lambda c: c[1], reverse=True)
        return best_rect, all_candidates
    return best_rect


SNAP_SEARCH_PX = 6  # search ±6px around current edge for wall snap


def snap_rect_to_walls(binary, rect, search_px=SNAP_SEARCH_PX):
    """Snap rectangle edges to the modal wall position on each face.

    After largest_rect_no_hits, edges may be off by ±2-3px because the
    comb rays (spaced at COMB_STEP_PX) hit different wall features
    (window panes, wall segments) depending on seed position.

    Fix: for each face, densely scan along the edge and find the first
    wall pixel searching from the room interior outward. The mode across
    all samples = true inner wall position. This ensures we stop at the
    innermost wall feature (window line) rather than overshooting to the
    outer wall.
    """
    x0, y0, x1, y1 = rect
    margin = 3  # skip corners where perpendicular walls interfere

    # North face: search from interior (increasing y) toward exterior (decreasing y)
    y0 = _snap_edge(binary, list(range(x0 + margin, x1 - margin)),
                    y0, axis='y', direction=-1, search_px=search_px)
    # South face: search from interior (decreasing y) toward exterior (increasing y)
    y1 = _snap_edge(binary, list(range(x0 + margin, x1 - margin)),
                    y1, axis='y', direction=+1, search_px=search_px)
    # West face: search from interior (increasing x) toward exterior (decreasing x)
    x0 = _snap_edge(binary, list(range(y0 + margin, y1 - margin)),
                    x0, axis='x', direction=-1, search_px=search_px)
    # East face: search from interior (decreasing x) toward exterior (increasing x)
    x1 = _snap_edge(binary, list(range(y0 + margin, y1 - margin)),
                    x1, axis='x', direction=+1, search_px=search_px)

    return (x0, y0, x1, y1)


def _snap_edge(binary, scan_positions, edge_val, axis, direction,
               search_px):
    """Find modal wall position along one edge by searching from interior.

    For each position along the edge, search from the room interior
    outward and record the first wall pixel found. The mode of these
    positions = true inner wall surface.

    Args:
        binary: wall mask (True = wall)
        scan_positions: coordinates along the edge (x for N/S, y for E/W)
        edge_val: current edge coordinate (y for N/S, x for E/W)
        axis: 'y' for N/S faces, 'x' for E/W faces
        direction: +1 or -1 — outward direction from the room interior
        search_px: search range in pixels

    Returns:
        Snapped edge coordinate (mode of first wall hits from interior).
    """
    h, w = binary.shape
    wall_hits = []

    # Search from interior toward exterior:
    # Start at edge_val - direction*search_px (deep inside room)
    # End at edge_val + direction*search_px (past the wall)
    for pos in scan_positions:
        for step in range(-search_px, search_px + 1):
            coord = edge_val + direction * step
            if axis == 'y':
                px, py = pos, coord
            else:
                px, py = coord, pos
            if 0 <= px < w and 0 <= py < h and binary[py, px]:
                wall_hits.append(coord)
                break

    if not wall_hits:
        return edge_val

    vals, counts = np.unique(wall_hits, return_counts=True)
    return int(vals[np.argmax(counts)])


def contract_to_interior(binary, rect, max_contract=10):
    """Contract each edge inward until no black pixel on the edge line.

    The rectangle from largest_rect_no_hits has edges ON the walls
    (first hit pixel = wall surface). Walls are 2-5px thick. This
    function moves each edge inward past the wall thickness until
    the edge line is fully white.

    To avoid false stops from perpendicular walls at the corners,
    only the middle 60% of each line/column is checked.
    """
    x0, y0, x1, y1 = rect
    h, w = binary.shape
    x_margin = max(3, (x1 - x0) // 5)
    y_margin = max(3, (y1 - y0) // 5)

    # North: contract y0 southward
    for _ in range(max_contract):
        if y0 >= y1:
            break
        if np.any(binary[y0, x0 + x_margin:x1 - x_margin]):
            y0 += 1
        else:
            break

    # South: contract y1 northward
    for _ in range(max_contract):
        if y1 <= y0:
            break
        if np.any(binary[y1, x0 + x_margin:x1 - x_margin]):
            y1 -= 1
        else:
            break

    # West: contract x0 eastward
    for _ in range(max_contract):
        if x0 >= x1:
            break
        if np.any(binary[y0 + y_margin:y1 - y_margin, x0]):
            x0 += 1
        else:
            break

    # East: contract x1 westward
    for _ in range(max_contract):
        if x1 <= x0:
            break
        if np.any(binary[y0 + y_margin:y1 - y_margin, x1]):
            x1 -= 1
        else:
            break

    return (x0, y0, x1, y1)


def snap_through_white(binary, rect, max_advance=8):
    """Expand each edge outward through fully white lines.

    For each side, check the 1px line just outside the current edge.
    If entirely white (no black pixel), advance the edge 1px outward.
    Repeat until hitting a line with at least one black pixel, or
    max_advance reached.

    Prerequisite: the rectangle must be inset from the walls (edges
    on white pixels, not on wall pixels). See largest_rect_no_hits.

    This aligns edges with the nearest wall/window feature, fixing
    ±2-3px offsets caused by comb discretization.
    """
    x0, y0, x1, y1 = rect
    h, w = binary.shape

    # North: advance y0 upward
    for _ in range(max_advance):
        if y0 <= 0:
            break
        if not np.any(binary[y0 - 1, x0:x1]):
            y0 -= 1
        else:
            break

    # South: advance y1 downward
    for _ in range(max_advance):
        if y1 >= h - 1:
            break
        if not np.any(binary[y1 + 1, x0:x1]):
            y1 += 1
        else:
            break

    # West: advance x0 leftward
    for _ in range(max_advance):
        if x0 <= 0:
            break
        if not np.any(binary[y0:y1, x0 - 1]):
            x0 -= 1
        else:
            break

    # East: advance x1 rightward
    for _ in range(max_advance):
        if x1 >= w - 1:
            break
        if not np.any(binary[y0:y1, x1 + 1]):
            x1 += 1
        else:
            break

    return (x0, y0, x1, y1)


def snap_to_wall(binary, rect, max_advance_per_face=None):
    """Extend each face outward until a wall (solid pixels) is found.

    Unlike snap_through_white (which advances <=8px for fine alignment),
    this function handles the case where a face has NO wall at all —
    the rectangle stopped too early because of parasitic hits from an
    adjacent room. It advances until finding a line with solid pixels.

    Args:
        binary: binary image (True = solid).
        rect: (x0, y0, x1, y1).
        max_advance_per_face: dict {face: max_px} limiting how far each
            face can advance. Prevents unbounded extension. Default: 200px
            for each face.

    Returns:
        (x0, y0, x1, y1) — extended rectangle.
    """
    x0, y0, x1, y1 = rect
    h, w = binary.shape
    defaults = 200
    caps = max_advance_per_face or {}

    def _has_wall(line_pixels):
        """A line has a wall if it contains at least 1 solid pixel."""
        return np.any(line_pixels)

    # North: check if current edge touches a wall, if not advance
    if x1 > x0 and not _has_wall(binary[max(0, y0 - 1), x0:x1]):
        limit = caps.get('north', defaults)
        for _ in range(limit):
            if y0 <= 0:
                break
            y0 -= 1
            if _has_wall(binary[y0, x0:x1]):
                break

    # South
    if x1 > x0 and y1 + 1 < h and not _has_wall(binary[min(h - 1, y1 + 1), x0:x1]):
        limit = caps.get('south', defaults)
        for _ in range(limit):
            if y1 >= h - 1:
                break
            y1 += 1
            if _has_wall(binary[y1, x0:x1]):
                break

    # West
    if y1 > y0 and not _has_wall(binary[y0:y1, max(0, x0 - 1)]):
        limit = caps.get('west', defaults)
        for _ in range(limit):
            if x0 <= 0:
                break
            x0 -= 1
            if _has_wall(binary[y0:y1, x0]):
                break

    # East
    if y1 > y0 and x1 + 1 < w and not _has_wall(binary[y0:y1, min(w - 1, x1 + 1)]):
        limit = caps.get('east', defaults)
        for _ in range(limit):
            if x1 >= w - 1:
                break
            x1 += 1
            if _has_wall(binary[y0:y1, x1]):
                break

    return (x0, y0, x1, y1)


DOOR_PROBE_PX = 4   # ~2cm, offset for probing door position
DOOR_GROUP_GAP_PX = 25  # max gap between pixels of the same arc (~door width)
WALL_MARGIN_PX = 3   # exclude pixels close to perpendicular walls


def _group_pixels(pixels, max_gap=DOOR_GROUP_GAP_PX):
    """Group contiguous pixels (with max gap)."""
    if not pixels:
        return []
    pixels = sorted(pixels)
    groups = []
    current = [pixels[0]]
    for p in pixels[1:]:
        if p - current[-1] <= max_gap:
            current.append(p)
        else:
            groups.append(current)
            current = [p]
    groups.append(current)
    return groups


def _seed_scan_range(x0, y0, x1, y1, face, face_seeds, door_width_px,
                     tolerance, margin):
    """Return the list of along-the-wall coordinates to scan for arc pixels.

    Default (no seeds) = full face minus a margin at each end — the
    original behavior used when door positions are unknown (OCR mode
    or legacy preprocessed JSON without seed_x/seed_y).

    When `face_seeds` is given (D-145 seed-anchored scan), restrict the
    scan to the union of small windows of ± (door_width_px × (1+tol))
    around each seed. Narrows detection to expected door zones and
    avoids arc fragments elsewhere being mistaken for micro-doors.
    """
    if face in ("south", "north"):
        full_start, full_end = x0 + margin, x1 - margin + 1
    else:
        full_start, full_end = y0 + margin, y1 - margin + 1

    if not face_seeds:
        return list(range(full_start, full_end))

    radius = max(1, int(round(door_width_px * (1 + tolerance))))
    coords: set[int] = set()
    for s in face_seeds:
        key = "seed_x" if face in ("south", "north") else "seed_y"
        c = s.get(key)
        if c is None:
            continue
        lo = max(full_start, int(c) - radius)
        hi = min(full_end, int(c) + radius + 1)
        coords.update(range(lo, hi))
    return sorted(coords)


def _detect_doors_on_face(binary, rect, face_hits, face,
                          door_width_px, tolerance,
                          face_seeds=None, binary_arcs=None, diag=None,
                          filter_rect=None):
    """Detect door swings on one face using hit-based arc analysis (D-173).

    Algorithm:
      1. Find the real wall = mode of perpendicular coordinates among
         all hits for this face (most hits align on the wall).
      2. Hits shorter than the real wall = arc candidates.
      3. Verify arc profile: monotonic distance from hinge to free jamb.
      4. Verify wall opening: wall interrupted in the arc zone.
      5. Door width = extent of the arc zone along the wall.

    When face_seeds contains a seed near this wall, thresholds are relaxed
    (seed confirms presence, arc determines geometry).

    Args:
        binary: cleaned binary. Used for wall-opening heuristic.
        face_hits: hits for THIS face direction only (e.g. south hits
            for face="south"). Each hit = (x, y).
        face: "south", "north", "east" or "west".
        face_seeds: (OPT) list of {seed_x, seed_y} near this face.
        binary_arcs: (OPT) not used by the new algo but kept for
            interface compatibility.
        diag: (OPT) dict for diagnostic output.
        filter_rect: (OPT) pre-pillar-extension rect. Limits the
            along-axis range of hits to avoid false positives from
            pillar extension on adjacent faces.

    Returns:
        (wall_px, door_infos) or (None, []).
    """
    from collections import Counter
    x0, y0, x1, y1 = rect
    face_len = (x1 - x0) if face in ("south", "north") else (y1 - y0)

    seed_confirmed = bool(face_seeds)

    # Diagnostic dict for this face (filled progressively).
    fd: dict = {
        'face': face,
        'rect': [x0, y0, x1, y1],
        'face_len_px': face_len,
        'door_width_px': door_width_px,
        'tolerance': tolerance,
        'has_seeds': seed_confirmed,
        'seeds_count': len(face_seeds) if face_seeds else 0,
        'seed_confirmed': seed_confirmed,
        'total_face_hits': len(face_hits),
    }

    def _finish(reason, extra=None):
        """Record rejection reason and append diag."""
        fd['rejected'] = reason
        if extra:
            fd.update(extra)
        if diag is not None:
            diag.setdefault('door_faces', []).append(fd)
        return None, []

    if not face_hits:
        return _finish('no_face_hits')

    # Filter hits to along-axis range of filter_rect (pre-pillar bbox).
    fx0, fy0, fx1, fy1 = filter_rect if filter_rect else rect
    if face in ("south", "north"):
        face_hits = [h for h in face_hits if fx0 <= h[0] <= fx1]
    else:
        face_hits = [h for h in face_hits if fy0 <= h[1] <= fy1]

    if not face_hits:
        return _finish('no_face_hits_in_range')

    # === Step 1: find the real wall (mode of perpendicular coords) ===
    if face in ("south", "north"):
        perp_vals = [h[1] for h in face_hits]
    else:
        perp_vals = [h[0] for h in face_hits]

    perp_counter = Counter(perp_vals)
    wall, wall_count = perp_counter.most_common(1)[0]

    fd['wall_px'] = int(wall)
    fd['wall_hits'] = int(wall_count)
    fd['wall_distribution'] = [
        {'pos': int(pos), 'count': int(cnt)}
        for pos, cnt in perp_counter.most_common()[:20]
    ]

    min_wall_hits = 1 if seed_confirmed else 3
    if wall_count < min_wall_hits:
        return _finish('wall_too_few_hits',
                       {'wall_count': int(wall_count)})

    # === Step 2: identify arc hits (shorter than the wall) ===
    if face == "south":
        arc_hits = [(h[0], h[1]) for h in face_hits if h[1] < wall]
    elif face == "north":
        arc_hits = [(h[0], h[1]) for h in face_hits if h[1] > wall]
    elif face == "east":
        arc_hits = [(h[0], h[1]) for h in face_hits if h[0] < wall]
    else:  # west
        arc_hits = [(h[0], h[1]) for h in face_hits if h[0] > wall]

    fd['arc_hits_count'] = len(arc_hits)

    if not arc_hits:
        if not seed_confirmed:
            return _finish('no_arc_hits')
        origin = x0 if face in ("south", "north") else y0
        face_end = x1 if face in ("south", "north") else y1
        seed_along = face_seeds[0]["seed_x"] if face in ("south", "north") \
            else face_seeds[0]["seed_y"]
        fb_offset = max(0, min(face_end - origin - door_width_px,
                               seed_along - origin - door_width_px // 2))
        fb_door = {
            "face": face,
            "offset_px": fb_offset,
            "width_px": min(door_width_px, face_end - origin),
            "hinge_side": "left",
            "opens_inward": True,
        }
        fd['rejected'] = None
        fd['doors_found'] = 1
        fd['seed_fallback'] = True
        if diag is not None:
            diag.setdefault('door_faces', []).append(fd)
        return wall, [fb_door]

    # === Step 3: verify arc profile ===
    if face in ("south", "north"):
        along_vals = [h[0] for h in arc_hits]
    else:
        along_vals = [h[1] for h in arc_hits]

    arc_min_along = min(along_vals)
    arc_max_along = max(along_vals)
    arc_span = arc_max_along - arc_min_along + 1

    fd['arc_span_px'] = int(arc_span)
    fd['arc_along_range'] = [int(arc_min_along), int(arc_max_along)]

    if arc_span >= face_len * 0.8:
        return _finish('arc_too_wide',
                       {'arc_span': int(arc_span),
                        'face_len': int(face_len)})

    min_arc_hits = 1 if seed_confirmed else 3
    if len(arc_hits) < min_arc_hits:
        return _finish('arc_too_few_hits',
                       {'arc_hits': len(arc_hits)})

    # Monotonicity: sort by along-axis, compute distance from wall.
    sorted_arc = sorted(
        arc_hits,
        key=lambda h: h[0] if face in ("south", "north") else h[1])
    if face == "south":
        dists = [wall - h[1] for h in sorted_arc]
    elif face == "north":
        dists = [h[1] - wall for h in sorted_arc]
    elif face == "east":
        dists = [wall - h[0] for h in sorted_arc]
    else:
        dists = [h[0] - wall for h in sorted_arc]

    if dists[0] >= dists[-1]:
        hinge_side = "left"
        profile_dists = dists
    else:
        hinge_side = "right"
        profile_dists = list(reversed(dists))

    violations = sum(1 for i in range(1, len(profile_dists))
                     if profile_dists[i] > profile_dists[i - 1])
    violation_ratio = violations / max(1, len(profile_dists) - 1)

    fd['arc_profile_dists'] = [int(d) for d in dists[:30]]
    fd['arc_hinge_side'] = hinge_side
    fd['arc_violations'] = violations
    fd['arc_violation_ratio'] = round(violation_ratio, 3)

    max_violation_ratio = 0.60 if seed_confirmed else 0.30
    if violation_ratio > max_violation_ratio:
        return _finish('arc_not_monotonic',
                       {'violation_ratio': round(violation_ratio, 3)})

    # Arc depth variation: hinge is far from wall, free jamb at wall.
    dist_range = max(dists) - min(dists)
    fd['arc_dist_range'] = int(dist_range)
    min_dist_range = 1 if seed_confirmed else 3
    if dist_range < min_dist_range:
        return _finish('arc_too_flat',
                       {'dist_range': int(dist_range)})

    # === Step 4: verify wall opening ===
    arc_zone_start = arc_min_along
    arc_zone_end = arc_max_along
    if face in ("south", "north"):
        wall_pixels_in_arc = sum(
            1 for x in range(arc_zone_start, arc_zone_end + 1)
            if 0 <= wall < binary.shape[0]
            and 0 <= x < binary.shape[1]
            and binary[wall, x])
    else:
        wall_pixels_in_arc = sum(
            1 for y in range(arc_zone_start, arc_zone_end + 1)
            if 0 <= wall < binary.shape[1]
            and 0 <= y < binary.shape[0]
            and binary[y, wall])

    arc_zone_len = arc_zone_end - arc_zone_start + 1
    wall_fill_ratio = wall_pixels_in_arc / max(1, arc_zone_len)

    fd['wall_pixels_in_arc'] = int(wall_pixels_in_arc)
    fd['arc_zone_len'] = int(arc_zone_len)
    fd['wall_fill_ratio'] = round(wall_fill_ratio, 3)

    max_wall_fill = 0.80 if seed_confirmed else 0.50
    if wall_fill_ratio > max_wall_fill:
        return _finish('wall_not_interrupted',
                       {'wall_fill_ratio': round(wall_fill_ratio, 3)})

    # === Step 5: build door info ===
    origin = x0 if face in ("south", "north") else y0
    offset = arc_min_along - origin
    door_width = arc_span

    fd['door_offset_px'] = int(offset)
    fd['door_width_detected_px'] = int(door_width)
    fd['wall_confirmation'] = int(wall_count)

    jamb_hinge = arc_min_along if hinge_side == "left" else arc_max_along
    jamb_free = arc_max_along if hinge_side == "left" else arc_min_along
    mid = (arc_min_along + arc_max_along) / 2
    if face == "south":
        seed_x = int(round(mid))
        seed_y = int(round(wall - DOOR_PROBE_PX))
    elif face == "north":
        seed_x = int(round(mid))
        seed_y = int(round(wall + DOOR_PROBE_PX))
    elif face == "east":
        seed_x = int(round(wall - DOOR_PROBE_PX))
        seed_y = int(round(mid))
    else:  # west
        seed_x = int(round(wall + DOOR_PROBE_PX))
        seed_y = int(round(mid))

    door = {
        "face": face,
        "offset_px": offset,
        "width_px": door_width,
        "hinge_side": hinge_side,
        "opens_inward": True,
        "jamb_hinge_px": jamb_hinge,
        "jamb_free_px": jamb_free,
        "wall_px": wall,
        "seed_x": seed_x,
        "seed_y": seed_y,
    }

    # Success — record diag
    fd['rejected'] = None
    fd['doors_found'] = 1
    if diag is not None:
        diag.setdefault('door_faces', []).append(fd)

    return wall, [door]


def expand_door_arcs(binary, rect, dir_hits, cx, cy,
                     door_width_px=23, tolerance=0.35,
                     door_seeds=None, binary_arcs=None,
                     diag=None, snap_rect=None,
                     scale_cm_per_px=0.5):
    """Phase 3: detect door swings and expand the rectangle (D-173).

    Args:
        binary: cleaned binary used for wall-opening heuristic.
        dir_hits: dict {face: [(x,y), ...]} — hits per direction.
        door_seeds: (OPT) list of {face, seed_x, seed_y}. Passed to
            _detect_doors_on_face for diagnostic / future use.
        binary_arcs: (OPT) kept for interface compatibility.
        snap_rect: (OPT) pre-pillar-extension rect used for the
            along-axis hit filter. Prevents a pillar on one face
            from widening the detection range of other faces.

    Returns:
        (expanded_rect, doors) where doors = list of door_info dicts.
    """
    x0, y0, x1, y1 = rect
    orig_rect = (x0, y0, x1, y1)
    doors = []

    seeds_by_face: dict[str, list] = {}
    faceless_seeds: list = []
    if door_seeds:
        for s in door_seeds:
            f = s.get("face")
            if f in ("south", "north", "east", "west"):
                seeds_by_face.setdefault(f, []).append(s)
            elif "seed_x" in s and "seed_y" in s:
                faceless_seeds.append(s)

    perp_tolerance_px = max(door_width_px * 3, int(200 / scale_cm_per_px)) \
        if scale_cm_per_px > 0 else door_width_px * 3

    def _seeds_for_face(face):
        result = list(seeds_by_face.get(face, []))
        for s in faceless_seeds:
            sx, sy = s["seed_x"], s["seed_y"]
            if face == "south":
                if abs(sy - y1) <= perp_tolerance_px and x0 <= sx <= x1:
                    result.append(s)
            elif face == "north":
                if abs(sy - y0) <= perp_tolerance_px and x0 <= sx <= x1:
                    result.append(s)
            elif face == "east":
                if abs(sx - x1) <= perp_tolerance_px and y0 <= sy <= y1:
                    result.append(s)
            elif face == "west":
                if abs(sx - x0) <= perp_tolerance_px and y0 <= sy <= y1:
                    result.append(s)
        return result or None

    for face in ("south", "north", "east", "west"):
        face_hits = dir_hits.get(face, [])
        new_edge, face_doors = _detect_doors_on_face(
            binary, orig_rect, face_hits, face,
            door_width_px, tolerance,
            face_seeds=_seeds_for_face(face),
            binary_arcs=binary_arcs, diag=diag,
            filter_rect=snap_rect)
        if new_edge is not None:
            if face == "south": y1 = new_edge
            elif face == "north": y0 = new_edge
            elif face == "east": x1 = new_edge
            elif face == "west": x0 = new_edge
            doors.extend(face_doors)

    return (x0, y0, x1, y1), doors


@dataclass
class CombResult:
    """Result of detect_room: bbox, hits, doors, pillars, diagnostics."""

    bbox: tuple[int, int, int, int]
    hits: list[tuple[int, int]]
    doors: list[dict]
    pillars: list[dict] = field(default_factory=list)
    pillar_hits: list[tuple[int, int]] = field(default_factory=list)
    dir_hits: dict[str, list[tuple[int, int]]] = field(default_factory=dict)
    coarse_hits: dict[str, list[tuple[int, int]]] = field(
        default_factory=dict)


def detect_room(binary, cx, cy, step_px, door_width_px=23, other_seeds=None,
                scale_cm_per_px: float | None = None,
                binary_for_arcs=None, door_seeds=None,
                diag=None, detection_overrides=None,
                stop_mask=None):
    """Detect a room rectangle: comb ��� hits → largest rectangle → door arc expansion.

    Args:
        binary: cleaned binary (post `remove_non_ortho`) — used for
            comb ray-cast, rectangle fitting and `snap_through_white`.
        binary_for_arcs: (OPT, D-145) pre-`remove_non_ortho` binary —
            used by `expand_door_arcs` to preserve door arc pixels that
            would be removed as non-orthogonal. Falls back to `binary`.
        door_seeds: (OPT, D-145) list of `{face, seed_x, seed_y}` used
            as anchors to scope the arc scan locally instead of
            scanning the whole face. `expand_door_arcs` ignores faces
            not listed when a non-None list is provided.
    """
    if scale_cm_per_px is not None:
        _apply_detection_config(scale_cm_per_px, detection_overrides)
    all_hits, dir_hits, coarse_hits = comb_collect_hits(
        binary, cx, cy, step_px,
        other_seeds=other_seeds,
        diag=diag,
        stop_mask=stop_mask)

    # Phase 2b: filter out narrow pillar hits before rectangle fitting.
    # Door seeds define exclusion squares so arc fragments near doors
    # are not mistaken for pillars.
    from olm.core.detection_config import DEFAULT_DETECTION_CONFIG_CM
    _det_cfg = DEFAULT_DETECTION_CONFIG_CM.to_px(
        scale_cm_per_px if scale_cm_per_px else 0.5)
    if diag is not None:
        diag['hits_after_seed_filter'] = {
            d: len(dir_hits[d]) for d in dir_hits
        }

    pillars, pillar_hit_coords = _filter_pillar_hits(
        dir_hits, cx, cy, MIN_OBSTACLE_WIDTH_PX,
        min_pillar_size_px=MIN_PILLAR_SIZE_PX,
        max_pillar_size_px=MAX_PILLAR_SIZE_PX,
        door_seeds=door_seeds,
        min_door_width_px=_det_cfg.min_door_width_px,
        step_px=step_px,
    )
    # Rebuild all_hits from filtered dir_hits (pillar hits removed).
    all_hits_filtered = [h for hits in dir_hits.values() for h in hits]

    if diag is not None:
        diag['hits_after_pillar_filter'] = {
            d: len(dir_hits[d]) for d in dir_hits
        }
        diag['pillar_hits_removed'] = len(pillar_hit_coords)
        diag['pillars_detected'] = [
            {'face': p['face'], 'pos': p['pos_along_px'],
             'width': p['width_px'], 'depth': p['depth_px']}
            for p in pillars
        ]

    rect = largest_rect_no_hits(all_hits_filtered, cx, cy)
    if rect is None:
        return CombResult(
            bbox=(cx - 1, cy - 1, cx + 1, cy + 1),
            hits=all_hits, doors=[], dir_hits=dir_hits,
            coarse_hits=coarse_hits)

    if diag is not None:
        diag['rect_after_largest'] = rect

    # Expand each edge outward through fully white lines
    rect = snap_through_white(binary, rect)

    # Step 3: if a face has no wall (edge is on white pixels), extend
    # outward until finding solid pixels. Limit by coarse_max to avoid
    # unbounded extension. Handles cases where parasitic hits from
    # adjacent rooms caused the rectangle to stop too early.
    _cm = diag.get('coarse_max', {}) if diag else {}
    _snap_caps = {
        'north': _cm.get('north', 200),
        'south': _cm.get('south', 200),
        'west': _cm.get('west', 200),
        'east': _cm.get('east', 200),
    }
    rect = snap_to_wall(binary, rect, max_advance_per_face=_snap_caps)

    if diag is not None:
        diag['rect_after_snap'] = rect

    # snap_rect = rectangle BEFORE pillar extension (D-173).  Pillar
    # extension enlarges the bbox on one face to reach the real wall
    # behind a pillar.  This must NOT widen the hit-filter range of
    # OTHER faces.  snap_rect is passed to _detect_doors_on_face as
    # filter_rect so each face filters hits against the original
    # (pre-pillar) bounds.
    snap_rect = rect

    # Extend bbox edges to include pillar wall position (mode_coord_px).
    # The rectangle may stop at the pillar tip; extend to the real wall.
    if pillars:
        rx0, ry0, rx1, ry1 = rect
        for p in pillars:
            mc = p['mode_coord_px']
            pf = p['face']
            if pf == 'north':
                ry0 = min(ry0, mc)
            elif pf == 'south':
                ry1 = max(ry1, mc)
            elif pf == 'west':
                rx0 = min(rx0, mc)
            elif pf == 'east':
                rx1 = max(rx1, mc)
        rect = (rx0, ry0, rx1, ry1)

    if diag is not None:
        diag['rect_after_pillars'] = rect

    # Phase 3: door arc expansion (D-173) — analyse les hits par
    # direction pour trouver les arcs de porte.
    rect, doors = expand_door_arcs(binary, rect, dir_hits, cx, cy,
                                   door_width_px=door_width_px,
                                   door_seeds=door_seeds,
                                   binary_arcs=binary_for_arcs,
                                   diag=diag,
                                   snap_rect=snap_rect,
                                   scale_cm_per_px=scale_cm_per_px)

    return CombResult(
        bbox=rect, hits=all_hits, doors=doors,
        pillars=pillars, pillar_hits=pillar_hit_coords,
        dir_hits=dir_hits, coarse_hits=coarse_hits)


# Automatic exclusion zone extension removed.
# Exclusion zones are entered manually in the Review phase.


def extract_all_rooms(image_path, scale_cm_per_px=None, threshold=None,
                      detection_overrides=None):
    """Run the full extraction pipeline on a floor plan image.

    Args:
        image_path: path to the raster floor plan image
        scale_cm_per_px: cm per pixel (estimated if not provided)
        threshold: binarization threshold (default BINARIZE_THRESHOLD)
        detection_overrides: dict of DetectionConfigCm overrides from user
            settings (ex. ``{"cartouche_margin_cm": 5.0}``)

    Returns:
        dict with:
          'rooms': list of room dicts (name, bbox_px, width_cm, depth_cm,
                   windows, openings, doors, exterior_faces, corridor_face)
          'image_size': (width, height) in pixels
          'scale_cm_per_px': used scale
          'binary': binarized image as numpy array (for visualization)
    """
    from olm.ingestion.extract import _classify_wall_direct

    thr = threshold or BINARIZE_THRESHOLD
    # Scale fourni par le caller (drawing_scale ou scale_cm_per_px) ou
    # auto-détecté plus bas. À l'étape de classification (avant l'auto-
    # détection), on a besoin d'un scale réaliste pour que les seuils en
    # cm de DEFAULT_DETECTION_CONFIG_CM se convertissent en px corrects.
    # Sans scale fourni → fallback 0.5 (= comportement historique).
    classify_scale = scale_cm_per_px if scale_cm_per_px is not None else 0.5
    logger.info(f"Ingestion: loading {image_path}")
    img_gray = load_image(image_path)
    logger.debug(f"  image size: {img_gray.width} × {img_gray.height} px")

    # Aligne les constantes pixels du module sur le scale réel AVANT
    # find_seeds_by_ocr — sans ça, CARTOUCHE_MARGIN_PX reste à sa
    # valeur d'import (1 px), ce qui produit des bboxes cartouche trop
    # serrées et laisse du texte dans l'image binarisée.
    _apply_detection_config(classify_scale, detection_overrides)

    seeds, cart_bboxes = find_seeds_by_ocr(img_gray)

    if not seeds:
        logger.error(f"ERROR: No seeds found! Check the room_code setting and cartouche text in the floor plan.")
        return {
            'rooms': [],
            'image_size': (img_gray.size[0], img_gray.size[1]),
            'scale_cm_per_px': scale_cm_per_px or 0.5,
            'threshold': thr,
        }

    logger.info(f"Ingestion: processing {len(seeds)} room(s)")
    gray_arr = np.array(img_gray)
    cleaned = erase_cartouches(gray_arr, cart_bboxes)
    binary = cleaned < thr
    logger.debug(f"  binarization: {np.sum(binary)} wall pixels (threshold={thr})")

    all_seed_positions = [(v[0], v[1]) for v in seeds.values()]

    rooms = []
    for name, seed_data in sorted(seeds.items()):
        cx, cy = seed_data[0], seed_data[1]
        surface_m2 = seed_data[2] if len(seed_data) > 2 else 0.0
        other = [(ox, oy) for ox, oy in all_seed_positions
                 if (ox, oy) != (cx, cy)]
        # door_width_px doit être en px au scale courant : la valeur par
        # défaut de detect_room (23 px) suppose scale=0.5 et est
        # complètement fausse à un autre scale (ex. plan big 0.95 cm/px →
        # 23 px = 21 cm, cherche des arcs trop courts → micro-portes).
        from olm.core.detection_config import DEFAULT_DETECTION_CONFIG_CM
        _cfg_px = DEFAULT_DETECTION_CONFIG_CM.to_px(classify_scale)
        cr = detect_room(binary, cx, cy, COMB_STEP_PX,
                         door_width_px=_cfg_px.default_door_width_px,
                         other_seeds=other,
                         scale_cm_per_px=classify_scale)

        # Filtre largeur min/max porte (élimine micro-portes et faux positifs).
        _min_door_w_px = _cfg_px.min_door_width_px
        _max_door_w_px = _cfg_px.max_door_width_px
        doors = [d for d in cr.doors
                 if _min_door_w_px <= d.get('width_px', 0) <= _max_door_w_px]

        x0, y0, x1, y1 = cr.bbox
        width_px = x1 - x0
        height_px = y1 - y0

        # Debug: save intermediate image
        save_debug_image(binary, cr.hits, cr.bbox, name, f"comb_{width_px}x{height_px}")

        # Classify walls
        wall_segs = {}
        for face in ('north', 'south', 'east', 'west'):
            segs, _ = _classify_wall_direct(binary, binary, cr.bbox, face, 5,
                                            scale_cm_per_px=classify_scale)
            wall_segs[face] = segs

        # Extract windows, openings, doors from wall segments
        windows = []
        openings = []
        for face, segs in wall_segs.items():
            face_len = width_px if face in ('north', 'south') else height_px
            for seg in segs:
                if seg.kind == 'window':
                    windows.append({
                        'face': face,
                        'offset_px': seg.start_px,
                        'width_px': seg.end_px - seg.start_px,
                    })
                elif seg.kind == 'opening':
                    openings.append({
                        'face': face,
                        'offset_px': seg.start_px,
                        'width_px': seg.end_px - seg.start_px,
                    })

        # Derive exterior faces (faces with windows)
        exterior_faces = list(set(w['face'] for w in windows))

        # Corridor face (face with a door)
        corridor_face = doors[0]['face'] if doors else ''

        # Scale
        s = scale_cm_per_px or 0.5
        room = {
            'name': name,
            'seed_px': (cx, cy),
            'bbox_px': (x0, y0, x1, y1),
            'width_px': width_px,
            'height_px': height_px,
            'surface_m2': surface_m2,
            'windows': windows,
            'openings': openings,
            'doors': doors,
            'exterior_faces': exterior_faces,
            'corridor_face': corridor_face,
            'hits': [[int(h[0]), int(h[1]), face[0]]
                     for face, fhits in cr.dir_hits.items()
                     for h in fhits],
            'coarse_hits': [[int(h[0]), int(h[1]), face[0]]
                            for face, fhits in cr.coarse_hits.items()
                            for h in fhits],
        }
        logger.debug(f"  room '{name}': bbox=({x0},{y0},{x1},{y1}) {width_px}×{height_px}px, "
                     f"win={len(windows)} open={len(openings)} door={len(doors)}")
        rooms.append(room)

    # Auto-calibrate scale from OCR-annotated surfaces (D-155).
    # Always run regardless of scale_cm_per_px: the annotated surfaces on the
    # plan are ground truth, while the provided scale may assume a wrong DPI.
    img_w, img_h = img_gray.size
    scale_samples = []
    for r in rooms:
        x0, y0, x1, y1 = r['bbox_px']
        at_edge = (x0 < CALIB_EDGE_MARGIN_PX or y0 < CALIB_EDGE_MARGIN_PX
                   or x1 > img_w - CALIB_EDGE_MARGIN_PX
                   or y1 > img_h - CALIB_EDGE_MARGIN_PX)
        if (r['surface_m2'] >= MIN_CALIB_SURFACE_M2
                and r['width_px'] > MIN_CALIB_DIM_PX
                and r['height_px'] > MIN_CALIB_DIM_PX
                and not at_edge):
            area_cm2 = r['surface_m2'] * 10000
            area_px2 = r['width_px'] * r['height_px']
            scale_samples.append((area_cm2 / area_px2) ** 0.5)
    if scale_samples:
        scale_samples.sort()
        s = scale_samples[len(scale_samples) // 2]  # median
        logger.info(
            "Scale auto-calibrated from %d room surface(s): %.4f cm/px"
            " (hint was %.4f)",
            len(scale_samples), s, scale_cm_per_px or 0.0,
        )
    else:
        s = scale_cm_per_px if scale_cm_per_px is not None else 0.5
        logger.info("No rooms eligible for scale calibration — using %.4f cm/px",
                     s)

    # Apply scale to all rooms
    for r in rooms:
        r['width_cm'] = round(r['width_px'] * s)
        r['depth_cm'] = round(r['height_px'] * s)

    logger.info(f"Ingestion: SUCCESS — {len(rooms)} room(s), scale={s:.3f} cm/px")
    for r in rooms:
        logger.debug(f"  {r['name']}: {r['width_cm']}×{r['depth_cm']}cm")

    return {
        'rooms': rooms,
        'image_size': (img_gray.size[0], img_gray.size[1]),
        'scale_cm_per_px': round(s, 3),
        'threshold': thr,
        # Cart_bboxes en absolu pixels image — exposés au front pour
        # debug overlay (D-148 + viz). Ils servent aussi au erase au scan
        # initial. Liste de (x0, y0, x1, y1) déjà avec CARTOUCHE_MARGIN_PX.
        'cart_bboxes_px': [list(map(int, cb)) for cb in cart_bboxes],
    }


def draw_debug_all(image, results, output_path):
    img = image.convert("RGB").copy()
    draw = ImageDraw.Draw(img)

    colors = [
        (255, 0, 0), (0, 0, 255), (0, 180, 0), (255, 128, 0),
        (180, 0, 180), (0, 180, 180), (128, 128, 0), (255, 0, 128),
    ]

    for i, (name, bbox, cx, cy, _hits, _doors) in enumerate(results):
        x0, y0, x1, y1 = bbox
        color = colors[i % len(colors)]
        draw.rectangle([x0, y0, x1, y1], outline=color, width=2)
        draw.ellipse([cx - 2, cy - 2, cx + 2, cy + 2], fill=(0, 255, 0))
        draw.text((x0, y0 - 12), name, fill=color)

    img.save(output_path)
    print(f"Debug image saved: {output_path}")


def draw_debug_single(image, binary, name, bbox, hits, cx, cy, output_path):
    x0, y0, x1, y1 = bbox
    margin = 40

    img = image.convert("RGB").copy()
    draw = ImageDraw.Draw(img)

    # Hits in red
    for hx, hy in hits:
        draw.ellipse([hx - 2, hy - 2, hx + 2, hy + 2], fill=(255, 0, 0))

    # Rectangle in blue
    draw.rectangle([x0, y0, x1, y1], outline=(0, 0, 255), width=2)
    # Seed in green
    draw.ellipse([cx - 3, cy - 3, cx + 3, cy + 3], fill=(0, 255, 0))

    crop_x0 = max(0, x0 - margin)
    crop_y0 = max(0, y0 - margin)
    crop_x1 = min(img.width, x1 + margin)
    crop_y1 = min(img.height, y1 + margin)
    img.crop((crop_x0, crop_y0, crop_x1, crop_y1)).save(output_path)
    print(f"Single room debug: {output_path}")


def main():
    # Configure logging to see debug messages
    logging.basicConfig(
        level=logging.DEBUG,
        format='[%(levelname)s] %(message)s'
    )

    target_room = sys.argv[1] if len(sys.argv) > 1 else None

    print(f"Loading plan: {PLAN_PATH}")
    img_gray = load_image(PLAN_PATH)
    print(f"Image: {img_gray.size}")

    print("Step 1+2: OCR → seeds + label boxes...")
    seeds, cartouche_bboxes = find_seeds_by_ocr(img_gray)

    if not seeds:
        print("No seeds found!")
        return

    print(f"Seeds found: {len(seeds)}")

    print("Step 4: erasing label boxes...")
    gray_arr = np.array(img_gray)
    cleaned_arr = erase_cartouches(gray_arr, cartouche_bboxes)
    Image.fromarray(cleaned_arr).save(os.path.join(_TMP, "cleaned_plan.png"))

    print("Step 3: binarizing at threshold 80...")
    binary = binarize(cleaned_arr)
    print(f"  Wall pixels: {np.sum(binary)}")

    print("Step 3b: removing non-orthogonal elements...")
    # remove_non_ortho disabled — door detection works on raw geometry
    # (hits + contact pattern), non-ortho elements don't interfere
    # binary = remove_non_ortho(binary)
    print(f"  Wall pixels after: {np.sum(binary)}")

    # Save for debug
    Image.fromarray((~binary * 255).astype(np.uint8)).save(os.path.join(_TMP, "ortho_plan.png"))

    step_px = COMB_STEP_PX

    all_seed_positions = [(v[0], v[1]) for v in seeds.values()]

    if target_room:
        if target_room not in seeds:
            print(f"Room {target_room} not found. "
                  f"Available: {sorted(seeds.keys())}")
            return
        cx, cy = seeds[target_room][0], seeds[target_room][1]
        other = [(ox, oy) for ox, oy in all_seed_positions if (ox, oy) != (cx, cy)]
        print(f"\n=== {target_room} (seed {cx},{cy}) ===")
        cr = detect_room(binary, cx, cy, step_px, other_seeds=other)
        x0, y0, x1, y1 = cr.bbox
        print(f"Rectangle: ({x0},{y0}) → ({x1},{y1})")
        print(f"Size: {x1 - x0} x {y1 - y0} px")
        print(f"Hits: {len(cr.hits)}")
        for d in cr.doors:
            print(f"Door: face={d['face']}, offset={d['offset_px']}px, "
                  f"width={d['width_px']}px, hinge={d['hinge_side']}")
        for p in cr.pillars:
            print(f"Pillar: face={p['face']}, pos={p['pos_along_px']}px, "
                  f"w={p['width_px']}px, d={p['depth_px']}px")
        draw_debug_single(Image.fromarray(cleaned_arr), binary,
                          target_room, cr.bbox, cr.hits, cx, cy,
                          os.path.join(_TMP, f"comb_{target_room}.png"))
    else:
        results = []
        for name, seed_data in sorted(seeds.items()):
            cx, cy = seed_data[0], seed_data[1]
            other = [(ox, oy) for ox, oy in all_seed_positions if (ox, oy) != (cx, cy)]
            cr = detect_room(binary, cx, cy, step_px, other_seeds=other)
            x0, y0, x1, y1 = cr.bbox
            door_str = f" | {len(cr.doors)} door(s)" if cr.doors else ""
            print(f"  {name}: ({x0},{y0}) → ({x1},{y1}) = "
                  f"{x1 - x0}x{y1 - y0}px{door_str}")
            results.append((name, cr.bbox, cx, cy, cr.hits, cr.doors))

        draw_debug_all(Image.fromarray(cleaned_arr), results,
                       os.path.join(_TMP, "comb_all.png"))


if __name__ == "__main__":
    main()

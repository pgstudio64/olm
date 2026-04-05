"""
Test du peigne adaptatif sur test_floorplan2.png.

Pipeline complet :
  1. OCR (pytesseract --psm 11, upscale x2) → trouver tous les "14"
  2. Parsing syntaxique des cartouches → seed = centre géométrique, nom = numéro pièce
  3. Binarisation seuil 80
  4. Effacement des cartouches → blanc
  5. Peigne adaptatif (condition d'arrêt dynamique) → grille de points
  6. Plus grand rectangle contenant le seed
  7. Visualisation debug

Usage:
  python /tmp/test_comb.py              # toutes les pièces
  python /tmp/test_comb.py 916          # pièce 916 seule
"""

import sys
import numpy as np
import cv2
from PIL import Image, ImageDraw
from collections import deque

# --- Paramètres ---
PLAN_PATH = "/Users/patrickguehl/AI-OLM/project/plans/test_floorplan2.png"
BINARIZE_THRESHOLD = 80
COMB_STEP_PX = 5   # pas du peigne en pixels
MAX_RAY_PX = 1500
CARTOUCHE_MARGIN_PX = 1


def load_image(path):
    return Image.open(path).convert("L")


def find_seeds_by_ocr(image):
    try:
        import pytesseract
    except ImportError:
        print("pytesseract non disponible")
        return {}, []

    ocr_image = image.resize((image.width * 2, image.height * 2), Image.LANCZOS)
    data = pytesseract.image_to_data(ocr_image, config='--psm 11',
                                     output_type=pytesseract.Output.DICT)
    words = []
    for i in range(len(data["text"])):
        text = data["text"][i].strip()
        if not text:
            continue
        x = data["left"][i] // 2
        y = data["top"][i] // 2
        w = data["width"][i] // 2
        h = data["height"][i] // 2
        words.append({
            "text": text,
            "cx": x + w // 2, "cy": y + h // 2,
            "x": x, "y": y, "w": w, "h": h,
        })

    words.sort(key=lambda w: (w["cy"], w["cx"]))

    seeds = {}
    cartouche_bboxes = []

    for word in words:
        if word["text"] != "14":
            continue

        seed_cx = word["cx"]
        seed_cy = word["cy"]

        cart_words = [word]
        room_name = f"room_{seed_cx}_{seed_cy}"

        for other in words:
            if other is word:
                continue
            if (other["cy"] > seed_cy and
                other["cy"] < seed_cy + 80 and
                abs(other["cx"] - seed_cx) < 30):
                cart_words.append(other)
                if other["text"].isdigit() and len(other["text"]) == 3:
                    room_name = other["text"]

        all_x0 = min(w["x"] for w in cart_words)
        all_y0 = min(w["y"] for w in cart_words)
        all_x1 = max(w["x"] + w["w"] for w in cart_words)
        all_y1 = max(w["y"] + w["h"] for w in cart_words)
        cartouche_bboxes.append((
            all_x0 - CARTOUCHE_MARGIN_PX,
            all_y0 - CARTOUCHE_MARGIN_PX,
            all_x1 + CARTOUCHE_MARGIN_PX,
            all_y1 + CARTOUCHE_MARGIN_PX,
        ))

        seed_cx = (all_x0 + all_x1) // 2
        seed_cy = (all_y0 + all_y1) // 2
        seeds[room_name] = (seed_cx, seed_cy)

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


def remove_non_ortho(binary):
    """Supprime les éléments non-orthogonaux (arcs de porte, cotations).

    Analyse chaque composante connexe par minAreaRect. Si l'orientation
    dominante n'est ni ~0° ni ~90° (tolérance 5°), la composante est supprimée.
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


def ray_single(binary, x, y, dx, dy, max_dist=MAX_RAY_PX):
    """Retourne la distance au premier mur, ou -1 si le point de départ est sur un mur."""
    h, w = binary.shape
    if 0 <= x < w and 0 <= y < h and binary[y, x]:
        return -1
    px, py = x, y
    for d in range(1, max_dist + 1):
        px += dx
        py += dy
        if px < 0 or px >= w or py < 0 or py >= h:
            return d
        if binary[py, px]:
            return d
    return max_dist


def comb_collect_hits(binary, cx, cy, step_px):
    """Peigne adaptatif avec condition d'arrêt dynamique.

    Lance des rays depuis le seed dans les 4 directions, en s'écartant
    par pas de step_px. S'arrête dans une direction quand on a dépassé
    le max de distance trouvé dans la direction perpendiculaire.

    Retourne la liste des hits (px, py) = points d'impact sur les murs.
    """
    max_ns = 0
    max_ew = 0
    hits = []

    # Rays initiaux
    for dx, dy in [(0, -1), (0, 1), (-1, 0), (1, 0)]:
        d = ray_single(binary, cx, cy, dx, dy)
        if d > 0:
            hits.append((cx + dx * d, cy + dy * d))
            if dy != 0:
                max_ns = max(max_ns, d)
            else:
                max_ew = max(max_ew, d)

    # Peigne vertical (rays N et S) — s'arrête quand offset > max_ew
    step = 1
    while True:
        offset = step * step_px
        if offset > max_ew:
            break
        for rx in (cx - offset, cx + offset):
            d = ray_single(binary, rx, cy, 0, -1)
            if d > 0:
                hits.append((rx, cy - d))
                max_ns = max(max_ns, d)
            d = ray_single(binary, rx, cy, 0, 1)
            if d > 0:
                hits.append((rx, cy + d))
                max_ns = max(max_ns, d)
        step += 1

    # Peigne horizontal (rays E et O) — s'arrête quand offset > max_ns
    step = 1
    while True:
        offset = step * step_px
        if offset > max_ns:
            break
        for ry in (cy - offset, cy + offset):
            d = ray_single(binary, cx, ry, -1, 0)
            if d > 0:
                hits.append((cx - d, ry))
                max_ew = max(max_ew, d)
            d = ray_single(binary, cx, ry, 1, 0)
            if d > 0:
                hits.append((cx + d, ry))
                max_ew = max(max_ew, d)
        step += 1

    return hits


def largest_rect_no_hits(hits, cx, cy):
    """Plus grand rectangle contenant (cx,cy) sans aucun hit à l'intérieur.

    Les hits peuvent être sur les bords du rectangle.
    Approche : pour chaque paire de bornes y (top, bottom) définies par
    les hits, trouver les bornes x les plus larges telles qu'aucun hit
    ne soit strictement à l'intérieur.
    """
    if not hits:
        return (cx - 1, cy - 1, cx + 1, cy + 1)

    # Collecter toutes les coordonnées y uniques des hits
    ys = sorted(set(h[1] for h in hits))

    best_area = 0
    best_rect = None

    # Pour chaque paire (y_top, y_bottom) qui contient cy
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

            # Trouver les bornes x : les hits dans la bande
            # y_top <= hit_y <= y_bot contraignent x
            x_left = -999999
            x_right = 999999

            for hx, hy in hits:
                if y_top <= hy <= y_bot:
                    # Ce hit est dans la bande (bords inclus)
                    if hx <= cx:
                        x_left = max(x_left, hx)
                    if hx >= cx:
                        x_right = min(x_right, hx)

            w = x_right - x_left
            if w <= 0:
                continue

            area = w * h
            if area > best_area:
                best_area = area
                best_rect = (x_left, y_top, x_right, y_bot)

    return best_rect


DOOR_PROBE_PX = 4   # ~2cm, décalage pour sonder la position de la porte
DOOR_GROUP_GAP_PX = 25  # gap max entre pixels d'un même arc (~largeur porte)
WALL_MARGIN_PX = 3   # exclure les pixels proches des murs perpendiculaires


def _group_pixels(pixels, max_gap=DOOR_GROUP_GAP_PX):
    """Regroupe des pixels contigus (avec gap max)."""
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


def _detect_doors_on_face(binary, rect, hits, face, door_width_px, tolerance):
    """Détecte les arcs de porte sur une face du rectangle.

    Returns:
        (new_edge, door_infos) ou (None, []).
    """
    from collections import Counter
    x0, y0, x1, y1 = rect
    min_dist = door_width_px * (1 - tolerance)
    max_dist = door_width_px * (1 + tolerance)
    m = WALL_MARGIN_PX

    if face == "south":
        far = [h for h in hits if h[1] > y1 and min_dist <= h[1] - y1 <= max_dist]
        if not far: return None, []
        wall, n = Counter(h[1] for h in far).most_common(1)[0]
        contact = sum(1 for x in range(x0, x1+1) if 0<=y1<binary.shape[0] and binary[y1,x])
        if n < 5 or contact > 10: return None, []
        probe = wall - DOOR_PROBE_PX
        pixels = [x for x in range(x0+m, x1-m+1) if 0<=probe<binary.shape[0] and binary[probe,x]]
    elif face == "north":
        far = [h for h in hits if h[1] < y0 and min_dist <= y0 - h[1] <= max_dist]
        if not far: return None, []
        wall, n = Counter(h[1] for h in far).most_common(1)[0]
        contact = sum(1 for x in range(x0, x1+1) if 0<=y0<binary.shape[0] and binary[y0,x])
        if n < 5 or contact > 10: return None, []
        probe = wall + DOOR_PROBE_PX
        pixels = [x for x in range(x0+m, x1-m+1) if 0<=probe<binary.shape[0] and binary[probe,x]]
    elif face == "east":
        far = [h for h in hits if h[0] > x1 and min_dist <= h[0] - x1 <= max_dist]
        if not far: return None, []
        wall, n = Counter(h[0] for h in far).most_common(1)[0]
        contact = sum(1 for y in range(y0, y1+1) if 0<=x1<binary.shape[1] and binary[y,x1])
        if n < 5 or contact > 10: return None, []
        probe = wall - DOOR_PROBE_PX
        pixels = [y for y in range(y0+m, y1-m+1) if 0<=probe<binary.shape[1] and binary[y,probe]]
    elif face == "west":
        far = [h for h in hits if h[0] < x0 and min_dist <= x0 - h[0] <= max_dist]
        if not far: return None, []
        wall, n = Counter(h[0] for h in far).most_common(1)[0]
        contact = sum(1 for y in range(y0, y1+1) if 0<=x0<binary.shape[1] and binary[y,x0])
        if n < 5 or contact > 10: return None, []
        probe = wall + DOOR_PROBE_PX
        pixels = [y for y in range(y0+m, y1-m+1) if 0<=probe<binary.shape[1] and binary[y,probe]]
    else:
        return None, []

    groups = _group_pixels(pixels)
    origin = x0 if face in ("south", "north") else y0
    size = (x1 - x0) if face in ("south", "north") else (y1 - y0)
    doors = []
    for g in groups:
        offset = min(g) - origin
        width = max(g) - min(g) + 1
        hinge_side = "left" if (offset < size / 2) else "right"
        doors.append({"face": face, "offset_px": offset,
                      "width_px": width, "hinge_side": hinge_side})

    return wall, doors


def expand_door_arcs(binary, rect, hits, cx, cy,
                     door_width_px=23, tolerance=0.35):
    """Phase 3 : détecte les arcs de porte et agrandit le rectangle.

    Returns:
        (expanded_rect, doors) où doors = liste de door_info dicts.
    """
    x0, y0, x1, y1 = rect
    doors = []

    for face in ("south", "north", "east", "west"):
        new_edge, face_doors = _detect_doors_on_face(
            binary, (x0, y0, x1, y1), hits, face,
            door_width_px, tolerance)
        if new_edge is not None:
            if face == "south": y1 = new_edge
            elif face == "north": y0 = new_edge
            elif face == "east": x1 = new_edge
            elif face == "west": x0 = new_edge
            doors.extend(face_doors)

    return (x0, y0, x1, y1), doors


def detect_room(binary, cx, cy, step_px, door_width_px=23):
    """Détecte le rectangle d'une pièce : peigne → hits → plus grand rectangle → expansion arcs."""
    hits = comb_collect_hits(binary, cx, cy, step_px)

    rect = largest_rect_no_hits(hits, cx, cy)

    if rect is None:
        return (cx - 1, cy - 1, cx + 1, cy + 1), hits, []

    # Phase 3 : expansion arcs de porte
    rect, doors = expand_door_arcs(binary, rect, hits, cx, cy,
                                   door_width_px=door_width_px)

    return rect, hits, doors


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

    # Hits en rouge
    for hx, hy in hits:
        draw.ellipse([hx - 2, hy - 2, hx + 2, hy + 2], fill=(255, 0, 0))

    # Rectangle bleu
    draw.rectangle([x0, y0, x1, y1], outline=(0, 0, 255), width=2)
    # Seed vert
    draw.ellipse([cx - 3, cy - 3, cx + 3, cy + 3], fill=(0, 255, 0))

    crop_x0 = max(0, x0 - margin)
    crop_y0 = max(0, y0 - margin)
    crop_x1 = min(img.width, x1 + margin)
    crop_y1 = min(img.height, y1 + margin)
    img.crop((crop_x0, crop_y0, crop_x1, crop_y1)).save(output_path)
    print(f"Single room debug: {output_path}")


def main():
    target_room = sys.argv[1] if len(sys.argv) > 1 else None

    print(f"Loading plan: {PLAN_PATH}")
    img_gray = load_image(PLAN_PATH)
    print(f"Image: {img_gray.size}")

    print("Étape 1+2 : OCR → seeds + cartouches...")
    seeds, cartouche_bboxes = find_seeds_by_ocr(img_gray)

    if not seeds:
        print("Aucun seed trouvé !")
        return

    print(f"Seeds trouvés: {len(seeds)}")

    print("Étape 4 : effacement des cartouches...")
    gray_arr = np.array(img_gray)
    cleaned_arr = erase_cartouches(gray_arr, cartouche_bboxes)
    Image.fromarray(cleaned_arr).save("/tmp/cleaned_plan.png")

    print("Étape 3 : binarisation seuil 80...")
    binary = binarize(cleaned_arr)
    print(f"  Pixels mur: {np.sum(binary)}")

    print("Étape 3b : suppression éléments non-orthogonaux...")
    binary = remove_non_ortho(binary)
    print(f"  Pixels mur après: {np.sum(binary)}")

    # Sauvegarder pour debug
    Image.fromarray((~binary * 255).astype(np.uint8)).save("/tmp/ortho_plan.png")

    step_px = COMB_STEP_PX

    if target_room:
        if target_room not in seeds:
            print(f"Pièce {target_room} non trouvée. "
                  f"Disponibles: {sorted(seeds.keys())}")
            return
        cx, cy = seeds[target_room]
        print(f"\n=== {target_room} (seed {cx},{cy}) ===")
        bbox, hits, doors = detect_room(binary, cx, cy, step_px)
        x0, y0, x1, y1 = bbox
        print(f"Rectangle: ({x0},{y0}) → ({x1},{y1})")
        print(f"Taille: {x1 - x0} x {y1 - y0} px")
        print(f"Hits: {len(hits)}")
        for d in doors:
            print(f"Porte: face={d['face']}, offset={d['offset_px']}px, "
                  f"largeur={d['width_px']}px, charnière={d['hinge_side']}")
        draw_debug_single(Image.fromarray(cleaned_arr), binary,
                          target_room, bbox, hits, cx, cy,
                          f"/tmp/comb_{target_room}.png")
    else:
        results = []
        for name, (cx, cy) in sorted(seeds.items()):
            bbox, hits, doors = detect_room(binary, cx, cy, step_px)
            x0, y0, x1, y1 = bbox
            door_str = f" | {len(doors)} porte(s)" if doors else ""
            print(f"  {name}: ({x0},{y0}) → ({x1},{y1}) = "
                  f"{x1 - x0}x{y1 - y0}px{door_str}")
            results.append((name, bbox, cx, cy, hits, doors))

        draw_debug_all(Image.fromarray(cleaned_arr), results,
                       "/tmp/comb_all.png")


if __name__ == "__main__":
    main()

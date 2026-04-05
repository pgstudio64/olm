"""Serveur Flask pour l'outil de gestion et création de patterns — solver_lab.

Point d'entrée : python pattern_server.py → http://localhost:5051
Stockage : catalogue/patterns.json
"""
from __future__ import annotations

import json
import os
import traceback

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
    """Sert les fichiers statiques depuis le dossier static/."""
    return send_from_directory(os.path.join(BASE_DIR, "static"), filename)


def _load_catalogue() -> list[dict]:
    """Charge le catalogue depuis le fichier JSON."""
    if not os.path.exists(CATALOGUE_PATH):
        return []
    with open(CATALOGUE_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("patterns", [])


def _save_catalogue(patterns: list[dict]) -> None:
    """Sauvegarde le catalogue dans le fichier JSON."""
    os.makedirs(CATALOGUE_DIR, exist_ok=True)
    with open(CATALOGUE_PATH, "w", encoding="utf-8") as f:
        json.dump({"patterns": patterns}, f, indent=2, ensure_ascii=False)


def _find_pattern(patterns: list[dict], name: str) -> int:
    """Retourne l'index du pattern par nom, ou -1."""
    for i, p in enumerate(patterns):
        if p["name"] == name:
            return i
    return -1


_BASE_BLOCKS = [BLOCK_1, BLOCK_2_FACE, BLOCK_2_SIDE, BLOCK_3_SIDE, BLOCK_4_FACE, BLOCK_6_FACE,
                BLOCK_2_ORTHO_L, BLOCK_2_ORTHO_R]

# Blocs face-à-face : E/W zones = chair + passage (ES-06)
_FACE_TO_FACE_BLOCKS = {"BLOCK_2_FACE", "BLOCK_4_FACE", "BLOCK_6_FACE"}

# Blocs orthogonaux : zones chair + passage_single sur les faces chaise
_ORTHO_BLOCKS = {
    "BLOCK_2_ORTHO_R": {"north", "east"},   # chaises desk1=N, desk2=E (L bas-gauche)
    "BLOCK_2_ORTHO_L": {"north", "west"},   # chaises desk1=N, desk2=W (L bas-droite)
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
    """Convertit un Block en dict JSON, recalculant les dimensions depuis la config."""
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
    """Construit les définitions de blocs pour un standard donné.

    Les zones fixes (débattement chaise) et de circulation varient
    selon le standard d'aménagement.
    """
    chair = cfg.chair_clearance_cm      # ES-01
    passage = cfg.passage_cm            # ES-06
    passage_single = cfg.access_single_desk_cm - chair  # ES-03 - ES-01

    defs = {}
    for block in _BASE_BLOCKS:
        d = _block_def_to_json(block)
        if block.name in _FACE_TO_FACE_BLOCKS:
            # Face-à-face : E/W = chair + passage
            for face in ("east", "west"):
                d["faces"][face] = {
                    "non_superposable_cm": chair,
                    "candidate_cm": passage,
                }
        elif block.name in _ORTHO_BLOCKS:
            # Ortho : chair + passage_single sur les faces chaise
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
            # Seul/côte : W = chair + passage_single
            d["faces"]["west"] = {
                "non_superposable_cm": chair,
                "candidate_cm": passage_single,
            }
        defs[block.name] = d
    return defs


# Cache par standard
_BLOCK_DEFS_CACHE: dict[str, dict] = {}


def _get_block_defs(standard_name: str) -> dict:
    """Retourne les block defs pour un standard (avec cache)."""
    if standard_name not in _BLOCK_DEFS_CACHE:
        cfg = ALL_CONFIGS.get(standard_name)
        if cfg is None:
            cfg = ALL_CONFIGS["AFNOR_ADVICE"]
        _BLOCK_DEFS_CACHE[standard_name] = _build_block_defs(cfg)
    return _BLOCK_DEFS_CACHE[standard_name]


@app.route("/")
def index():
    """Sert la page de l'éditeur de patterns."""
    return send_from_directory(os.path.join(BASE_DIR, "templates"), "pattern_editor.html")


@app.route("/test_rooms.json")
def serve_test_rooms():
    """DEV: sert test_rooms.json pour auto-chargement."""
    return send_from_directory(os.path.join(os.path.dirname(BASE_DIR), "project"), "test_rooms.json")


@app.route("/test_floor_plan.png")
def serve_test_floor_plan():
    """DEV: sert le raster de test."""
    return send_from_directory(
        os.path.join(os.path.dirname(BASE_DIR), "project", "plans"),
        "test_floorplan.png")


@app.route("/specs/<path:filename>")
def serve_specs(filename: str):
    """Sert les fichiers de specs."""
    return send_from_directory(os.path.join(os.path.dirname(BASE_DIR), "docs", "specs"), filename)


@app.route("/matching")
def matching_viewer():
    """Sert la page du matching viewer."""
    return send_from_directory(os.path.join(BASE_DIR, "templates"), "matching_viewer.html")


@app.route("/api/blocks", methods=["GET"])
def api_blocks():
    """Retourne les définitions des blocs pour le standard demandé.

    Query param optionnel : ?standard=GROUP (défaut AFNOR_ADVICE)
    """
    standard = request.args.get("standard", "AFNOR_ADVICE")
    cfg = ALL_CONFIGS.get(standard, ALL_CONFIGS["AFNOR_ADVICE"])
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
    """GET : retourne les 3 configurations d'espacement.
    POST : met à jour un standard. Body: {"standard": "SITE", "values": {...}}.
    """
    if request.method == "POST":
        from olm.core.spacing_config import update_config
        from olm.core.spacing_config import update_config, reset_config
        data = request.json
        name = data.get("standard")
        values = data.get("values", {})
        if not name:
            return jsonify({"error": "Champ requis : standard"}), 400
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
    """Liste tous les patterns du catalogue."""
    patterns = _load_catalogue()
    return jsonify({"patterns": patterns, "count": len(patterns)})


@app.route("/api/catalogue/export", methods=["GET"])
def api_catalogue_export():
    """Exporte le catalogue complet en JSON (téléchargement)."""
    patterns = _load_catalogue()
    response = jsonify({"patterns": patterns})
    response.headers["Content-Disposition"] = "attachment; filename=patterns.json"
    response.headers["Content-Type"] = "application/json"
    return response


@app.route("/api/catalogue/import", methods=["POST"])
def api_catalogue_import():
    """Importe des patterns dans le catalogue (merge, D-53).

    Body JSON : {"patterns": [...]} au format catalogue.
    Les patterns importés sont ajoutés. En cas de conflit de nom,
    le nommage auto D-50 renumérotation s'applique.
    """
    try:
        data = request.json
        if not data or "patterns" not in data:
            return jsonify({"error": "Champ requis : patterns"}), 400

        imported = data["patterns"]
        if not isinstance(imported, list):
            return jsonify({"error": "patterns doit être une liste"}), 400

        # Validation minimale du schéma
        required_fields = {"rows", "room_width_cm", "room_depth_cm", "standard"}
        for i, p in enumerate(imported):
            missing = required_fields - set(p.keys())
            if missing:
                return jsonify({
                    "error": f"Pattern #{i} : champs manquants : {missing}",
                }), 400

        catalogue = _load_catalogue()
        n_before = len(catalogue)

        # Merge : ajouter les patterns importés
        for p in imported:
            catalogue.append(p)

        # Compactage (renumérotation D-50) — résout les conflits de noms
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
    """Crée ou met à jour un pattern.

    Body JSON : un pattern au format PATTERN_DSL_SPEC.md.
    Si un pattern du même nom existe, il est remplacé.
    Si auto_name=true dans le body, le nom est généré automatiquement (D-50).
    Après chaque sauvegarde, les incréments sont compactés par groupe.
    """
    try:
        data = request.json
        if not data or "rows" not in data:
            return jsonify({"error": "Champ requis : rows"}), 400

        patterns = _load_catalogue()

        # Nommage automatique si demandé ou si pas de nom fourni
        auto_name = data.pop("auto_name", False)
        if auto_name or "name" not in data:
            data["name"] = generate_auto_name(data, patterns)

        idx = _find_pattern(patterns, data["name"])
        if idx >= 0:
            patterns[idx] = data
        else:
            patterns.append(data)

        # Compactage des incréments par groupe (D-50)
        compact_catalogue_names(patterns)

        _save_catalogue(patterns)
        return jsonify({"ok": True, "name": data["name"], "count": len(patterns)})
    except Exception as e:
        return jsonify({"error": str(e), "trace": traceback.format_exc()}), 500


@app.route("/api/patterns/<name>", methods=["GET"])
def api_pattern_get(name: str):
    """Retourne un pattern par nom."""
    patterns = _load_catalogue()
    idx = _find_pattern(patterns, name)
    if idx < 0:
        return jsonify({"error": f"Pattern non trouvé : {name}"}), 404
    return jsonify(patterns[idx])


@app.route("/api/patterns/<name>", methods=["DELETE"])
def api_pattern_delete(name: str):
    """Supprime un pattern par nom et compacte les incréments (D-50)."""
    patterns = _load_catalogue()
    idx = _find_pattern(patterns, name)
    if idx < 0:
        return jsonify({"error": f"Pattern non trouvé : {name}"}), 404
    patterns.pop(idx)
    compact_catalogue_names(patterns)
    _save_catalogue(patterns)
    return jsonify({"ok": True, "name": name, "count": len(patterns)})


@app.route("/api/patterns/<name>/duplicate", methods=["POST"])
def api_pattern_duplicate(name: str):
    """Duplique un pattern avec un nouveau nom.

    Body JSON optionnel : {"new_name": "P_COPY"}.
    Si absent, suffixe _copy ajouté.
    """
    try:
        patterns = _load_catalogue()
        idx = _find_pattern(patterns, name)
        if idx < 0:
            return jsonify({"error": f"Pattern non trouvé : {name}"}), 404

        data = request.json or {}
        new_name = data.get("new_name", name + "_copy")
        if _find_pattern(patterns, new_name) >= 0:
            return jsonify({"error": f"Nom déjà utilisé : {new_name}"}), 409

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
    """Parse du DSL texte en JSON.

    Body JSON : {"dsl": "P_B4: BLOCK_4_FACE, 180, BLOCK_2_FACE"}
    """
    try:
        data = request.json
        if not data or "dsl" not in data:
            return jsonify({"error": "Champ requis : dsl"}), 400
        result = parse_dsl(data["dsl"])
        return jsonify(result)
    except DSLError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e), "trace": traceback.format_exc()}), 500


@app.route("/api/dsl/export", methods=["POST"])
def api_dsl_export():
    """Exporte un pattern JSON en DSL texte.

    Body JSON : un pattern au format PATTERN_DSL_SPEC.md.
    """
    try:
        data = request.json
        if not data or "name" not in data:
            return jsonify({"error": "Champ requis : name"}), 400
        dsl_text = to_dsl(data)
        return jsonify({"dsl": dsl_text})
    except Exception as e:
        return jsonify({"error": str(e), "trace": traceback.format_exc()}), 500


@app.route("/api/room-dsl/parse", methods=["POST"])
def api_room_dsl_parse():
    """Parse du DSL pièce en JSON.

    Body JSON : {"dsl": "ROOM 300x480\\nWINDOW N 0 300\\nDOOR S 0 90 INT L"}
    Retourne les champs parsés pour mise à jour de l'éditeur.
    """
    try:
        data = request.json
        if not data or "dsl" not in data:
            return jsonify({"error": "Champ requis : dsl"}), 400
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
    """Calcule l'emprise EO (largeur) de la premiere rangee d'un pattern."""
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
    """Compte le nombre total de postes dans un pattern."""
    total = 0
    for row in pattern.get("rows", []):
        for block in row.get("blocks", []):
            bdef = BLOCK_DEFS.get(block.get("type", ""), {})
            total += bdef.get("n_desks", 0)
    return total


@app.route("/api/mock-candidates", methods=["GET"])
def api_mock_candidates():
    """Genere des solutions candidates fictives pour la piece de reference."""
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
    """Ancien endpoint de matching (abandonné D-35). Redirige vers /api/floor-plan/match."""
    return jsonify({"error": "Deprecated. Use POST /api/floor-plan/match instead."}), 410


@app.route("/api/floor-plan/match", methods=["POST"])
def api_floor_plan_match():
    """Lance le matching catalogue sur un jeu de pièces pour le floor plan viewer.

    Body JSON : {"rooms": [...]} au format load_rooms_json.
    Retourne les résultats de matching par pièce avec tous les candidats scorés.
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
            return jsonify({"error": "Champ requis : rooms"}), 400

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

            # Construire la réponse pour cette pièce
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
                # Calculer les positions des desks pour le rendu
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
    """Analyse de couverture du catalogue sur un jeu de pièces.

    Body JSON : {"rooms": [...]} au format load_rooms_json.
    Retourne le rapport de couverture avec backlog.
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
            return jsonify({"error": "Champ requis : rooms"}), 400

        # Construire les RoomSpec depuis le JSON
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
    print("Éditeur de patterns — http://localhost:5051")
    print(f"Catalogue : {CATALOGUE_PATH}")
    app.run(debug=True, port=5051)

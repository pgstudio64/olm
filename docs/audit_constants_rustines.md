# Audit constantes-rustines — 2026-05-13

> Objectif : identifier les valeurs numériques en dur ajoutées empiriquement pour faire passer un cas de test, et qui réduisent la robustesse face à la variabilité des plans réels. Cible : supprimer ou paramétrer.

---

## Synthèse

- **~30 entrées flaggées**, dont 9 critiques, 14 modérées, 7 borderline / cosmétiques.
- **Bonne pratique en place** : `olm/core/detection_config.py` centralise les tolérances en cm, converties au runtime via `to_px(scale_cm_per_px)`. Les constantes `*_PX` du module `test_comb.py` (L52-69, 597-598, 1207, 1466-1468) sont des *caches* remplis par `_apply_detection_config` — la rustine ici est **leur valeur par défaut en dur**, utilisée comme fallback si `_apply_detection_config` n'est pas appelée.
- **Top 3 fichiers concernés** :
  1. `olm/ingestion/test_comb.py` — défauts px module + seuils empiriques (gap_threshold, monotonie 70%, calibration)
  2. `olm/core/circulation_analysis.py` — grades A-F en valeurs littérales, seuils violations
  3. `olm/core/detection_config.py` — quelques valeurs cm non justifiées (`min_door_arc_width_cm: 45`, `max_absorb_cm: 30`, `snap_search_cm: 18`)
- **Top 3 motifs récurrents** :
  - Multiplicateurs empiriques sur `step_px` (`3 * step_px`, `min_count = 3`) au lieu de cm
  - Seuils ratio binaires (`0.7`, `0.5`, `1.30`) sans nom métier ni config
  - Défauts en pixels dans signatures de fonctions, sans dérivation cm

---

## Méthode et exclusions

**Inclus** : `olm/ingestion/`, `olm/core/`, `olm/server/`, `olm/static/`. Grep sur conditions numériques, constantes module, défauts de signatures, suivi du flux de scale.

**Exclus volontairement** :
- Constantes normatives métier déjà nommées (`CHAIR_CLEARANCE_CM`, `PASSAGE_CM`, `CHAIR_W_CM`, `default_door_width_cm=90`, etc.)
- `olm/core/spacing_config.py`, `olm/core/matching_config.py` (config métier)
- Couleurs / opacités / strokes SVG / font sizes (UI pure)
- Constantes de protocole (DPI=300, `_INCH_TO_CM=2.54`)
- `olm/tests/`

---

## Critique (change la détection)

### olm/ingestion/test_comb.py

| Ligne | Snippet | Cat. | Pourquoi rustine | Suggestion |
|---|---|---|---|---|
| L52-59 | `BINARIZE_THRESHOLD = 140` … `MAX_PILLAR_SIZE_PX = 60` | A/E | Défauts px en dur calibrés pour `scale = 0.5 cm/px`. Si `_apply_detection_config` n'est pas appelée (chemin oublié, refactor, test unitaire isolé), ces valeurs s'appliquent silencieusement et produisent des résultats faux à 1.0 cm/px. | Remplacer chaque `XX_PX = N` par un *property* qui lit `DEFAULT_DETECTION_CONFIG_CM.to_px(...)` lazily, ou faire échouer (`= None`) tant que `_apply_detection_config` n'a pas été appelée. |
| L362 | `if 0.5 < val < 2000.0:` | B | Bornes magiques sur valeur OCR (surface m²?). Coupe au-delà de 2000 m² → casse pour grandes pièces (open-spaces, halls). | Nommer `OCR_PLAUSIBLE_SURFACE_M2 = (0.5, 2000.0)` dans `detection_config` ou un module `ocr_filters.py` avec justification. |
| L513 | `if 5 < angle < 85:` | B | Filtre angles "non-orthogonaux". Le 5 est cohérent avec `ortho_angle_tolerance_deg` mais dupliqué localement. | Lire `cfg.ortho_angle_tolerance_deg` au lieu de répéter. |
| L945 | `gap_threshold = 3 * step_px` | A/B | Multiplicateur 3 empirique. Détermine si deux hits adjacents sont dans le même groupe (porte/poteau). À 0.5 cm/px ça fait 3×5=15 px = 7.5 cm ; à 2.5 cm/px ça fait 75 cm — comportement non-équivalent. | Convertir en cm : exposer `pillar_group_gap_cm` dans `DetectionConfigCm` (≈ 15-20 cm), passer en px via to_px. |
| L961 | `if len(group) < 3: continue` | B | Seuil 3 hits min pour qu'un groupe soit un pillar. Empirique. À comb_step plus fin ce 3 devient trop laxiste, à pas plus large trop strict. | Exposer `min_pillar_hits` dérivé de `min_pillar_size_cm / comb_step_cm`. |
| L981 | `if positive > 0.7 * n or negative > 0.7 * n:` | B | Seuil monotonie 70 % qui qualifie un groupe de hits comme "arc de porte" vs "poteau". Pas de nom, pas de doc, choix arbitraire. | Constante nommée `ARC_MONOTONICITY_RATIO = 0.7` documentée, idéalement dans `detection_config`. |
| L64-69 | `MIN_CALIB_SURFACE_M2 = 8.0` ; `MIN_CALIB_DIM_PX = 20` ; `CALIB_EDGE_MARGIN_PX = 5` | B/A | Trois seuils de calibration scale-from-surfaces : px-fixes (20, 5) et arbitraire (8 m²). Sur un plan dense de bureaux, beaucoup de pièces < 8 m² → calibration sur 2-3 pièces seulement. | Convertir 20 et 5 en cm dans `detection_config` ; documenter le 8 m² (« exclut WC et placards ») ou exposer dans config projet. |

### olm/ingestion/extract.py

| Ligne | Snippet | Cat. | Pourquoi rustine | Suggestion |
|---|---|---|---|---|
| L1259-1260 | `margin_px: int = 8, tolerance: int = 40,` | A | Défauts en px dans la signature de `_find_label_color_band` (à 0.5 cm/px : 4 cm et 20 cm). Pas de dérivation runtime. | Passer en cm dans la signature ou supprimer le défaut et forcer le caller à fournir. |
| L1815-1816 | `int(200 / scale_cm_per_px)` | B | `200 cm` en dur dans `perp_tolerance_px = max(door_width_px * 3, int(200 / scale_cm_per_px))`. Le 200 cm n'a pas de nom métier ; il ne tombe pas sur une dimension de porte connue. | Exposer `door_perp_tolerance_cm` dans `detection_config`, justifier ou supprimer la branche. |

---

## Modéré (affecte rendu / matching, ré-essayable)

### olm/core/detection_config.py

| Ligne | Constante | Cat. | Pourquoi flagger | Suggestion |
|---|---|---|---|---|
| L43 | `max_absorb_cm: 30.0` | B | Gap absorbé dans un mur. Pourquoi 30 et pas 20 ou 50 ? Pas de justification métier. | Documenter (« plus grand qu'une fente d'aération, plus petit qu'une porte ») ou tirer de `min_door_width_cm`. |
| L47 | `snap_search_cm: 18.0` | B | Recherche bord ± 18 cm. Le 18 est non rond. | Documenter origine ou arrondir à 20 cm. |
| L48 | `mode_tolerance_cm: 15.0` | B | Tolérance autour du mode de mur. | Documenter, ou dériver de `wall_depth_cm`. |
| L59 | `door_group_gap_cm: 75.0` | B | Gap max dans un arc de porte (« ~door width » selon commentaire ligne 1467 test_comb). Si c'est vraiment ~door width, devrait référencer `default_door_width_cm` (90), pas être 75. | Dériver de `default_door_width_cm` (ex. `0.8 * default_door_width_cm`). |
| L60 | `door_wall_margin_cm: 9.0` | B | Marge anti-mur perpendiculaire pour porte. Non rond, non justifié. | Documenter ou arrondir à 10. |
| L66 | `min_door_arc_width_cm: 45.0` | B | 45 cm — pourquoi ? La porte standard fait 90 cm, demi = 45. Plausible mais à expliciter. | Documenter "= 0.5 × default_door_width_cm". |

### olm/core/circulation_analysis.py

| Ligne | Snippet | Cat. | Pourquoi flagger | Suggestion |
|---|---|---|---|---|
| L856-862 | `if connectivity_pct >= 100.0 and worst_detour < 1.30: return "A"` (+ 90/1.60, 70/2.00, 50) | B | Quatre paliers de grade A-F en valeurs littérales empiriques. Aucun nom, aucune table de référence. | Extraire en `CIRCULATION_GRADES = [("A", 100, 1.30), ...]` dans `matching_config` ou un module dédié. |
| L887 | `MIN_ISOLATED_AREA_M2 = 0.50` | B | Locale à `_compute_violations`, non exposée. | Remonter au niveau module avec docstring (« plus grand qu'un pilier, plus petit qu'un poste de travail »). |
| L899 | `if worst_detour > 2.0` | B | Seuil violation détour. Probablement déjà dans le tableau A-F (palier "C") mais répété ici. | DRY : référencer le palier du grade. |
| L905 | `if area_m2 > 2.0` | B | Seuil "large isolated zone". 2 m² = ~un poste mais arbitraire. | Renommer constante locale `LARGE_ISOLATED_AREA_M2`, documenter. |

### olm/ingestion/extract.py

| Ligne | Snippet | Cat. | Pourquoi flagger | Suggestion |
|---|---|---|---|---|
| L33 | `ORTHO_ANGLE_TOLERANCE = 5` | B | Degrés. Cohérent avec `detection_config.ortho_angle_tolerance_deg` mais dupliqué. | Supprimer la constante locale, lire depuis `detection_config`. |
| L204 | `threshold: int = 180` (binarize) | A | Défaut local divergent du `BINARIZE_THRESHOLD = 140` de test_comb. Deux binarize_threshold différents dans le code. | Aligner sur `detection_config.binarize_threshold`. |
| L235 | `min_component_px: int = 5` | A | Défaut px pour filtre composante orthogonale. | Convertir en cm. |
| L403 | `max_depth: int = 30` | A | Profondeur de probe en px. À 0.5 cm/px = 15 cm, raisonnable mais px. | Dériver de `wall_depth_cm`. |
| L745 | `max_absorb_px: int = 120` | A | Défaut px sur `_merge_wall_segments`. Cohérent avec `max_absorb_cm: 30 @ 0.5 cm/px` = 60 px... mais ici 120. **Incohérence** avec `detection_config`. | Supprimer le défaut, forcer le caller à passer `cfg.max_absorb_px`. |
| L947 | `max_dist: float = 500` | A | Distance max pour la recherche d'un cluster de texte. 500 px ~= 250 cm à 0.5 cm/px. | Convertir en cm. |
| L1834 | `threshold: int = 140` (dans `extract_room_features`) | A | Triple source du binarize_threshold (ici, L204, et detection_config). | Lire depuis `detection_config`. |
| L1835 | `classify_step_cm: float = 15.0` | B | Pas de classification. 15 cm est plausible mais non justifié. | Documenter ou exposer en config. |

---

## Borderline / cosmétique

| Lieu | Snippet | Pourquoi non-flaggé en haut | Note |
|---|---|---|---|
| `olm/static/editor.js` L24-25 | `SEED_DISC_R_PX = 3; HIT_DISC_R_PX = 1.5;` | Rendu SVG, rayon en px écran. | OK. |
| `olm/static/editor.js` L19-21 | `ZOOM_IN_FACTOR = 0.8` etc. | UI zoom factor. | OK. |
| `olm/static/block_constants.js` L24-25 | `CHAIR_W_CM = 65; CHAIR_D_CM = 60;` | Dimensions physiques normatives. | OK. |
| `olm/ingestion/test_comb.py` L112 | `TESSERACT_UPSCALE = 2` | Multiplicateur OCR. Empirique mais sans impact géométrique. | OK, à documenter. |
| `olm/ingestion/extract.py` L32 | `RAY_FAN_STEP = 3` | Pas d'échantillonnage du fan. | À documenter, perf-related. |
| `olm/ingestion/extract.py` L112-126 | `cx-15, cy-25, ...` (bboxes texte locales) | Construction d'un fixture de bbox de texte | OK si test-only, à vérifier que ce n'est pas utilisé en prod. |
| `olm/static/editor.js` L3 | `SCALE = 0.5` | Échelle de rendu SVG | OK si non utilisé pour calcul géométrique. |

---

## Recommandations transversales

1. **Source unique pour les tolérances** — `detection_config.DetectionConfigCm` doit être la seule source. Toute constante `*_PX` du code applicatif devient un cache dérivé. Les défauts par dur en haut de `test_comb.py` (L52-59) devraient être supprimés au profit d'un accès lazy à `DEFAULT_DETECTION_CONFIG_CM.to_px(scale)` au moment du besoin. Tant que ces défauts existent, un chemin qui oublie `_apply_detection_config` reste silencieusement faux.

2. **Triple binarize_threshold à dédupliquer** — 140 dans test_comb L52, 180 dans extract.py L204, 140 dans extract.py L1834. Trois sources, deux valeurs différentes. À unifier sur `detection_config.binarize_threshold`.

3. **Multiplicateurs sur `step_px` → cm** — les patterns `3 * step_px`, `min_count = 3` sont sensibles au pas de comb. Les exprimer en cm via `detection_config` (`pillar_group_gap_cm`, dérivation de `min_pillar_hits`).

4. **Seuils monotonie 70 %, ratio 50 %, etc.** — extraire en constantes nommées avec docstring, idéalement dans `detection_config` (section `Heuristiques de discrimination`).

5. **Grades circulation A-F** — encoder le tableau (palier, connectivité_pct, worst_detour) une fois pour toutes, le réutiliser dans `_compute_violations` plutôt que dupliquer les seuils.

6. **Variable de calibration scale (`MIN_CALIB_SURFACE_M2 = 8.0`)** — exposer dans `project/config.json` car dépend du type de plan (bureaux denses vs entrepôts).

---

## Pour aller plus loin

- Audit de couverture des appels à `_apply_detection_config` : ajouter une assertion défensive au démarrage de chaque fonction publique de `test_comb.py` qui utilise les constantes module (`if MAX_PILLAR_SIZE_PX is None: raise RuntimeError("_apply_detection_config must be called first")`).
- Test de robustesse au scale : lancer la détection sur le même plan rasterisé à 0.3 / 0.5 / 1.0 / 2.0 cm/px et vérifier l'invariance des sorties. Tout drift > 5 % révèle un px-fixe oublié.

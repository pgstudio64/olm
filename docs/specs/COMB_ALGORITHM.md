# Algorithme du peigne — Détection de contour de pièce

Version : 3.0 — 2026-04-06

## Principe

Trouver le **plus grand rectangle** contenu dans une pièce à partir d'un seed (centre géométrique du cartouche) sur une image binarisée (noir = mur, blanc = vide).

## Pipeline complet

```
 1. OCR (pytesseract --psm 11, image upscalée x2) → détecter les "14"
 2. Parsing syntaxique des cartouches → seed, nom pièce, surface m²
 3. Binarisation seuil 110
 4. Effacement des cartouches → blanc
 5. Peigne adaptatif 2 passes → hits par direction
 6. Filtrage hits par seeds voisins
 7. Plus grand rectangle (hits = dernier pixel blanc, pas le mur)
 8. Snap through white → extension bords à travers lignes blanches
 9. Expansion arcs de porte → extension rectangle
10. Classification murale → fenêtres, portes, ouvertures
11. Auto-détection échelle → cm/px
```

Note : `remove_non_ortho` est **désactivé** — la détection de porte fonctionne sur la géométrie brute.

---

## Phase 1 — Peigne adaptatif 2 passes (D-74)

### Passe grossière (phase 1)

Rays à pas large (`COARSE_STEP_PX = 30`) depuis le seed dans les 4 directions. Condition d'arrêt adaptative (offset > max perpendiculaire).

Les distances collectées par direction servent à calculer :
- **Mode** par direction = distance au mur dominant (élimine les outliers = rays qui traversent les portes)
- **Max** par direction = distance au mur le plus lointain (inclut les portes)

Le mode définit la **bbox** (positions de départ des rays fins). Le max définit la **portée** maximale des rays fins (permet de traverser les portes pour la détection ultérieure).

### Passe fine (phase 2)

Rays à pas `COMB_STEP_PX = 5`, limités en :
- **Position** : aucun ray lancé au-delà de la bbox (mode par direction)
- **Portée** : chaque ray limité à `max_direction + RAY_MARGIN_PX` pixels

Résultat : `(all_hits, dir_hits)` — hits tagués par direction (north/south/east/west).

### Performance

12× plus rapide que le peigne 1 passe (0.03s vs 0.94s / 29 pièces). 89% → 36% de hits parasites hors pièce.

---

## Phase 2 — Filtrage par seeds voisins

Tous les seeds sont connus avant l'analyse de chaque pièce. Un hit est **rejeté** s'il dépasse la position d'un seed voisin dans la direction du ray :
- Hit est → rejeté si `hx > ox` pour un seed voisin `(ox, oy)` avec `ox > cx`
- Hit ouest → rejeté si `hx < ox` pour un seed voisin `(ox, oy)` avec `ox < cx`
- Idem pour N/S

Empêche les rectangles de s'étendre dans les pièces voisines.

---

## Phase 3 — Plus grand rectangle

### ray_single retourne d-1

Chaque ray retourne la distance au **dernier pixel blanc** avant le mur (pas le mur lui-même). Les hits sont donc sur des pixels blancs → le rectangle ne contient aucun pixel noir par construction.

### Algorithme

Pour chaque paire de bornes y `(y_top, y_bot)` tirée des coordonnées y des hits :
1. `y_top ≤ cy ≤ y_bot`
2. Hits dans la bande contraignent `x_left` (max des hits gauche) et `x_right` (min des hits droite)
3. Surface = `(x_right - x_left) × (y_bot - y_top)`
4. Garder le rectangle de plus grande surface

---

## Phase 4 — Snap through white

Après le plus grand rectangle, chaque bord est étendu vers l'extérieur ligne par ligne. Pour chaque face :
1. Vérifier la ligne 1px au-delà du bord (sur toute la largeur/hauteur)
2. Si entièrement blanche → avancer le bord de 1px
3. Répéter jusqu'à trouver une ligne avec un pixel noir, ou `max_advance = 8` atteint

Aligne les bords avec le mur/fenêtre le plus proche quand le rectangle initial est légèrement en retrait.

---

## Phase 5 — Expansion arcs de porte

Détecte les portes et étend le rectangle au-delà de l'arc jusqu'au vrai mur du couloir.

### Conditions

Pour chaque face :
1. **Far hits** : hits au-delà de la face, à distance ≈ largeur de porte (door_width_px ± tolerance)
2. **Contact** : mesuré **1px au-delà** du rectangle (sur le mur, pas sur le bord). Seuil relatif : contact < **20%** de la longueur de la face
3. **Minimum hits** : n ≥ 3 far hits alignés

### Résultat

Pour chaque porte détectée :
- `face`, `offset_px`, `width_px`, `hinge_side`
- `opens_inward` (True si l'arc est côté intérieur)
- `jamb_hinge_px`, `jamb_free_px` (positions absolues des montants)
- `wall_px` (position du mur du couloir)

---

## Phase 6 — Classification murale

Via `_classify_wall_direct` (extract.py). Pour chaque face du rectangle :
1. Localise le mur (search ±3px sur **binary_raw**, pas dilated)
2. Probe texture perpendiculaire (`WALL_DEPTH_PX = 8` ≈ 30cm)
3. Compte les transitions noir→blanc : ≥2 = fenêtre, 1 = mur, 0 = ouverture
4. Segmentation + merge (absorption uniquement wall-opening-wall)
5. Filtrage : ouvertures < 30cm largeur ou < 30cm profondeur → reclassées "wall", fenêtres < 30cm → reclassées "wall"

Faces extérieures = faces avec au moins une fenêtre (H-06 supprimée, pas de sondage au-delà des murs).

---

## Phase 7 — Auto-détection de l'échelle

1. Sélectionner les pièces **simples** : 1 porte, pas d'ouverture, surface OCR > 0
2. Pour chacune : `scale_i = √(surface_m² × 10000 / (width_px × height_px))`
3. **Médiane** des `scale_i` → échelle robuste
4. Appliquer à toutes les pièces

---

## OCR

### psm 11 (sparse text)

Mode obligatoire. Psm 3 (défaut) rate la majorité des "14". Psm 11 détecte quasi tous.

### Upscale x2

Image agrandie x2 (LANCZOS) avant OCR. Coordonnées ramenées /2 après.

### Parsing syntaxique des cartouches

Mots rattachés au "14" par syntaxe descendante (colonne ±30px, jusqu'à 80px en dessous).
- Numéro 3 chiffres → nom de pièce
- Nombre décimal (1.0 < val < 200.0) → surface m²
- Seed = centre géométrique de la bbox du cartouche

---

## Paramètres

| Paramètre | Valeur | Rôle |
|---|---|---|
| `BINARIZE_THRESHOLD` | 110 | Seuil binarisation (< = noir = mur) |
| `COMB_STEP_PX` | 5 | Pas du peigne fin (pixels) |
| `COARSE_STEP_PX` | 30 | Pas du peigne grossier (pixels) |
| `RAY_MARGIN_PX` | 10 | Marge portée au-delà du max phase 1 |
| `WALL_DEPTH_PX` | 8 | Profondeur probe texture (~30cm) |
| `MIN_OPENING_WIDTH_PX` | 8 | Largeur min ouverture (~30cm) |
| `MIN_OPENING_DEPTH_PX` | 8 | Profondeur min ouverture (~30cm) |
| `MIN_WINDOW_WIDTH_PX` | 8 | Largeur min fenêtre (~30cm) |
| `door_width_px` | 23 | Largeur porte standard (~90cm) |
| `door tolerance` | 0.35 | Tolérance distance porte (±35%) |
| `contact threshold` | 20% face_len | Contact max pour détection porte |
| `hits threshold` | n ≥ 3 | Min far hits pour détection porte |
| `snap max_advance` | 8 | Extension max snap through white |

---

## Scripts et outils

- `olm/ingestion/test_comb.py` — pipeline complet + main CLI
- `olm/ingestion/dev_viewer.py` — viewer Flask standalone (port 5070, debug)
- OLM Import tab — viewer intégré (port 5051, production)

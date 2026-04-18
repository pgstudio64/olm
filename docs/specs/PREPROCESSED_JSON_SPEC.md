# PREPROCESSED_JSON_SPEC — Format JSON Mode Préprocessé (v3)

> **Ce document est la référence unique** — toute modification du format passe par cette spec.
> Aucune trace externe au repo : CLAUDE et l'utilisateur s'alignent uniquement sur ce fichier.

Format JSON attendu en entrée du Mode Préprocessé (D-74, D-76, D-77) pour l'ingestion des plans d'étage dans OLS.

Ce JSON est produit soit :
- par un **outil de preprocessing externe** à partir d'un PDF de plan,
- soit par le **bouton DEV "Export v3 JSON"** de l'onglet Load qui sérialise l'état de l'OCR interne dans ce format (voir §5).

Il accompagne deux fichiers PNG :
- **PNG overlay** (nom = `<plan_id>.png`) : plan officiel avec cartouches et annotations — affichage utilisateur.
- **PNG enhanced** (nom = `<plan_id>_enhanced.png`) : plan avec cartouches supprimés, extérieur peint en bleu RGB(135,206,235), couloirs peints en vert RGB(193,247,179) — utilisé par le pipeline ray-cast.

### Suffixe réservé `_enhanced`

Le suffixe `_enhanced` est **réservé** au Mode Préprocessé. Aucun plan ne doit être nommé avec ce suffixe comme identifiant principal — il est toujours interprété comme la variante algorithmique d'un plan parent. Conséquences :

- La route `GET /api/plans` **groupe** `<plan_id>.png` et `<plan_id>_enhanced.png` sous un seul plan d'id `<plan_id>` avec un flag `has_enhanced`.
- Le PNG `_enhanced` **n'apparaît jamais** dans le dropdown Load en mode OCR (il n'a pas de cartouches lisibles).
- Le PNG `_enhanced` sert d'**overlay par défaut** en Mode Préprocessé une fois l'orientation canonique des pièces activée (D-83) — pour éviter d'afficher les cartouches à l'envers quand les pièces sont tournées pour avoir la porte au sud et les fenêtres au nord. Un toggle UI permettra de basculer entre l'overlay plein (avec numéros lisibles dans l'orientation native) et l'overlay enhanced (sans cartouches, mais propre sous rotation).

---

## 1. Structure globale (ROOT)

```json
{
  "file": "test_floorplan_ocr.png",
  "building_id": "B01",
  "floor_id": "R+1",
  "north_angle_deg": 0,
  "page_width_px": 1920,
  "page_height_px": 1080,
  "rooms": { "237": { ... }, "918": { ... } }
}
```

| Champ | Type | Description |
|---|---|---|
| `file` | string | Nom du fichier image source (PNG ou PDF rasterisé) |
| `building_id` | string | ID du bâtiment (peut être vide) |
| `floor_id` | string | ID de l'étage (peut être vide) |
| `north_angle_deg` | float, optionnel | Angle entre le haut de l'image et le nord géographique, en degrés sens horaire. `0` = le haut de l'image pointe vers le nord géographique. Purement métadonnée pour outils aval (ensoleillement, orientation, vent). **N'affecte pas la géométrie OLS** — toutes les coordonnées restent dans le cadre image. Défaut : `0`. |
| `page_width_px` | integer | Largeur de l'image raster en pixels |
| `page_height_px` | integer | Hauteur de l'image raster en pixels |
| `rooms` | object | **Dictionnaire indexé par ID de pièce**. Clé = `room_id` (string, ex: `"237"`, `"22K"`). Valeur = objet pièce (voir §2). |

**Pourquoi un objet indexé, pas un array** : les IDs de pièces sont uniques par définition, donc l'objet est l'abstraction naturelle. Bénéfices : lookup O(1) par ID, unicité garantie par le format, symétrie avec `olm_state.rooms_state` qui utilise déjà la même clé, et disparition du champ `id` dupliqué dans chaque valeur. L'ordre d'itération n'est pas garanti par le standard JSON mais est préservé par tous les moteurs modernes (JS, Python 3.7+, jq) ; OLS trie par clé au rendu pour un affichage stable.

**Pas d'échelle dans le fichier** : la conversion `cm_per_px` est **déduite côté OLS** à partir des surfaces m² des pièces (médiane de `√(surface_cm² / surface_px²)` sur les pièces mesurables). Cette approche permet de gérer des plans sans indication d'échelle imprimée.

**Supprimé en v3** : `plan_scale`, `dpi`, `scale_factor`, `rotation_angle`, `page_width_pts`, `page_height_pts`, `total_rooms`, `total_doors`, `total_text_blocks`, `all_text_blocks[]`. Aucun de ces champs n'était réellement consommé par le pipeline OLS.

---

## 2. Objet `rooms` (indexé par ID)

La clé est l'`id` de pièce (ex: `"237"`, `"22K"`). La valeur est un objet décrivant la surface, le seed et les ouvertures imbriquées. **Pas de champ `id` ni `code` dans la valeur** : l'`id` est déjà la clé, et le `code` pièce est un filtre interne côté OLS (Settings) — tous les rooms du fichier sont implicitement du type ciblé.

### 2.1 Champs d'une pièce (Input)

Format minimal attendu en entrée :

```json
"237": {
  "surface": "14.28 m2",
  "seed_x": 1234,
  "seed_y": 575,
  "doors": [
    { "label_x": 1200, "label_y": 680 }
  ]
}
```

| Champ | Statut | Type | Description |
|---|---|---|---|
| `surface` | **Required** | string | Surface au format `"N.NN m2"` (ex: `"14.28 m2"`). OLS parse à la lecture, pas de duplication en float. |
| `seed_x` | **Required** | integer | Centre du cartouche en pixels, axe X. Point de départ du ray-cast. |
| `seed_y` | **Required** | integer | Centre du cartouche en pixels, axe Y. |
| `doors` | Optional | array | Liste des portes (voir §2.3). Si absent ou tableau vide → aucune porte fournie ; OLS tentera une détection via ray-cast. |
| `bbox_px` | **Save-only** | array[4] int | Enrichi par OLS (voir §2.2) |
| `canonical_top_face` | **Save-only** | string | Enrichi par OLS (voir §2.2) |
| `openings` | **Save-only** | array | Enrichi par OLS (voir §2.2) |
| `windows` | **Save-only** | array | Enrichi par OLS (voir §2.2) |

> **Convention d'omission** : tout champ non requis qui n'est pas renseigné est **absent** du JSON, jamais `""`, `null`, `0` ou `[]` "par défaut". Un consommateur doit tester la présence (`if "champ" in obj`) avant l'accès. L'omission est sémantiquement "pas renseigné / à déduire".

### 2.2 Champs enrichis par OLS (Save)

Après le ray-cast et l'analyse de segments de mur, OLS ajoute les champs suivants dans chaque pièce :

```json
"237": {
  "surface": "14.28 m2",
  "seed_x": 1234,
  "seed_y": 575,
  "bbox_px": [1100, 500, 1368, 700],
  "canonical_top_face": "north",
  "doors": [
    {
      "label_x": 1200,
      "label_y": 680,
      "face": "south",
      "offset_px": 120,
      "width_px": 27,
      "hinge_side": "left",
      "opens_inward": true
    }
  ],
  "openings": [
    { "face": "north", "offset_px": 40, "width_px": 20 }
  ],
  "windows": [
    { "face": "east", "offset_px": 10, "width_px": 80 }
  ]
}
```

| Champ | Type | Description |
|---|---|---|
| `bbox_px` | array[4] int | Rectangle englobant `[x0, y0, x1, y1]` de la pièce, résultat du ray-cast. Évite le re-ray-cast au re-import. |
| `canonical_top_face` | string | Face image (`"north"` / `"south"` / `"east"` / `"west"`) qui doit devenir le HAUT de la vue canonique D-83 (fenêtres en haut, couloir en bas). Auto-dérivée de la porte principale par OLS : porte sur `south` → `canonical_top_face = "north"`. Sert au renderer de Review et Design pour appliquer la bonne rotation discrète (0°/90°/180°/270°). L'utilisateur peut l'override dans Review si ambigu. Absent au re-import → OLS re-dérive. |
| `openings[]` | array | Passages sans porte (embrasures, halls ouverts). |
| `windows[]` | array | Fenêtres détectées sur les murs extérieurs. |

### Mapping `canonical_top_face` → rotation de rendu

| Valeur | Rotation appliquée au groupe SVG |
|---|---|
| `"north"` | 0° (cadre image déjà canonique) |
| `"east"` | 90° CCW (mur image-east devient haut) |
| `"south"` | 180° |
| `"west"` | 90° CW (mur image-west devient haut) |

Les pièces non-orthogonales au cadre image (rares) sont traitées via leur bbox orthogonale et classifiées par leur face dominante. Pas d'angle libre — garder 4 valeurs discrètes évite les bugs géométriques (la rotation du bbox reste un simple swap w↔h).

**Principe** : un fichier Save est un **fichier Input enrichi** — re-importer un Save fonctionne naturellement. Les enrichissements `face/offset_px/width_px/hinge_side/opens_inward/bbox_px` sont détectés à l'absence et ignorés à la présence (skip le ray-cast pour les portes déjà analysées).

**Principe d'idempotence** : `hits[]` (points d'intersection du ray-cast) n'est **pas** persisté. Il est recalculable à la demande.

### 2.3 Schémas des ouvertures imbriquées

#### Door

| Champ | Type | Input/Save | Description |
|---|---|---|---|
| `label_x` | integer | Input | Axe X du centre du texte label de porte sur le plan — seed de la porte fourni par le preprocessing externe |
| `label_y` | integer | Input | Axe Y du centre du texte label de porte |
| `face` | string | Save | Mur portant la porte : `"north"` / `"south"` / `"east"` / `"west"` |
| `offset_px` | integer | Save | Position du jamb côté charnière le long du mur (pixels, depuis le coin NW ou NE selon la face) |
| `width_px` | integer | Save | Largeur de l'ouverture en pixels |
| `hinge_side` | string | Save | `"left"` ou `"right"` (orientation vue depuis l'extérieur de la pièce) |
| `opens_inward` | boolean | Save | `true` si la porte ouvre à l'intérieur de la pièce |

#### Opening

Passage sans porte. **Pas dans l'Input** — détecté par OLS via analyse des segments de mur.

| Champ | Type | Description |
|---|---|---|
| `face` | string | Mur portant l'ouverture |
| `offset_px` | integer | Position le long du mur |
| `width_px` | integer | Largeur en pixels |

#### Window

**Pas dans l'Input** — détecté par OLS via analyse des segments de mur (traits parallèles sur façade + bordure extérieure bleue en Mode Préprocessé).

| Champ | Type | Description |
|---|---|---|
| `face` | string | Mur portant la fenêtre |
| `offset_px` | integer | Position le long du mur |
| `width_px` | integer | Largeur en pixels |

---

## 3. Calcul du centre et de l'échelle dans OLS

### 3.1 Seed d'une pièce

Fourni directement par `seed_x` / `seed_y` — pas de calcul annexe.

### 3.2 Conversion pixels → cm

Non fournie dans le fichier. OLS déduit `cm_per_px` à partir des surfaces m² :

```python
samples = [math.sqrt((surface_m2 * 10000) / (width_px * height_px))
           for room in rooms
           if room_has_ray_cast_dimensions(room)]
cm_per_px = statistics.median(samples)
```

C'est la même logique que `extract_all_rooms` en Mode OCR. Un seul plan avec au moins une pièce mesurable suffit pour caler toutes les autres.

---

## 4. Extension `olm_state` (Save uniquement, R-11)

Ajout **non-breaking** au niveau ROOT pour persister les sélections et amendements au moment du Save. Absent d'un fichier Input.

```json
{
  // ... champs v3 standards ...
  "olm_state": {
    "version": 1,
    "plan_file": "test_floorplan_ocr.png",
    "last_saved": "2026-04-14T18:00:00Z",
    "rooms_state": {
      "237": {
        "selected_pattern_id": "B2_SITE_4",
        "layout_amendments": [ ... ],
        "geometry_amendments": { ... },
        "forbidden_zones": [ ... ],
        "comments_md": "Notes libres au format markdown."
      }
    }
  }
}
```

> **Note D-100** : le champ `merges` antérieurement prévu a été supprimé. Le besoin "étudier la suppression de murs entre pièces" est couvert par le workflow resize + Add/Delete + `comments_md` par pièce.

Voir R-11 dans `TODO.md` et D-78 dans `Decisions.md` pour le détail du round-trip complet.

---

## 5. Bouton DEV — Export v3 JSON

Un bouton développement est disponible dans l'onglet Load (couleur orange vif contour, label `DEV · Export v3 JSON`). Il permet de produire un JSON v3 à partir de l'état interne de l'OCR Mode sans dépendre d'un outil de preprocessing externe.

Fonctionnement :
1. Prendre `ingState.rooms` (résultat de l'OCR + éditions manuelles bbox / add / delete)
2. Pour chaque pièce, produire l'objet v3 (`surface` / `seed_x` / `seed_y` / `bbox_px` + listes enrichies `doors` / `openings` / `windows`)
3. Sérialiser en JSON, déclencher un téléchargement navigateur sous `<plan_stem>.json`

Ce JSON est pleinement utilisable en Mode Préprocessé (une fois le PNG enhanced créé manuellement — cf TODO R-05). Permet d'amorcer le test end-to-end du Mode Préprocessé sans dépendance externe.

---

## 6. Extraction dans OLS

Côté OLS (fonction `extract_rooms_from_preprocessed()` dans `olm/ingestion/extract.py`) :

1. **Validation** : clé `rooms` (objet non vide), fichiers PNG présents
2. **Metadata** : calcul de `cm_per_px` depuis les surfaces m² (§3.2)
3. **Par entrée `(room_id, room_obj)` dans `rooms`** :
   - `room_name = room_id` (la clé elle-même)
   - Parse de `room_obj.surface` (regex `\d+[.,]?\d*\s*m[²2]`) → valeur m² en mémoire
   - `seed = (room_obj.seed_x, room_obj.seed_y)` directement
   - Si `room_obj.bbox_px` présent → utilise tel quel (skip ray-cast)
   - Sinon → déclenche le ray-cast depuis le seed
   - Si `room_obj.doors[]` contient `face/offset_px/...` → utilise tel quel (skip door detection)
   - Sinon → détecte les portes depuis `label_x` / `label_y` + analyse des segments de mur
4. Retourne la structure consommée par le pipeline UI (toujours une liste, pas un dict, pour compatibilité interne)

---

## 7. Limitations v3

- **bbox approximative si Input minimal** : sans `bbox_px`, OLS doit ray-caster depuis le seed — la qualité dépend du PNG enhanced
- **`rotation_angle` non géré** : on suppose 0°. Si le PDF source est tourné, le preprocessing doit redresser l'image AVANT production du JSON
- **Pas de cartes avec unités non-métriques** : `surface` est en m², l'heuristique scale est en cm/px

---

## 8. Historique des versions

- **v1** (D-76, obsolète) : structure `cartouches` avec wrapper `center`
- **v2** (D-77, 2026-04-14) : structure `rooms` avec `code_line1` / `surface_line2` / `id_line3` imbriqués. Ajout de `doors` top-level et `all_text_blocks`. `scale` renommé en `scale_factor`
- **v3** (2026-04-14) : simplification radicale — suppression de `all_text_blocks`, `font_*`, `color_rgb`, `points_*`, `scale_factor`, `plan_scale`, `dpi`, `rotation_angle`, `page_*_pts`, `total_*`. Aplatissement du cartouche (champs plats au lieu des 3 objets imbriqués). Imbrication des `doors/openings/windows` dans chaque room (plus de `associated_room`). Échelle déduite des surfaces côté OLS. Schéma door scindé Input (label seul) vs Save (enrichi par OLS). **`rooms` est un objet indexé par `id` de pièce** (plus un array), suppression des champs `id` et `code` dans chaque valeur (clé unique + filtre code interne Settings).
- **v3.1** (2026-04-15) : affinage — split `seed_px: [x,y]` en `seed_x` / `seed_y` (champs scalaires), idem `label_px` → `label_x` / `label_y` dans les doors. Marquage explicite **Required / Optional / Save-only** sur chaque champ. Ajout de la **convention d'omission** : tout champ non renseigné est absent du JSON, jamais `""`/`null`/`0`/`[]`. `bbox_px` reste en array 4-tuple (décision : c'est une structure, pas 4 attributs indépendants).

---

## 9. Références

- D-74 : Architecture dual-mode ingestion
- D-76 : Format JSON cartouches (v1, obsolète)
- D-77 : Format JSON v2 (obsolète)
- D-78 : Round trip round `olm_state`
- `olm/ingestion/extract.py` : `extract_rooms_from_preprocessed()`
- `olm/server/app.py` : route `POST /api/import/preprocessed`

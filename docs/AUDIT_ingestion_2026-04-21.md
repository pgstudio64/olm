# Audit dette technique — `olm/static/ingestion.js`

Date : 2026-04-21 (post-D-135, avant commit). Fichier ~2000 lignes, historique
R-12 / R-14 / D-94→D-135. Audit passif : aucun code modifié.

---

## 1. Code mort & références obsolètes

| Ligne | Problème | Action |
|---|---|---|
| 80 | `var _rotR = window.canonicalIO.rotateRect;` assigné mais jamais utilisé | Supprimer |
| 145 & 178 | `var cio = window.canonicalIO;` redéfini | Hoister au module |
| 1479 | `// TODO: use window.GRID_STEP_CM if exposed by editor.js; fallback to 10 cm` | Extraire en constante nommée |
| 1561-1575 | Bloc D-128 potentiellement mort (bloqué par condition L-1550) | Vérifier couverture |

## 2. Duplications résiduelles post-refactor

**`extractRooms` (L-402) vs `extractRoomsPreprocessed` (L-1887)** — les deux
fonctions partagent ~50 lignes à l'identique :
- Affichage des boutons toolbar (hdrEl, btnSave, btnExport, btnClose, eraseWrap, ingTb)
- Séquence de finalisation `renderIngestion()` / `populateRoomsJson()` /
  `updateIngRoomList()` / `updatePlanDependentUI()`

**Action** : extraire `_setupPostExtractionUI(planId)`.

**`eraseWallSegment` (L-1214) vs `drawWallFeature` (L-1236)** — chacun contient
4 branches if/else presque identiques (north/south/west/east) pour composer
des segments SVG.

**Action** : helper `_getSvgLineAttrs(face, ...)` qui retourne les attributs en
une passe.

## 3. Magic numbers (règle projet "zéro valeur en dur")

| Ligne | Valeur | Contexte | Constante proposée |
|---|---|---|---|
| 637 | `400, 500` | Dims stub room par défaut | `STUB_DEFAULT_W_CM`, `STUB_DEFAULT_D_CM` |
| 643-644 | `50` | Seuil min dimensions room | `MIN_ROOM_DIM_CM` |
| 654 | `50` | Marge entre rooms auto-layout | `ROOM_BBOX_MARGIN_CM` |
| 969 | `8` | Tolérance détection murs partagés (px) | `WALL_MERGE_TOLERANCE_PX` |
| 1036 | `400` | Délai double-clic (ms) | `DOUBLE_CLICK_DELAY_MS` |
| 1099 | `50` | Padding zoom fit (px) | `ZOOM_FIT_PADDING_PX` |
| 1141, 1307-1308 | `1.15 / 0.87 / 0.7 / 1.4` | Facteurs zoom | `ZOOM_IN_FACTOR`, `ZOOM_OUT_FACTOR` |
| 1216 | `2` | Épaisseur trait d'effacement (px) | `ERASE_STROKE_WIDTH_PX` |
| 1238 | `3` | Offset feature mur (px) | `WALL_FEATURE_OFFSET_PX` |
| 1516 | `50` | Taille mini resize (px) | `MIN_RESIZE_PX` |
| 1657 | `90` (fallback) | Largeur default porte cm | Utiliser `APP_CONFIG.default_door_width_cm` sans fallback hard |
| 1964 | `0.10` | Padding auto-focus zones (ratio) | `BBOX_AUTOFOCUS_PADDING_RATIO` |

**Action** : bloc `const` en tête de fichier (après l'IIFE).

## 4. Logique entortillée & nommage ambigu

- **L-1653 `_sig(k, e)`** — crée une signature `kind|face|offset|width` pour
  identifier les openings. Nom obscur → `_createOpeningSignature(kind, op)`.
- **`am`** (amendments) utilisé partout → renommer en `amendments` dans le
  handler batch. Confusion fréquente avec `r` (room) et `fr` (fpData room).
- **`prevW / prevOp / prevDr / manualW / manualO`** → `prevWindows,
  prevOpenings, prevDoors, manualWindows, …`
- **L-1713-1716** : création d'un `resultsByName` dict juste pour un lookup,
  alors qu'un `.find()` direct suffirait.
- **L-1491-1494** : `room.bbox_px = […]; room.x0=…; room.y0=…; room.x1=…;
  room.y1=…; room.seed_px = […]; room.seed = […];` → deux sources de vérité
  pour la même donnée. Choisir `bbox_px` / `seed_px` comme source unique.

## 5. Commentaires décalés

- **L-1374-1375** : français/anglais mixte + "anciennes valeurs" flou.
- **L-1561** : "D-128" — vérifier si le correctif est encore pertinent.
- **L-248** : ancien code commenté suggère migration partielle vers
  `ingestion_scale.js` — vérifier qu'il ne reste pas d'implémentations
  alternatives de `parseDrawingScale` / `computeCmPerPx` / `getDrawingScale`.

## 6. Cycles d'état fragiles (risque de régression type D-135 rider)

**Le pattern « muter en parallèle ingState.rooms / fpRoomAmendments /
fpData.rooms »** est présent L-1759 → L-1841 (handler batch rescan). C'est
exactement le mécanisme où s'est glissé le bug D-135 rider (dims non propagées
aux amendments).

Risques résiduels :
- Si `fpData.rooms.find()` renvoie `undefined`, mutation silencieuse sautée
  (L-1809) sans log.
- Si `window.reanchorCanonicalZones` absent, `reanchored` reste `null` →
  accès `reanchored.exclusion_zones` potentiellement lancé sans garde aux
  3 sites (r / am / fr).
- `window.fpRoomAmendments = window.fpRoomAmendments || {}` crée une
  dépendance implicite au window global sans contrat documenté.

**Action stratégique** : `_syncRoomToAllStores(roomName, updates)` qui encapsule
les 3 mutations + try/catch + warn si divergence.

---

## Top 5 priorités recommandées

| # | Action | Impact | Effort |
|---|---|---|---|
| 1 | Bloc CONSTANTS en tête de fichier | haut | bas |
| 2 | `_setupPostExtractionUI(planId)` (fusion extractRooms / extractRoomsPreprocessed) | moyen | bas |
| 3 | `_syncRoomToAllStores(name, updates)` + try/catch sur les 3 stores | haut | moyen |
| 4 | Renommages ambigus (`am` → `amendments`, `_sig` → `_createOpeningSignature`, etc.) | moyen | moyen |
| 5 | Dead code cleanup (`_rotR`, `cio` dupliqué, branches if mortes L-1561+) | bas | bas |

Les actions 1, 2, 5 sont à peu près sans risque. L'action 3 est la plus
value-producing pour la robustesse future (elle aurait évité le bug D-135
rider). L'action 4 est mécanique mais touche à beaucoup de lignes.

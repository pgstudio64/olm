# TODO — OLM (Office Layout Matching)

Dernière mise à jour : 2026-04-21 (D-124 : re-ancrage zones post-re-analyze ; D-123 : perf Re-analyze All + fix bug openings→doors ; D-122 : R-14 canonique P1-P7)

> Renommage OLO → OLM (D-67). Le projet est un planificateur d'aménagement de bureaux, pas un optimiseur au sens mathématique. Le nom reflète l'ensemble des fonctionnalités : ingestion, matching, revue, export.

Orientation stratégique : **pattern = pièce + standard** (D-35/D-36). Chaque pattern est conçu pour une pièce de taille, géométrie et standard donnés.

Stratégie de peuplement du catalogue (D-55) : construction du bas vers le haut — chaque pattern est créé à la taille minimale de pièce pour un assemblage de blocs donné. Le front de Pareto du matching sélectionne automatiquement le meilleur. Voir `specs/CATALOGUE_STRATEGY.md`.

---

## Architecture cible

### Séparation open source / spécifique (D-68)

Deux parties distinctes dans le système de fichiers :

```
olm/                              ← OPEN SOURCE (licence MIT)
├── LICENSE                       ← MIT
├── README.md
├── pyproject.toml
├── requirements.txt
├── install.bat                   ← Windows : crée le venv + installe
├── launch.bat                    ← Windows : démarre le serveur
├── src/
│   └── olm/
│       ├── core/                 ← modèles, matching, scoring, circulation
│       ├── ingestion/            ← pipeline extraction raster (ray-cast)
│       ├── rendering/            ← SVG, PDF
│       ├── server/               ← Flask app, API, templates HTML/JS
│       └── config/               ← defaults, schema validation, paramètres
├── static/                       ← JS partagé (block_svg, block_constants…)
├── templates/                    ← HTML
└── tests/

project/                          ← SPÉCIFIQUE (non publié)
├── standards/                    ← définitions des standards métier
│   ├── std_1.json                ← ex-AFNOR_ADVICE
│   ├── std_2.json                ← ex-GROUP
│   └── std_3.json                ← ex-SITE
├── catalogue/
│   └── patterns.json
├── config.json                   ← paramètres spécifiques (room_code, labels…)
├── test_rooms.json
└── plans/                        ← plans raster de test

docs/                             ← INTERNE (non publié)
├── SRS.md, SDS.md, TODO.md
├── specs/
├── Decisions.md
└── CHANGELOG.md
```

### Interface : 2 onglets principaux + Settings

```
┌─────────────────────────────────────────────────────────────────── ⚙ ┐
│  Floor Plan  │  Office Layout  │                              Settings │
├──────────────┴─────────────────┘                                      │
│                                                                       │
│  Floor Plan sous-onglets :                                            │
│  ┌────────┬────────┬────────┬────────┐                                │
│  │ Import │ Review │ Match  │ Export │                                │
│  └────────┴────────┴────────┴────────┘                                │
│                                                                       │
│  Office Layout sous-onglets :                                         │
│  ┌───────────┬─────────┐                                              │
│  │ Catalogue │ Editor  │                                              │
│  └───────────┴─────────┘                                              │
└───────────────────────────────────────────────────────────────────────┘
```

### Paramètres centralisés (Settings ⚙)

Panneau accessible via la roue dentée, organisé en sections :

| Section | Paramètres |
|---|---|
| **General** | `room_code` (défaut "14"), `default_door_width_cm` (90), `desk_width_cm` (80), `desk_depth_cm` (180), `grid_cell_cm` (10) |
| **Standards** | Nombre, noms affichés (label_1, label_2, label_3), valeurs ES-*/PS-* par standard |
| **Matching** | Poids densité vs confort (`w_density`, `w_comfort`), seuils de couverture |
| **Ingestion** | Échelle, seuil binarisation, pas ray-cast, code pièce |
| **Export** | Formats activés (JSON, CSV, PDF), options PDF |

Migration de paramétrage : bouton "Upgrade to new standard" qui lit le paramétrage actuel, applique les nouveaux defaults, affiche le diff et demande validation.

---


---

## Chantiers actifs — Refonte OLM

### R-12 consolidation — réduction de dette (C1 → C4) ✅ D-120

Livrée en 2026-04-20 (D-120). Quatre étapes réalisées :

- [x] **C1** — `_canonicalizeRoom` / `_decanonicalizeRoom` +
  `_FACE_MAPS` / `_INV_FACE_MAPS` supprimés de `floor_plan.js`.
  `editor.js save()` (Room amend) bascule sur `canonicalIO.toStorage`.
  Bug latent corrigé : `origCf` lu depuis `original_corridor_face` en
  priorité (corridor_face est toujours "south" en canon R-12).
- [x] **C2** — `computeCanonicalReanalyzeResult` réécrit en wrapper
  mince autour de `fromStorage`. Matrice `FACE_MAPS` locale disparue.
- [x] **C3** — Fusion des sérialiseurs dans `ingestion_serialize.js`
  (renommé). Nouvelle API `window.olmSerialize`.
- [x] **C4** — `fpLoadAndMatch` bimode (string legacy / Array direct).
  Call sites internes (ingestion.js) passent `ingState.rooms`. Textarea
  devient informatif.

**Dette différée (non bloquante)** :
- Fusion `bbox_px` / `bbox_abs_px` et `seed_px` / `seed_abs_px` en un
  seul champ : refactor plus lourd des consommateurs overlay, à faire
  en bloc plus tard.
- ~~`offset_px` non rotés par `toStorage`~~ ✅ livré : recalculé à la
  sérialisation dans `serializeForStorage`.
- ~~Amendements Room perdus à l'export v3~~ ✅ livré : `editor.js save()`
  propage windows/openings/doors/zones vers `ingState.rooms`.
- Bug **bouton Save** : clic programmatique fonctionne, clic physique
  non intercepté (`document.elementFromPoint` retourne undefined à
  la position du bouton). Confirmé non-lié à C1-C4 après consolidation.
  À investiguer séparément — probablement un overlay transparent qui
  capture les events (pas de liseré `:hover`, pas de click).
- Bouton **Check orient.** ajouté dans Room toolbar (handler prêt,
  R-13 étape 2) : à tester visuellement maintenant que C1-C4 sont livrés.

### R-14 : Refactor canonique unifié (D-121) — PRIORITÉ HAUTE

Plan complet : `docs/specs/CANONICAL_REFACTOR_PLAN.md`.

Origine : 4 sessions de fixes sur le repère canonique (D-117, D-120, +
3 commits même journée) révèlent l'absence d'une frontière unique, de
structures uniformes, et d'un contrat front/back explicite. Les 6
symptômes observés (902/915/922/906/...) partagent la même cause
racine. Refactor structurel en 7 phases.

- [x] **P1 — Rotation `offset_px` intégrée à canonicalIO** ✅ 2026-04-20
  (D-122). Signature `fromStorage(room, scale)` / `toStorage(room,
  scale)` ; helper `_syncPx` interne recalcule
  `offset_px = round(offset_cm × pxPerCm)` après la rotation de
  `offset_cm`. Recalculs ad-hoc supprimés dans `_pxFromCm` et
  `_renderFeat` ; tous les call sites passent désormais `scale`.
  Tests round-trip 4/4 OK avec `offset_px` intégré aux samples.
- [x] **P2 — Fusion `bbox_abs_px` / `seed_abs_px`** ✅ 2026-04-20
  (D-122). Champs redondants supprimés ; `bbox_px` / `seed_px` seules
  coords image absolues (jamais rotés). Adapté dans canonical_io,
  editor.js save, init_rvtool re-analyze, ingestion batch re-analyze,
  fpLoadAndMatch.
- [x] **P3 — Renommage `original_corridor_face` → `corridor_face_abs`** ✅
  2026-04-20 (D-122). Rename global front + endpoint
  `/api/room/orientation-check`. Lectures ambiguës
  `room.original_corridor_face || room.corridor_face` supprimées (4
  sites : _canonicalAngle, _absToCanon2, editor.save, init_rvtool
  re-analyze). `state.corridor_face` retiré. JSON v3 disque inchangé.
- [x] **P4 — Séparation openings/doors uniforme dans state** ✅
  2026-04-20 (D-122). `state.room_doors` introduit comme collection
  séparée ; `has_door:true` banni du state. `buildRoomDSL`,
  `_stateToDsl`, `renderRoomElements`, CRUD, `_rvCommitFromState`,
  batch re-analyze et amendments adaptés. Combine+split aux
  frontières supprimés. Forme combinée conservée uniquement aux
  frontières API externes (matching, catalogue disque).
- [x] **P5 — Contrat front/back `/api/floor-plan/match`** ✅
  2026-04-20 (D-122). Frontend envoie du canonique (suppression
  `toStorage` préalable dans `serializeForMatching` + `editor.save`).
  Backend suppose canonique (docstring explicité) ; pas de
  `canonicalize_room()` ajoutée côté Python (redondant si frontend
  respecte le contrat). `fpLoadAndMatch` / `fpRematchRoom` splittent
  l'openings combiné reçu pour préserver l'invariant P4.
- [x] **P6 — Suppression des conversions ad-hoc** ✅ 2026-04-20
  (D-122). Helpers publics `canonicalIO.rotatePoint` /
  `canonicalIO.rotateRect` ajoutés (8 assertions auto-test).
  `pointAbsToCanon` (ingestion.js) et `_absToCanon2` (editor.js)
  supprimés.
  **Reste à faire** : `_canonicalAngle` local (editor.js) pas encore
  centralisé — la convention CSS du rendu SVG diverge des matrices
  de `fromStorage/toStorage`, migration demande un test visuel.
  FACE_MAPS restent dans canonical_io (sources uniques) mais ne sont
  plus dupliquées ailleurs.
- [x] **P7 — Tests round-trip complets + spec** ✅ 2026-04-20
  (D-122). Nouveau `docs/specs/CANONICAL_STATE.md` (structure, 4
  frontières I/O, API publique, 6 antipatterns). 12 auto-tests dans
  `canonical_io.js` (4 round-trips + 8 rotations), tous verts via
  Node. Tests Python `test_canonical.py` 19/19.

Points ouverts à arbitrer avant démarrage :
- Backend `/api/room/reanalyze` reste en absolu (pragmatique).
- JSON v3 sur disque reste en absolu (évite migration), seul le
  renommage `original_corridor_face` → `corridor_face_abs` impacte.
- `scale` toujours disponible aux call sites canonicalIO (confirmé).

### R-13 : Auto-test d'orientation canonique (D-119)

Objectif : valider automatiquement l'invariant « posture humaine » R-12
via les couleurs sémantiques du PNG -SD. Évite les régressions silencieuses
sur fromStorage / rendu / rotation / flux re-analyze.

- [ ] **Étape 1 — Test corridor sud canon (minimal)** :
  `olm/ingestion/orientation_check.py` avec fonction
  `check_corridor_south(enhanced_png, bbox_px, original_corridor_face)`
  → retourne `{ok, ratio_green, face_abs_checked}`.
- [ ] **Étape 2 — Test extérieur nord canon** : extension + `exterior_faces`.
- [ ] **Étape 3 — Test fenêtres côté bleu** : itération sur windows canon.
- [ ] **Endpoint** `/api/room/orientation-check` (1 pièce) +
  `/api/floor-plan/orientation-report` (batch).
- [ ] **UI** : bouton dans Room toolbar → badge inline. Version avancée :
  rapport agrégé avec pièces problématiques listées.
- [ ] **Documentation** : seuils et faux-positifs (cours intérieures,
  pièces enclavées) dans la spec.

### R-12 : Repère canonique unifié — posture humaine invariante (D-117)

Objectif : déplacer toutes les rotations abs ↔ canon à deux frontières I/O
uniques (`fromStorage` / `toStorage`), de sorte que tout le state
frontend vit en repère canonique (corridor_face constant = "south"). Voir
`docs/specs/CANONICAL_STATE_REFACTOR.md`.

Principe : « devant chaque porte, la même posture humaine » — toute
pièce est présentée avec son corridor d'accès en bas, quelle que soit
son orientation dans le bâtiment.

- [ ] **Étape A** : introduire `fromStorage` / `toStorage` en
  coexistence. `fpLoadAndMatch` applique `fromStorage` ; l'export
  applique `toStorage`. `_canonicalizeRoom` reste appelé (no-op car
  `corridor_face === "south"`). Round-trip JSON identique avant/après.
- [ ] **Étape B** : retirer les appels à `_canonicalizeRoom` /
  `_decanonicalizeRoom` des consommateurs (rendu Review, éditeur, save
  editor, matching). Tests visuels inchangés sur pièces 917, 922, 929.
- [ ] **Étape C** : rotation CSS de l'overlay plan selon
  `original_corridor_face`. Fix visuel attendu sur pièces 922, 929, 900.
- [ ] Après stabilisation : renommer `corridor_face` (state) →
  `_canonical_south`, mutualiser les matrices de rotation dans un module
  `olm/static/canonical_io.js`.

### R-04 : Floor Plan — 4 sous-onglets (Import / Review / Match / Export)

#### Import

Objectif : ingestion simplifiée — rectangles + murs + fenêtres + ouvertures. Pas de zones interdites (ajoutées en Review).

- [x] ~~Bug overlay post-simplification Import~~ — corrigé : overlays persistés dans `olm_overlays/` ([app.py:594-600](../olm/server/app.py#L594-L600)).
- [x] ~~Bug Save inactif après pan/scale/fullscreen~~ — non reproduit au 2026-04-19.

- [ ] **Grille 1m côté négatif invisible (Floor)** : les lignes `-1m`, `-2m`, etc. sont bien générées par `renderShared.gridSvg` avec `marginRatio=0.3` mais restent hors du viewBox SVG `{x:0, y:0, w:planW, h:planH}`. Pour les afficher il faudrait élargir le viewBox initial (ex : décaler vb.x/vb.y de -margin au load) ou changer les conventions. Pré-existant, signalé après P2.

Abandonné (inutile) : saisie manuelle d'échelle (cm/px ou points de calage) et saisie de code pièce à l'import — l'échelle vient de `plan_scale` du JSON v2 en Préprocessé ou des métadonnées OCR, le code pièce vient de Settings.

#### Review

Objectif : amender les pièces importées avant matching. Remplace l'ancien "Adjust room" (D-63).

- [x] CRUD ouvertures : ajout, suppression, déplacement, redimensionnement (D-103). Changement de type non implémenté (on supprime et on redessine).
- [x] **Zones interdites et transparentes (Room)** : zones interdites (rouge, `EXCLUSION`) et zones transparentes (vert, `TRANSPARENT`) définissables dans Room amend mode via le dropdown "Add room items" (D-103).
- [x] **Bug zones d'exclusion — déplacement vertical intempestif** ✅
  2026-04-21 (D-124) — les deux symptômes fixés par le re-ancrage des
  zones à la position absolue image après re-analyze
  (`reanchorCanonicalZones`, pipeline canon → abs → abs(new) → canon(new)).
  - Symptôme 2 (re-analyze) : root cause directe — zones restaient en
    canonique room-local alors que le bbox détecté dérivait dans l'image.
  - Symptôme 1 (placement décalé nord au clic) : cause commune, pas un
    bug de placement. L'état des zones avait déjà dérivé via un
    re-analyze antérieur ; le placement suivant héritait de coordonnées
    canoniques pointant sur un feature décalé. Validé par l'utilisateur
    après D-124.
- [x] **Relance analyse pièce (Room)** (D-104 puis D-107) : bouton "Re-analyze" en Room amend mode fait un ray-cast depuis seed via `test_comb.detect_room`, masque auto portes + zones transparentes, recalcule bbox + windows + openings. V/H-rays visualisables. Masques debug affichés.
- [x] **Préserver les modifications manuelles** (D-104) : chaque élément porte `origin: "auto"|"manual"` ; la ré-analyse remplace uniquement les auto et respecte `deleted_auto_signatures` pour éviter la réapparition d'éléments auto supprimés.
- [ ] **Persistance `origin` dans le JSON v3** : actuellement `origin` est runtime uniquement ; à ajouter au save/load du JSON v3 (olm_state) pour que la distinction auto/manuel survive entre sessions.
- [ ] **Re-analyze + resize pièce** : la ré-analyse utilise le bbox original. Si l'utilisateur a déjà redimensionné la pièce en amend mode, propager le nouveau bbox avant l'appel.
- [ ] **Zoom arrière bloqué trop tôt (Review / Room)** : la limite max de dézoom se déclenche avant que l'utilisateur puisse voir toute la pièce + marge confortable. Ajuster le clamp `maxW` (actuellement `planW × 1.1` dans ingestion.js). À revoir aussi pour Room amend mode.
- [x] ~~**Re-analyze instable — 2 passes quasi systématiques**~~ ✅ fixé
  2026-04-20 : bug dans le filtre `preservedDoors` (init_rvtool.js /
  ingestion.js). Utilisait `o.origin !== "auto"` → capturait les doors
  initiales (origin:undefined) et bloquait la redétection au 1er appel.
  Passé à `o.origin === "manual"`, cohérent avec `manualW` / `manualO`.
- [x] **Perf Re-analyze All** ✅ 2026-04-20 (D-123). Mesuré ×9.83
  speedup sur M4 : 831 ms/pièce → 15 ms/pièce + 831 ms one-shot
  précompute. Extrapolation 28 pièces sur cible CPU 10× plus lent :
  ~230 s → ~13 s. Mise en œuvre : `extract_room_features` accepte
  `binary_precomputed`, `/api/room/reanalyze_batch` calcule
  binarisation + `remove_non_ortho` une fois en amont.
- [ ] **Toggle « lock bbox » sur Re-analyze (D-118)** : checkbox dans la Room toolbar. Quand coché, le re-analyze ne modifie pas `state.room_width_cm/depth_cm`, `originalRoom.bbox_px`, ni l'overlay ; seuls les openings/windows/doors/hits sont adoptés. Utile pour raffiner les ouvertures après repositionnement manuel ou dépose d'un mur modélisée via zone transparente.
- [ ] **Re-analyze : fusionner Re-analyze + lock-bbox dans un dropdown** :
  remplacer le bouton simple « Re-analyze » par un dropdown (ou split
  button) avec deux options :
  - « Re-analyze — full » : comportement actuel (bbox, ouvertures,
    tout est redétecté).
  - « Re-analyze — keep walls » : équivalent du toggle lock bbox
    activé (bbox + dimensions figées, seuls openings/windows/doors/
    hits sont adoptés).
  Supprime le toggle indépendant, cohérent avec une seule action
  utilisateur paramétrée au clic.
- [x] **Bouton Close** : ferme le projet courant avec confirmation (warning unsaved changes implicite).
- [x] **Bouton Erase** (All / Layout only) avec confirmation.

#### Layout général

- [ ] **Taille minimale de la zone centrale (plan / pièce)** : définir un
  seuil min raisonnable pour la zone d'affichage du plan (Floor) ou de
  la pièce (Room / Office). En-dessous, soit scroll horizontal/vertical
  sur la zone, soit empêcher que les panneaux latéraux ne la rabotent
  jusqu'à l'invisibilité. Cas d'usage : fenêtre rétrécie ou écrans
  étroits.

#### Office (ex-Match/Design)

- [ ] **Bug "No matching patterns"** : le matching ne trouve aucun candidat — investiguer pourquoi (échelle, dimensions, catalogue vide ou incompatible ?)
- [ ] **Amend layout en place** : éditer la solution directement dans Office (sélection de blocs/postes, suppression Delete, sauvegarde), sans basculer vers l'éditeur de patterns

#### Export

- [ ] Export CSV : tableau tabulaire importable dans Excel (inclut traçabilité des amendements manuels)
- [ ] Export PDF : fond de plan raster + overlay aménagement

### R-05 : Module d'ingestion — Dual-mode (OCR + Préprocessé)

#### Mode OCR — Validation Tesseract sur test_floorplan3 (D-73)

- [ ] Rejouer l'extraction OCR sur `test_floorplan3.png` avec la nouvelle configuration Tesseract (D-73)
- [ ] Vérifier que les 28 pièces sont correctement détectées (numéro + surface exacts)
- [ ] **Taille minimale ouvertures/portes** : filtrer les ouvertures et portes détectées automatiquement en dessous de 60 cm (seuil paramétrable). Exception : ouverture < 60 cm acceptée si elle est directement connectée à une autre ouverture (entrée commune pour 2 pièces contiguës).

#### Mode OCR — Cartouche 3 lignes (D-81)

Passer de 5 lignes à 3 lignes (code / surface / id). Format identique au Mode Préprocessé.

- [ ] Adapter le regroupement cartouche (5→3 lignes) + revalider sur test_floorplan3.png + mettre à jour les tests

#### Mode Préprocessé (D-74)

**Convention de nommage des fichiers** (à respecter à l'import et en interne) :

Un jeu Mode Préprocessé est composé de **deux PNG** + le JSON :

| Fichier | Rôle |
|---|---|
| `<plan_id>.png` | **Fichier d'affichage** — conserve les cartouches, labels, cotes, bref le plan tel que l'humain le lit. C'est celui montré par défaut en **overlay** dans Review/Match. Le nom de base (`<plan_id>`) sert d'identifiant de référence du floor plan (clé stable pour R-11, round trip). |
| `<plan_id>-SD.png` | **Fichier algorithmique** (Sans Description) — pas de cartouches, extérieur peint en bleu ciel `preprocessed_exterior_rgb`, couloirs en vert `preprocessed_corridor_rgb`. C'est celui consommé par l'extraction ray-cast / détection de pièces. |
| `<plan_id>.json` | JSON v3 (rooms dict indexé, `drawing_scale_text`, `drawing_scale_measured`, `orientation`, `olm_state`). |

Règle : l'utilisateur fournit `<plan_id>.png` à l'import, OLM résout automatiquement `<plan_id>-SD.png` et `<plan_id>.json` dans le même dossier. Erreur explicite si l'un des deux est absent. Jamais de fichier -SD affiché à l'utilisateur sauf mode debug.

Tâches :
- [x] **Overlay par niveau** : Floor affiche `<plan_id>.png` (standard), Room et Office affichent `<plan_id>-SD.png` (sans description)

---


**(C) Automatisation future (optionnelle)** — générateur CLI qui enchaîne A + B automatiquement :

- [ ] Script `olm/tools/make_preprocessed_test.py` prenant un PNG Mode OCR et produisant le triplet (`<plan_id>.png`, `<plan_id>-SD.png`, `<plan_id>.json`)
- [ ] Étapes B automatisées : effacement cartouches via `clean_text_from_image()`, flood fill extérieur bleu ciel depuis les bords, détection couloirs (stratégie à définir — flood fill manuel via clics ou auto par exclusion des zones blanches non-pièces)
- [ ] Validation end-to-end : charger le triplet produit → vérifier cohérence avec le résultat du Mode OCR sur le même plan

#### Exploitation avancée du PNG -SD et du JSON v3 (D-77)

- [ ] **Ray-casting traversant les portes** : masque de transparence sur les zones de porte (via `doors[]` du JSON) pour que le ray-cast atteigne le vrai mur derrière le trait de porte
- [ ] **Détection fenêtres Mode Préprocessé** : refondre la logique — le bleu extérieur change le raisonnement (mur bordant du bleu = façade → candidat fenêtre). Distinguer mur plein / fenêtre / baie vitrée sur segments façade.
- [ ] **Détection couloirs via le vert** : segment de mur bordant du vert RGB(193,247,179) = porte sur couloir, sans classification texture

---

#### Topologies de bâtiment — Mode Préprocessé

Le preprocessing et les règles de détection (fenêtres, corridor, extérieur)
doivent tenir compte de la variété des topologies réelles. À passer en revue
et documenter avant d'industrialiser le Mode Préprocessé.

- [ ] **Bâtiment classique (barre, plot, L)** : fenêtres vers l'extérieur
  périphérique (bleu ciel), corridor central (vert). Cas de référence.
- [ ] **Cours intérieures** : zones extérieures enclavées dans le bâtiment,
  non atteintes par le flood fill depuis les bords. Doivent être peintes en
  bleu comme l'extérieur périphérique pour que la détection fenêtres
  fonctionne côté cour.
- [ ] **Patios / atriums vitrés** : zones intérieures traversées par la
  lumière mais entourées de surfaces vitrées. Choix de coloration à
  arbitrer (bleu extérieur, vert corridor, ou statut dédié ?).
- [ ] **Mezzanines / demi-niveaux** : pièces sur plusieurs niveaux sur le
  même plan. Impact sur l'unicité du `plan_id` et les bbox si elles se
  chevauchent.
- [ ] **Bâtiments mitoyens / parties communes** : murs mitoyens à
  distinguer des murs pleins internes ; absence de façade sur certaines
  faces. Règle de détection fenêtre à adapter.
- [ ] **Parking / techniques / circulations non occupables** : exclure du
  matching. Marquage à définir (room_code dédié, filtre par surface, ou
  coloration spéciale).
- [ ] **… cas à collecter au fil des plans réels** — ouvrir la liste à
  mesure que des topologies nouvelles apparaissent.

Pour chaque topologie, documenter dans
`docs/specs/RASTER_EXTRACTION_SPEC.md` ou une spec dédiée : règle de
coloration attendue dans le PNG -SD, comportement du ray-cast, règle de
détection fenêtre / corridor.

#### Robustesse ingestion

- [ ] **Arcs de porte** : le preprocessing génère des artefacts aux arcs de porte → post-traitement par consensus médian sur les hits du ray-cast (filtrer les encoches causées par les arcs)
- [ ] **Cours intérieures** : détecter les zones extérieures enclavées dans le bâtiment (non atteintes par le flood fill depuis les bords) et les marquer comme extérieur pour la détection fenêtres

### R-11 : Full round trip — Persistance des amendements dans le JSON

Objectif : garantir qu'à un re-import d'un plan déjà travaillé, l'utilisateur retrouve **toutes les sélections et amendements** précédents sans recalcul automatique. L'outil devient stateful : chaque session enrichit le JSON qui sert ensuite de source de vérité.

**Identification du plan** : par nom du fichier PNG (pas de hash, pas de contenu). Deux imports successifs de `test_floorplan3.png` sont considérés comme le même plan.

**Persistance** : l'état (sélections de patterns, amendements layout, amendements géométrie, zones interdites ajoutées en Review, commentaires markdown) est **sauvegardé dans le fichier JSON** accompagnant le PNG (Mode Préprocessé) ou dans un JSON sidecar (Mode OCR). L'export = la sauvegarde. (Fusions de pièces retirées — voir D-100.)

**Structure de l'état dans le JSON** (extension non-breaking du format v2) :

```json
{
  // ... champs v2 existants ...
  "olm_state": {
    "version": 1,
    "plan_file": "test_floorplan3.png",
    "last_saved": "2026-04-14T10:32:00Z",
    "rooms_state": {
      "237": {
        "selected_pattern_id": "B2_AFNOR_4",
        "layout_amendments": [...],
        "geometry_amendments": {...},
        "forbidden_zones": [...]
      },
      "22K": { ... }
    }
  }
}
```

**Clé de pièce** : `id_line3.text` (ex: `"237"`, `"22K"`). Stable entre imports tant que le fichier de preprocessing reste cohérent.

**Politique de diff à la réouverture** :
- Pièces **présentes dans les deux** (JSON actuel et `olm_state`) → réhydrater sélection + amendements
- Pièces **nouvelles** (présentes dans le JSON, absentes de `olm_state`) → démarrer vierge, marquer visuellement (badge "Nouveau")
- Pièces **orphelines** (présentes dans `olm_state`, absentes du JSON actuel) → warning listant les pièces disparues, proposer nettoyage ou conservation (au cas où le plan a été régénéré avec une erreur)
- L'utilisateur peut toujours **réinitialiser** une pièce (reset state) pour revenir au candidat automatique

Tâches :

- [ ] Fonction `build_olm_state()` : à l'export, sérialiser l'état courant (sélections + amendements) dans la structure `olm_state`
- [ ] Modifier la route d'export pour produire un JSON enrichi avec `olm_state` à jour
- [ ] UI : badge "Nouveau" sur les pièces sans état + warning listant les orphelines
- [ ] Test end-to-end : import → sélection + amendement → export → re-import → vérifier réhydratation

### Commentaires markdown par pièce (remplace R-09 — voir D-100)

Pour couvrir le cas "étudier l'aménagement en supprimant des murs entre pièces", on utilise maintenant le workflow **resize + Add/Delete room** (D-99 + Add room existant) plutôt qu'un système de merge. Un champ commentaires libre permet à l'utilisateur de tracer son raisonnement.

- [ ] **Champ `comments_md`** dans chaque entrée `rooms.{id}` du JSON v3 préprocessé + UI dans Room (textarea markdown associé à la pièce courante, sauvegardé avec l'amendement).
- [ ] **Section "Commentaires"** dans le rapport final PDF/CSV : rendu markdown par pièce, inclus si non vide.
- [ ] **SRS** : documenter le workflow officiel "suppression de murs = resize + delete + commentaire" (D-100).

### Room → Floor propagation pour orientations non-south (D-99)

- [ ] Étendre la propagation `bbox_px` de `save()` (Room amend) aux rooms avec `corridor_face ∈ {north, east, west}`. Nécessite un axis-remapping (les dimensions locales après canonicalisation ne correspondent pas directement aux axes du plan).

### Save v3 export préserve les champs inconnus

- [ ] `devExportV3Json` reconstruit le JSON à partir de `ingState` mais **écrase** les champs non gérés par le frontend (notamment `orientation`). Correctif : conserver une référence au JSON d'origine (au moment de l'import) et merger les champs manquants à la sauvegarde.



### R-07 : Packaging et déploiement

- [ ] Packaging Windows sans admin : `requirements.txt`, `install.bat`, `launch.bat`, validation Anaconda, test cycle complet

---

## Priorité moyenne — Revue UX et refactoring restants

### Revue UX (restant)

- [ ] **Pipeline Préprocessé refondu (D-105)** — gros chantier :
  - [ ] `extract_rooms_from_preprocessed` : ray-cast depuis seed sur `-SD` binarisé au lieu de lire `bbox_px` du JSON.
  - [ ] Zone transparente auto-générée à chaque seed de porte (côté pièce, dos au couloir) appliquée avant binarisation → les rays traversent les portes. Largeur = `default_door_width_cm` (paramètre général, défaut 90 cm), profondeur = même valeur (arc de 90°). Cette zone absorbe **aussi** le trait d'arc qui bloquerait sinon les rayons.
  - [ ] `_classify_wall_direct` appliqué sur le bbox recalculé.
  - [ ] Fenêtres — algo combiné :
    - [ ] Détection par transitions de texture (primaire) pour identifier les fenêtres individuelles dans une façade (cas standard : plusieurs fenêtres séparées).
    - [ ] Fallback couleur : si la face borde du bleu extérieur (`exterior_rgb`) et qu'aucune fenêtre n'a été détectée par texture, poser **une fenêtre unique couvrant toute la face**.
  - [ ] Portes depuis seeds JSON, snap à la face la plus proche, largeur = `default_door_width_cm`. Pas de détection par arc.
  - [ ] **Nouveau paramètre global `default_door_width_cm`** dans Settings (onglet General), valeur par défaut 90 cm, utilisé aussi bien pour CRUD manuel (D-103) que pour la zone transparente auto-porte et la largeur auto des portes depuis seeds.
  - [ ] **Renommer `origin: "auto"|"manual"` en `modified: bool`** (cohérence avec "amended" existant). Propager : `state.room_windows[i].modified`, `state.room_openings[i].modified`, merge logic D-104, JSON v3 (quand persistance ajoutée).
  - [ ] `extract_room_features` (re-analyze D-104) : aligner sur ce pipeline (seed + door seeds en entrée).
  - [ ] Endpoints `/api/room/reanalyze` et `/api/room/reanalyze_batch` : accepter `seed_px` et `door_seeds_px` ; bbox devient optionnel.
  - [ ] Produire `hits` (ray-cast) pour V/H-rays en Préprocessé (résolu par la refonte ci-dessus).
  - [ ] Mettre à jour `docs/specs/PREPROCESSED_JSON_SPEC.md` : clarifier quels champs sont entrée fiable vs dérivés.
- [ ] **Mode OCR : utiliser `-SD.png` s'il existe pour ray-cast** : `extract_rooms_from_preprocessed` ne génère pas de hits actuellement (pas de ray-cast actif). Faire un ray-cast léger sur le PNG `-SD` pour peupler `room.hits` et rendre les cases V-rays / H-rays de Floor fonctionnelles en mode Préprocessé.
- [ ] **Mode OCR : utiliser `-SD.png` s'il existe pour ray-cast** : en Mode OCR (sans JSON), si un fichier `<plan_id>-SD.png` est présent dans `project/plans/`, l'utiliser comme source pour l'algo de détection / ray-cast (H-rays et V-rays) au lieu de supprimer les descriptions manuellement. Le `-SD` (avec cartouches effacés, extérieur bleu, couloirs verts) donne des résultats plus propres.
- [ ] **Nettoyer handlers de couplage de pièces (Floorplan)** : D-100 a supprimé le concept de merge mais il reste des handlers dans le code Floor (couplage/association de pièces). Les retirer.
- [ ] **Fine-tuning taille éléments graphiques** : ajuster les épaisseurs de traits (murs, fenêtres, portes, arcs), diamètre des ronds de grille, taille des poignées/badges pour un rendu visuellement agréable à tous les niveaux de zoom. Actuellement : non-scaling-stroke appliqué partout + cap sur les dots grille à 2 px.
- [ ] **Total area en m² non rafraîchi au changement d'échelle** : quand l'utilisateur modifie l'échelle (drawing_scale), le total area affiché reste sur l'ancienne valeur. À relier au recompute scale.
- [ ] **Édition contours au niveau Room** : ajouter la capacité de modifier les contours de la pièce dans Room (même outil que l'édition bbox dans Floor)

- [ ] **Bug position pièce 305 dans Office** : la pièce 305 est positionnée en (0,0) dans Office alors qu'elle est correctement placée dans Floor et Room. Semble arriver lorsqu'il y a un match automatique.
- [ ] **Bug orientation pièce 922** : la pièce 922 (`canonical_top_face: "west"`) est positionnée comme si elle était à l'est alors qu'elle est au nord. Vérifier la logique de rotation canonique pour les pièces en orientation non standard.
- [ ] Bug : Design Layout ne rote pas correctement les patterns selon l'orientation de la porte. Si la porte est en haut, les patterns devraient être rotatés mais ils conservent leur orientation par défaut (bureau sur la porte). À auditer dans le pipeline matching + rendu (fpCanvas).
- [ ] **Rendu homogène Import/Review/Design** : utiliser le même rendu détaillé (arcs de porte, fenêtres épaisses, ouvertures) dans Import que dans Review/Design. Niveau de détail adaptatif selon le zoom : détails complets quand on zoome sur une pièce, traits simplifiés quand on voit tout le plan. Adapter l'épaisseur des traits au niveau de zoom pour rester lisible à toutes les échelles.
- [ ] **Ajout manuel d'un seed** dans Floor/Room : besoin pour les pièces ajoutées à la main (nouveau contour sans cartouche OCR détecté) — permettre de placer le seed avec un clic pour que la re-analyze puisse partir.
- [ ] **Afficher le seed (disque vert) dès l'activation V-Rays ou H-Rays** : aujourd'hui le seed est affiché en même temps que les rays. Le montrer dès qu'une des deux cases est cochée, même sans hits.

### Refactoring architecture frontend — poursuite éventuelle

- [x] **State unique** (D-94 P1) : store `olmStore` unifié.
- [x] **Découpage JS** (D-94 P2/P3/P4) : `render_shared.js`, `init_rvtool.js`, `init_resize.js`, `ingestion_scale.js`, `ingestion_export.js`.
- [ ] Éventuellement : extraction supplémentaire de `renderIngestion` (330 l.) depuis `ingestion.js` — demande exposition étendue de helpers locaux, ROI plus faible qu'aux phases précédentes.
- [ ] Fonctions de rendu pures (sans dépendance au state global) — chantier long, à évaluer selon les besoins futurs.

---

## Étapes existantes non impactées

### Peuplement du catalogue (priorité haute)

- [ ] **Minimize room size** : calcul de la pièce minimale par pattern par standard, Ctrl+M unitaire + batch "minimize all", feedback visuel
- [ ] **Recalibration patterns SITE** (D-56) : recalculer les tailles minimales avec les nouvelles distances, vérifier/recréer les patterns SITE

---

## Après le prototype — Industrialisation

- [ ] **Nettoyage** : supprimer les anciens modèles et code abandonné (solver/model.py, debt_model.py, matcher.py, static_matcher.py)
- [ ] **Documentation** : réécriture SRS/SDS alignée OLM, SPEC_matcher.md

---

## Phases conditionnelles (R&D dans solver_lab/)

- [ ] **Phase 2** : CP-SAT résiduel sur zones libres après matching statique
- [ ] **Phase 3** : géométrie stochastique (MCMC warm-started depuis catalogue)

---


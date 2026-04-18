# Decisions.md — OLM

Journal des décisions de conception du projet OLM (Office Layout Matching).
Chaque entrée indique la date, la décision, la justification et l'impact.

> **Note** : Décisions historiques (D-01 à D-60, architectures antérieures CP-SAT et refactoring) archivées dans `Decisions_archive.md`.

---

## D-98 · Split ingestion.js — ingestion_scale + ingestion_export (2026-04-18)

**Décision** : Phase 4 du refactoring front-end D-94. Extraction de deux modules auto-contenus depuis `ingestion.js` (1605 l.) :

- `olm/static/ingestion_scale.js` (~90 l.) : helpers purs de parsing et conversion d'échelle (`parseDrawingScale`, `computeCmPerPx`, `getDrawingScale`, `getRenderDpi`, `suggestDrawingScale`). Exposés via `window.olmScale.*`.
- `olm/static/ingestion_export.js` (~125 l.) : `devExportV3Json` — sérialisation `ingState.rooms` vers le format JSON v3 + téléchargement. Exposé via `window.devExportV3Json` (utilisé par le bouton Save dans `init.js`). D-95 écrit `drawing_scale_text` et `drawing_scale_measured` depuis `ingState.scale`.

`ingestion.js` passe de 1605 → 1432 l. Le reste (renderIngestion, extractRooms/Preprocessed, room CRUD, toggles, init wiring) demeure couplé à `COLORS` local, `ingState` local et aux helpers mutuellement dépendants — extraire au-delà nécessiterait une exposition étendue sur `window`, pire que le couplage actuel.

**Justification** : les deux extraits sont des "feuilles" du graphe de dépendance (scale : pures fonctions ; export : une fonction top-level). ROI élevé (thématisation claire, ingestion.js plus lisible) sans risque de régression.

**Impact** :
- Nouveau `olm/static/ingestion_scale.js`.
- Nouveau `olm/static/ingestion_export.js`.
- `olm/static/ingestion.js` −173 l.
- `olm/templates/pattern_editor.html` : chargement des 2 nouveaux scripts avant `ingestion.js`.

---

## D-97 · Split init.js — init_rvtool + init_resize (2026-04-18)

**Décision** : Phase 3 du refactoring front-end D-94. Extraction de deux modules auto-contenus depuis `init.js` (1082 l.) :

- `olm/static/init_rvtool.js` (~300 l.) : outil zones d'exclusion pour le Room amend mode (placing/drawing/selected/dragging/resizing), incluant les handlers clavier (flèches = déplacer, Delete/Backspace = supprimer, Escape = désélectionner/annuler, Enter = commit). Capture-phase sur le `keydown` pour préempter la navigation Room/Office de `floor_plan.js`.
- `olm/static/init_resize.js` (~100 l.) : les deux drag-handles de redimensionnement des panneaux gauches (Floor + Room), déjà encapsulés en IIFE avant extraction.

Fixes UX associés (rvtool) :
- Couleur sélection zone : rouge (`#c05858`) au lieu de vert.
- Poignées de redimensionnement aux 4 coins (drag = resize, `MIN_CM = GRID_STEP_CM`). Taille 2×2 SVG units (−75 % vs proto initial).
- Clampage complet à la pièce (drag + resize + flèches) sur les 4 faces, plus seulement W/N.
- Enter (Retour) désélectionne (commit), complément à Escape (annulation).
- Bouton renommé "Add exclusion zone" (au lieu de "+ Zone").

`init.js` passe de 1082 → 724 l. Le reste (orchestration `init()`, onglets, amend mode global, catalogue, erase) reste dans `init.js` — couplage plus fort au flow d'init, extraction risquée sans gain net.

**Justification** : les deux modules extraits étaient déjà thématiquement autonomes (rvtool seule consomme `state.roomAmendMode`, `SCALE`, `GRID_STEP_CM`, `render()` via globals ; resize ne dépend que du DOM). Les laisser dans `init.js` rendait le fichier difficile à naviguer (1000+ lignes) sans bénéfice architectural.

**Impact** :
- Nouveau `olm/static/init_rvtool.js`.
- Nouveau `olm/static/init_resize.js`.
- `olm/static/init.js` −358 l.
- `olm/static/editor.js` : couleur sélection + 4 poignées SVG rendues dans `renderRoomElements`.
- `olm/templates/pattern_editor.html` : chargement des 2 nouveaux scripts après `init.js`.

---

## D-96 · render_shared.js — primitives SVG partagées (2026-04-18)

**Décision** : Création de `olm/static/render_shared.js` (phase 2 du refactoring front-end D-94). Expose `renderShared.doorSvg()` et `renderShared.gridSvg()` pour centraliser la logique de rendu dupliquée entre `editor.js` et `ingestion.js`.

- `doorSvg(face, hingeCoord, freeCoord, wallCoord, swingSide, opensInward, leafOffsetMag)` → retourne `[arcPath, leafLine]`. West wall inverse la relation swing↔hinge-coord (convention héritée).
- `gridSvg({ vb, cmPerPx, dotColor?, lineColor?, marginRatio?, minStartAt0? })` → retourne `{ dots, lines }` séparés pour que l'appelant applique des z-indices différents (editor : dots z=-0.5, lines z=-0.4).
- Constantes exposées : `COLOR_DOOR_ARC`, `COLOR_DOOR_LEAF`, `COLOR_WINDOW`, `COLOR_OPENING`.

**Justification** : 172 lignes de rendu porte/grille étaient dupliquées entre `editor.js` et `ingestion.js`. Toute correction (couleur, style, géométrie) devait être portée manuellement dans deux endroits. Single source of truth = moins de risque de désynchronisation.

**Impact** :
- `olm/static/render_shared.js` : nouveau fichier (~175 lignes).
- `olm/static/editor.js` : -70 lignes (portes + grille).
- `olm/static/ingestion.js` : -50 lignes (portes + grille).
- `pattern_editor.html` : `render_shared.js` chargé après `block_svg.js`, avant les modules qui l'utilisent.

---

## D-95 · Échelle de dessin — l'input UI prime et écrase les deux champs JSON (2026-04-18)

**Décision** : Option D. Le champ `drawing_scale` de l'UI permet à l'utilisateur d'outrepasser les valeurs présentes dans le JSON v3 préprocessé. Toute édition du champ est immédiatement propagée à `ingState.rooms` ET à `fpData.rooms` (Room/Office restent synchronisés). À la sauvegarde (Save / Export), les deux champs `drawing_scale_text` ET `drawing_scale_measured` du JSON sont écrits depuis la valeur courante de `ingState.scale` — les anciennes valeurs mesurées sont écrasées.

**Justification** : D-91 avait fait primer `drawing_scale_measured` sur le texte saisi, au motif que la règle mesurée sur le plan est « plus fiable ». En pratique l'utilisateur a besoin de pouvoir corriger une mesure erronée ou imposer une échelle de référence, et de persister cette correction. Faire primer l'UI est cohérent avec le reste de l'outil (toute modification manuelle l'emporte sur les valeurs auto). L'écrasement des deux champs à la sauvegarde supprime le risque de divergence au re-import.

**Impact** :
- `ingestion.js` : `_applyDrawingScale` propage désormais les nouvelles dims à `fpData.rooms` (fix bug — Room/Office affichaient des dimensions stales après changement d'échelle).
- `ingestion.js` : `devExportV3Json` ajoute `drawing_scale_text` et `drawing_scale_measured` au JSON exporté.
- D-91 — priorité `measured > text` au backend (`app.py:694-720`) reste valide pour le tout premier import d'un fichier préprocessé tiers, mais ne pose plus de conflit durable : dès le premier Save, les deux champs convergent.

---

## D-94 · Refactoring front-end — store unifié + découpage modules (2026-04-18)

**Décision** : Lancement d'un refactoring front-end en 6 phases pour consolider les fondations avant les prochaines features (R-11 round trip notamment).

- **P0** (ce commit) : suppression de `matching_viewer.html` (1138 l., dead code — route `/matching` jamais référencée depuis HTML/JS) + route Flask associée.
- **P1** : création de `olm/static/store.js` — store unifié `olmStore` remplaçant les 5 globals `ingState`, `fpData`, `fpOverlay`, `fpAmendments`, `fpRoomAmendments` (232 occurrences, 4 fichiers). Pattern `set(path, value)` + `subscribe(path, cb)`. Migration progressive via shims de compat sur `window.*`.
- **P2** : extraction `render_shared.js` — primitives SVG communes (porte, fenêtre, ouverture, grille) dupliquées entre `editor.js`, `ingestion.js`, `floor_plan.js`.
- **P3** : split `init.js` (1088 l.) → `init_tabs.js`, `init_rvtool.js`, `init_amend.js` + bootstrap réduit.
- **P4** : split `ingestion.js` (1605 l.) → `ingestion_render.js`, `ingestion_import.js`, `ingestion_scale.js`.
- **P5-P6** (optionnelles) : split `floor_plan.js` et `editor.js` selon besoin.

**Justification** : 5 sources de vérité sur l'état du plan, fichiers de 1000-1850 lignes, rendu et state entremêlés. R-11 (persistance des amendements dans le JSON) exige un état sérialisable cohérent — le bon moment pour consolider. Phasage itératif (pas de big-bang), chaque phase est commitable et testable isolément.

**Impact** : suppression `olm/templates/matching_viewer.html`, route `/matching` retirée de `olm/server/app.py`, arborescence `CLAUDE.md` mise à jour.

---

## D-93 · Settings restructuration + poids scoring Office (2026-04-17)

**Décision** : Refonte du panneau Settings et ajout des poids de scoring.

- Standards dans General : radio default + label éditable par ligne, sans clé technique affichée.
- Settings Floor : Plans directory élargi, DPI centré, "Standard colors" (ex-Semantic colors) avec descriptions.
- Settings Office : 5 poids de matching — Density, Comfort (existants), Back to door, Natural light, Face to wall (nouveaux, défaut 0 = inactifs).
- Export intégré dans General.
- Toolbar Floor masquée tant qu'aucun plan n'est chargé.

**Justification** : Settings organisé par onglet applicatif. Poids de scoring préparés dans l'UI avant implémentation des détections correspondantes.

**Impact** : `pattern_editor.html`, `config.js`, `init.js`, `ingestion.js`.

---

## D-91 · Convention fichiers -SD + drawing_scale_measured (2026-04-17)

**Décision** : Refonte de la convention de nommage des fichiers préprocessés et de la gestion de l'échelle.

- PNG standard `<plan_id>.png` (avec cartouches) + PNG `<plan_id>-SD.png` (Sans Description, pour l'algo). Remplace l'ancien suffixe `_enhanced`.
- JSON v3 : `drawing_scale` renommé `drawing_scale_text`, ajout `drawing_scale_measured` (cm/px depuis la règle de 5m) et `orientation` (degrés par rapport au nord).
- `drawing_scale_measured` prioritaire sur le calcul text+DPI, avec log warning si divergence > 20%.

**Justification** : Le preprocessing externe fournit une échelle mesurée sur la règle du plan, plus fiable que l'échelle textuelle. Le suffixe `-SD` est plus explicite que `_enhanced`.

**Impact** : `config.json`, `app.py`, `ingestion.js`, `extract.py`, JSON de test mis à jour. Convention `-SD` propagée dans TODO et code.

---

## D-92 · Renommage sous-onglets + restructuration Settings (2026-04-17)

**Décision** : Renommage des sous-onglets et alignement des Settings.

- Sous-onglets : Floor, **Room** (ex-Rooms), **Office** (ex-Design), Catalogue.
- Settings : General (+ Export intégré) | Floor, Office, Catalogue. Séparateur visuel entre General et les onglets applicatifs.
- Standard par défaut pré-sélectionné dans Office à chaque changement de pièce.
- Bouton Export ajouté à droite de Save dans la barre d'actions.

**Justification** : Cohérence nommage entre onglets et Settings. "Office" reflète mieux le rôle (aménagement de bureau). Export est un paramètre global, pas un onglet dédié.

**Impact** : `pattern_editor.html`, `init.js`, `floor_plan.js`.

---

## D-90 · Option B layout — navigation gauche, détail droite (2026-04-16)

**Décision** : Réorganisation des colonnes selon le pattern "navigation à gauche, détail à droite".

- **Floor** : colonne unique à gauche (plan selector, scale, floor properties, room list). Pas de colonne droite — un seul objet (le plan), pas de séparation utile.
- **Rooms** : room list à gauche, room props + DSL + adjust à droite.
- **Design** : room list + candidates à gauche, room info + layout info + workstations à droite. Room list ajoutée au-dessus des candidates pour navigation cohérente avec Rooms.
- **Catalogue Editor** : inchangé.

**Justification** : Cohérence "je sélectionne à gauche, je vois le détail à droite" (pattern IDE). Floor est une exception car il n'y a qu'un objet à consulter.

**Impact** :
- `olm/templates/pattern_editor.html` : colonne droite ajoutée dans Rooms, room list ajoutée dans Design
- `olm/static/ingestion.js` : room list Design câblée (clic = changement de pièce sans changer d'onglet)
- `olm/static/floor_plan.js` : fpRenderCurrent appelle updateIngRoomList

---

## D-89 · Navigation UX — onglets, sous-onglets, hover, descriptions (2026-04-16)

**Décision** : Refonte UX de la navigation par onglets.

- Renommage Import → Floor, Review → Rooms (plus court, plus clair).
- Sous-onglets Catalogue : sub-tab-bar séparée (l'approche inline D-89 initiale a été abandonnée — trop de conflits visuels). Description italique à droite. Actif en gras + jaune.
- Zone hover des onglets étendue via pseudo-element `::before` (-8px top, -5px latéral) — pas de changement visuel, meilleure réactivité.
- Onglets Review/Design masqués (`display:none`) tant qu'aucun plan n'est chargé. Sections Scale/Floor Properties/Room List conditionnelles.
- Contraste onglets renforcé : actif #e8c46a, inactif #6a655c.
- Standard par défaut configurable (`default_standard` dans config.json + Settings).
- Dézoom limité au fitViewBox × 1.1.
- Double-click plan Import : détection par timer mousedown (400ms) au lieu du dblclick natif (cassé par re-render).

**Impact** :
- `olm/static/style.css` : couleurs onglets, pseudo-element hover, sub-tab-bar, descriptions italiques
- `olm/templates/pattern_editor.html` : renommage onglets, description sous-onglets
- `olm/static/init.js` : descriptions sous-onglets, handlers
- `olm/static/ingestion.js` : masquage conditionnel, dblclick timer
- `olm/static/config.js` : default_standard wiring
- `project/config.json` : `default_standard: "SITE"`

---

## D-88 · Drawing scale — échelle explicite du plan (2026-04-16)

**Décision** : L'échelle du plan est désormais un paramètre explicite `drawing_scale` (format `"1 : 100"`) combiné au `render_dpi` (DPI de rastérisation du PDF, 300 par défaut).

**Formule** : `cm_per_px = 2.54 × scale_number / render_dpi`

**Sources d'échelle par priorité** :
1. **Champ UI** `drawing_scale` dans Import (sous le sélecteur de plan) — saisi par l'utilisateur
2. **Estimation médiane** — si le champ est vide, le backend calcule cm_per_px à partir des surfaces m² et des bbox (formule existante). L'échelle estimée est rétro-affichée dans le champ en jaune (warning) avec mention "may be inaccurate".
3. **Fallback 0.5** — si aucune donnée disponible

**render_dpi** : configurable dans Settings > Floorplan (défaut 300). Correspond au DPI utilisé pour rastériser le PDF source en PNG.

Modifier le champ `drawing_scale` après import recalcule **immédiatement** les dimensions de toutes les pièces (via `ingState.scale` et `_updateRoomDims`), sans re-import.

**Justification** : La déduction par médiane des surfaces était le seul chemin et produisait des échelles incorrectes quand les bbox ne collaient pas exactement aux pièces. Un paramètre explicite élimine cette source d'erreur pour les plans dont l'échelle est connue.

**Impact** :
- `project/config.json` : ajout `drawing_scale` (string) et `render_dpi` (int) dans `ingestion`
- `olm/templates/pattern_editor.html` : champ Drawing scale dans Import + champ Render DPI dans Settings > Floorplan
- `olm/static/ingestion.js` : parsing, envoi au backend, recalcul live, suggestion inverse
- `olm/server/app.py` : routes OCR et Preprocessed acceptent `drawing_scale` + `render_dpi`
- `olm/ingestion/extract.py` : supporte `_override_cm_per_px` dans json_data

---

## D-87 · Solidification D-83 — overlay, state, port Python + tests (2026-04-16)

**Décision** : Correction des bugs résiduels de l'orientation canonique (D-83) et port de la logique en Python avec couverture de tests.

**Corrections** :
- **Overlay décalé 90°/270°** : ajout d'un `translate` compensatoire `(w-h)/2` lors de la rotation de l'overlay PNG pour corridor east/west. Sans cela, l'image était décalée d'une demi-pièce car les dimensions canonicalisées (w/h swappés) ne correspondaient plus au cadre de l'overlay original.
- **corridor_face perdu après Save** : `enterRoomAmendMode()` ne propageait pas `corridor_face` dans `state`, et `fpRoomAmendments` ne conservait pas `corridor_face` sur les données amendées. Résultat : après Save, la rotation overlay revenait à 0°.

**Port Python** :
- Module `olm/core/canonical.py` : `canonicalize_room()` et `decanonicalize_room()`, port fidèle de la logique JS (`floor_plan.js`). Réutilisable côté serveur (matching, export).
- 19 tests pytest (`olm/tests/test_canonical.py`) : round-trip pour les 4 orientations, dimensions, face mapping, exclusion zones, rooms minimales.

**Justification** : Les bugs étaient visibles sur toute pièce avec corridor east/west (≈50 % des pièces typiques). Le port Python garantit la cohérence JS/Python et permet des tests automatisés.

**Impact** :
- `olm/static/editor.js` : 3 lignes modifiées (translate overlay, state.corridor_face dans enterRoomAmendMode, corridor_face dans amendedRoom).
- `olm/core/canonical.py` : nouveau module.
- `olm/tests/test_canonical.py` : nouveau fichier de tests.

---

## D-86 · Portes principales/secondaires et orientation canonique (2026-04-15)

**Décision** : Classification des ouvertures en deux catégories et orientation canonique des pièces dans Review et Design.

**Catégories d'ouvertures** :

| Catégorie | Définition | Rôle |
|---|---|---|
| **Principale** | Ouverture/porte donnant sur le couloir (zone verte dans le PNG enhanced) | Définit le **sud** du référentiel canonique de la pièce |
| **Secondaire** | Ouverture/porte entre bureaux (zone blanche — pièce voisine) | N'affecte pas l'orientation canonique |

**Orientation canonique** :
- Dans les vues Review et Design, toute pièce est affichée avec la porte principale en bas (sud) et les fenêtres en haut (nord)
- L'utilisateur "entre" visuellement par le bas de l'écran
- Rotation purement visuelle (0°/90°/180°/270°) déduite de la face réelle de la porte principale sur le plan d'étage
- Coordonnées internes de la pièce inchangées

**Détection de la porte principale** :
- Mode Préprocessé : la face qui borde la zone verte (couloir) dans le PNG enhanced est la face principale
- Mode OCR : heuristique existante `corridor_face` (première face avec une porte détectée)
- Le champ `corridor_face` (déjà présent dans `DetectedRoom` et transmis au frontend) porte cette information

**Justification** : Les patterns sont conçus dans un référentiel canonique (couloir au sud, fenêtres au nord). L'affichage canonique garantit que le rendu visuel correspond toujours à cette convention, quelle que soit l'orientation réelle sur le plan d'étage. Pas besoin de rotation dans le pipeline de matching — seul le rendu est transformé.

**Impact** :
- `corridor_face` devient la source de vérité pour l'orientation
- Helper JS `computeCanonicalRotation(corridorFace)` retourne l'angle de rotation
- Wrapper `<g transform="rotate(...)">` appliqué au contenu des canvas `rvCanvas` et `fpCanvas`
- L'overlay (image du plan) est inclus dans le groupe transformé
- ViewBox ajusté après rotation si nécessaire

---

## D-61 · Navigation : 2 onglets principaux + sous-onglets (2026-04-03)

**Décision** : Restructuration de la navigation en 2 onglets principaux (Floor Plan / Office Layout) avec sous-onglets. Interface traduite en anglais.
**Justification** : Clarifier la navigation entre le workflow d'analyse par étage et l'édition de patterns.
**Impact** : `pattern_editor.html` restructuré, onglet actif en fond accent.

## D-62 · Exclusions périphériques réduisent les dimensions effectives de la pièce (2026-04-03)

**Décision** : Une exclusion qui longe un mur sur toute sa largeur ou profondeur réduit la dimension effective de la pièce pour la sélection des patterns candidats dans le matching. Exemple : `EXCL 0 0 400 30` sur une pièce de 400×500 → profondeur effective = 470 cm.
**Justification** : Permet de modéliser proprement un obstacle le long d'un mur (poteau, gaine, retrait) sans changer les dimensions brutes de la pièce. Le matching sélectionne alors des patterns plus petits, adaptés à l'espace réellement utilisable.
**Impact** : Fonction `effective_dimensions()` ajoutée dans `catalogue_matcher.py`, utilisée par `_fits_in_room()`.

## D-63 · Workflow d'amendement : Amend layout + Adjust room (2026-04-03)

**Décision** : Deux workflows d'amendement distincts dans Floor Plan / Matching :
- **Amend layout** : éditer la solution (blocs) pour une pièce donnée, sauver comme amendement local, possibilité de Discard.
- **Adjust room** : éditer la géométrie de la pièce (dimensions, ouvertures, exclusions), sauver et relancer le matching.
Les amendements sont stockés côté client (pas en base). Le nom de la pièce porte "(amended)" quand la géométrie a été modifiée. Un amendement de layout masque les candidats automatiques et affiche uniquement la solution amendée.
**Justification** : Séparer clairement l'édition du pattern source (Edit pattern → éditeur catalogue) de l'ajustement contextuel à une pièce (Amend layout / Adjust room). L'utilisateur peut corriger les erreurs d'ingestion (Adjust room) ou affiner le placement (Amend layout) sans polluer le catalogue.
**Impact** : `enterAmendMode()`, `enterRoomAmendMode()`, `fpAmendments`, `fpRoomAmendments`, `fpRematchRoom()` dans `pattern_editor.html`. Boutons : Adjust room | Edit pattern, Amend layout, Discard amendment.

## D-64 · Overlay raster du plan d'étage (2026-04-03)

**Décision** : Le plan d'étage raster est chargé comme entrée dans Floor Plan / Input (image + échelle px/cm). Il s'affiche en filigrane derrière la pièce dans le matching (checkbox Overlay + slider opacité) et automatiquement en mode Adjust room (opacité 30%). Par défaut désactivé en Floor Plan, activé en Room Amend.
**Justification** : Permet à l'utilisateur de vérifier visuellement que l'interprétation de chaque pièce est correcte en la superposant au plan réel. Si l'overlay ne colle pas, c'est l'ingestion qu'il faut corriger (via Adjust room), pas l'overlay qu'on déplace.
**Impact** : `state.overlay`, `window.fpOverlay` dans `pattern_editor.html`. Route `/test_floor_plan.png` pour le dev.

## D-65 · Settings : paramètres d'espacement éditables et persistés (2026-04-03)

**Décision** : Les 11 paramètres d'espacement (ES-01 à PS-04) de chaque standard sont éditables depuis un onglet Settings dans Office Layout. Les modifications sont sauvées immédiatement dans `spacing_overrides.json` (delta par rapport aux défauts) et prises en compte par le rendu et le matching sans redémarrage.
**Justification** : Permettre d'ajuster les contraintes d'espacement sans modifier le code Python. Les fallbacks hardcodés en JS ont été supprimés — tout passe par `CURRENT_SPACING` chargé depuis l'API.
**Impact** : `spacing_config.py` : `update_config()`, `reset_config()`, persistence JSON. `pattern_server.py` : POST `/api/spacing`. `pattern_editor.html` : onglet Settings, `renderSpacingSettings()`.

## D-66 · VISION_LLM_IO_SPEC : spécification entrées/sorties LLM Vision (2026-04-03)

**Décision** : Création de `specs/VISION_LLM_IO_SPEC.md` documentant le format JSON et DSL attendu en sortie du LLM Vision pour l'ingestion des plans d'étage. Couvre le système de coordonnées NW→SE, la structure pièce/fenêtres/ouvertures/exclusions, les cas particuliers (pièces en L, sens des portes) et les règles de validation.
**Justification** : Fournir un contrat clair pour le module d'ingestion futur. Réutilise le format JSON déjà consommé par le pipeline de matching et le DSL de `room_dsl.py`.
**Impact** : `specs/VISION_LLM_IO_SPEC.md`. La tâche TODO "Définir le prompt-type pour le LLM vision" est partiellement couverte.

---

## D-67 · Refactoring frontend : un canvas SVG par vue (2026-04-04)

**Décision** : Chaque vue (Editor, Review, Match) possède son propre élément SVG statique. Le canvas unique déplacé par appendChild entre les vues est supprimé.
**Justification** : Le mécanisme de déplacement DOM (moveCanvasToFloorPlan, moveCanvasToReview, moveCanvasToEditor) avec snapshot/restore de l'état éditeur était la source de 80% des bugs UX (état fantôme, pièce vide au retour, mode Adjust qui switch d'onglet). Les canvas séparés éliminent cette classe de bugs.
**Impact** : Les fonctions de rendu (render, zoomFit, updateViewBox, zoomIn, zoomOut) acceptent un paramètre optionnel targetSvg. Le CSS inline est externalisé, le JS est découpé en 4 modules. Le save/restore de l'état éditeur est simplifié (state-only, plus de DOM).

---

## D-68 · Navigation : 5 étapes workflow + Edit catalogue (2026-04-05)

**Décision** : L'interface passe de 2 onglets principaux (Floor Plan / Office Layout) à 6 onglets plats : ①Import floor plan, ②Review rooms, ③Identify merges, ④Design layout, ⑤Export results, + Edit catalogue (séparé visuellement). Chaque onglet workflow porte un numéro dans un cercle coloré. Un bandeau description dynamique s'affiche sous le header. Le catalogue a 3 sous-onglets : Card view, Grid view, Pattern editor.
**Justification** : Le workflow en 5 étapes rend le processus explicite et guidé. La séparation du catalogue (outil de création) du workflow (processus d'aménagement) clarifie les rôles. Les sous-onglets Cards/Grid remplacent le toggle précédent.
**Impact** : Tous les sélecteurs programmatiques (`.click()`) dans editor.js, floor_plan.js, catalogue.js, init.js migrés vers les nouveaux `data-tab`/`data-subtab`. Les gardes canvas/clavier inversées (autorisent uniquement Catalogue > Editor). L'onglet Merge est un placeholder.

---

## D-69 · Convention desk : width = face large, depth = avant-arrière (2026-04-05)

**Décision** : `DESK_W_CM` = 180 cm (largeur, face large gauche-droite), `DESK_D_CM` = 80 cm (profondeur, avant-arrière vers l'écran). Le mapping config.json → code est direct (pas d'inversion).
**Justification** : Aligne la convention interne sur la perspective de l'utilisateur assis au bureau. Les labels Settings "Desk width" et "Desk depth" correspondent à l'intuition humaine.
**Impact** : Toutes les formules de blocs dans pattern_generator.py inversées (eo = f(D), ns = f(W)). getDeskRects dans block_geometry.js adapté. _BLOCK_DESK_FACTORS dans app.py recalcule dynamiquement les dimensions de blocs quand desk width/depth changent dans les Settings.

---

## D-70 · Design tokens CSS et polices constantes (2026-04-05)

**Décision** : Toutes les valeurs visuelles (couleurs, tailles de police, espacements) sont définies comme CSS custom properties dans `:root` et utilisées partout via `var()`. Les tailles de police dans les SVG sont compensées par `zf = 1 / min(pxW/vbW, pxH/vbH)` pour rester constantes quel que soit le zoom ou la taille de la pièce.
**Justification** : Élimine les incohérences visuelles entre vues (font-size 10px ici, 12px là), les valeurs en dur répétées (6 blocs inline identiques pour les inputs Settings), et le problème de textes illisibles en zoom out ou trop gros en zoom in.
**Impact** : 7 niveaux de taille de police (`--fs-xs` à `--fs-room`), 7 niveaux d'espacement (`--sp-xs` à `--sp-page`), classes utilitaires (`.settings-input`, `.btn-toolbar`, `.btn-cancel`, `.edit-mode`). `window._currentZf` partagé entre `editor.js` et `block_svg.js`.

---

## D-71 · Rulers HTML fixes hors du SVG (2026-04-05)

**Décision** : Les graduations métriques (0m, 1m, 2m...) sont rendues en HTML (`<span>` positionnés absolument) dans un `ruler-box` div autour du SVG, et non plus comme éléments `<text>` dans le SVG.
**Justification** : Les labels SVG se déplaçaient avec le pan et changeaient de taille avec le zoom. Les labels HTML restent fixes aux bords du canvas et leur taille est constante.
**Impact** : `_ensureRulers(svg)` crée dynamiquement un `ruler-box` autour de chaque SVG (éditeur, Design, Review). `updateRulers(svg)` recalcule les positions via `svg.getScreenCTM()`. Les rulers sont mis à jour à chaque render, zoom et pan.

---

## D-72 · Renommage UI : Office Layout Studio (2026-04-05)

**Décision** : Le nom affiché dans l'interface est "Office Layout Studio" (OLS). Le package Python reste `olm`.
**Justification** : "Matching" est un terme technique interne qui n'apparaît pas dans le workflow utilisateur. "Studio" reflète l'aspect interactif de l'outil sans prétention.
**Impact** : Titre `<title>` et header modifiés. Package et imports inchangés.

---

## D-73 · OCR Tesseract : whitelist typée + désactivation dictionnaires + upscale x2 (2026-04-12)

**Décision** : Tesseract configuré avec whitelist de caractères (chiffres + tirets), dictionnaires désactivés, upscale x2 pour améliorer la reconnaissance des cartouches.
**Justification** : Améliorer la robustesse de l'extraction des pièces depuis le PNG d'origine face aux cartouches non-standard.
**Impact** : `extract.py`, paramètres OCR module.

---

## D-74 · Dual-mode ingestion : Mode OCR vs Mode Préprocessé (2026-04-12)

**Décision** : OLS accepte deux modes d'ingestion pour un plan d'étage donné :

1. **Mode OCR** (existant, par défaut) :
   - Entrée : un fichier PNG du plan brut comprenant cartouches
   - Traitement : ray-cast 3 phases + OCR optionnel cartouches
   - Sortie : liste des pièces détectées (width, depth, area, seed position)

2. **Mode Préprocessé** (nouveau) :
   - Entrées : 
     - Fichier JSON contenant liste des pièces (id, surface, seed position)
     - Fichier PNG overlay (plan officiel du bâtiment)
     - Fichier PNG "_enhanced" (PNG overlay avec cartouches supprimés, extérieur bleu RGB(135,206,235), couloirs vert RGB(193,247,179))
   - Traitement : parsing JSON directement, analyse du PNG enhanced pour affiner topologie
   - Sortie : liste des pièces (directement du JSON)

Le mode est sélectionné via une dropdown "Input Mode: [OCR | Preprocessed]" dans le panneau Settings (section "Ingestion").

**Justification** : 
- Mode OCR : gérer les plans existants sans prétraitement. OCR optionnel permet de critiquer visuellement les cartouches.
- Mode Préprocessé : réduire l'impact des artefacts OCR en utilisant des données structurées externes. Le PNG enhanced facilite l'analyse topologique (fenêtres/portes/couloirs). Cartouches préalablement supprimés en preprocessing.

**Impact** : 
- `olm/ingestion/extract.py` : deux fonctions parallèles (`extract_rooms_from_raster_ocr`, `extract_rooms_from_preprocessed`)
- `olm/server/app.py` : routes POST `/api/import/ocr` et `/api/import/preprocessed`
- `pattern_editor.html` : deux formulaires upload distincts (radio buttons ou onglets), refresh du rendu côté client
- `olm/core/types.py` : enum `IngestionMode = {"ocr", "preprocessed"}` dans `RoomSpec`
- Note : artefacts au niveau des arcs de portes dans le PNG enhanced requis étude spécifique (D-75)

---

## D-85 · Auto-détection OCR / Preprocessed par fichier — mode invisible à l'UI (2026-04-15)

**Décision** : Suppression du sélecteur de mode global (OCR / Preprocessed) dans l'UI et dans Settings. Le mode est désormais **détecté automatiquement par plan** selon la règle :
- PNG seul (pas de JSON compagnon) → mode **OCR**
- PNG + JSON compagnon **plus récent que le PNG** (`JSON.mtime > PNG.mtime`, strictement) → mode **Preprocessed** (= chargement rapide depuis JSON)
- PNG + JSON compagnon plus ancien que le PNG → le JSON est **considéré comme obsolète** → fallback **OCR** automatique (retoucher le PNG force une re-ingestion)

**Le mode est invisible à l'UI** : le dropdown Load présente une **liste plate** triée alphabétiquement, sans sections ni badges de mode. L'utilisateur clique sur un plan, OLS fait ce qu'il faut selon le `effective_mode` détecté.

Note : une fois R-11 (Save) implémenté, OLS écrira un JSON à côté de chaque PNG après la première sauvegarde. Le JSON deviendra donc la norme pour tous les plans déjà ouverts. La distinction OCR/Preprocessed perd sa pertinence UX — d'où le choix de la rendre invisible.

**Confirmation avant extraction OCR** : lorsque l'utilisateur sélectionne un plan dont le `effective_mode` est `"ocr"` (pas de JSON), afficher une `confirm()` navigateur avec un message type `"No JSON file found for this plan. Processing the input with Optical Character Recognition — this may take a few seconds. Continue?"`. Si l'utilisateur annule, l'extraction n'est pas lancée et la sélection est réinitialisée. En mode `"preprocessed"`, pas de confirmation — le chargement est rapide.

**Format JSON unique** : seul le format v3 est valide. Si un JSON est présent mais au format v2 (ancien), l'extraction échoue avec une erreur explicite. Pas de fallback silencieux ni de compatibilité descendante — voir `PREPROCESSED_JSON_SPEC.md`.

**Justification** :
- **Simplicité utilisateur** : le fichier "sait" son mode. Plus de toggle à se rappeler, plus d'erreur "j'ai choisi le mauvais mode".
- **Gestion naturelle des cas limites** : regénération d'un PNG → mtime change → JSON devient obsolète → refresh OCR automatique.
- **Alignement avec la règle doc unique source** : pas de divergence possible entre un "paramètre de mode" et l'état réel des fichiers.
- **Paramètre `plans_dir`** exposé dans Settings pour permettre à l'utilisateur de pointer vers un dossier externe de plans (usage multi-postes sur disque partagé).

**Impact** :
- `olm/server/app.py` : route `GET /api/plans` enrichie d'un champ `effective_mode` (`"ocr"` ou `"preprocessed"`) par plan, déduit de la présence et du mtime du JSON. `PLANS_DIR` lit désormais `ingestion.plans_dir` depuis `config.json` (avec fallback `"project/plans"`).
- `olm/static/ingestion.js` : suppression du `#ingModeSelect`, de `ingState.ingestionMode`, de `rebuildPlansDropdown(mode)`, de `renderImportPanel`. Le dropdown est peuplé une seule fois via `<optgroup>`. La fonction d'extraction route vers OCR ou Preprocessed selon `effective_mode` de l'option sélectionnée.
- `olm/templates/pattern_editor.html` : suppression de `#ingModeSelect` et de son label.
- `project/config.json` : ajout de la clé `ingestion.plans_dir`.
- `olm/ingestion/extract.py` : le parser v3 lève une `ValueError` explicite si les champs `code_line1` / `surface_line2` / `id_line3` (v2) sont détectés dans le JSON — message indiquant que seul le format v3 est supporté.

---

## D-84 · JSON v3 simplifié + règle "docs = source unique de vérité" (2026-04-14)

**Décision** : Refonte du format JSON Mode Préprocessé en v3, avec simplification radicale :

- ROOT : suppression de `plan_scale`, `dpi`, `scale_factor`, `rotation_angle`, `page_width_pts`, `page_height_pts`, `total_*`, `all_text_blocks[]`. Conservés : `file`, `building_id`, `floor_id`, `page_width_px`, `page_height_px`, `rooms[]`.
- Échelle `cm_per_px` **déduite côté OLS** à partir des surfaces m² détectées (médiane sur pièces mesurables), plus besoin de la fournir dans le fichier.
- `rooms` devient un **objet indexé par `room_id`** (plus un array), aligné avec `olm_state.rooms_state`. Lookup O(1), unicité garantie par le format, disparition du champ `id` redondant dans chaque valeur.
- **Orientation** : ajout de `north_angle_deg` au ROOT (angle entre haut de l'image et nord géographique, purement métadonnée) et de `canonical_top_face` par pièce (face image devenant le haut de la vue canonique D-83). `canonical_top_face` est auto-dérivé côté OLS depuis la face opposée à la porte principale, donc Save-enrichi uniquement. Valeurs discrètes `north`/`south`/`east`/`west` (pas d'angle libre — garde la rotation bbox orthogonale).
- Per room : aplatissement du cartouche en champs plats (plus les objets imbriqués `code_line1` / `surface_line2` / `id_line3`). Ajout de `seed_px` direct + `bbox_px` optionnel. Suppression de toutes les métadonnées typographiques (`font_size`, `font_name`, `color_rgb`) et du référentiel points PDF (`points_*`, `width_pt`, `height_pt`). Le champ `code` (ex: `"14"`) est également supprimé : c'est un filtre interne du Settings OLS, pas une donnée à persister.
- Ouvertures (`doors`, `openings`, `windows`) **imbriquées dans chaque room**, plus d'`associated_room` cross-référence.
- Schéma `door` scindé Input (`label_px` seul) vs Save (enrichi par OLS avec `face`, `offset_px`, `width_px`, `hinge_side`, `opens_inward`). Un fichier Save est un fichier Input enrichi — ré-import idempotent.
- `hits[]` (points d'intersection ray-cast) jamais persistés : recalculables.

En parallèle, ajout d'une **règle générale** dans `CLAUDE.md` : toute information utile à long terme vit **dans `docs/` uniquement**. L'utilisateur n'a rien à noter de son côté. Les fichiers du repo sont la source de vérité unique. En cas de conflit entre conversation et `docs/`, `docs/` fait foi.

**Justification** :
- Le format v2 exposait trop d'informations jamais consommées par OLS (métadonnées PDF, fontes, référentiel points), ce qui compliquait la production manuelle ou par un preprocessing tiers et rendait le ré-import fragile.
- La règle "docs = source unique" évite la divergence conversation ↔ spec et garantit qu'un nouveau contributeur (humain ou agent) peut se caler uniquement sur les fichiers du repo.
- La décision va de pair avec l'implémentation du bouton DEV "Export v3 JSON" (onglet Load, contour orange vif) qui sérialise l'état de l'OCR en v3 et permet de tester le Mode Préprocessé end-to-end sans preprocessing externe.

**Impact** :
- `docs/specs/PREPROCESSED_JSON_SPEC.md` réécrit en v3 (référence unique).
- `CLAUDE.md` enrichi d'une section "Documentation = source unique de vérité".
- `docs/TODO.md` : section "Générateur de plan de test" restructurée en 3 morceaux (A : bouton DEV implémenté, B : PNG enhanced manuel, C : script CLI futur).
- Bouton DEV "Export v3 JSON" ajouté dans `olm/templates/pattern_editor.html` (contour orange vif `#ff6600`) et handler `devExportV3Json()` dans `olm/static/ingestion.js`.
- Téléchargement navigateur direct (Blob), nom fichier = stem du plan courant.
- `extract_rooms_from_preprocessed()` dans `olm/ingestion/extract.py` **à adapter** pour le schéma v3 (tâche suivante) : parser les 3 champs plats `code`/`surface`/`id`, utiliser `seed_px` directement, skipper le ray-cast si `bbox_px` présent, skipper la détection porte si `face/offset_px/...` déjà enrichis.

---

## D-83 · Orientation canonique des pièces en Review et Design : couloir en bas, fenêtres en haut (2026-04-14)

**Décision** : Toute pièce affichée dans les onglets **Review** et **Design** est systématiquement orientée avec :
- La **porte d'entrée (couloir) en bas**
- Les **fenêtres en haut**
- Optionnellement, des fenêtres à gauche et/ou droite

L'utilisateur est toujours placé à la position "entrant par la porte", donc **"devant soi = haut de l'écran"**. La vue subit une rotation de 0°, 90°, 180° ou 270° (et éventuellement un miroir horizontal) par rapport au repère du plan d'origine pour respecter cette convention, quel que soit le placement réel de la pièce dans le plan.

Cette rotation est **purement visuelle** : les coordonnées internes (bbox, DSL pièce, exclusions, etc.) restent inchangées dans le repère natif du plan. Seul le rendu SVG applique une transformation.

**Justification** :
- **Cohérence cognitive** : l'utilisateur n'a pas à ré-interpréter mentalement l'orientation à chaque pièce, ce qui est particulièrement critique quand on enchaîne la revue ou le design de dizaines de pièces.
- **Aligne la vue sur l'intuition métier** : "devant soi" = là où on va poser les postes (vers les fenêtres), "derrière soi" = là où on entre. C'est l'angle naturel d'un aménageur.
- **Stabilise la lecture des patterns** : dans le catalogue, les patterns sont tous dessinés avec cette même convention (porte en bas, fenêtres en haut) — la correspondance pattern ↔ pièce devient directe.
- **Simplifie la comparaison de candidats** : comparer plusieurs solutions pour une même pièce ou une même solution appliquée à plusieurs pièces se fait désormais à orientation constante.

**Impact** :
- Nouveau helper côté rendering : `computeRoomViewTransform(room)` qui retourne la matrice de rotation/miroir à appliquer au rendu SVG, déduite de la position de la porte principale (face `bottom` cible) et des fenêtres (face `top` cible).
- `rvCanvas` (Review) et `fpCanvas` (Design) appliquent cette transformation au groupe racine du SVG.
- Les overlays (grille, règles, labels, pointeurs souris pour l'outil zone interdite) doivent être cohérents avec le référentiel transformé — ajustements à prévoir dans `editor.js` et `init.js`.
- Si une pièce a plusieurs portes, la porte côté couloir principal est choisie comme référence (heuristique à définir : porte avec le segment mural le plus long adjacent à un corridor, ou porte marquée `primary` dans le DSL si ajouté plus tard).
- L'outil Match dans Design continue de rendre les patterns dans la même orientation canonique — pas de rotation additionnelle à ce niveau.

**Non impacté** :
- Vue globale du plan dans Load : aucune rotation, le plan reste dans son orientation d'origine (on doit pouvoir le comparer visuellement au scan PNG).
- Export JSON / PDF : géométrie dans le repère natif du plan (pas la vue tournée).

---

## D-82 · R-01 finalisé — README racine + pyproject valide (2026-04-14)

**Décision** : Clôture du chantier R-01 (renommage OLO → OLM + séparation OSS/privé). `olm/README.md` est promu en `README.md` à la racine du dépôt. `pyproject.toml` corrigé : `build-backend = "setuptools.build_meta"` (l'ancienne valeur `"setuptools.backends._legacy:_Backend"` était invalide) et `readme = "README.md"`. Le `.gitignore` existant couvre déjà l'exclusion de `project/`, `docs/`, `solver_lab/`, `CLAUDE.md`, `CLAUDE_IMPLEMENTER.md` et `.claude/`.

**Justification** : Un README à la racine est la convention GitHub (page d'accueil du dépôt) ; avoir le README dans un sous-dossier casse l'affichage. Le build-backend erroné empêchait tout build wheel/sdist. Aucun autre fichier n'était à créer côté `.gitignore`.

**Impact** : R-01 entièrement cochée dans `TODO.md`. `pyproject.toml` devient buildable (`python -m build` fonctionnel). Aucun changement de code produit.

---

## D-81 · Cartouche OCR à 3 lignes — suppression N REEL / N THEO (2026-04-14)

**Décision** : Le format du cartouche Mode OCR passe de 5 lignes à **3 lignes**, alignées sur le format Mode Préprocessé :

```
Ligne 1 : code pièce     (ex: "14", paramétrable via room_code)
Ligne 2 : surface        (ex: "14.28 m2", suffixe " m2" explicite)
Ligne 3 : identifiant    (ex: "237", "12a", "1AB")
```

Les lignes **N REEL** (nombre de personnes réel) et **N THEO** (nombre théorique) qui figuraient dans l'ancien format 5 lignes sont **supprimées**.

**Justification** :

- **Non exploitées** : N REEL et N THEO ne sont consommées par aucun module du pipeline OLS (ni matching, ni rendu, ni export)
- **Source d'ambiguïté OCR** : des chiffres courts isolés (`"2"`, `"3"`) au milieu du cartouche créent des faux positifs quand Tesseract parse les numéros de pièce (D-73 a mitigé mais n'a pas éliminé le risque)
- **Unification avec le Mode Préprocessé** : le format Préprocessé est déjà à 3 lignes (`code_line1` / `surface_line2` / `id_line3`, cf. D-77). L'alignement simplifie le parsing, permet un code d'extraction commun entre les deux modes, et réduit la surface de maintenance
- **Pas de régression métier** : N REEL et N THEO étaient une information d'occupation que ni le matching ni l'utilisateur ne manipulent. L'aménagement est piloté par la surface et les standards d'espacement, pas par un nombre théorique d'occupants

**Impact** :

- `specs/INGESTION_HYPOTHESES.md` §H-09 : mise à jour du format cartouche et ajout d'une note historique sur l'ancien format 5 lignes
- `olm/ingestion/extract.py` / `test_comb.py` : algorithme de regroupement adapté (chercher 3 textes empilés au lieu de 5)
- Whitelist Tesseract + regex D-73 : déjà cohérentes (elles ciblent uniquement code / surface / id), vérification finale nécessaire
- Tolérance rétrocompatible : si l'OCR détecte 5 lignes (ancien plan), loguer un warning et ignorer les 2 lignes intermédiaires
- R-05 (TODO.md) : nouvelle sous-section « Mode OCR — Cartouche 3 lignes » avec 6 tâches
- Alignement des deux modes : Mode OCR et Mode Préprocessé partagent désormais la même sémantique de cartouche à 3 lignes, facilitant les évolutions futures (unification possible du parsing)

---

## D-80 · Zones interdites : promotion auto des petits artefacts + UX Review (2026-04-14)

**Décision** : Les zones interdites (`EXCL`) peuvent avoir **deux origines** convergeant vers la même structure de données et le même traitement aval :

**1. Promotion automatique en ingestion**

Un paramètre `min_size_artifact_cm2` (défaut : 2500 = 50×50 cm, éditable dans Settings > Ingestion) définit le seuil en dessous duquel un artefact détecté à l'intérieur d'une pièce est automatiquement promu en zone interdite plutôt que traité comme mur ou obstacle majeur.

Effet dans le pipeline :
- **Phase ray-cast / rectangle inscrit** : les pixels de l'artefact sont traités comme de l'intérieur libre — les rays les traversent et la bbox de la pièce peut englober un grand rectangle utile même s'il contient un poteau. Plus d'entaille dans la géométrie pour cause de petit obstacle.
- **Phase matching** : l'exclusion générée est prise en compte par `effective_dimensions()` (D-62) et par le scoring de couverture. Le matching **ne part pas de zéro** — il propose le meilleur pattern open space global, en ignorant les postes qui collideraient avec les poteaux. L'utilisateur lève les conflits résiduels via Amend layout en place (D-63).

Cas d'usage typique : **grand open space avec poteaux structurels**. Aujourd'hui ces pièces génèrent soit des bbox tronquées soit aucun matching ; demain elles bénéficient d'un pattern de référence + un amendement local sur les zones des poteaux.

**2. Amendement manuel en Review**

L'utilisateur peut ajouter / déplacer / supprimer des zones interdites à la souris dans l'onglet Review via un outil sélectionnable dans la toolbar (mode "Add forbidden zone", dessin par clic + drag). **Pas de redimensionnement souris** : pour modifier la taille, passer par le DSL pièce (ligne `EXCL x y w h` éditable). Cohérence avec la philosophie "édition visuelle simple, géométrie précise via DSL".

Cas d'usage : obstacles non détectés par l'ingestion (mobilier fixe, gaines, escaliers) ou correction d'une exclusion auto mal positionnée.

**Justification** :

Les plans réels contiennent régulièrement des obstacles internes (poteaux, gaines) qui ne doivent ni briser la détection du rectangle ni être ignorés en aménagement. Traiter ces obstacles comme des murs donne des bbox absurdes (morcelées) ; les ignorer donne des placements invalides (postes sur un poteau). La solution est d'introduire une classe intermédiaire — la zone interdite — avec un critère de taille pour décider automatiquement.

Le double mécanisme (auto + manuel) donne de la robustesse : l'auto couvre les cas courants sans intervention, le manuel rattrape les cas limites. La même structure `EXCL` à la fin garantit qu'un seul pipeline aval (matching, rendu, export) traite les deux cas de façon identique.

Le choix "pas de redimensionnement souris" est délibéré : la souris est excellente pour positionner et supprimer, médiocre pour dimensionner précisément. Le DSL reste la source de vérité pour les dimensions exactes — l'UI souris n'y apporterait qu'une imprécision déroutante.

**Impact** :

- `project/config.json` + Settings > Ingestion : nouveaux paramètres `min_size_artifact_cm2` (2500) et `artifact_promotion_enabled` (true)
- Pipeline ingestion (`olm/ingestion/extract.py`) : la phase de détection des artefacts intérieurs applique le seuil et émet soit une `EXCL`, soit un obstacle bloquant les rays
- Pipeline rectangle inscrit (`RASTER_EXTRACTION_SPEC.md` §7.1) : les pixels promus en `EXCL` sont considérés comme intérieur libre pendant la recherche du rectangle utile
- `catalogue_matcher.py` : `effective_dimensions()` (D-62) déjà compatible — pas de changement requis, juste validation
- UI Review : outil souris "Add forbidden zone" (toolbar), sélection + Delete, pas de redimensionnement souris, redim via DSL
- UI Match : badge visuel sur les pièces avec `EXCL` promues auto (signalement "poteau détecté, vérifier")
- Spec DSL pièce : marqueur optionnel `EXCL auto` pour tracer l'origine (auto vs manuel) — utile pour le round trip D-78 et le reset utilisateur
- R-04 Review (TODO.md) : clarification de l'outil souris (pas de redimensionnement)
- R-05 (TODO.md) : nouvelle sous-section « Zones interdites — promotion automatique des petits artefacts » avec les tâches d'implémentation

---

## D-79 · Ray-casting context-aware en Mode Préprocessé (2026-04-14)

**Décision** : En Mode Préprocessé, le pipeline ray-cast devient **context-aware** — il exploite simultanément l'image binarisée et des informations sémantiques externes pour produire un résultat plus robuste. Deux mécanismes indissociables :

**1. Zones de transparence de porte via `doors[]`**

Pour chaque porte du JSON v2 (`doors[]` avec `associated_room`), construire un masque rectangulaire centré sur `(pixels_x, pixels_y)`, de dimensions `(width_px, height_px)` + marge. Les pixels à l'intérieur de ce masque sont **ignorés** par le ray-cast : les rays traversent la porte au lieu de s'arrêter sur le trait d'huisserie ou l'arc de cercle.

Effet : le ray s'arrête sur le vrai mur derrière la porte — mur de la pièce mitoyenne, frontière couloir, ou façade — et le segment couvert par le masque **est** automatiquement classifié comme ouverture (pas de détection d'arc a posteriori).

**2. Arrêt sur frontières sémantiques (blanc↔vert et blanc↔bleu)**

Le PNG enhanced introduit deux couleurs sémantiques au-delà du binaire noir/blanc :
- **Vert RGB(193,247,179)** : couloirs
- **Bleu ciel RGB(135,206,235)** : extérieur du bâtiment (et cours intérieures)

Le ray-cast s'arrête quand il rencontre l'un de ces trois états non-blancs (noir, vert, bleu). La **couleur d'arrêt qualifie immédiatement la nature du mur rencontré** :
- Noir → mur plein ou mitoyen
- Vert → mur sur couloir
- Bleu → mur façade (candidat fenêtre — analyse de texture uniquement sur ces segments)

**Justification** :

Le ray-cast pur décrit dans `RASTER_EXTRACTION_SPEC.md` §4–10 reste valide pour le Mode OCR, mais souffre de deux faiblesses sur lesquelles des heuristiques coûteuses ont été construites :
- Détection des arcs de porte a posteriori (§6.5) — fragile si l'arc est partiellement effacé (D-75)
- Détection de la face couloir (§7.3) — nécessite un flood fill et des heuristiques de connectivité

Le Mode Préprocessé dispose d'informations que le Mode OCR n'a pas (positions de portes du PDF source, coloration sémantique de l'outil de preprocessing). Les exploiter explicitement comme inputs du ray-cast — plutôt que comme étapes de classification post-hoc — simplifie radicalement le pipeline, neutralise D-75 en Mode Préprocessé, et rend la détection de la face couloir triviale et 100 % fiable. Les cours intérieures sont gérées gratuitement puisque peintes en bleu comme l'extérieur.

Le pipeline context-aware **enrichit** le ray-cast plutôt que de le remplacer : c'est toujours un ray-cast, avec des règles d'arrêt enrichies et un masque de transparence préalable. Aucune nouvelle primitive géométrique, uniquement une lecture plus riche de l'image.

**Impact** :

- `docs/specs/RASTER_EXTRACTION_SPEC.md` : section 11bis ajoutée (Ray-casting context-aware) décrivant les 4 états sémantiques, la règle d'arrêt enrichie, et le schéma des deux pipelines (pur vs context-aware)
- R-05 (TODO.md) : tâches d'implémentation déjà présentes dans la section « Exploitation avancée du PNG enhanced et du JSON v2 »
- Sections 6.5 et 7.3 inutilisées en Mode Préprocessé (toujours utilisées en Mode OCR)
- Section 6.6 (texture fenêtre) conservée mais restreinte aux segments pré-filtrés par la couleur bleu
- Les constantes RGB(193,247,179) et RGB(135,206,235) deviennent des paramètres critiques de l'ingestion — à exposer dans Settings > Ingestion pour le Mode Préprocessé

---

## D-78 · Navigation 3 onglets + Full round trip via olm_state (2026-04-14)

**Décision** : Deux changements d'architecture liés qui remplacent partiellement D-68 :

**1. Navigation simplifiée en 3 onglets plats** (au lieu de 5 étapes workflow) :

```
Floor plan  │  Office layout  │  Export     ‖    Catalogue [Cards | Grid | Editor]
```

- **Floor plan** regroupe Import + Review + Merge (sous-onglets internes)
- **Office layout** regroupe Design + Match (sous-onglets internes)
- **Export** reste autonome
- **Catalogue** séparé visuellement (inchangé)

Suppression de la numérotation pédagogique (cercles colorés) et des descriptions d'onglets par étape.

**2. Full round trip via `olm_state` dans le JSON** :

L'outil devient stateful. À chaque export, les sélections et amendements sont **sauvegardés dans le JSON v2** du plan sous une clé `olm_state` (extension non-breaking). À la réouverture, le système réhydrate l'état au lieu de recalculer un delta automatique.

- **Identification du plan** : nom du fichier PNG (pas de hash)
- **Clé de pièce** : `id_line3.text` (ex: `"237"`, `"22K"`)
- **Persistance** : clé `olm_state` dans le JSON v2 (Mode Préprocessé) ou sidecar JSON à côté du PNG (Mode OCR)
- **Politique de diff à la réouverture** :
  - Pièces présentes dans les deux → réhydratation des sélections/amendements
  - Pièces nouvelles (dans le JSON, absentes de `olm_state`) → badge "Nouveau", candidat automatique
  - Pièces orphelines (dans `olm_state`, absentes du JSON) → warning listant les disparues, choix utilisateur (nettoyage ou conservation)
- **Reset** : bouton par pièce pour supprimer son état et revenir au candidat auto

Structure (extension non-breaking du format v2) :
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
      }
    },
    "merges": [ {"ids": ["238", "239"], "merged_name": "238+239"}, ... ]
  }
}
```

**Justification** :

Sur le renommage 3 onglets : la structure 5 étapes (D-68) était pédagogique mais trop rigide. Trois onglets reflètent mieux les deux domaines métier réels (préparation du plan vs aménagement) + l'export comme action finale, et permettent une navigation plus libre pour un utilisateur régulier.

Sur le full round trip : le workflow actuel perd tout le travail entre deux imports, ce qui est inacceptable pour un usage réel. Persister l'état dans le JSON qui accompagne le plan garantit l'autonomie totale (pas de DB, pas de state serveur), reste cohérent avec l'esprit 100 % local de l'outil, et transforme l'export en simple sauvegarde. Le JSON devient source de vérité — simple, robuste, portable.

**Impact** :

- R-08 (TODO.md) refondu pour la nav 3 onglets — remplace ses tâches initiales
- R-11 (TODO.md) nouveau : 11 sous-tâches pour le round trip
- `PREPROCESSED_JSON_SPEC.md` : section `olm_state` à documenter
- Code frontend (init.js, editor.js, floor_plan.js, catalogue.js) : refonte sélecteurs `data-tab`/`data-subtab`
- Code backend : `merge_state_into_rooms()` + `build_olm_state()` + enrichissement des routes import/export
- D-68 partiellement obsolète (le workflow 5 étapes est remplacé ; les autres décisions de D-68 restent valides)

---

## D-77 · Format JSON preprocessé v2 — structure rooms/doors (2026-04-14)

**Décision** : La structure JSON du Mode Préprocessé évolue vers une forme v2 qui remplace D-76 :

- Clé principale `cartouches` → `rooms`
- Plus de wrapper `center` : chaque room contient directement `code_line1`, `surface_line2`, `id_line3`
- Chaque ligne porte ses propres métadonnées typographiques (`font_name`, `color_rgb`)
- `scale` → `scale_factor` (renommage, sens inchangé = dpi/72)
- Nouveaux champs ROOT : `total_text_blocks`, `total_rooms`, `total_doors`, `all_text_blocks[]`, `doors[]`
- Le centre du cartouche n'est plus fourni explicitement — OLS le calcule : `cx = moyenne(pixels_x des 3 lignes)`, `cy = surface_line2.pixels_y`

Exemple room v2 :
```json
{
  "code_line1":    {"text": "14",       "pixels_x": 1234, "pixels_y": 560, ...},
  "surface_line2": {"text": "14.28 m2", "pixels_x": 1234, "pixels_y": 575, ...},
  "id_line3":      {"text": "237",      "pixels_x": 1234, "pixels_y": 590, ...}
}
```

**Justification** : Le nouveau format est plus proche de la structure brute extraite par l'outil de preprocessing (pas de wrapper artificiel). Inclut les portes (`doors[]`) pour exploitation future (déduction des ouvertures) et tous les blocs texte PDF (`all_text_blocks[]`) pour analyses futures (cotes, labels).

**Impact** :
- `olm/ingestion/extract.py` : `extract_rooms_from_preprocessed()` refactorisée + helper `_room_center_from_lines()` ajouté
- `docs/specs/PREPROCESSED_JSON_SPEC.md` : réécrite pour v2 (section historique des versions ajoutée)
- `room_id` primaire = `id_line3.text` (plus de fallback vers `cartouche.number`)
- Validation : `rooms` (liste), chaque room doit avoir `code_line1`/`surface_line2`/`id_line3` avec `pixels_x/y`
- `doors[]` loggées mais non exploitées v1
- D-76 marquée obsolète (remplacée par D-77)

---

## D-76 · Format JSON cartouches pour Mode Préprocessé (2026-04-12) [OBSOLÈTE]

> ⚠️ Remplacée par D-77 (2026-04-14). Conservée pour historique.

**Décision** : Le JSON d'entrée du Mode Préprocessé suit une structure "cartouches" (et non "rooms") avec métadonnées globales du PDF + liste de cartouches détectés. Le facteur cm réel par pixel est calculé via `cm_per_px = (2.54/dpi) * plan_scale_ratio` — le champ `scale` (= dpi/72) n'est PAS utilisé pour cette conversion (c'est un facteur interne PDF→raster).

Structure principale :
```json
{
  "file", "building_id", "floor_id",
  "plan_scale": "1:N",     // N = ratio plan/réel
  "dpi": 300,              // convention PNG fournis
  "scale": 4.167,          // dpi/72 (non utilisé pour cm/px)
  "rotation_angle": 0,
  "page_width_pts", "page_height_pts",
  "page_width_px", "page_height_px",
  "total_cartouches",
  "cartouches": [
    {
      "number": "916",
      "center": {
        "number", "line1", "line2", "line3",
        "pixels_x", "pixels_y",
        "width_px", "height_px", "font_size"
      },
      "components": []
    }
  ]
}
```

Chaque `lineN` contient `{text, pixels_x, pixels_y, font_size}`. `line1.text` = code pièce (ex: "14"), `line2.text` = surface ("14.28 m2"), `line3.text` = numéro de pièce.

**Justification** : Aligne OLS sur le format produit par l'outil de preprocessing externe. Utiliser `dpi+plan_scale` plutôt que `scale` garantit une conversion correcte (scale=dpi/72 est un facteur interne au rendu PDF, pas un ratio géométrique).

**Impact** :
- `olm/ingestion/extract.py` : `extract_rooms_from_preprocessed()` refactorisée (helpers `_parse_plan_scale_ratio`, `_cm_per_px_from_metadata`, `_parse_surface_m2`)
- `docs/specs/PREPROCESSED_JSON_SPEC.md` : spec complète créée
- Validation : clé `cartouches`, liste, `center.pixels_x/y` obligatoires
- Bbox : carré centré sur seed, côté = √(surface_m2 × 10000) / cm_per_px
- Convention : PNG fournis en 300 DPI par défaut

---

## D-75 · Artefacts arc de porte dans PNG enhanced (TBD)

**Décision** : À définir après analyse — le preprocessing supprime les cartouches mais introduit des artefacts au niveau des arcs de porte (disparition partielle).

**Justification** : Comprendre la cause des artefacts pour adapter le post-traitement ou la stratégie de detection wall-tracing.

**Impact** : Tâche R-05 « Robustesse aux arcs de porte » intègre l'analyse de ces artefacts.

**Décision** : L'appel Tesseract dans `find_seeds_by_ocr` utilise systématiquement :
- `tessedit_char_whitelist` couvrant exactement les 3 types de tokens attendus dans les cartouches :
  - Code pièce : 2 chiffres + lettre optionnelle → `"14"`, `"14c"`, `"12d"`
  - Numéro de pièce : 1-3 chiffres, ou 2 chiffres + lettre, ou 1 chiffre + 2 lettres → `"916"`, `"12a"`, `"1AB"`
  - Surface : nombre décimal → `"14.28 m2"`
  - Whitelist résultante : `0123456789.,abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ ` (espace inclus pour `m2`)
- `load_system_dawg=0` + `load_freq_dawg=0` — désactivation explicite des dictionnaires anglais/fréquents. La whitelist seule est insuffisante quand des lettres sont présentes : Tesseract continue à biaiser les résultats vers des mots de dictionnaire.
- Upscale x2 (LANCZOS) avant OCR, coordonnées TSV divisées par 2 en sortie
- `--oem 3` explicite, `--psm 11` conservé

**Algorithme de matching room number** : les candidats sont triés par longueur décroissante puis distance croissante (priorité aux tokens longs). Cela évite qu'un token court comme `"2"` (extrait de `"m2"`) batte un vrai numéro `"916"` simplement parce qu'il est plus proche dans le cartouche.

**Justification** : La whitelist restreint l'espace de reconnaissance aux caractères effectivement présents dans les cartouches. La désactivation des dictionnaires supprime les corrections orthographiques parasites. L'upscale améliore la reconnaissance sur le texte de petite taille (10-20 px → 20-40 px), conforme aux recommandations Tesseract (≥ 300 DPI). Les regex `_RE_ROOM_CODE`, `_RE_ROOM_NUMBER`, `_RE_SURFACE` documentent les patterns attendus et servent à filtrer/classer les tokens en post-traitement.

**Impact** : 28 pièces correctement détectées sur `test_floorplan3.png`, numéros et surfaces exacts. Constantes `TESSERACT_UPSCALE`, `TESSERACT_CHAR_WHITELIST` et regex `_RE_*` définies au niveau module dans `test_comb.py`.

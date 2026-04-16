# CHANGELOG

Toutes les modifications notables de ce projet sont documentées ici.
Format basé sur [Keep a Changelog](https://keepachangelog.com/fr/1.0.0/).

---

## [Unreleased] — 2026-04-16 : D-87 solidification D-83

### Corrigé
- Overlay PNG décalé d'une demi-pièce pour les pièces avec corridor east/west (rotation 90°/270°) — ajout d'un translate compensatoire dans `editor.js`.
- `corridor_face` perdu après Save en mode Room Amend — propagation dans `enterRoomAmendMode()` et `fpRoomAmendments`.

### Ajouté
- Module Python `olm/core/canonical.py` : port de `canonicalize_room()` / `decanonicalize_room()` depuis JS.
- 19 tests pytest round-trip dans `olm/tests/test_canonical.py`.

### Amélioré (UX)
- Couleur labels dimensions : `--text-dim` #6e6a62 → #908a7e, `COLOR_RULER` → #b0a898, labels SVG utilisent la constante.
- Hauteur onglets principaux : padding 10px → 14px. Sous-onglets : 4px → 8px (zone cliquable élargie).
- Contraste onglet actif : border-bottom 3px accent, hover fond surface2.
- Croix fermeture Settings : padding élargi + flex center (zone cliquable alignée).
- Add room : prompt auto-incrémenté basé sur max ID numérique existant.
- Dézoom limité : clamp zoom min 0.5 (Review/Design), clamp viewBox max 2× plan (Import).

### Corrigé (bugs)
- Plan fantôme : canvas rvCanvas/fpCanvas vidés quand aucune room n'est chargée.
- Esc bbox editor Import : restaure la position ET désélectionne la pièce.
- Review après Save : render() masque state.rows en Review hors mode édition, empêche l'affichage résiduel de blocs Design.
- Synchro liste gauche : auto-scroll étendu à Import (était limité à Review).
- Warning sortie Adjust room : confirm() bloque le changement d'onglet si modifications non sauvegardées.
- Double-click Import → Review : dblclick délégué sur ingSvg (survit aux re-renders SVG).
- Room list Review : hauteur alignée sur Import (210px, min/max/resize).
- Labels dimensions : rectangle de fond sombre pour lisibilité sur overlay.
- Grille Design : labels "1m", "2m"… le long des bords de la pièce.
- UI 100% anglais : 5 chaînes françaises dans ingestion.js traduites.

### Fonctionnalité (D-89)
- **Sous-onglets Catalogue inline** : Card/Grid/Editor intégrés dans la tab-bar LAYOUT sur une seule ligne, apparition dynamique.

### Fonctionnalité (D-88)
- **Drawing scale** : paramètre explicite `drawing_scale` (format "1 : 100") dans Import + `render_dpi` dans Settings > Floorplan. Formule `cm_per_px = 2.54 × scale / dpi`. Si non renseigné, estimation inverse affichée en jaune. Recalcul live des dimensions sans re-import.

---

## [Unreleased] — Conception 2026-04-14 / 2026-04-15 : D-78 à D-85

### Décisions d'architecture (tracées dans Decisions.md)

- **D-85** — Auto-détection OCR / Preprocessed par fichier, mode invisible à l'UI. Suppression du sélecteur de mode global et du paramètre Settings associé. Règle : PNG seul → OCR, PNG + JSON dont mtime > PNG.mtime → Preprocessed, sinon fallback OCR. Dropdown Load en liste plate triée alphabétiquement (pas de sections, pas de badges). Confirmation navigateur avant extraction OCR ("No JSON file found — Processing with Optical Character Recognition..."). Paramètre `ingestion.plans_dir` exposé dans Settings pour pointer vers un dossier externe. Format JSON v2 (legacy) explicitement rejeté par le parser avec message d'erreur clair.
- **D-84** — JSON v3 simplifié + règle "docs = source unique de vérité". `PREPROCESSED_JSON_SPEC.md` réécrit : suppression de `plan_scale`, `dpi`, `all_text_blocks`, métadonnées typographiques et référentiel points. Aplatissement du cartouche en 3 champs plats, imbrication des `doors/openings/windows` dans chaque room. Schéma door scindé Input (`label_px`) vs Save (enrichi OLS). Bouton DEV "Export v3 JSON" (contour orange vif) implémenté côté frontend pour sérialiser l'état OCR dans ce format. Règle générale ajoutée dans `CLAUDE.md` : toute information utile à long terme vit dans `docs/` uniquement.
- **v3.1 du JSON spec (2026-04-15)** — affinage : split `seed_px` / `label_px` (arrays `[x, y]`) en champs scalaires `seed_x` / `seed_y` / `label_x` / `label_y`. Marquage explicite Required/Optional/Save-only sur chaque champ. Convention d'omission formalisée (champ non renseigné = absent du JSON). `rooms` devient un objet indexé par room_id. Ajout de `canonical_top_face` (D-83) et `north_angle_deg`. Suffixe `_enhanced` réservé — les PNG `<plan_id>_enhanced.png` sont groupés avec leur parent par `/api/plans`.

### Implémentations livrées (2026-04-15)

- Parser `extract_rooms_from_preprocessed` réécrit pour le format v3 : lit l'objet rooms indexé par id, déduit `cm_per_px` depuis les surfaces m² des pièces déjà bboxées, skippe le ray-cast si `bbox_px` présent. Rejette le format v2 legacy avec `ValueError` explicite.
- Route `GET /api/plans` : enrichie avec `effective_mode` et `has_enhanced`, groupement du suffixe `_enhanced`, lit `ingestion.plans_dir` depuis `config.json` via `_get_plans_dir()`.
- Routes `/api/import/ocr` et `/api/import/preprocessed` : acceptent un paramètre `plan_id` qui résout les chemins depuis `plans_dir` (plus besoin d'upload de fichier multipart).
- Frontend Load : suppression du dropdown mode, liste plate des plans, confirmation navigateur avant OCR, bouton DEV Export v3 JSON (orange vif), badge plan courant dans le header.
- Nav 2+2 avec onglets principaux Floorplan / Layout (fond jaune doré, coins arrondis, alignement baseline du label avec les sous-onglets) + contenus Import/Review et Design/Catalogue. Bouton Save dans le header.
- Bbox editor générique : ajout/déplacement/redimensionnement de pièce à la souris, flèches clavier pour déplacer, Delete pour supprimer, Escape pour restaurer la position de début de session.
- Add room manuel avec stub 300×400 cm placé au-dessus du plan, bouton "Add" inline.
- Règle `_enhanced` comme suffixe réservé documentée dans `PREPROCESSED_JSON_SPEC.md`.
- Dual-pass OCR Tesseract (PSM 11 + PSM 6) + clustering ancré sur les surfaces avec fenêtre adaptative `h_med * 7` vertical — élimine le matching greedy qui cassait sur cartouches partiellement lus.
- **D-83** — Orientation canonique des pièces en Review et Design : couloir en bas / fenêtres en haut, l'utilisateur est toujours positionné "en entrant par la porte". Rotation purement visuelle appliquée au groupe racine SVG via un helper `computeRoomViewTransform(room)`. Coordonnées internes inchangées. Aligne la vue sur le référentiel des patterns du catalogue.
- **D-82** — Clôture R-01 : `olm/README.md` promu en `README.md` racine (convention GitHub), `pyproject.toml` corrigé (`build-backend = "setuptools.build_meta"`, `readme = "README.md"`). `.gitignore` déjà conforme (exclusion `project/`, `docs/`, `solver_lab/`, `CLAUDE*.md`, `.claude/`).
- **D-78** — Navigation 3 onglets (Floor plan / Office layout / Export) + full round trip via clé `olm_state` dans le JSON v2. Remplace partiellement le workflow 5 étapes de D-68. Identification du plan par nom fichier PNG, politique de diff explicite (réhydratation / badge "Nouveau" / warning orphelines).
- **D-79** — Ray-casting context-aware en Mode Préprocessé : zones de transparence de porte via `doors[]` + règle d'arrêt sémantique sur les frontières blanc↔vert (couloir) et blanc↔bleu (extérieur). `RASTER_EXTRACTION_SPEC.md` §11bis ajoutée.
- **D-80** — Zones interdites à double origine : promotion automatique des petits artefacts en ingestion (`min_size_artifact_cm2` défaut 2500) pour les open space avec poteaux, + outil souris Review (Add / move / Delete, pas de redimensionnement souris — DSL = source de vérité).
- **D-81** — Cartouche OCR aligné sur 3 lignes (code / surface / id), alignement avec le format Mode Préprocessé. Suppression de N REEL / N THEO non exploitées et sources d'ambiguïté OCR. `INGESTION_HYPOTHESES.md` §H-09 mise à jour.

### Session 2026-04-15 (après-midi)

#### UX / Interface
- Fusion header + barre d'onglets en une seule ligne (table layout). Suppression du titre "Office Layout Studio".
- Onglets agrandis (+20%), espacement ajusté entre groupes et sous-onglets.
- Fond des sous-onglets inactifs assombri pour meilleure lisibilité.
- Description de l'onglet actif affichée à droite des onglets.
- Bouton Save masqué tant qu'aucun plan n'est chargé. Bouton DEV Export v3 supprimé (redondant avec Save).
- Boutons Close et Erase (All / Layout only) ajoutés dans le header. Erase ne ferme plus le plan.
- Zoom molette souris dans Import (centré sur curseur).
- Focus auto sur la bbox des pièces en mode Préprocessé à l'ouverture.
- Double-click sur une pièce dans Import → navigation vers Review avec focus.
- Enter valide la sélection bbox dans Import. Esc annule en mode Adjust room.
- Re-trigger du matching après ajout/suppression de pièce dans Import.
- Prompt dialog si ajout de pièce sans ID. Placeholder "Room ID" simplifié.
- Marge haute colonne gauche Import/Review. Renommage "Floor plan" → "Current floorplan".
- Debug log supprimé de Import.
- Colonne gauche Review redimensionnable (poignée + localStorage) — instructions IMPLEMENTER.

#### Backend / Pipeline
- Endpoint `/api/image` sécurisé : ne sert que depuis `olm_overlays` et `PLANS_DIR` (réalpath + guard).
- Choix plan base/enhanced selon contexte : plan de base en Import, enhanced en overlay Review/Match.
- `corridor_face` calculé en mode Préprocessé depuis `doors[0].face` (au lieu de `""` en dur).
- Détection couleurs de face (`_detect_face_colors`) : échantillonnage pixels au-delà de chaque face de bbox dans le PNG enhanced pour détecter vert (couloir) et bleu (extérieur).
- Paramètres `preprocessed_exterior_rgb` et `preprocessed_corridor_rgb` dans config.json.
- Outil CLI `olm/tools/colorize_enhanced.py` : flood fill extérieur (bleu) + couloirs (vert) avec dilatation des murs pour boucher les portes.

#### Settings
- Drawer Settings restructuré en 5 onglets : General, Floorplan, Layout, Catalogue, Export.
- Couleurs sémantiques (exterior RGB, corridor RGB) exposées dans Settings > Floorplan avec preview.

#### Corrections
- Fix crash `fpBtnExport` manquant (guard `if` ajouté).
- Fix crash `fpOverlayStatus` null (guard ajouté).
- Fix lignes blanches fantômes : portes avec coordonnées `undefined` ignorées, rect fond SVG ajouté.
- Fix grille 1m : lignes à x=0/y=0 ne sont plus privilégiées.
- Fix Close : dropdown plan reset à la position placeholder.

#### Architecture (D-86)
- **D-86** — Classification portes principales (couloir/vert) vs secondaires (entre bureaux). `corridor_face` = source de vérité pour l'orientation canonique. Rotation D-83 préparée (code posé puis désactivée en attente du PNG enhanced colorisé).

### Documentation

- `docs/TODO.md` : R-08 refondu (nav 3 onglets), R-11 nouveau (round trip), R-05 enrichi (validation Tesseract D-73, cartouche 3 lignes D-81, zones interdites D-80, paramétrage couleurs RGB sémantiques, révision logique fenêtres, générateur de plan de test)
- `docs/specs/RASTER_EXTRACTION_SPEC.md` : section 11bis ray-casting context-aware
- `docs/specs/PREPROCESSED_JSON_SPEC.md` : section 6bis exploitations futures (portes, couleurs, all_text_blocks)
- `docs/specs/INGESTION_HYPOTHESES.md` §H-09 : cartouche 3 lignes

---

## [Unreleased] — Format JSON preprocessé v2 (D-77) (2026-04-14)

### Modifié (breaking)
- **`extract_rooms_from_preprocessed()`** : migré vers la structure v2 :
  - Clé principale `cartouches` → `rooms`
  - Plus de wrapper `center` : `code_line1` / `surface_line2` / `id_line3` directement sur la room
  - `room_id` primaire depuis `id_line3.text`
  - Seed du cartouche calculé via nouveau helper `_room_center_from_lines()` (moyenne pixels_x des 3 lignes, pixels_y de surface_line2)
  - Support ROOT : `total_text_blocks`, `total_rooms`, `total_doors`, `all_text_blocks[]`, `doors[]`
  - `scale_factor` (renommage de `scale`, non utilisé pour cm/px)
- **`docs/specs/PREPROCESSED_JSON_SPEC.md`** : réécrite pour la v2 avec section historique des versions

### Ajouté
- **`_room_center_from_lines()`** (`olm/ingestion/extract.py`) : calcule le centre d'un cartouche depuis ses 3 lignes
- Portes (`doors[]`) loggées à l'import (non exploitées v1)

---

## [Unreleased] — Format JSON cartouches pour Mode Préprocessé (D-76) (2026-04-12)

### Ajouté
- **`docs/specs/PREPROCESSED_JSON_SPEC.md`** : spec complète du format JSON cartouches (métadonnées globales, structure cartouche/center/lineN, conversion cm_per_px)
- **Helpers** (`olm/ingestion/extract.py`) : `_parse_plan_scale_ratio()`, `_cm_per_px_from_metadata()`, `_parse_surface_m2()`

### Modifié
- **`extract_rooms_from_preprocessed()`** : parse la structure `cartouches` (au lieu de `rooms`). Extrait `room_id` depuis `cartouche.number`, seed depuis `center.pixels_x/y`, surface parsée depuis `line2.text`. Bbox carrée centrée sur seed, côté calculé via `cm_per_px = (2.54/dpi) × plan_scale_ratio`. DPI par défaut 300.

---

## [Unreleased] — Dual-mode ingestion : Mode OCR + Mode Préprocessé (2026-04-12)

### Ajouté
- **`IngestionMode` enum** (`olm/core/types.py`) : `OCR` et `PREPROCESSED`
- **`extract_rooms_from_preprocessed()`** (`olm/ingestion/extract.py`) : parse JSON préprocessé + valide les PNG enhanced/overlay, retourne la liste de dicts pièces
- **Route `/api/import/ocr`** (`app.py`) : wraps le pipeline OCR existant, champ `floorplan_image` + `scale_cm_per_px`
- **Route `/api/import/preprocessed`** (`app.py`) : reçoit JSON + PNG enhanced + PNG overlay, retourne les pièces
- **Route `/api/import/preprocessed/image`** (`app.py`) : sert le PNG enhanced temporaire vers le navigateur
- **Dropdown Input Mode** (`pattern_editor.html`) : sélecteur "OCR / Préprocessé" en haut du panel Import
- **Formulaire préprocessé** (`pattern_editor.html`) : upload JSON + PNG enhanced + PNG overlay
- **`renderImportPanel()`** (`ingestion.js`) : affichage conditionnel OCR vs Préprocessé
- **`extractRoomsPreprocessed()`** (`ingestion.js`) : appel `/api/import/preprocessed`, intégration pipeline floor_plan

---

## [Unreleased] — OCR Tesseract : whitelist typée + désactivation dictionnaires (2026-04-12)

### Amélioré
- **Whitelist Tesseract** (`test_comb.py`) : couvre exactement les 3 types de tokens attendus — codes pièce (`14`, `14c`), numéros de pièce (`916`, `12a`, `1AB`), surfaces (`14.28 m2`). Whitelist : `0-9 . , a-z A-Z espace`
- **Désactivation dictionnaires** : `load_system_dawg=0` + `load_freq_dawg=0` — sans cela, Tesseract biaie les tokens vers des mots anglais même avec une whitelist contenant des lettres
- **Regex de validation** : `_RE_ROOM_CODE`, `_RE_ROOM_NUMBER`, `_RE_SURFACE` définies au niveau module, utilisées pour filtrer et classer les tokens OCR
- **Algorithme de matching** : tri des candidats numéro de pièce par longueur décroissante puis distance croissante — évite que des tokens courts (`"2"` de `"m2"`) battent de vrais numéros (`"916"`) plus éloignés
- **Upscale x2 LANCZOS** + ajustement des coordonnées TSV (÷2), timeout 30 s

### Impact
- 28 pièces correctement détectées sur `test_floorplan3.png`, numéros et surfaces exacts

---

## [Unreleased] — Matching restauré, UX fixes, Design Layout OK (2026-04-07)

### Corrigé
- **Catalogue vide** : restauré 20 patterns depuis commit 53d75bc (standards AFNOR_ADVICE, GROUP, SITE). Était vidé lors de D-68 (séparation open source)
- **isReview undefined** : renderRoomElements() appelée sans paramètre `isReview` → fixé en détectant `svg.id === 'rvCanvas'` dans _renderImpl()
- **fpBtnLoadJson null** : addEventListener() sur élément supprimé → protégé avec null check
- **Arc de porte UX** : stroke-width 0.8 → 1.5, dasharray 3 2 → 6 3 (4 fichiers : ingestion.js, catalogue.js, editor.js, matching_viewer.html) pour aligner avec pointillé green "open bay"
- **Design Layout grille** : ajout fond opaque #1e1e1e (z=0.5) masquant grille sous blocs + zones circulation

### Impact
- Design layout fonctionne de nouveau (affiche candidats matching)
- Arc de porte cohérent visuellement dans toutes les vues
- Matching disponible sur toutes les pièces (grande/petite taille)

---

## [Unreleased] — Revue UX complète, rulers, overlay Review (2026-04-05)

### Ajouté
- **Design tokens CSS** : palette, typographie (fs-xs→fs-room), espacements (sp-xs→sp-page) dans `:root`, propagés dans tout le CSS
- **Classes utilitaires** : `.settings-grid`, `.settings-input`, `.btn-toolbar`, `.btn-cancel`, `.help-link`, `.hint-text`, `.svg-canvas`, `.edit-mode`
- **Fauteuil SVG redesign B1-3** : assise arrondie (rx proportionnel) + dossier arc courbe, proportionnel au SCALE
- **Rulers HTML fixes** : barres haut/bas/gauche/droite avec labels de graduation, créées dynamiquement via `ruler-box`, indépendantes du zoom et du pan
- **Polices constantes** : distances inter-blocs, dimensions pièce, grille, labels de postes — taille visuelle constante via `zf = 1/svgScale` (compensation viewBox/pixel)
- **Dirty tracking** : indicateur `.edit-mode` (liseré ambre) quand un pattern a des modifications non sauvegardées, bouton Cancel visible
- **Overlay raster dans Review rooms** : toggle + opacité synchronisés avec Design layout, auto-coché au chargement
- **Pan souris** sur les 3 canvas (éditeur, Design, Review) via `setupPan()`
- **Tooltip DSL layout** : syntaxe complète (blocs, gaps, rotations, offsets NS, sticks, multi-rangées), centré à l'écran, croix de fermeture, scrollbar
- **Zoom fit** adapté au ratio d'aspect du SVG (plus de letterboxing), marges augmentées

### Modifié
- Renommage UI : **Office Layout Studio** (titre + `<title>`)
- Harmonisation Adjust room / Amend layout : classe `.edit-mode` commune, Cancel/Save cohérents
- Amend layout : onglet Design reste actif (pas Edit catalogue), sous-onglets cachés, sélection/clavier fonctionnels
- Cancel en amend layout retourne vers Design (pas Review)
- Amend sans modification : pas d'amendment créé
- Edit catalogue : retour sur Card view (pas Pattern editor)
- Écran SVG décalé vers l'intérieur du bureau, fenêtre SVG affinée (stroke-width 1.5)
- Tab buttons sans border-bottom (ligne unique avec desc bar), desc bar en italique
- Nettoyage inline styles massif (settings inputs ×6, cancel buttons ×3, zoom buttons ×9, help links, SVG canvas)
- Bug fix : filtre standard dans Design layout (listener manquant)
- Bug fix : state périmé au toggle Grid/Circ dans Design layout (re-render via fpRenderSvg)
- Bug fix : grille étendue au-delà du viewBox pour survivre au pan

---

## [Unreleased] — R-08 navigation, bug fixes, convention desk (2026-04-05)

### Ajouté
- **R-08 Navigation** : 6 onglets principaux (①Import ②Review ③Merge ④Design ⑤Export + Edit catalogue) avec numéros d'étape en cercles, bandeau description dynamique, nom "Office Layout Matching" dans le header (D-68)
- **Catalogue** : 3 sous-onglets Card view / Grid view / Pattern editor (remplace le toggle Cards/Grid)
- **Merge placeholder** : onglet ③ avec message "coming soon"
- **Desk dynamique** : desk width/depth, door width, grid cell size depuis Settings propagés en temps réel au rendu SVG et aux blocs serveur
- TODO enrichi : R-08, R-09 (Identify merges), R-10 (splash screen), audit rotation patterns, test floor plan

### Corrigé
- Pan (Shift+drag) : pointeur décalé ~50px → pxToSvg compense le letter-boxing preserveAspectRatio
- Review rooms : navigation clavier flèches restaurée
- Zoom buttons : event object passé comme SVG element → wrappé dans closure
- Convention desk : DESK_W=180 (largeur), DESK_D=80 (profondeur) — perspective humaine (D-69)

### Modifié
- 14 fichiers modifiés, +350/-169 lignes
- Tous les sélecteurs programmatiques migrés (floorPlan→design, officeLayout→catalogue, etc.)
- Gardes canvas/clavier inversées : autorisent uniquement Catalogue > Editor
- setCatalogueView/catalogueViewMode supprimés

---

## [Unreleased] — Refactoring frontend : découplage des vues (2026-04-04)

### Modifié
- CSS externalisé : pattern_editor.html inline `<style>` → olm/static/style.css (787 lignes)
- JS découpé en modules : catalogue.js (795 l.), shared.js (628 l.), config.js (211 l.), floor_plan.js (719 l.)
- 3 canvas SVG séparés : #canvas (éditeur), #fpCanvas (matching), #rvCanvas (review) — plus de déplacement DOM
- render(), zoomFit(), updateViewBox(), zoomIn(), zoomOut() paramétrés avec targetSvg optionnel
- Classe section-title unifiée (fp-sidebar-title supprimé), styles inline nettoyés, hr.sep supprimés
- Titres Review : "Review rooms" (pluriel), nom de pièce centré dans la nav bar
- Boutons Adjust room : Apply avant Syntax help, Save room/Cancel dans la nav bar avec liseré ambre
- Annulation automatique du mode amend quand on navigue hors de l'éditeur
- JS entièrement externalisé : editor.js (1562 l.), init.js (501 l.) — pattern_editor.html réduit de 5719 à 483 lignes, zéro script inline

### Supprimé
- moveCanvasToFloorPlan(), moveCanvasToReview(), moveCanvasToEditor(), updateCanvasLocation(), getActiveSubtab()
- _canvasInEditor guard, hr.sep (HTML + CSS), fp-sidebar-title (CSS), canvasDims (masqué)

### Corrigé
- updateViewBox() ne propageait pas le SVG cible dans _renderImpl → viewBox appliqué sur le mauvais canvas
- rvUpdateRoomInfo non exporté sur window → erreur "not defined" après extraction IIFE
- preserveAspectRatio="none" sur matrixSvg → patterns déformés en vue grille (corrigé en xMidYMid meet)

---

## [Unreleased] — Amend workflow, overlay, settings, exclusions périphériques (2026-04-03)

### Ajouté
- **Amend layout** : édition de solution en place pour une pièce, sauvegarde locale, Discard amendment (D-63)
- **Adjust room** : édition géométrie de pièce, re-matching automatique, pièces amendées marquées "(amended)" (D-63)
- **Overlay raster** : chargement image plan d'étage dans Floor Plan / Input, affichage en filigrane avec checkbox + opacité, actif par défaut en mode Adjust room (D-64)
- **Settings** : onglet Office Layout / Settings — paramètres d'espacement éditables par standard, persistés en JSON, prise en compte immédiate dans le rendu (D-65)
- **Exclusions périphériques** : une exclusion couvrant tout un côté réduit les dimensions effectives pour le matching (D-62)
- `specs/VISION_LLM_IO_SPEC.md` : spécification entrées/sorties pour le LLM Vision d'ingestion des plans (D-66)
- `generate_test_floor_plan.py` + `test_floor_plan.png` : raster de test 7 pièces alignées
- Aide DSL : tooltip hover avec exemple annoté ligne par ligne
- Zones de recul/circulation visibles en mode circulation (plus masquées)
- Auto-chargement `test_rooms.json` + `test_floor_plan.png` au démarrage (dev)
- Route `/specs/<filename>` et `/test_floor_plan.png` dans Flask

### Modifié
- Navigation : 2 onglets principaux (Floor Plan / Office Layout) + sous-onglets, onglet actif en fond accent (D-61)
- Interface traduite en anglais
- Boutons Floor Plan : Adjust room | Edit pattern, Amend layout, Discard amendment
- Boutons éditeur réordonnés : New, Load, Save, Duplicate, Delete + Cancel (mode amend)
- Nom du pattern centré au-dessus du canvas dans la colonne éditeur
- Liste Load triée comme le catalogue (depth asc, width asc, name)
- Sélection candidat : liseré ambre inset (compatible avec liseré vert "best")
- Load file à gauche dans Floor Plan / Input
- `spacing_config.py` : configs mutables, persistence `spacing_overrides.json`, `update_config()`, `reset_config()`
- `catalogue_matcher.py` : `effective_dimensions()` pour exclusions périphériques
- Suppression des fallbacks hardcodés (|| 90, || 140, || 160) dans le JS — tout via `CURRENT_SPACING`
- Deep copy des candidats dans `fpRenderSvg` et `switchToEditorWithPattern` (évite mutation par référence)

---

## [Unreleased] — Pipeline matching, éditeur, floor plan (2026-04-01)

### Ajouté
- `catalogue_matcher.py` : pipeline matching 7 étapes (D-54) — sélection Pareto, miroir E-O, calage sticks + homothétie, suppression unitaire postes, scoring circulation, sélection meilleur, rectangle résiduel
- `coverage_analysis.py` : analyse de couverture catalogue × pièces (COVERED/NO_FIT/LOW_DENSITY/LOW_SCORE), backlog d'enrichissement (D-51)
- `specs/CATALOGUE_STRATEGY.md` : stratégie peuplement catalogue du bas vers le haut (D-55)
- Convention de nommage automatique des patterns D-50 : `{W}x{D}_{STD}[_{k}O]_{n}` avec compactage
- Import/export catalogue JSON (D-53) : endpoints API + boutons interface
- Onglet Floor Plan dans `pattern_editor.html` : navigation prev/next, matching, candidats, export résultats, bouton Editer → éditeur
- Multi-portes : clustering cellules DOOR, BFS par cluster, meilleur chemin par poste
- Accès par poste individuel pour blocs ortho (BLOCK_2_ORTHO_R/L) dans la circulation
- DSL pattern v1.3 : gap initial autorisé, blocs ORTHO dans la grammaire
- Endpoint `/api/floor-plan/match` : matching catalogue × pièces avec positions desks
- Endpoint `/api/coverage` : analyse de couverture + backlog
- Endpoint `/api/catalogue/export` et `/api/catalogue/import`
- `test_rooms.json` : jeu de 7 pièces de test (250×350 à 1400×950)
- Decisions D-50 à D-55

### Modifié
- `pattern_server.py` : nommage auto au save, compactage après suppression, APIs import/export/coverage/floor-plan
- `pattern_editor.html` : 3 onglets (Catalogue/Éditeur/Floor Plan), boutons import/export
- `pattern_dsl.py` : gap avant premier bloc accepté (distance mur ouest)
- `PATTERN_DSL_SPEC.md` v1.3 : blocs ORTHO_R/L, gap initial, exemples enrichis
- `circulation_analysis.py` : accès ortho par poste, multi-portes via clustering
- `static_matcher.py` : BLOCK_2_ORTHO_R/L ajoutés dans `_BLOCKS`
- `catalogue/patterns.json` : noms migrés vers convention D-50
- `adapt_to_room()` : remplace la géométrie pièce par celle de la pièce cible
- `docs/SDS.md` : réécriture complète v3.0

---

## [Unreleased] — Audit documentation + nouveau workflow (2026-03-28)

### Ajouté
- D-26 : changement de repère NW→SE (origine Nord-Ouest, y→Sud)
- Workflow dual-instance ARCHITECT (Opus/VSCode) + IMPLEMENTER (Sonnet/terminal)
- `CLAUDE_IMPLEMENTER.md` : instructions de rôle pour l'instance terminal
- `solver_lab/TODO.md` : tâches + idées du week-end (vocabulaire, fonctions de base, standards)

### Modifié
- `CLAUDE.md` : section dual-instance, fichiers de référence solver_lab, règle Decisions.md auto, format prompts IMPLEMENTER
- `solver_lab/Decisions.md` : D-05 corrigée (dimensions post-D-25), D-11/D-12 marquées supersédées, D-18 marquée supprimée, D-21→D-25 format normalisé, D-25 mis à jour repère NW, D-26 ajoutée
- `solver_lab/specs/BLOCS_SPEC.md` : réécriture complète alignée D-25/D-26
- `solver_lab/specs/CONSTRAINTS.md` : §Stratégie mis à jour pour pipeline catalogue D-14
- `docs/SDS.md` : réécriture complète v2.0 (architecture actuelle, repère D-26)
- `solver_lab/solver/model.py` : commentaire y_m aligné D-26

### Supprimé
- `docs/BROWSER_CONTEXT.md` : obsolète (accès fichiers direct dans VSCode)
- `solver_lab/specs/BROWSER_CONTEXT.md` : idem, contenu migré dans TODO.md
- `AGENT.md` : fusionné dans CLAUDE.md

### Connu
- 10 tests en échec sur 501 (debt_model, matcher) — à diagnostiquer en session de travail

---

## [Unreleased] — solver_lab : refonte placement simultané postes + corridors (2026-03-17)

### Ajouté
- `CellType.CORRIDOR = 4` dans `model.py`
- `CorridorSpec` dataclass dans `model.py`
- `SolverParams.corridor_min_length_m` (défaut 1,50 m) et `corridor_min_width_m` (défaut 0,80 m)
- `ScoringWeights.distance_to_door` (défaut 30) — poids du hint pré-résolution
- `PlacementResult.corridors` : liste `[(x_m, y_m, w_m, d_m)]` des corridors placés
- `BlockShape.is_corridor` : flag pour distinguer postes et corridors
- `_build_corridor_catalogue(params)` : 12 blocs corridor (6 longueurs × 2 orientations)
- C-1 non-chevauchement global postes ∪ corridors dans `solve()`
- C-2 accessibilité côté chaise : chaque poste actif adjacent à au moins un corridor actif
- C-3 connexité corridors via flux CP-SAT : `f_ij ∈ [0, N]` + `door_source_j` pour corridors porte-adjacents
- Objectif : `nb_postes × 1000 − hint_distance_porte` (hint euclidien, max ≈ 220 ≪ 1 000)
- Métriques `nb_corridors` et `avg_distance_to_door_m` (BFS sur FREE + CORRIDOR post-résolution)
- Rendu corridor en bleu dans le SVG HTML et en `'-'` dans le plan ASCII
- Décision D-13 dans `solver_lab/Decisions.md`

### Modifié
- `build_grid()` : signature étendue pour recevoir candidats postes + corridors séparément ; marque CORRIDOR avant FOOTPRINT
- `solve()` : résolution unique (plus de boucle de coupes), budget temps partagé pour la résolution unique
- `run.py` : affichage des nouvelles métriques, chargement des nouveaux paramètres depuis JSON scénario

### Supprimé
- Boucle de coupes de connectivité (D-12) : remplacée par C-3 flux CP-SAT (D-13)
- `_find_connectivity_cuts()` supprimée de `cpsat_solver.py`

---

## [Unreleased] — Phase 0 : Setup

### Ajouté
- Structure complète du projet
- `CLAUDE.md` — contexte projet, workflow, conventions de code
- `docs/PROJECT_CHARTER.md` — vision, périmètre, jalons
- `docs/SRS.md` — exigences fonctionnelles et non-fonctionnelles (EF-01 à EF-09)
- `docs/SDS.md` — architecture en modules, structures de données, interfaces
- `docs/TEST_PLAN.md` — stratégie de test, 30+ cas de test, fixtures attendues
- `pyproject.toml` — dépendances (Pillow, ReportLab, pytest)
- `.gitignore` — cache OLO, Python, IDE
- Arborescence `src/olo/` avec sous-packages (models, ingestion, geometry, placement, rendering)
- Arborescence `tests/fixtures/` (plans, json, expected_outputs)

---

<!-- Template pour les prochaines phases :

## [0.x.0] — Phase N — Nom
### Ajouté
- ...
### Modifié
- ...
### Testé
- `tests/test_xxx.py` : couverture XX %

-->

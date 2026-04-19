# TODO — OLM (Office Layout Matching)

Dernière mise à jour : 2026-04-17

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
- [ ] **Relance analyse pièce (Room)** : bouton pour relancer l'identification automatique des fenêtres, portes et ouvertures sur la pièce courante. Permet de placer d'abord les zones interdites/transparentes, puis de relancer l'analyse qui en tiendra compte.
- [ ] **Préserver les modifications manuelles** : lorsque l'utilisateur a redéfini manuellement la taille ou les contours d'une pièce, la relance de l'analyse automatique ne doit pas remettre en cause ces modifications. Les données manuelles ont priorité sur la détection auto.
- [ ] **Bouton Close** : ferme le projet courant. Si des modifications non sauvegardées existent, émettre un warning de confirmation avant de fermer.
- [ ] **Bouton Erase** avec deux options :
  - **All** : supprime toutes les données chargées (floorplan + layouts)
  - **Layout only** : supprime uniquement les descriptions de layout (bureaux/postes) mais conserve les amendements éventuels du floorplan (bbox, ouvertures, zones interdites). Nettoie le JSON des informations de layout associées.

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

- [ ] **Fine-tuning taille éléments graphiques** : ajuster les épaisseurs de traits (murs, fenêtres, portes, arcs), diamètre des ronds de grille, taille des poignées/badges pour un rendu visuellement agréable à tous les niveaux de zoom. Actuellement : non-scaling-stroke appliqué partout + cap sur les dots grille à 2 px.
- [ ] **Total area en m² non rafraîchi au changement d'échelle** : quand l'utilisateur modifie l'échelle (drawing_scale), le total area affiché reste sur l'ancienne valeur. À relier au recompute scale.
- [ ] **Édition contours au niveau Room** : ajouter la capacité de modifier les contours de la pièce dans Room (même outil que l'édition bbox dans Floor)

- [ ] **Bug position pièce 305 dans Office** : la pièce 305 est positionnée en (0,0) dans Office alors qu'elle est correctement placée dans Floor et Room. Semble arriver lorsqu'il y a un match automatique.
- [ ] **Bug orientation pièce 922** : la pièce 922 (`canonical_top_face: "west"`) est positionnée comme si elle était à l'est alors qu'elle est au nord. Vérifier la logique de rotation canonique pour les pièces en orientation non standard.
- [ ] Bug : Design Layout ne rote pas correctement les patterns selon l'orientation de la porte. Si la porte est en haut, les patterns devraient être rotatés mais ils conservent leur orientation par défaut (bureau sur la porte). À auditer dans le pipeline matching + rendu (fpCanvas).
- [ ] **Rendu homogène Import/Review/Design** : utiliser le même rendu détaillé (arcs de porte, fenêtres épaisses, ouvertures) dans Import que dans Review/Design. Niveau de détail adaptatif selon le zoom : détails complets quand on zoome sur une pièce, traits simplifiés quand on voit tout le plan. Adapter l'épaisseur des traits au niveau de zoom pour rester lisible à toutes les échelles.

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


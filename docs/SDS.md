# SDS.md — Software Design Specification

**Projet** : Office Layout Optimizer (OLO)
**Version** : 3.0
**Date** : 2026-04-01
**Statut** : Prototype opérationnel — aligné avec Decisions.md D-01 à D-55

---

## 1. Vue d'ensemble

OLO est une application Python locale d'aide à l'aménagement de bureaux. Le système prend des descriptions de pièces (JSON) et un catalogue de patterns d'aménagement, et produit pour chaque pièce la meilleure proposition d'aménagement par standard normatif, avec métriques et scores.

L'architecture comporte deux sous-systèmes :
- **`src/olo/`** — Application principale (ingestion, rendu PDF, CLI) — stubs
- **`solver_lab/`** — Sous-projet opérationnel : catalogue de patterns, matching, éditeur interactif, analyse de couverture

---

## 2. Repère de coordonnées (D-26)

| Propriété | Valeur |
|---|---|
| Origine (0,0) | Coin **Nord-Ouest** |
| x positif | vers Est |
| y positif | vers Sud |
| Convention grille | row 0 = Nord (haut), col 0 = Ouest (gauche) |

Cohérent avec numpy/images. Fenêtres au nord, portes au sud (convention par défaut).

---

## 3. Architecture — solver_lab

### 3a. Pipeline principal (D-54)

```
                   Création manuelle (éditeur)
                   Stratégie bas→haut (D-55)
                          │
                          ▼
┌─────────────────────────────────────────┐
│           Catalogue (patterns.json)      │
│  Format : {W}x{D}_{STD}[_{k}O]_{n}     │ ← Nommage auto D-50
│  Import/Export JSON (D-53)              │
└─────────────────────┬───────────────────┘
                      │
          pour chaque pièce × 3 standards
                      │
                      ▼
┌─────────────────────────────────────────┐
│       catalogue_matcher.py (D-54)        │
│                                          │
│  1. Sélection : emprise ≤ pièce         │
│     Front de Pareto (W, D)              │
│  2. Miroir E-O : variantes             │
│  3. Calage sticks + homothétie          │
│  4. Suppression unitaire de postes      │
│     (intersection zones interdites)     │
│  5. Scoring : circulation + m²/poste    │
│  6. Sélection meilleur par standard     │
│  7. Rectangle vide résiduel (m²)        │
└─────────────────────┬───────────────────┘
                      │
          ┌───────────┼───────────┐
          ▼           ▼           ▼
     AFNOR_ADVICE   GROUP       SITE
     (meilleur)    (meilleur)  (meilleur)
          │           │           │
          └───────────┼───────────┘
                      ▼
┌─────────────────────────────────────────┐
│       coverage_analysis.py (D-51)        │
│  Rapport : COVERED / NO_FIT /           │
│    LOW_DENSITY / LOW_SCORE              │
│  Backlog : patterns à créer             │
└─────────────────────────────────────────┘
```

### 3b. Interface web (Flask)

Deux serveurs :
- **pattern_server.py** (port 5051) : éditeur de patterns + floor plan viewer + APIs
- **server.py** (port 5050) : studio de solve CP-SAT (indépendant)

Interface HTML (`pattern_editor.html`) avec 2 onglets principaux (D-61) :

| Onglet principal | Sous-onglets | Fonctionnalité |
|---|---|---|
| **Floor Plan** | Input | Saisie DSL pièce, import JSON |
| | Matching | Canvas de rendu, matching catalogue × pièce, candidats |
| | Output | Export résultats |
| **Office Layout** | Catalogue | Vue cartes + grille matricielle, filtres, import/export |
| | Editor | Placement de blocs, DSL pattern, scoring, circulation |

Contrôles de l'éditeur (standard, New/Save/Load/Duplicate/Delete) dans la barre de sous-onglets Office Layout. Le canvas est partagé entre l'onglet Editor et l'onglet Floor Plan > Matching selon le contexte.

### 3c. Structure des fichiers

```
solver_lab/
├── specs/
│   ├── CONSTRAINTS.md          # Contraintes normatives (PS/ES/MO/SV/SS/SE/IN)
│   ├── BLOCS_SPEC.md           # 8 blocs canoniques (D-25/D-26)
│   ├── PATTERN_DSL_SPEC.md     # DSL texte ↔ JSON v1.3 (D-29/D-38)
│   ├── ROOM_DSL_SPEC.md        # DSL description de pièce (D-44)
│   └── CATALOGUE_STRATEGY.md   # Stratégie peuplement catalogue (D-55)
├── Decisions.md                # D-01 à D-55
├── TODO.md                     # Tâches et prochaines étapes
│
│  -- Modules principaux --
├── pattern_generator.py        # Blocs canoniques, compositions, rotations/miroirs
├── pattern_dsl.py              # Bijection DSL texte ↔ JSON
├── room_model.py               # RoomSpec, FloorPlan, WindowSpec, OpeningSpec
├── room_dsl.py                 # DSL description de pièce
├── spacing_config.py           # 3 configs d'espacement (AFNOR/GROUP/SITE)
├── catalogue_matcher.py        # Pipeline matching 7 étapes (D-54)
├── coverage_analysis.py        # Analyse de couverture + backlog (D-51)
├── circulation_analysis.py     # Grille, Dijkstra 8-connexe, chemins, largeurs
├── matching_config.py          # Paramètres grille (GRID_CELL_CM) et seuils
│
│  -- Données --
├── catalogue/
│   └── patterns.json           # Catalogue de patterns (nommage D-50)
├── test_rooms.json             # Jeu de pièces de test
│
│  -- Interface web --
├── pattern_server.py           # API Flask éditeur (port 5051)
├── pattern_editor.html         # Interface 3 onglets
├── static/
│   ├── block_constants.js
│   ├── block_geometry.js
│   └── block_svg.js
│
│  -- Studio solve (indépendant) --
├── server.py                   # API Flask studio (port 5050)
├── solver/
│   ├── model.py                # Dataclasses (Room, CellType, etc.)
│   ├── cpsat_solver.py         # Solveur OR-Tools CP-SAT
│   ├── circulation.py          # Analyse circulation studio
│   ├── config_dsl.py           # DSL heuristique studio
│   ├── scoring.py              # Scores de confort
│   └── election.py             # Élection candidats
│
│  -- Ancien code (référence, abandonné D-35) --
├── matcher.py
├── debt_model.py
├── static_matcher.py
│
└── tests/
```

---

## 4. Modèle de données

### 4a. Pièce (`room_model.py`)

```python
@dataclass
class RoomSpec:
    width_cm: int               # dimension ouest→est
    depth_cm: int               # dimension nord→sud
    windows: list[WindowSpec]
    openings: list[OpeningSpec]  # portes battantes ou baies
    exclusion_zones: list[ExclusionZone]
    name: str                   # ex. "B.4.12", "98K"

@dataclass
class FloorPlan:
    rooms: list[RoomSpec]
    building_angle_deg: float
    scale_cm_per_px: float
```

### 4b. Blocs et patterns (`pattern_generator.py`)

8 blocs canoniques : BLOCK_1, BLOCK_2_FACE, BLOCK_2_COTE, BLOCK_3_COTE, BLOCK_4_FACE, BLOCK_6_FACE, BLOCK_2_ORTHO_R, BLOCK_2_ORTHO_L.

```python
@dataclass
class Block:
    name: str
    eo_cm: int              # dimension physique Est-Ouest
    ns_cm: int              # dimension physique Nord-Sud
    n_desks: int
    faces: FaceCandidates   # zones fixe + circulation par face
    symmetric_180: bool
    derogatory: bool        # True = BLOCK_6_FACE (hors AFNOR ES-10)
```

Patterns JSON en catalogue (`patterns.json`) :
```json
{
  "name": "310x480_SITE_1",
  "rows": [{"blocks": [{"type": "BLOCK_2_ORTHO_R", "orientation": 0,
             "gap_cm": 130, "offset_ns_cm": 100, "sticks": ["E"]}]}],
  "row_gaps_cm": [],
  "room_width_cm": 310, "room_depth_cm": 480,
  "standard": "SITE",
  "room_windows": [...], "room_openings": [...], "room_exclusions": []
}
```

### 4c. Standards d'espacement (`spacing_config.py`)

3 configs : AFNOR_ADVICE, GROUP, SITE. Chacune définit :

| Code | Description | AFNOR | GROUP | SITE |
|---|---|---|---|---|
| ES-01 | Débattement chaise | 70 | 70 | 70 |
| ES-04 | Passage derrière 1 rangée | 160 | 120 | 100 |
| ES-06 | Passage inter-blocs | 90 | 90 | 80 |
| ES-08 | Zone libre porte | 180 | 180 | 120 |
| ES-09 | Distance table→mur | 20 | 10 | 0 |
| ES-10 | Taille max bloc | 4 | 6 | 6 |

(Toutes les valeurs en cm, sauf ES-10 en postes)

### 4d. Matching (`catalogue_matcher.py`)

```python
@dataclass
class PatternCandidate:
    pattern: dict               # JSON brut
    name: str
    room_width_cm: int
    room_depth_cm: int
    standard: str
    n_desks: int

@dataclass
class MatchScore:
    pattern_name: str
    standard: str
    n_desks: int
    m2_per_desk: float
    circulation_grade: str      # A-F
    connectivity_pct: float
    min_passage_cm: float
    worst_detour: float
    largest_free_rect_m2: float
    adapted_pattern: dict       # pattern avec gaps ajustés

@dataclass
class MatchingResult:
    room: RoomSpec
    by_standard: dict[str, MatchScore | None]
    all_scores: list[MatchScore]
```

### 4e. Couverture (`coverage_analysis.py`)

```python
class CoverageStatus(Enum):
    COVERED      # Pattern trouvé, scores acceptables
    NO_FIT       # Aucun pattern ne rentre
    LOW_DENSITY  # m²/poste > 15 (pièce sous-exploitée)
    LOW_SCORE    # Circulation grade < C
```

---

## 5. Pipeline de matching — détail des 7 étapes (D-54)

### Étape 1 — Sélection + front de Pareto

Filtre : `pattern.room_width_cm ≤ room.width_cm` ET `pattern.room_depth_cm ≤ room.depth_cm`. Parmi les patterns qui rentrent, extraction du front de Pareto : un pattern dominé en largeur ET profondeur par un autre est exclu.

### Étape 2 — Miroir Est-Ouest

Pour chaque candidat, génération d'une variante miroir :
- Ordre des blocs inversé par rangée, gaps recalculés
- Types ortho : BLOCK_2_ORTHO_R ↔ BLOCK_2_ORTHO_L
- Sticks : E ↔ O
- Ouvertures : offsets miroir, hinge_side inversé

### Étape 3 — Calage sticks + homothétie

- Blocs stick O : position fixe (distance au mur ouest préservée)
- Blocs stick E : décalés de `dw = target_width - orig_width`
- Blocs sans stick EO : interpolation linéaire entre ancres
- Dimension NS : distribution proportionnelle dans les row_gaps
- Géométrie pièce (fenêtres, ouvertures, exclusions) remplacée par celle de la pièce cible

### Étape 4 — Suppression unitaire de postes

Chaque poste individuel dont le rectangle intersecte une zone d'exclusion ou dépasse de la pièce est supprimé. Le bloc entier n'est pas retiré.

### Étape 5 — Scoring

- Circulation : `circulation_analysis.analyse()` avec Dijkstra 8-connexe pondéré
- Multi-portes : clustering des cellules DOOR, BFS par cluster, meilleur chemin par poste
- Blocs ortho : accès par poste individuel (pas par face de bloc)
- m²/poste : surface brute / nombre de postes restants

### Étape 6 — Sélection du meilleur

Tri lexicographique : n_desks max → grade circulation min → m²/poste min.

### Étape 7 — Rectangle vide résiduel

Algorithme histogramme maximal (O(rows×cols)) sur grille 10 cm. Surface en m² du plus grand rectangle libre après aménagement.

---

## 6. Convention de nommage des patterns (D-50)

Format : `{W}x{D}_{STANDARD}[_{k}O]_{n}`

| Composant | Description |
|---|---|
| `{W}x{D}` | Dimensions pièce en cm |
| `{STANDARD}` | AFNOR, GROUP ou SITE |
| `{k}O` | Nombre d'ouvertures si ≥ 2 (omis pour 1) |
| `{n}` | Incrément auto-compacté dans le groupe |

Compactage : à chaque sauvegarde/suppression, les incréments sont renumérotés 1, 2, 3… sans trous.

---

## 7. APIs Flask (`pattern_server.py`, port 5051)

| Endpoint | Méthode | Description |
|---|---|---|
| `/api/patterns` | GET | Liste tous les patterns |
| `/api/patterns` | POST | Crée/met à jour un pattern (nommage auto) |
| `/api/patterns/<name>` | GET | Retourne un pattern par nom |
| `/api/patterns/<name>` | DELETE | Supprime + compacte |
| `/api/patterns/<name>/duplicate` | POST | Duplique un pattern |
| `/api/blocks` | GET | Définitions blocs par standard |
| `/api/spacing` | GET | Configs d'espacement |
| `/api/dsl/parse` | POST | Parse DSL texte → JSON |
| `/api/dsl/export` | POST | Export JSON → DSL texte |
| `/api/room-dsl/parse` | POST | Parse DSL pièce → JSON |
| `/api/catalogue/export` | GET | Téléchargement catalogue JSON |
| `/api/catalogue/import` | POST | Import avec merge (D-53) |
| `/api/floor-plan/match` | POST | Matching catalogue × pièces |
| `/api/coverage` | POST | Analyse de couverture + backlog |

---

## 8. Constantes dimensionnelles (D-25)

| Symbole | Constante | Valeur | Source |
|---|---|---|---|
| W | `DESK_W_CM` | 80 cm | AFNOR NF X35-102 |
| D | `DESK_D_CM` | 180 cm | AFNOR NF X35-102 |
| CHR | `CHAIR_CLEARANCE_CM` | 70 cm | ES-01 |
| PAS | `PASSAGE_CM` | 90 cm | ES-06 |
| — | `GRID_CELL_CM` | 10 cm | D-03 |

---

## 9. Moteur d'optimisation (D-01)

**OR-Tools CP-SAT est le seul moteur d'optimisation autorisé.** Aucune logique de résolution maison (BFS, DFS, backtracking, greedy, recuit simulé) n'est permise.

CP-SAT intervient dans le studio de solve (`server.py`) pour le placement complémentaire sur zones résiduelles après matching par le catalogue. Le pipeline principal (`catalogue_matcher.py`) est déterministe et n'utilise pas CP-SAT.

---

## 10. Décisions de conception

Maintenues dans `solver_lab/Decisions.md` (D-01 à D-55). Décisions clés :

| ID | Décision | Date |
|---|---|---|
| D-01 | OR-Tools CP-SAT seul moteur autorisé | 2026-03-17 |
| D-03 | Grille 10 cm/cellule | 2026-03-17 |
| D-25 | Langage formel blocs/patterns | 2026-03-27 |
| D-26 | Repère NW→SE | 2026-03-28 |
| D-35 | Pivot pattern=pièce+standard | 2026-04-01 |
| D-44 | DSL description de pièce | 2026-04-01 |
| D-50 | Convention de nommage des patterns | 2026-04-01 |
| D-51 | Boucle retour matching → catalogue | 2026-04-01 |
| D-52 | Floor plan viewer : onglets intégrés | 2026-04-01 |
| D-61 | Navigation 2 onglets principaux (Floor Plan / Office Layout) + sous-onglets | 2026-04-03 |
| D-53 | Import/export catalogue | 2026-04-01 |
| D-54 | Pipeline matching 7 étapes | 2026-04-01 |
| D-55 | Stratégie peuplement catalogue bas→haut | 2026-04-01 |

---

## 11. Conventions de code

- PEP 8 strict, 100 caractères max par ligne
- Python 3.10+, annotations de type sur toutes les fonctions publiques
- Dataclasses pour toutes les entités métier
- Docstrings Google style sur toutes les fonctions publiques
- Constantes AFNOR nommées (jamais de magic numbers)
- `logging` uniquement (jamais `print()` hors de `main.py` / `server.py`)

# SPEC — Modèle de dette de circulation (`debt_model.py`)

**Fichier cible** : `solver_lab/debt_model.py`  
**Dépendances** : `pattern_generator.py`, `circulation.py`, `solver/model.py`  
**Tests** : `solver_lab/tests/test_debt_model.py`

---

## 1. Vue d'ensemble

Le modèle de dette prend un `Pattern` ou `DoubleRowPattern` et une pièce cible
`(room_eo_cm, room_ns_cm)`, et retourne un `DebtResult` indiquant si le pattern
est valide pour cette pièce, avec les dimensions compactées après résolution.

Pipeline :

```
pattern + room_dims
    │
    ▼
Phase 1 — Critère d'entrée
    emprise minimale ≤ room_dims ? → rejeté si non
    │
    ▼
Phase 2a — Rasterisation synthétique
    pattern_to_grid() → np.ndarray (grille avec DOOR fictive)
    │
    ▼
Phase 2b — Analyse de circulation
    analyse_circulation() → CirculationReport
    zones candidates actives identifiées
    │
    ▼
Phase 2c — Compaction
    zones candidates inutilisées supprimées
    blocs resserrés au minimum normé
    espace libre résiduel calculé
    │
    ▼
Phase 2d — Placement complémentaire (optionnel, stub)
    si espace libre ≥ emprise minimale d'un bloc → tentative d'ajout
    │
    ▼
DebtResult
```

---

## 2. Dataclasses

```python
@dataclass
class RoomDims:
    eo_cm: int
    ns_cm: int


@dataclass
class CompactedLayout:
    """Pattern après résolution de la dette.

    Attributes:
        eo_cm: Dimension EO compactée (physique + non-superposables actifs).
        ns_cm: Dimension NS compactée.
        free_eo_cm: Espace libre EO résiduel (room_eo_cm - eo_cm).
        free_ns_cm: Espace libre NS résiduel (room_ns_cm - ns_cm).
        west_zone_cm: Zone active côté ouest (0 si supprimée).
        east_zone_cm: Zone active côté est (0 si supprimée).
        north_zone_cm: Zone active côté nord (0 si supprimée).
        south_zone_cm: Zone active côté sud (0 si supprimée).
    """
    eo_cm: int
    ns_cm: int
    free_eo_cm: int
    free_ns_cm: int
    west_zone_cm: int
    east_zone_cm: int
    north_zone_cm: int
    south_zone_cm: int


@dataclass
class DebtResult:
    """Résultat du modèle de dette pour un pattern dans une pièce.

    Attributes:
        valid: True si le pattern est placeable dans la pièce.
        rejection_reason: Message si valid=False, None sinon.
        compacted: Layout compacté si valid=True, None sinon.
        circulation_report: CirculationReport de la Phase 2a.
        pattern_name: Nom du pattern source.
    """
    valid: bool
    rejection_reason: str | None
    compacted: CompactedLayout | None
    circulation_report: CirculationReport | None
    pattern_name: str
```

---

## 3. Constantes

```python
# Grille synthétique : résolution 10 cm/cellule
CELL_CM = 10

# DOOR fictive : ligne de cellules au bord sud, largeur 90 cm centré
DOOR_WIDTH_CM = 90
```

---

## 4. Fonction principale

```python
def resolve_debt(
    pattern: "Pattern | DoubleRowPattern",
    room: RoomDims,
) -> DebtResult:
```

### Phase 1 — Critère d'entrée (D-21)

Calculer l'emprise minimale du pattern :

```
min_eo_cm = west.non_superposable_cm + physical_eo_cm + east.non_superposable_cm
min_ns_cm = physical_ns_cm  # zones candidates NS entièrement supprimables
```

Pour un `DoubleRowPattern` :
```
min_ns_cm = physical_ns_cm + central_corridor_cm
          = DESK_D_CM * 2 + PASSAGE_CM
          = 450 cm
```

Si `min_eo_cm > room.eo_cm` ou `min_ns_cm > room.ns_cm` :

```python
return DebtResult(
    valid=False,
    rejection_reason=f"Emprise minimale {min_eo_cm}×{min_ns_cm} cm "
                     f"> pièce {room.eo_cm}×{room.ns_cm} cm",
    compacted=None,
    circulation_report=None,
    pattern_name=pattern.name,
)
```

### Phase 2a — Rasterisation synthétique

Appeler `pattern_to_grid(pattern, room)` → `np.ndarray`.

Règles de rasterisation (grille de `room_ns_cm / CELL_CM` lignes ×
`room_eo_cm / CELL_CM` colonnes) :

- Centrer le pattern dans la pièce.
- Cellules occupées par les blocs physiques → `CellType.DESK`.
- Cellules des zones candidates (bleues) → `CellType.CORRIDOR`.
- Cellules des zones non-superposables (oranges) → `CellType.CORRIDOR` (franchissables
  physiquement — la contrainte orange est une interdiction de superposition de mobilier,
  pas une obstruction ; cf. D-22).
- Cellules hors emprise du pattern mais dans la pièce → `CellType.CORRIDOR`.
- DOOR fictive : 1 ligne de cellules au bord sud (row = ROWS-1), colonnes centrées
  sur `DOOR_WIDTH_CM / CELL_CM` cellules → `CellType.DOOR`.

### Phase 2b — Analyse de circulation

```python
# Construire un PlacementResult minimal pour circulation.py
result = _make_placement_result(grid, room)
report = analyse_circulation(result)
```

`_make_placement_result` est une fonction interne qui construit un `PlacementResult` avec :
- `grid` : la grille rasterisée
- `metrics = {"cell_size_m": CELL_CM / 100}`
- `room.width_m = room.eo_cm / 100`, `room.height_m = room.ns_cm / 100`
- `desks = []` (pas de desks individuels à ce stade)

### Phase 2c — Compaction

Identifier quelles zones candidates périphériques sont actives (traversées par au
moins un chemin BFS dans le `CirculationReport`).

**Règle de suppression** : une zone candidate périphérique (N, S, E, W) est supprimée
si aucune cellule de cette zone n'appartient à un rectangle du `CirculationReport`
qui est atteignable depuis la DOOR.

Après suppression, calculer les dimensions compactées :

```
compacted_eo = min_eo_cm + (west_active  ? west.candidate_cm  : 0)
                         + (east_active  ? east.candidate_cm  : 0)
compacted_ns = min_ns_cm + (north_active ? north.candidate_cm : 0)
                         + (south_active ? south.candidate_cm : 0)

free_eo = room.eo_cm - compacted_eo
free_ns = room.ns_cm - compacted_ns
```

Si `free_eo < 0` ou `free_ns < 0` après compaction → rejet :

```
rejection_reason = "Dette résiduelle non résorbable après suppression des zones inutiles"
```

### Phase 2d — Placement complémentaire (stub)

Si `free_eo >= 0` et `free_ns >= 0` : ne pas implémenter dans cette version.
Laisser un stub commenté :

```python
# TODO Phase 2d : ajout de blocs complémentaires si free_eo ou free_ns suffisant
```

---

## 5. Fonction `pattern_to_grid`

```python
def pattern_to_grid(
    pattern: "Pattern | DoubleRowPattern",
    room: RoomDims,
) -> np.ndarray:
    """Rasterise un pattern en grille synthétique pour analyse de circulation.

    Args:
        pattern: Pattern simple rangée ou double rangée.
        room: Dimensions de la pièce cible.

    Returns:
        Grille numpy de shape (room_ns/CELL_CM, room_eo/CELL_CM)
        avec valeurs CellType.
    """
```

Logique de centrage :

```python
cols = room.eo_cm // CELL_CM
rows = room.ns_cm // CELL_CM

# Offset pour centrer le pattern total dans la pièce
offset_col = (room.eo_cm - pattern.total_eo_cm) // 2 // CELL_CM
offset_row = (room.ns_cm - pattern.total_ns_cm) // 2 // CELL_CM
```

Si `total_eo_cm > room.eo_cm` ou `total_ns_cm > room.ns_cm` : centrer quand même
(le pattern dépasse, Phase 1 a déjà validé l'emprise *minimale*).

---

## 6. Tests (`test_debt_model.py`)

### `test_phase1_reject_too_small`
Pattern `P_B4` (min_eo=460 cm), pièce 400×400.  
Vérifier `valid=False`, `rejection_reason` contient "Emprise minimale".

### `test_phase1_accept_exact_minimum`
Pattern `P_B4`, pièce 460×180.  
Vérifier `valid=True` (emprise minimale exacte).

### `test_pattern_to_grid_shape`
`pattern_to_grid(P_B4, RoomDims(640, 360))` → shape `(36, 64)`.

### `test_pattern_to_grid_has_door`
Vérifier que la grille contient au moins une cellule `CellType.DOOR`
sur la dernière ligne (row = ROWS-1).

### `test_pattern_to_grid_has_corridor`
Vérifier que la grille contient au moins une cellule `CellType.CORRIDOR`.

### `test_compaction_removes_unused_candidate`
Pattern `P_B4` dans pièce 460×360 (= emprise minimale EO,
zones candidates E/W ne rentrent pas).  
Vérifier `compacted.west_zone_cm == 0` et `compacted.east_zone_cm == 0`.

### `test_compaction_keeps_active_corridor`
Pattern `P_B4` dans pièce 640×360 (= total_eo exact).  
Vérifier que les zones E/W sont actives (`west_zone_cm > 0` ou `east_zone_cm > 0`).

### `test_free_space_calculation`
Pattern `P_B4` (total_eo=640 cm), pièce 700×400.  
Vérifier `free_eo >= 60` et `free_ns >= 0`.

### `test_double_row_phase1`
Pattern `P_B4_B4` (min_ns=450 cm), pièce 640×449. Vérifier `valid=False`.  
Pattern `P_B4_B4`, pièce 640×450. Vérifier `valid=True`.

---

## 7. Contraintes d'implémentation

- PEP 8 strict, 100 caractères max par ligne.
- Annotations de type sur toutes les fonctions publiques.
- Docstrings Google style.
- `logging` uniquement, jamais `print()`.
- Aucune dépendance externe sauf `numpy`, `pattern_generator`, `circulation`,
  `solver.model`.
- Pas d'import circulaire : `debt_model` importe depuis `pattern_generator`
  et `circulation`, jamais l'inverse.

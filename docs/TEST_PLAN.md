# TEST_PLAN.md — Plan de test

**Projet** : Office Layout Optimizer (OLO)
**Version** : 1.0
**Date** : 2026-03-09
**Statut** : Approuvé

---

## 1. Stratégie de test

| Niveau | Outil | Couverture cible | Périmètre |
|---|---|---|---|
| Unitaire | pytest | > 80 % | Modules `geometry/` et `placement/` |
| Intégration | pytest | Nominal | Chaînes ingestion → placement |
| Système (golden) | pytest | 2 scénarios | Entrée complète → PDF + JSON attendu |
| Régression | pytest | Automatique | Cache hit/miss, rotations |

---

## 2. Cas de test par exigence fonctionnelle

### EF-01 — Chargement image

| ID | Description | Entrée | Résultat attendu |
|---|---|---|---|
| TC-EF01-01 | PNG valide 300 DPI | `simple_rectangle_400x300.png` | FloorPlan créé, width=400, height=300 |
| TC-EF01-02 | JPEG valide | `simple_rectangle.jpg` | FloorPlan créé |
| TC-EF01-03 | Fichier corrompu | `corrupted.png` | `ImageLoadError` levée |
| TC-EF01-04 | Fichier inexistant | `nonexistent.png` | `ImageLoadError` levée |

### EF-02 — Parsing JSON

| ID | Description | Entrée | Résultat attendu |
|---|---|---|---|
| TC-EF02-01 | JSON valide, 1 pièce | `single_room_valid.json` | 1 Room instanciée, pixels_per_meter=50 |
| TC-EF02-02 | JSON valide, 2 pièces | `multi_room_valid.json` | 2 Room instanciées |
| TC-EF02-03 | Champ `rooms` absent | `missing_field.json` | `ValidationError` levée |
| TC-EF02-04 | Polygone < 3 points | `invalid_polygon.json` | `ValidationError` levée |
| TC-EF02-05 | Type de pièce inconnu | `unknown_room_type.json` | Warning loggé, pièce ignorée |

### EF-04 — Placement sur grille

| ID | Description | Entrée | Résultat attendu |
|---|---|---|---|
| TC-EF04-01 | Pièce 20 m² open space | `single_room_valid.json` | ≥ 2 postes placés |
| TC-EF04-02 | Pièce trop petite | `tiny_room.json` | 0 poste placé, pas d'erreur |
| TC-EF04-03 | Couloir | `corridor_room.json` | 0 poste placé |

### EF-05 — Contraintes AFNOR

| ID | Description | Vérification |
|---|---|---|
| TC-EF05-01 | Deux postes adjacents | Distance entre postes ≥ MIN_AISLE_WIDTH_M |
| TC-EF05-02 | Dégagement frontal | Distance frontale ≥ MIN_FRONT_CLEARANCE_M |
| TC-EF05-03 | Placement impossible (pièce 5 m²) | `PlacementResult.total_desks == 0` |
| TC-EF05-04 | Aucun poste hors zone | Toutes les cellules occupées dans le masque praticable |

### EF-06 — Rotation des postes

| ID | Description | Vérification |
|---|---|---|
| TC-EF06-01 | Rotation 90° | `ws.width_m` et `ws.depth_m` inversés par rapport à 0° |
| TC-EF06-02 | Rotation 180° | Dimensions identiques à 0° |
| TC-EF06-03 | Rotation 270° | Dimensions identiques à 90° |
| TC-EF06-04 | Pièce étroite | Solver choisit la rotation qui maximise le placement |

### EF-07 — Cache fingerprint

| ID | Description | Vérification |
|---|---|---|
| TC-EF07-01 | Deux appels identiques | Deuxième retourne `from_cache=True` |
| TC-EF07-02 | Image modifiée | Cache invalidé, `from_cache=False` |
| TC-EF07-03 | JSON modifié | Cache invalidé, `from_cache=False` |
| TC-EF07-04 | Cache absent | Premier appel retourne `from_cache=False` |

### EF-08 — Génération PDF

| ID | Description | Vérification |
|---|---|---|
| TC-EF08-01 | PDF généré | Fichier existe, taille > 0 |
| TC-EF08-02 | PDF contient au moins 1 page | Lecture avec PyMuPDF ou comptage pages ReportLab |
| TC-EF08-03 | Format A3 paysage | Dimensions page dans le PDF |

### EF-09 — Tableau de synthèse

| ID | Description | Vérification |
|---|---|---|
| TC-EF09-01 | Tableau présent | PDF contient le texte "Taux d'occupation" (golden file) |
| TC-EF09-02 | Cohérence des chiffres | Somme des postes par pièce = total résultat |

---

## 3. Données de test (fixtures)

```
tests/fixtures/
├── plans/
│   ├── simple_rectangle_400x300.png    # Pièce unique 8m×6m, cas trivial
│   ├── simple_rectangle_400x300.jpg    # Même pièce en JPEG
│   ├── l_shaped_room.png               # Forme en L, test algorithme
│   ├── multi_room_office.png           # 3 pièces, cas réaliste
│   └── corrupted.png                   # Fichier invalide (non-image)
├── json/
│   ├── single_room_valid.json          # 1 pièce open_space 20m²
│   ├── multi_room_valid.json           # 3 pièces (open_space, bureau, couloir)
│   ├── tiny_room.json                  # 1 pièce < 8m² (placement impossible)
│   ├── corridor_room.json              # Type couloir uniquement
│   ├── missing_field.json              # Champ "rooms" absent
│   ├── invalid_polygon.json            # Polygone à 2 points
│   └── unknown_room_type.json          # Type "salle_sport" inconnu
└── expected_outputs/
    ├── single_room_result.json         # Golden : placement attendu pièce unique
    └── multi_room_result.json          # Golden : placement attendu multi-pièces
```

### Spécification des fixtures JSON

**single_room_valid.json**
```json
{
  "scale": { "pixels_per_meter": 50 },
  "rooms": [
    {
      "id": "room_01",
      "name": "Open space A",
      "type": "open_space",
      "polygon": [[0, 0], [400, 0], [400, 300], [0, 300]],
      "allowed_desk_types": ["standard"]
    }
  ]
}
```

---

## 4. Commandes d'exécution

```bash
# Tous les tests avec couverture
pytest --cov=src/olo --cov-report=term-missing

# Tests unitaires seulement
pytest tests/ -k "not integration and not system"

# Tests d'un module spécifique
pytest tests/test_solver.py -v

# Test système golden file
pytest tests/ -k "system" -v
```

---

## 5. Critères de validation par phase

| Phase | Tests à passer avant de continuer |
|---|---|
| Phase 2 — Ingestion | TC-EF01-*, TC-EF02-* |
| Phase 3 — Geometry | TC-EF06-* (rotations), TC-EF07-01 à 04 (fingerprint) |
| Phase 4 — Placement | TC-EF04-*, TC-EF05-* |
| Phase 5 — Rendering | TC-EF08-*, TC-EF09-* |
| Phase 6 — Intégration | Tous les TC-* + test système golden |

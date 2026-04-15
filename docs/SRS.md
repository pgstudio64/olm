# SRS.md — Software Requirements Specification

**Projet** : Office Layout Optimizer (OLO)
**Version** : 1.0
**Date** : 2026-03-09
**Statut** : Approuvé

---

## 1. Introduction

### 1.1 Objectif du document

Ce document définit les exigences fonctionnelles et non-fonctionnelles du système OLO. Il constitue le contrat fonctionnel entre le Product Owner et l'équipe de développement (assistée par LLM). Toute ambiguïté sur le comportement attendu est arbitrée par ce document.

### 1.2 Glossaire

| Terme | Définition |
|---|---|
| Plan raster | Image bitmap (PNG/JPEG/TIFF) représentant un étage vu de dessus ; le haut de l'image correspond par convention à une direction géographique déclarée (`top_compass_direction`) |
| Pièce (Room) | Zone rectangulaire du plan, éventuellement réduite par des zones d'exclusion rectangulaires, dans laquelle des postes de travail seront placés |
| Zone d'exclusion | Rectangle soustrait du rectangle de la pièce pour modéliser les parties non praticables (coins, colonnes, etc.) |
| Fenêtre | Segment sur un mur de la pièce, défini par un côté (N/S/E/O) et deux offsets en pixels |
| Porte / Entrée libre | Ouverture sur un mur ; une porte battante vers l'intérieur génère une zone d'exclusion (arc de débattement) ; une entrée libre génère uniquement une contrainte de passage dégagé |
| Poste de travail (Desk) | Unité d'occupation composée d'un bureau rectangulaire (180 cm × 80 cm par défaut) + fauteuil + écran 34 pouces + dégagements réglementaires |
| Grille discrète | Découpage du plan en cellules régulières de 10 cm × 10 cm |
| Fingerprint géométrique | Hash SHA-256 calculé sur le contenu normalisé de l'image + JSON |
| Rotation | Orientation du poste de travail : 0°, 90°, 180° ou 270° |
| Contrainte AFNOR | Règle issue de la norme NF X35-102 sur les espaces de travail |
| Cache hit | Résultat de placement chargé depuis le cache sans recalcul |
| Taux d'occupation | Ratio surface occupée par les postes / surface utilisable de la pièce |

### 1.3 Références normatives

- AFNOR NF X35-102 — Conception ergonomique des espaces de travail en bureaux
- [PROJECT_CHARTER.md](PROJECT_CHARTER.md) — Périmètre et critères de succès

---

## 2. Description générale

### 2.1 Contexte d'utilisation

L'application est invoquée en ligne de commande par un utilisateur disposant d'un plan d'étage numérisé et d'un fichier de description des pièces. Elle produit un PDF prêt à l'emploi.

```
python -m olo --plan floor.png --rooms rooms.json --output result.pdf
```

### 2.2 Hypothèses et dépendances

- L'image fournie est à l'échelle, avec la résolution (pixels/mètre) renseignée dans le JSON
- Les pièces sont décrites par un rectangle (x, y, width, height) en coordonnées pixels, dans le référentiel de l'image
- Les formes non rectangulaires (L, U, T) sont modélisées par un rectangle + liste de zones d'exclusion rectangulaires
- Python 3.10+ est installé sur la machine cible
- Aucune connexion réseau n'est requise ni utilisée

---

## 3. Exigences fonctionnelles

### EF-01 — Chargement de l'image

Le système **doit** charger une image raster d'un plan d'étage aux formats PNG, JPEG et TIFF.

- L'image est convertie en mode RGB normalisé en mémoire
- Si l'image est illisible ou corrompue, une exception `ImageLoadError` est levée avec un message explicite
- Résolution minimale acceptée : 72 DPI

### EF-02 — Parsing du fichier JSON des pièces

Le système **doit** lire et valider un fichier JSON décrivant les pièces du plan.

**Schéma JSON attendu :**
```json
{
  "scale": {
    "pixels_per_meter": 50.0
  },
  "top_compass_direction": "north",
  "rooms": [
    {
      "id": "room_01",
      "name": "Open space A",
      "rectangle": {"x": 100, "y": 100, "width": 400, "height": 300},
      "exclusion_zones": [
        {"x": 300, "y": 100, "width": 200, "height": 150}
      ],
      "windows": [
        {"wall": "north", "start_px": 150, "end_px": 350}
      ],
      "doors": [
        {"wall": "east", "start_px": 50, "end_px": 130, "has_door": true, "swing_inward": true}
      ],
      "allowed_desk_types": ["standard", "pmr"]
    }
  ]
}
```

- `exclusion_zones` est optionnel (défaut : liste vide)
- `windows` est optionnel (défaut : liste vide)
- `doors` est optionnel (défaut : liste vide)
- `has_door` et `swing_inward` sont optionnels (défauts : `true`)
- `top_compass_direction` est optionnel (défaut : `"north"`) — valeurs : `"north"` | `"south"` | `"east"` | `"west"`
- Valeurs de `wall` autorisées : `"north"` | `"south"` | `"east"` | `"west"` (dans le référentiel image, haut = `top_compass_direction`)

> Le JSON ne contient que des espaces de bureau. Couloirs et salles de réunion sont hors périmètre et ne figurent pas dans le fichier d'entrée.

Si un champ obligatoire est absent ou invalide, une `ValidationError` est levée.

### EF-03 — Détection des zones praticables

Le système **doit** calculer, pour chaque pièce, la zone praticable en soustrayant les marges réglementaires au polygone brut.

### EF-04 — Placement des postes sur grille discrète

Le système **doit** placer des postes de travail dans chaque pièce praticable, en utilisant une grille discrète dont la résolution est déduite de `pixels_per_meter`.

- L'algorithme maximise le nombre de postes placés
- Chaque cellule de la grille est soit libre, soit occupée (par un poste ou une marge)
- Le placement est déterministe : même entrée → même sortie

### EF-05 — Respect des contraintes réglementaires et recommandations

#### EF-05a — Contraintes bloquantes (un poste violant ces règles ne doit pas être placé)

| Contrainte | Valeur | Référence |
|---|---|---|
| Dégagement frontal (recul chaise + circulation) | ≥ 0,90 m | NF X35-102 |
| Largeur de passage 1 personne | ≥ 0,80 m | NF X35-102 |
| Circulation principale longeant un poste (sans séparatif) | ≥ 0,90 m libre entre circulation et bord du poste | INRS ED950 §9.3.2 |
| Accès à un poste (minimum absolu) | > 1,00 m | INRS ED950 §9.3.3 |
| Circulation dans le dos d'un poste | Interdite (à proscrire) | INRS ED950 §9.3.3 |
| Passage civière / évacuation d'urgence | 0,90 m × 2,00 m dégagé sur au moins un axe par pièce | Sécurité incendie / INRS ED950 |

> **Circulation dans le dos** : aucun poste ne peut être placé si la seule voie de circulation disponible dans son dos est celle utilisée pour accéder à d'autres postes (seuls les passages vers postes contigus sont tolérés).

#### EF-05b — Recommandations (métriques de sortie calculées et affichées dans le PDF, non bloquantes)

| Recommandation | Valeur cible | Référence |
|---|---|---|
| Accès à un poste isolé | ≥ 1,20 m | INRS ED950 §9.3.3 fig. 9.1 |
| Accès à des postes contigus côte à côte | ≥ 1,60 m | INRS ED950 §9.3.3 fig. 9.1 |
| Accès à des postes dos à dos | ≥ 2,30 m | INRS ED950 §9.3.3 fig. 9.1 |
| Orientation écran | Perpendiculaire aux fenêtres (ni face ni dos) | INRS ED950 §9.2 |

L'objectif est de maximiser le nombre de postes placés et de présenter les métriques ci-dessus pour chaque pièce dans le PDF de synthèse.

### EF-06 — Rotation des postes

Le système **doit** tester les 4 orientations (0°, 90°, 180°, 270°) pour chaque poste et retenir celle qui maximise le nombre total de postes dans la pièce.

- Une rotation de 90° inverse les dimensions largeur/profondeur
- Les marges AFNOR s'appliquent après rotation

### EF-07 — Cache à fingerprint géométrique

Le système **doit** calculer un fingerprint SHA-256 combinant le hash de l'image et le hash du JSON.

- Si le fingerprint existe dans `.olo_cache/`, le résultat est chargé depuis le cache
- Le résultat retourné indique `from_cache: True` dans ce cas
- Si l'image ou le JSON est modifié, le cache est automatiquement invalidé (nouveau fingerprint)
- Le dossier `.olo_cache/` doit être ajouté au `.gitignore`

### EF-08 — Génération du PDF avec superposition

Le système **doit** générer un fichier PDF contenant :

- Le plan d'origine en fond (semi-transparent, opacité 60 %)
- Les postes représentés par des rectangles colorés selon leur type
- Une légende des couleurs
- Format : A3 paysage

### EF-09 — Tableau de synthèse dans le PDF

Le système **doit** inclure dans le PDF un tableau de synthèse contenant, par pièce :

| Colonne | Description |
|---|---|
| Pièce | Nom de la pièce |
| Surface totale | En m² |
| Surface utilisable | En m² (après marges) |
| Nombre de postes | Placés |
| Taux d'occupation | % surface utilisée |

---

## 4. Exigences non-fonctionnelles

| ID | Exigence | Valeur cible |
|---|---|---|
| ENF-01 | Temps de traitement (plan 1 000 m²) | < 30 secondes |
| ENF-02 | Temps de traitement (cache hit) | < 1 seconde |
| ENF-03 | Reproductibilité | Même entrée → même sortie, toujours |
| ENF-04 | Isolation réseau | Aucune connexion sortante |
| ENF-05 | Compatibilité Python | 3.10+ |
| ENF-06 | Couverture de tests | > 80 % sur `geometry/` et `placement/` |

---

## 5. Contraintes d'interface

### 5.1 Interface CLI

```
python -m olo --plan <image> --rooms <json> --output <pdf> [--grid-size <cm>]
```

| Argument | Requis | Description |
|---|---|---|
| `--plan` | Oui | Chemin vers l'image raster |
| `--rooms` | Oui | Chemin vers le fichier JSON des pièces |
| `--output` | Oui | Chemin du PDF à générer |
| `--grid-size` | Non | Taille des cellules de la grille en cm (défaut : 10) |
| `--ws-width` | Non | Largeur du bureau en cm (défaut : 180) |
| `--ws-depth` | Non | Profondeur du bureau en cm (défaut : 80) |
| `--monitor-size` | Non | Taille de l'écran en pouces (défaut : 34) |

### 5.2 Codes de sortie

| Code | Signification |
|---|---|
| 0 | Succès |
| 1 | Erreur d'argument ou fichier introuvable |
| 2 | Erreur de validation (JSON invalide, image illisible) |
| 3 | Erreur interne inattendue |

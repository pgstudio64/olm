# VISION_LLM_IO_SPEC — Spécification des entrées/sorties pour le LLM Vision

Version 1.0 — 2026-04-03

## Objectif

Ce document spécifie les formats que le LLM Vision doit respecter pour interpréter
un plan d'étage raster (image) et produire une description structurée des pièces
exploitable par le pipeline de matching OLO.

Le LLM Vision reçoit une **image** (PNG/JPEG/PDF rasterisé) et produit
un **fichier JSON** + optionnellement un **DSL textuel** par pièce.

---

## 1. Entrées du LLM Vision

### 1.1 Image du plan d'étage

- Format : PNG, JPEG ou page PDF rasterisée
- Contenu attendu : plan d'étage architectural avec murs, portes, fenêtres,
  numéros de pièces, éventuellement cotes
- Résolution recommandée : ≥ 150 DPI

### 1.2 Métadonnées fournies (prompt)

Le prompt accompagnant l'image doit préciser :

| Information | Obligatoire | Exemple |
|---|---|---|
| Échelle | oui | "1 cm sur le plan = 50 cm réels" ou "la cote indiquée de 3,10 m correspond à la largeur de la pièce B.4.01" |
| Étage / bâtiment | non | "4e étage, bâtiment B" |
| Convention de nommage des pièces | non | "Les pièces sont numérotées B.4.XX" |
| Orientation nord | non | "Le nord est en haut du plan" |
| Type de pièces à extraire | non | "Bureaux uniquement (code 14)" |

### 1.3 Consignes d'interprétation

Le LLM Vision doit :

1. Identifier chaque pièce fermée (rectangulaire ou assimilable à un rectangle)
2. Mesurer les dimensions intérieures en cm (largeur est-ouest × profondeur nord-sud)
3. Relever les ouvertures sur chaque mur (fenêtres, portes, baies libres)
4. Relever les obstacles fixes (poteaux, gaines techniques, placards encastrés)
5. Attribuer un identifiant à chaque pièce (numéro lu sur le plan ou généré)

---

## 2. Système de coordonnées

Convention NW→SE (décision D-26) :

```
        Nord (haut du plan)
        ┌─────────────────┐
        │ (0,0)       →  x│  x croissant vers l'Est
  Ouest │                  │ Est
        │ ↓ y              │
        │            (W, D)│
        └─────────────────┘
        Sud (bas du plan)
```

- **Origine** : coin nord-ouest de la pièce (intérieur des murs)
- **Axe x** : vers l'est (largeur `width_cm`)
- **Axe y** : vers le sud (profondeur `depth_cm`)
- **Unité** : centimètre (entier)

### Faces des murs

| Code | Nom | Position |
|---|---|---|
| `N` / `north` | Nord | y = 0 (mur du haut) |
| `S` / `south` | Sud | y = depth_cm (mur du bas) |
| `E` / `east` | Est | x = width_cm (mur de droite) |
| `O` / `west` | Ouest | x = 0 (mur de gauche) |

### Offset des ouvertures

L'offset d'une ouverture est mesuré **depuis le coin le plus proche de l'origine NW** :

- Murs **Nord** et **Sud** : offset depuis l'ouest (x croissant)
- Murs **Est** et **Ouest** : offset depuis le nord (y croissant)

---

## 3. Format de sortie JSON

### 3.1 Structure globale

```json
{
  "floor_plan": {
    "building": "B",
    "floor": 4,
    "scale_cm_per_px": 0.5,
    "building_angle_deg": 0.0,
    "north_direction": "up"
  },
  "rooms": [
    { ... },
    { ... }
  ]
}
```

Le champ `floor_plan` est optionnel (métadonnées). Le champ `rooms` est obligatoire.

### 3.2 Structure d'une pièce

```json
{
  "name": "B.4.01",
  "width_cm": 310,
  "depth_cm": 480,
  "windows": [
    {
      "face": "north",
      "offset_cm": 0,
      "width_cm": 310
    }
  ],
  "openings": [
    {
      "face": "south",
      "offset_cm": 0,
      "width_cm": 90,
      "has_door": true,
      "opens_inward": true,
      "hinge_side": "left"
    }
  ],
  "exclusion_zones": [
    {
      "x_cm": 200,
      "y_cm": 100,
      "width_cm": 40,
      "depth_cm": 40
    }
  ]
}
```

### 3.3 Champs de la pièce

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `name` | string | oui | Identifiant de la pièce lu sur le plan |
| `width_cm` | int | oui | Largeur intérieure est-ouest en cm |
| `depth_cm` | int | oui | Profondeur intérieure nord-sud en cm |
| `windows` | array | non | Liste des fenêtres (défaut : []) |
| `openings` | array | non | Liste des ouvertures/portes (défaut : []) |
| `exclusion_zones` | array | non | Liste des zones interdites (défaut : []) |

### 3.4 Fenêtre (`windows[]`)

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `face` | string | oui | Face du mur : `"north"`, `"south"`, `"east"`, `"west"` |
| `offset_cm` | int | oui | Distance depuis le coin NW le long du mur |
| `width_cm` | int | oui | Largeur de la fenêtre en cm |

**Règles :**
- `offset_cm >= 0`
- `offset_cm + width_cm <= longueur du mur` (width_cm pour N/S, depth_cm pour E/O)
- Une fenêtre couvrant tout le mur : `offset_cm = 0, width_cm = longueur du mur`

### 3.5 Ouverture / Porte (`openings[]`)

| Champ | Type | Obligatoire | Valeurs | Description |
|---|---|---|---|---|
| `face` | string | oui | `"north"`, `"south"`, `"east"`, `"west"` | Face du mur |
| `offset_cm` | int | oui | | Distance depuis le coin NW |
| `width_cm` | int | oui | | Largeur de l'ouverture (défaut 90) |
| `has_door` | bool | oui | `true` / `false` | `true` = porte battante, `false` = baie libre |
| `opens_inward` | bool | si has_door | `true` / `false` | `true` = ouvre vers l'intérieur de la pièce |
| `hinge_side` | string | si has_door | `"left"`, `"right"` | Côté des charnières vu depuis l'intérieur de la pièce |

**Règles :**
- Si `has_door = false`, les champs `opens_inward` et `hinge_side` sont ignorés
- Le sens d'ouverture crée une zone d'exclusion circulaire (quart de cercle, rayon = width_cm)
- `hinge_side` : `"left"` = charnières à gauche en regardant le mur depuis l'intérieur

### 3.6 Zone d'exclusion (`exclusion_zones[]`)

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `x_cm` | int | oui | Position x du coin NW de la zone |
| `y_cm` | int | oui | Position y du coin NW de la zone |
| `width_cm` | int | oui | Largeur (est-ouest) |
| `depth_cm` | int | oui | Profondeur (nord-sud) |

**Usages typiques :**
- Poteau structurel
- Gaine technique
- Placard encastré
- Portion non rectangulaire de la pièce (un L est modélisé comme un rectangle + exclusion)

---

## 4. Format DSL textuel (alternatif)

Le DSL textuel est une représentation compacte de la même information.
Le LLM Vision peut produire ce format directement — il est parsé par `room_dsl.py`.

### 4.1 Grammaire

```
room      := PIECE <W>x<D> \n element*
element   := FEN | PORTE | BAIE | EXCL | comment | ligne_vide
comment   := "--" texte_libre
```

### 4.2 Commandes

| Commande | Syntaxe | Exemple |
|---|---|---|
| Pièce | `PIECE <W>x<D>` | `PIECE 310x480` |
| Fenêtre plein mur | `FEN <face>` | `FEN N` |
| Fenêtre partielle | `FEN <face> <offset> <width>` | `FEN N 50 200` |
| Porte | `PORTE <face> <offset> <width> INT\|EXT G\|D` | `PORTE S 0 90 INT G` |
| Baie libre | `BAIE <face> <offset> <width>` | `BAIE E 100 150` |
| Zone interdite | `EXCL <x> <y> <width> <depth>` | `EXCL 200 100 40 40` |

### 4.3 Tokens

| Token | Valeurs | Signification |
|---|---|---|
| `<face>` | `N`, `S`, `E`, `O` | Face du mur |
| `INT` / `EXT` | | Ouvre vers l'intérieur / extérieur |
| `G` / `D` | | Charnières à gauche / droite |
| Dimensions | entiers positifs | Toujours en centimètres |

### 4.4 Règles

- `PIECE` doit être la **première ligne non vide**
- Une commande par ligne
- Les commentaires commencent par `--`
- L'ordre des éléments après `PIECE` est libre

### 4.5 Exemple complet

```
-- Bureau B.4.05, double porte
PIECE 1100x700
FEN N
PORTE S 0 90 INT G
PORTE S 1010 90 INT D
```

Équivalent JSON :

```json
{
  "name": "B.4.05",
  "width_cm": 1100,
  "depth_cm": 700,
  "windows": [{"face": "north", "offset_cm": 0, "width_cm": 1100}],
  "openings": [
    {"face": "south", "offset_cm": 0, "width_cm": 90, "has_door": true, "opens_inward": true, "hinge_side": "left"},
    {"face": "south", "offset_cm": 1010, "width_cm": 90, "has_door": true, "opens_inward": true, "hinge_side": "right"}
  ]
}
```

---

## 5. Correspondance DSL ↔ JSON

| DSL | JSON |
|---|---|
| `PIECE 310x480` | `"width_cm": 310, "depth_cm": 480` |
| `FEN N` | `{"face": "north", "offset_cm": 0, "width_cm": 310}` |
| `FEN N 50 200` | `{"face": "north", "offset_cm": 50, "width_cm": 200}` |
| `PORTE S 0 90 INT G` | `{"face": "south", "offset_cm": 0, "width_cm": 90, "has_door": true, "opens_inward": true, "hinge_side": "left"}` |
| `PORTE S 0 90 EXT D` | `{"face": "south", "offset_cm": 0, "width_cm": 90, "has_door": true, "opens_inward": false, "hinge_side": "right"}` |
| `BAIE E 100 150` | `{"face": "east", "offset_cm": 100, "width_cm": 150, "has_door": false}` |
| `EXCL 200 100 40 40` | `{"x_cm": 200, "y_cm": 100, "width_cm": 40, "depth_cm": 40}` |

---

## 6. Cas particuliers pour le LLM Vision

### 6.1 Pièces non rectangulaires

Les pièces en L, T, U ne sont pas supportées directement. Stratégies :

- **Rectangle englobant + exclusions** : modéliser le rectangle le plus grand qui contient la pièce, puis ajouter des `exclusion_zones` pour les parties manquantes
- **Décomposition** : si une porte se trouve dans un recoin, décomposer en deux pièces reliées par une baie libre

### 6.2 Portes — sens d'ouverture

Sur un plan, l'arc de cercle indique le sens d'ouverture :
- Arc **à l'intérieur** de la pièce → `opens_inward = true`
- Arc **à l'extérieur** → `opens_inward = false`

La charnière est du côté **sans l'arc** :
- Arc à droite (vu de l'intérieur) → `hinge_side = "left"`
- Arc à gauche → `hinge_side = "right"`

### 6.3 Fenêtres

- Représentées sur le plan par des doubles traits parallèles sur un mur
- Mesurer l'offset depuis le coin NW et la largeur de l'ouverture vitrée
- Si la fenêtre couvre tout le mur, utiliser `FEN <face>` (forme courte)

### 6.4 Poteaux et obstacles

- Modéliser comme `exclusion_zones` rectangulaires
- Pour un poteau circulaire : rectangle englobant

### 6.5 Cloisons intérieures

- Si une cloison divise un espace sans créer deux pièces fermées distinctes, la modéliser comme une zone d'exclusion
- Si elle crée deux pièces, produire deux entrées `rooms[]` distinctes

### 6.6 Précision dimensionnelle

- Arrondir toutes les dimensions au **centimètre** entier le plus proche
- Privilégier les cotes indiquées sur le plan plutôt que les mesures pixel
- En l'absence de cotes, utiliser l'échelle fournie dans le prompt
- Largeur de porte standard si non cotée : **90 cm**
- Largeur de porte double si non cotée : **140 cm**

---

## 7. Validation

Le JSON produit sera validé par les règles suivantes avant traitement :

1. Chaque pièce a `name`, `width_cm > 0`, `depth_cm > 0`
2. Toute ouverture a une `face` valide et `offset_cm + width_cm ≤ longueur du mur`
3. Toute exclusion est contenue dans le rectangle de la pièce
4. Au moins une ouverture (`openings`) par pièce (sinon la circulation ne peut pas être analysée)
5. Les fenêtres ne se chevauchent pas sur un même mur
6. Les ouvertures ne se chevauchent pas sur un même mur

---

## 8. Exemple complet multi-pièces

```json
{
  "rooms": [
    {
      "name": "B.4.01",
      "width_cm": 310,
      "depth_cm": 480,
      "windows": [{"face": "north", "offset_cm": 0, "width_cm": 310}],
      "openings": [{"face": "south", "offset_cm": 0, "width_cm": 90, "has_door": true, "opens_inward": true, "hinge_side": "left"}]
    },
    {
      "name": "B.4.05",
      "width_cm": 1100,
      "depth_cm": 700,
      "windows": [{"face": "north", "offset_cm": 0, "width_cm": 1100}],
      "openings": [
        {"face": "south", "offset_cm": 0, "width_cm": 90, "has_door": true, "opens_inward": true, "hinge_side": "left"},
        {"face": "south", "offset_cm": 1010, "width_cm": 90, "has_door": true, "opens_inward": true, "hinge_side": "right"}
      ]
    },
    {
      "name": "B.4.07",
      "width_cm": 600,
      "depth_cm": 500,
      "windows": [
        {"face": "north", "offset_cm": 50, "width_cm": 200},
        {"face": "north", "offset_cm": 350, "width_cm": 200}
      ],
      "openings": [
        {"face": "west", "offset_cm": 200, "width_cm": 90, "has_door": true, "opens_inward": true, "hinge_side": "left"}
      ],
      "exclusion_zones": [
        {"x_cm": 560, "y_cm": 0, "width_cm": 40, "depth_cm": 40}
      ]
    }
  ]
}
```

DSL équivalent pour B.4.07 :

```
-- Bureau en L avec poteau NE
PIECE 600x500
FEN N 50 200
FEN N 350 200
PORTE O 200 90 INT G
EXCL 560 0 40 40
```

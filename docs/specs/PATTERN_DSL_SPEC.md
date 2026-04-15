# Spécification du format de patterns — DSL texte et JSON

> **Version** : 1.3 — 2026-04-01
> **Décisions** : D-29, D-31, D-38, D-50

---

## 1. DSL texte

### Grammaire

```
pattern     := name ":" row_list
row_list    := row (";" gap ";" row)*
row         := element ("," element)*
element     := block | gap
block       := BLOCK_TYPE ("@" ORIENTATION)? (WS OFFSET)? (WS STICK)*
OFFSET      := ("SUD" | "NORD") INTEGER     -- décalage NS individuel en cm (D-31)
STICK       := "@S" DIRECTION               -- collé au mur/fenêtre (D-38)
DIRECTION   := "N" | "S" | "E" | "O"
gap         := INTEGER
BLOCK_TYPE  := "BLOCK_1" | "BLOCK_2_FACE" | "BLOCK_2_COTE" | "BLOCK_3_COTE"
             | "BLOCK_4_FACE" | "BLOCK_6_FACE"
             | "BLOCK_2_ORTHO_R" | "BLOCK_2_ORTHO_L"
ORIENTATION := "0" | "90" | "180" | "270"
INTEGER     := [0-9]+                          -- distance en cm
name        := [A-Za-z0-9_ ]+
```

### Règles

- `,` sépare les éléments d'une rangée (blocs et gaps alternés)
- `;` sépare les rangées ; un nombre entre deux `;` est le gap inter-rangée
- Un nombre nu = distance en cm entre emprises (zone de circulation)
- Un nom de bloc sans `@` = orientation 0° (regard vers l'est)
- `SUD<N>` / `NORD<N>` après un bloc = décalage NS individuel en cm par rapport à la ligne de base de la rangée (D-31). Positif = sud, négatif = nord. Pas de 10 cm. Absent = 0.
- `@SN`, `@SS`, `@SE`, `@SO` après un bloc = collé au mur/fenêtre dans la direction indiquée (D-38). Cumulable pour les coins (ex : `@SN @SO`). Absent = flottant.
- Un gap avant le premier bloc de la rangée est autorisé — il représente la distance entre le mur ouest et le premier bloc (`gap_cm` sur le premier bloc dans le JSON)
- Les espaces autour des séparateurs sont ignorés

### Exemples

```
-- Pattern simple : un bloc
P_B4: BLOCK_4

-- Simple rangée avec gap
P_B4_B2F: BLOCK_4, 180, BLOCK_2_FACE

-- Double rangée
P_B4_B4: BLOCK_4; 180; BLOCK_4

-- Double rangée mixte
P_B4B2F_B4: BLOCK_4, 180, BLOCK_2_FACE; 180; BLOCK_4

-- Orientation non standard
P_B4_R90: BLOCK_4@90

-- Rangées multiples avec orientations
P_COMPLEX: BLOCK_4@90, 200, BLOCK_2_FACE@90; 180; BLOCK_4@90, 200, BLOCK_1@270

-- Décalage NS individuel (D-31)
P_OFFSET: BLOCK_4_FACE, 180, BLOCK_2_FACE SUD20
P_MIXED: BLOCK_4_FACE@90 NORD30, 200, BLOCK_4_FACE@90

-- Gap initial (distance mur ouest → premier bloc)
P_GAP_INIT: 130, BLOCK_2_ORTHO_R @SE

-- Collé au mur (D-38)
P_STICK_N: BLOCK_4_FACE @SN, 180, BLOCK_4_FACE @SN
P_CORNER: BLOCK_4_FACE @SN @SO, 180, BLOCK_2_FACE @SN
P_FULL: BLOCK_4_FACE@90 SUD20 @SE, 200, BLOCK_4_FACE@90 @SO
```

---

## 2. JSON

### Schéma

```json
{
  "name": "P_B4B2F_B4",
  "rows": [
    {
      "blocks": [
        { "type": "BLOC_4", "orientation": 0 },
        { "type": "BLOC_2_FACE", "orientation": 0, "gap_cm": 180 }
      ]
    },
    {
      "blocks": [
        { "type": "BLOC_4", "orientation": 0 }
      ]
    }
  ],
  "row_gaps_cm": [180]
}
```

### Champs

| Champ | Type | Description |
|---|---|---|
| `name` | string | Identifiant unique du pattern |
| `rows` | array | Liste ordonnée de rangées (N→S) |
| `rows[].blocks` | array | Liste ordonnée de blocs dans la rangée (W→E) |
| `rows[].blocks[].type` | string | Type de bloc (`BLOCK_1`, `BLOCK_2_FACE`, `BLOCK_2_COTE`, `BLOCK_3_COTE`, `BLOCK_4_FACE`, `BLOCK_6_FACE`) |
| `rows[].blocks[].orientation` | int | Orientation en degrés (0, 90, 180, 270). Défaut : 0 |
| `rows[].blocks[].gap_cm` | int | Distance en cm. Pour le premier bloc : distance mur ouest → bloc. Pour les suivants : distance entre l'emprise du bloc précédent et ce bloc. Absent = 0. |
| `rows[].blocks[].offset_ns_cm` | int | Décalage NS individuel en cm (D-31). Positif = sud, négatif = nord. Absent ou 0 = pas de décalage. |
| `rows[].blocks[].sticks` | array[string] | Directions de collage au mur (D-38). Valeurs : `"N"`, `"S"`, `"E"`, `"O"`. Absent ou `[]` = flottant. |
| `row_gaps_cm` | array[int] | Distances en cm entre emprises de rangées successives. Longueur = nombre de rangées - 1. |

### Catalogue

Un catalogue est un fichier JSON contenant une liste de patterns :

```json
{
  "patterns": [
    { "name": "P_B4", "rows": [...], "row_gaps_cm": [] },
    { "name": "P_B4_B2F", "rows": [...], "row_gaps_cm": [] }
  ]
}
```

---

## 3. Bijection DSL ↔ JSON

La conversion est directe dans les deux sens :

| DSL | JSON |
|---|---|
| `name:` | `"name"` |
| `,` entre bloc et nombre | `gap_cm` sur le bloc suivant |
| `;` entre rangées | séparation des objets dans `rows` |
| nombre entre `;` | entrée dans `row_gaps_cm` |
| `BLOC_4` | `{ "type": "BLOC_4", "orientation": 0 }` |
| `BLOC_4@90` | `{ "type": "BLOC_4", "orientation": 90 }` |
| `BLOC_4 SUD20` | `{ "type": "BLOC_4", "orientation": 0, "offset_ns_cm": 20 }` |
| `BLOC_4@90 NORD30` | `{ "type": "BLOC_4", "orientation": 90, "offset_ns_cm": -30 }` |
| `BLOC_4 @SN` | `{ "type": "BLOC_4", "orientation": 0, "sticks": ["N"] }` |
| `BLOC_4 @SN @SO` | `{ "type": "BLOC_4", "orientation": 0, "sticks": ["N", "O"] }` |
| `BLOC_4@90 SUD20 @SE` | `{ "type": "BLOC_4", "orientation": 90, "offset_ns_cm": 20, "sticks": ["E"] }` |

### Propriétés calculées (non stockées)

Les métadonnées suivantes sont dérivées à l'instanciation, pas stockées :

- Nombre total de postes
- Dimensions d'emprise du pattern (dépendent des dimensions des blocs et des gaps)
- Dimensions minimales de pièce compatible (dépendent du standard actif)

# Glossaire — OLO

> **Version** : 2.0 — 2026-03-29
> **Statut** : Source de vérité pour le vocabulaire du projet.
> Toute ambiguïté dans le code ou les specs doit être résolue par ce glossaire.

---

## Échelle macro : bâtiment et plan

| Terme | Définition |
|---|---|
| **Bâtiment** | Immeuble tertiaire dont on aménage les étages. Associé à un **angle bâtiment** (degrés entre le haut du plan et le nord géographique). Pas modélisé en tant qu'objet dans le système — sert de contexte pour l'orientation. |
| **Plan d'étage** | Image raster d'un étage, extraite d'un fichier PDF. Porte une **échelle** (cm/px) et un **angle bâtiment** (degrés vs nord géographique). Chaque pièce y est repérée par son code fonctionnel et sa superficie en m². |

---

## Pièce et ses composants

| Terme | Définition |
|---|---|
| **Pièce** | Espace fermé ou semi-ouvert identifié sur le plan d'étage par un **code pièce** (seul le code 14 est candidat à l'aménagement). Modélisé comme un **rectangle** dans son repère local (origine NW, x→E, y→S) avec : largeur (O→E) et profondeur (N→S) en cm, position du coin NW dans le repère raster (px), direction de la pièce dans le plan (N/S/E/O), listes de fenêtres, ouvertures et zones interdites. Les pièces non rectangulaires (L, T, U) sont inscrites dans leur rectangle englobant avec des zones interdites fictives. |
| **Code pièce** | Identifiant fonctionnel de la pièce sur le plan. Seul le code **14** désigne les pièces candidates à l'aménagement. Les autres codes (12, 13, 15, 15d…) sont hors périmètre. |
| **Fenêtre** | Ouverture vitrée sur une face de la pièce. Définie par la face (N/S/E/O) et les positions de début et de fin (cm). Une pièce peut avoir des fenêtres sur plusieurs faces. |
| **Porte** | Ouverture de passage avec vantail, a priori 90 cm sauf exception. Positionnée sur une face (N/S/E/O), soit à l'une des extrémités de cette face, soit à une distance donnée par rapport à une extrémité. Le sens d'ouverture (intérieur/extérieur) est précisé — 99 % s'ouvrent vers l'intérieur mais des exceptions existent. Génère une **zone interdite** devant elle dont la profondeur dépend du standard (GROUP=180 cm, SITE=100 cm). |
| **Ouverture libre** | Ouverture de passage sans vantail, largeur variable. Pas de zone interdite propre — gérée par l'analyse de circulation. Également utilisée pour relier deux rectangles d'une pièce décomposée (ex. pièce en L). |
| **Zone interdite** | Rectangle dans lequel il est interdit de circuler ou de placer un poste. Trois origines possibles : **élément physique** (poteau, machinerie, gaine technique…), **zone fictive géométrique** (inscrit une pièce non rectangulaire dans son rectangle englobant — si une porte se trouve au niveau du creux, on traite la pièce comme deux rectangles séparés reliés par des ouvertures libres), **zone de débattement de porte** (générée automatiquement, profondeur selon le standard). |

---

## Repères et coordonnées

| Terme | Définition |
|---|---|
| **Repère local de la pièce** | Repère conventionnel fixe pour l'aménagement : fenêtres principales au nord, couloir au sud. Origine = coin NW. x→Est, y→Sud. Implicite, pas besoin de le préciser dans les données. |
| **Direction de la pièce** | Orientation des fenêtres principales de la pièce par rapport au haut du plan d'étage (N, S, E, O). Permet de passer du repère local au repère raster. |
| **Angle bâtiment** | Angle en degrés entre le haut du plan d'étage et le nord géographique (polaire). Utilisé dans le calcul des scores de confort (ensoleillement, éblouissement). |
| **Repère raster** | Repère du plan d'étage en pixels. Origine = premier pixel nord-ouest. Axes : est et sud. Chaque pièce est positionnée par son coin NW dans ce repère. |
| **Échelle** | Ratio cm/px du plan d'étage. Déterminée à partir de l'échelle indiquée sur le plan et des superficies annotées sur chaque pièce. |

---

## Éléments de placement : postes, blocs, zones

| Terme | Définition |
|---|---|
| **Poste de travail** | Table à laquelle s'assied une personne. Dimensions paramétrables (par défaut W=80 cm × D=180 cm). Orienté par la direction du regard de l'utilisateur. Terme code : `Desk`. |
| **Bloc** (bloc de postes de travail) | Ensemble de postes en configuration géométrique fixe (face à face, côte à côte, dos à dos). Les postes peuvent être contigus ou non contigus. Les positions relatives des postes sont figées. Déplaçable et orientable comme un tout. Le bloc le plus simple est constitué d'un seul poste — on ne parle que de blocs dans le système, jamais de postes isolés comme éléments de pattern. |
| **Zone fixe** | Ensemble de rectangles obligatoires autour d'un poste de travail (légal/ergonomique), non superposables, non supprimables. Exemple : débattement chaise CHR=70 cm. |
| **Emprise** | Rectangle englobant d'un bloc incluant ses zones fixes. C'est l'espace incompressible occupé par le bloc. Les contraintes d'espacement (≥ PAS) s'appliquent entre emprises. |

### Types de blocs

| Bloc | Composition | Postes | Conforme ES-10 |
|---|---|---|---|
| `BLOC_1` | 1 poste seul | 1 | Oui |
| `BLOC_2_FACE` | 2 postes face à face | 2 | Oui |
| `BLOC_2_COTE` | 2 postes côte à côte, regard identique | 2 | Oui |
| `BLOC_3_COTE` | 3 postes côte à côte, regard identique | 3 | Oui |
| `BLOC_4_FACE` | 2×2 postes dos à dos | 4 | Oui |
| `BLOC_6_FACE` | 3×2 postes dos à dos | 6 | Non (dérogatoire) |

---

## Pattern et aménagement

| Terme | Définition |
|---|---|
| **Pattern** | Assemblage de blocs positionnés les uns par rapport aux autres. La position relative des blocs peut être ajustée. Un pattern peut occuper une ou plusieurs rangées de postes et de blocs dans des orientations diverses, mais une fois défini on ne peut plus tourner des postes ou blocs au sein du pattern. |
| **Aménagement** | Résultat de l'application d'un pattern à une pièce réelle. Peut être un sous-ensemble du pattern d'origine si des postes dépassent de la pièce ou chevauchent des zones interdites (granularité = poste unitaire). Un aménagement est candidat tant qu'il n'est pas sélectionné, et devient l'aménagement retenu après scoring et sélection. |
| **Pièce aménagée** | Pièce + aménagement retenu + métriques (m²/poste, circulation) + scores de confort. |

---

## Standards d'aménagement

| Standard | Description |
|---|---|
| **AFNOR ADVICE** | Normes NF X35-102, caractère consultatif. Dimensions de référence pour le confort. |
| **GROUP** | Standard interne du groupe. Dimensionnement minimal / standard / confort. |
| **SITE** | Standard spécifique au site. |

---

## Opérations du pipeline

| Terme | Définition |
|---|---|
| **Matching** | Opération de recherche des aménagements candidats pour une pièce donnée. La pièce est superposée à chaque pattern du catalogue dans différentes positions et orientations ; les postes qui tombent hors de la pièce ou sur des zones interdites sont retirés, produisant des aménagements candidats. |
| **Scoring** | Évaluation quantitative d'un aménagement : m²/poste, grade de circulation, scores de confort (SC-V, SC-S, SC-E). |
| **Rééquilibrage** | Ajustement des positions des blocs dans une pièce après matching, en priorité pour maximiser les zones de circulation, puis pour améliorer l'esthétique et la symétrie. |

---

## Module d'ingestion

| Terme | Définition |
|---|---|
| **LLM vision** | Modèle de langage doté de capacités visuelles, opérant dans une zone sécurisée locale. Interprète le plan d'étage et génère le fichier JSON décrivant les pièces code 14. |

---

## Anciens termes — correspondances

| Ancien terme | Remplacé par |
|---|---|
| Bureau (table) | Poste de travail |
| Bureau (pièce) | Pièce |
| Desk, workstation (code) | `Desk` |
| Îlot | Bloc |
| Sous-pattern | Aménagement |
| Méga-pattern | Pattern |
| Zone candidate | Supprimé — remplacé par les contraintes d'espacement entre emprises |
| Modèle de dette | Supprimé — approche statique sans dette |
| Compaction | Supprimé — lié au modèle de dette |
| AFNOR (standard) | AFNOR ADVICE |
| KARDHAM | GROUP |
| LOCAL | SITE |

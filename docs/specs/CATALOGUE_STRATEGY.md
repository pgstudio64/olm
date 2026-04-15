# Stratégie de création du catalogue de patterns

## Principe

Le catalogue est construit **du bas vers le haut** : pour chaque standard d'aménagement, on crée les patterns en partant de la plus petite pièce viable et en montant progressivement en taille.

## Méthode

1. **Identifier l'assemblage de blocs optimal** pour un nombre de postes donné (ex. BLOC_2_ORTHO pour 2 postes en petit bureau).

2. **Créer le pattern à la taille minimale** : la plus petite pièce compatible avec cet assemblage pour le standard considéré. Les dimensions de la pièce sont celles qui accueillent exactement l'assemblage avec les espacements normatifs.

3. **Le matching fait le reste** : lorsqu'une pièce cible est plus grande que la pièce minimale du pattern, le calage (sticks) et l'homothétie redistribuent les blocs dans l'espace disponible. Le résultat reste acceptable visuellement et fonctionnellement car l'assemblage de blocs est le bon pour cette plage de tailles.

4. **Monter en taille** : ce pattern reste le meilleur candidat tant qu'aucun assemblage alternatif ne permet d'accueillir **plus de postes**. Dès qu'une pièce est assez grande pour qu'un assemblage différent (ex. BLOC_4_FACE au lieu de BLOC_2_ORTHO) offre plus de capacité, on crée un nouveau pattern avec ce nouvel assemblage à sa taille minimale.

5. **Répéter pour chaque standard** : les seuils de taille diffèrent car les espacements normatifs varient (AFNOR > GROUP > SITE).

## Couverture automatique

Le front de Pareto du pipeline de matching (D-54) garantit que pour une pièce cible donnée, le pattern retenu est celui qui maximise les postes parmi tous les patterns dont l'emprise rentre dans la pièce. Créer les patterns aux tailles minimales assure donc une couverture continue de l'espace des tailles de pièces :

```
Taille pièce croissante →

|-- Pattern A (2p) --|-- Pattern B (4p) --|-- Pattern C (6p) --|-- ...
    min_A                min_B                min_C

Chaque pattern couvre toutes les pièces entre sa taille minimale
et la taille minimale du pattern suivant (qui offre plus de postes).
Au-delà, le pattern suivant prend le relais via le Pareto.
```

## Exemple concret

Pour le standard SITE (espacements réduits) :

| Assemblage | Postes | Taille min pièce | Pattern créé |
|---|---|---|---|
| BLOC_2_ORTHO | 2 | 220×450 | `220x450_SITE_1` |
| BLOC_4_FACE | 4 | 480×480 | `480x480_SITE_1` |
| BLOC_4_FACE + BLOC_2_COTE | 6 | 640×540 | (à créer) |
| 2×BLOC_4_FACE | 8 | 640×720 | (à créer) |
| ... | ... | ... | ... |

Pour une pièce SITE de 500×500 : le Pareto retient `480x480_SITE_1` (4 postes) car il domine `220x450_SITE_1` (plus large ET plus profond).

## Rôle des variantes

Pour une même taille et un même standard, plusieurs patterns peuvent exister (D-50) :
- **Configurations de portes différentes** : porte à gauche vs à droite (le miroir E-O en génère une automatiquement, mais des géométries de pièce avec 2 portes nécessitent des patterns dédiés).
- **Solutions alternatives** : assemblages différents offrant le même nombre de postes mais avec des compromis confort/densité distincts.

## Enrichissement itératif

L'analyse de couverture (Étape 4, D-51) identifie les pièces mal couvertes et génère un backlog de patterns à créer. Le cycle est :

1. Créer les patterns de base (tailles minimales × standards)
2. Lancer le matching sur un jeu de pièces réelles
3. Analyser la couverture → identifier les trous
4. Créer les patterns manquants
5. Répéter

# Hypothèses du pipeline d'ingestion raster

Ces hypothèses doivent être validées sur chaque nouveau plan avant de lancer l'extraction.
Si une hypothèse n'est pas respectée, le pipeline peut donner des résultats incorrects.

## H-01 : Les murs sont noirs

Les murs (traits de structure) ont une valeur de gris < 80.
Le texte et les annotations ont une valeur de gris > 100.
Il existe un gap net entre la luminosité des murs et celle du texte.

**Seuil de binarisation** : 80 (ne capture que les murs noirs).

## H-02 : Le code "14" est toujours à l'intérieur de la pièce

Le texte "14" détecté par OCR est positionné dans l'espace intérieur de la pièce,
pas sur un mur, pas dans le couloir, pas à l'extérieur du bâtiment.

**Conséquence** : le seed est le centre géométrique du cartouche (pas du "14" seul).
Le cartouche entier est à l'intérieur de la pièce.

## H-03 : Le cartouche texte ne touche pas les murs

L'ensemble des textes d'une pièce (code, REEL, THEO, surface, numéro) forme un
cartouche rectangulaire situé à l'intérieur de la pièce, avec un espace libre
entre le cartouche et les murs.

**Conséquence** : on peut effacer le cartouche (fill blanc) sans détruire de mur.

## H-04 : Les murs sont orthogonaux

Les murs de structure sont horizontaux ou verticaux (±5° de tolérance).
Les éléments non-orthogonaux (arcs de porte, cotations, hachures) ne sont pas
des murs et peuvent être supprimés.

**Conséquence** : filtrage par composantes connexes + minAreaRect. Les composantes
dont l'orientation dominante n'est ni ~0° ni ~90° sont supprimées avant le peigne.

## H-05 : Les fenêtres sont deux traits parallèles

Une fenêtre se distingue d'un mur plein par la présence de deux ou trois bandes
noires séparées par des gaps blancs. La détection se fait par analyse de texture
(nombre de transitions noir→blanc dans un profil perpendiculaire au mur).

**Conséquence** : une face avec au moins une fenêtre est considérée extérieure.
Pas besoin de sonder au-delà du mur ni de connaître la zone extérieure du bâtiment.

## ~~H-06~~ : SUPPRIMÉE — L'extérieur n'a plus besoin d'être identifié

~~Un flood fill depuis les 4 bords de l'image remplit toute la zone extérieure.~~

**Supprimée** : la détection d'extérieur par sondage au-delà des murs a été
remplacée par une dérivation directe depuis la classification murale (H-05).
Face avec fenêtre = extérieur. Cela supprime la contrainte que l'extérieur
du bâtiment soit accessible depuis les bords de l'image, et rend le pipeline
compatible avec les cours intérieures, les plans partiels et les plans avec
bordure.

## H-07 : Un couloir n'a pas de murs latéraux continus

Quand on scanne verticalement depuis le seed et qu'on arrive à un y où
ni le mur est ni le mur ouest de la pièce n'existent → on est dans le couloir.
C'est le critère d'arrêt du scan bilatéral de profondeur.

## H-08 : L'échelle est connue ou calculable

L'échelle (cm par pixel) est soit fournie par l'utilisateur, soit calculable
à partir d'annotations sur le plan (dimensions cotées, barre d'échelle).

## H-09 : Le cartouche texte suit une syntaxe fixe, 3 lignes (D-81)

Le bloc texte à l'intérieur de chaque pièce est structuré verticalement,
de haut en bas, sur **exactement 3 lignes** :

```
14              ← ligne 1 : code pièce (paramétrable via `room_code`, défaut "14")
XX.XX m2        ← ligne 2 : surface avec suffixe " m2" explicite
9XX / 12a / 1AB ← ligne 3 : identifiant de pièce (chiffres + suffixe optionnel)
```

Chaque ligne est en dessous de la précédente. L'ensemble forme un cartouche
rectangulaire compact à l'intérieur de la pièce.

**Historique** : un format antérieur comportait 5 lignes (14 / N REEL / N THEO /
surface / numéro). Les lignes N REEL (nombre de personnes réel) et N THEO
(nombre théorique) ont été supprimées — non exploitées par le pipeline OLS et
source d'ambiguïté pour l'OCR (confusion avec les numéros de pièce courts).

**Conséquences** :
- Le regroupement des textes en cartouche se fait par parsing syntaxique
  descendant depuis le code pièce, pas par proximité géométrique.
- Les whitelist et regex Tesseract (D-73) sont alignées sur ce format 3 lignes :
  `_RE_ROOM_CODE` = code pièce, `_RE_SURFACE` = `\d+[.,]?\d*\s*m2`,
  `_RE_ROOM_NUMBER` = `\d+[a-z]*` ou `\d*[A-Z]+`.
- Le format de cartouche du Mode Préprocessé (`code_line1` / `surface_line2`
  / `id_line3`) est identique à ce format 3 lignes — les deux modes partagent
  la même sémantique de cartouche (cf. `PREPROCESSED_JSON_SPEC.md` §3).

## Mode debug

Le pipeline doit pouvoir produire des visualisations intermédiaires pour le diagnostic :

- **Cartouches détectés** : rectangles rouges sur le plan original, un par pièce "14"
- **Plan binarisé** : noir/blanc après seuil
- **Plan nettoyé** : après effacement des cartouches
- **Ray-cast debug** : bboxes rouges + seeds verts
- **Classification murale** : murs gris, fenêtres cyan, ouvertures rouge

Ces vues sont essentielles quand toutes les pièces ne sont pas trouvées,
car les plans ont des caractéristiques variées et le diagnostic visuel
permet d'identifier rapidement quelle étape échoue.

## H-10 : Les pièces sont rectangulaires

Les pièces à détecter sont des rectangles (pas de L, de T, de formes irrégulières).

**Conséquence** : le peigne adaptatif avec condition d'arrêt dynamique fonctionne
correctement. Pour des pièces non-rectangulaires, l'algorithme retournerait un
rectangle inscrit (sous-estimation de la surface).

## H-11 : L'OCR nécessite le mode sparse text (psm 11)

Sur les plans architecturaux, le texte est dispersé sans structure de paragraphe.
Le mode par défaut de pytesseract (psm 3, page segmentation) rate une majorité
des "14". Le mode psm 11 (sparse text) les détecte quasi tous.

**Paramètre** : `--psm 11` obligatoire, image upscalée x2 avant OCR.

---

À compléter au fur et à mesure des tests sur des plans réels.

Tâche R-12 étape A.1 — créer le module canonical_io.js.

Contexte : chantier R-12 (D-117) vise à déplacer toutes les rotations abs ↔ canon à deux frontières uniques (fromStorage / toStorage). Spec détaillée dans docs/specs/CANONICAL_STATE_REFACTOR.md (à lire avant de coder).

Cette sous-étape A.1 crée le module autonome, sans intégration. Aucun autre fichier ne doit être modifié. Aucun consommateur ne doit changer de comportement.

Fichier à créer : olm/static/canonical_io.js

Contenu attendu : un IIFE qui expose window.canonicalIO = { fromStorage, toStorage, FACE_MAPS, INV_FACE_MAPS }.

Signature fromStorage(roomStorage) -> roomCanon :
entrée = objet room tel que lu du JSON v3 ou retour re-analyze (repère absolu, corridor_face ∈ {"", "south", "north", "east", "west"}).
sortie = copie profonde avec :
  corridor_face = "south"
  original_corridor_face = roomStorage.corridor_face || ""
  width_cm / depth_cm swap si original_corridor_face ∈ {east, west}
  bbox_abs_px = roomStorage.bbox_px tel quel (préservé pour save + re-analyze)
  seed_abs_px = roomStorage.seed_px tel quel (même rôle)
  bbox_canon_cm = {x:0, y:0, w:width_cm, h:depth_cm}
  windows / openings / doors : face transformée par FACE_MAPS[orig] et offset_cm inversé pour north/west (même logique que floor_plan.js:_canonicalizeRoom lignes 36-48). Pour north et west, hinge_side flippé left↔right si présent.
  exclusion_zones / transparent_zones : transformées comme dans _canonicalizeRoom lignes 53-66.
  surface_m2_bbox = round(width_cm * depth_cm / 10000, 2). surface_m2 inchangé (cartouche).

Signature toStorage(roomCanon) -> roomStorage :
inverse exacte. Lit original_corridor_face du room canonique, applique la rotation inverse (INV_FACE_MAPS), restore corridor_face à original, écrit windows/openings/doors/zones en absolu. Recompose bbox_px et seed_px à partir de bbox_abs_px / seed_abs_px préservés (ou recompose depuis bbox_canon_cm si absents — pièce neuve créée en canon).

FACE_MAPS et INV_FACE_MAPS : copie conforme des dicts dans floor_plan.js:16-20 et :80-84. Ne pas les redéfinir ailleurs — ce module devient la source unique.

Propriété à garantir : toStorage(fromStorage(r)) doit être structurellement équivalent à r pour toute r valide (aux arrondis int près sur les offsets_cm). Le module doit inclure un bloc d'autotest en bas (activé via window.RUN_CANONICAL_IO_TESTS = true avant chargement) qui :
1. Prend un sample de 3 rooms avec corridor_face north / east / west / south et valide le round-trip.
2. Affiche console.log OK ou console.error DIFF + le diff.

Le sample peut être inline dans le fichier (3 rooms synthétiques aux 4 faces).

Ne pas importer ni modifier floor_plan.js, ingestion.js, editor.js, init_rvtool.js. Ne pas ajouter de <script> dans les templates HTML. Le module est autonome et non-chargé tant qu'un <script> ne le référence pas (ce sera fait en A.2).

Vérifications à faire après création :
1. Ouvrir le fichier dans un navigateur via console DevTools (file:// ou serveur en cours), charger manuellement le script, activer les tests, vérifier OK.
2. Lancer : cd ~/AI-OLM && python -m py_compile olm/ingestion/extract.py (pas impacté mais on vérifie que rien d'autre n'est cassé accidentellement).
3. git status doit montrer uniquement olm/static/canonical_io.js en nouveau fichier.

Contraintes de style :
Pas de `use strict` explicite (convention codebase).
IIFE classique (function(){ ... })();
JSDoc sur fromStorage et toStorage (paramètres, retours, exemples d'utilisation).
Lignes max 100 caractères.
Constantes en UPPER_SNAKE.
Pas de dépendance externe, pas d'import ES6.

À la fin, présenter un résumé en 5 points max : fichier créé, nombre de lignes, résultat des autotests, fichiers modifiés (doit être vide à part canonical_io.js), prochaine étape identifiée (A.2 — intégration au chargement).

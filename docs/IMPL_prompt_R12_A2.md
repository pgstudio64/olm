Tâche R-12 étape A.2 — intégration fromStorage / toStorage aux frontières.

Contexte : le module olm/static/canonical_io.js est en place (étape A.1 validée). Cette étape A.2 branche fromStorage au chargement JSON et toStorage à l'export. Les consommateurs (floor_plan.js, editor.js, matching) ne changent pas : ils continuent d'appeler _canonicalizeRoom, qui devient no-op car corridor_face sera "south" dans le state.

Spec complète : docs/specs/CANONICAL_STATE_REFACTOR.md §4 et §6 (étape A).

Sous-tâche 1 — charger canonical_io.js dans le template.

Fichier : olm/templates/pattern_editor.html
Insérer ligne 645 (juste après store.js, avant block_constants.js) :
    <script src="/static/canonical_io.js"></script>
Vérifier que le fichier se charge sans erreur console au reload navigateur.

Sous-tâche 2 — intégrer fromStorage dans fpLoadAndMatch.

Fichier : olm/static/floor_plan.js, fonction fpLoadAndMatch (ligne ~150).

Comportement actuel : parsed.rooms est envoyé au matching en repère absolu. Au retour, on ré-attache bbox_px / corridor_face / seed_px / doors depuis le dict *ByName (car le matching API ne les retourne pas).

Comportement cible : appliquer window.canonicalIO.fromStorage à chaque room parsed AVANT tout. Le matching reçoit des rooms canoniques (width_cm/depth_cm déjà swap si besoin, openings déjà retournés). Au retour, ré-attacher les champs préservés — mais maintenant depuis la copie canonique (donc bbox_abs_px et seed_abs_px au lieu de bbox_px / seed_px).

Modifications précises :
a) Après `parsed.rooms.sort(...)`, insérer :
       parsed.rooms = parsed.rooms.map(window.canonicalIO.fromStorage);
b) Remplacer la collecte actuelle par les champs canoniques :
   - bboxByName : prend room.bbox_abs_px (pas room.bbox_px)
   - corridorByName : prend room.original_corridor_face (pas room.corridor_face qui sera "south")
   - seedByName : prend room.seed_abs_px
   - doorsByName : inchangé
c) Au ré-attachement après matching :
   - r.bbox_abs_px = bboxByName[r.name] (nouveau champ)
   - r.original_corridor_face = corridorByName[r.name]
   - r.seed_abs_px = seedByName[r.name]
   - r.corridor_face = "south"  (explicite, car le matching API renvoie probablement "")
   - r.doors = doorsByName[r.name]
d) Toujours après le matching, ré-appliquer fromStorage n'est PAS nécessaire puisque les dimensions canoniques et openings arrivent déjà canoniques (le matching n'y touche pas). On reconstruit juste les champs auxiliaires.

Attention : le backend /api/floor-plan/match peut renvoyer des rooms modifiées (ajout de all_candidates, etc.). Préserver tous les autres champs — faire Object.assign(canonRoom, dataRoomFromMatching) sur les champs *sauf* ceux qui conflictent.

Sous-tâche 3 — intégrer toStorage dans devExportV3Json.

Fichier : olm/static/ingestion_export.js, fonction devExportV3Json.

Comportement actuel : itère sur ingState.rooms en lisant r.surface_m2, r.bbox_px, r.seed_px, r.doors, r.openings, r.windows (tous supposés absolus). Écrit canonical_top_face depuis doors[0].face.

Problème après A.2 sous-tâche 2 : fpData.rooms sera canonique (corridor_face="south"). Mais ingState.rooms (onglet Import / Ingestion viewer) n'aura PAS encore été canonicalisé par fromStorage — c'est un chargement indépendant. Pour A.2, garder ingState tel quel (absolu) et appliquer fromStorage quand il est chargé via extractRoomsPreprocessed (sous-tâche 4).

En pratique, devExportV3Json doit :
a) Accepter des rooms canoniques ou absolues. Pour déterminer : si r.corridor_face === "south" et r.original_corridor_face !== undefined, c'est canonique → appliquer toStorage avant sérialisation. Sinon c'est absolu → sérialiser tel quel (comportement actuel préservé).
b) Le plus propre : normaliser chaque room via :
       var rAbs = (r.original_corridor_face !== undefined)
         ? window.canonicalIO.toStorage(r)
         : r;
       // puis utiliser rAbs pour lire surface_m2, bbox_px, seed_px, doors, etc.

Sous-tâche 4 — canoniser ingState.rooms à l'import préprocessé.

Fichier : olm/static/ingestion.js, fonction extractRoomsPreprocessed (rechercher `ingState.rooms = data.rooms`).

Juste après l'affectation, ajouter :
    ingState.rooms = (data.rooms || []).map(window.canonicalIO.fromStorage);

Effet : toutes les rooms côté Import sont canoniques dès le chargement. Le bbox editor, le batch re-analyze, et tout le reste d'ingestion.js doivent continuer à fonctionner — ils lisent r.bbox_px (qui maintenant sera bbox canon) et r.width_cm / r.depth_cm (canoniques). Pour préserver le positionnement overlay absolu, ils doivent lire r.bbox_abs_px.

Sous-tâche 4.bis — concilier bbox_px (canon) vs bbox_abs_px (absolu).

fromStorage copie le bbox_px d'origine (absolu) dans bbox_abs_px, mais laisse r.bbox_px tel quel dans copy (= abs). C'est un conflit : bbox_px en canon serait un rectangle [0,0,w_cm,h_cm] en cm, non en px.

Décision pour A.2 : **après fromStorage, r.bbox_px reste en absolu (px image)**. Le champ r.bbox_canon_cm donne le rectangle en canon. Les consommateurs ingestion.js qui dessinent sur le plan raster utilisent r.bbox_px (absolu, pour position sur image). Les consommateurs canoniques (rendu Review, éditeur) utilisent r.width_cm / r.depth_cm.

Conséquence : dans canonical_io.js, fromStorage doit laisser copy.bbox_px = roomStorage.bbox_px tel quel (déjà fait) et ne pas créer bbox_canon_cm si sa sémantique cm n'est pas claire. Vérifier que le module actuel respecte ça — ne pas y toucher si c'est déjà le cas.

Tant que bbox_px reste absolu (preservé), le bbox editor de ingestion.js continue de marcher sans changement. Le toStorage au save reconstitue correctement le JSON car il copie bbox_abs_px → bbox_px.

Sous-tâche 5 — le re-analyze unitaire et batch continuent de fonctionner.

Les callers actuels envoient `origRoom.bbox_px` et `origRoom.seed_px` au backend. Après A.2 :
- Pour le batch (ingestion.js), `r.bbox_px` reste absolu (déjà garanti par sous-tâche 4.bis). OK.
- Pour l'unitaire (init_rvtool.js), `origRoom.bbox_px` est une référence à fpData.rooms[currentIdx].bbox_px — qui doit rester absolu. Donc ne PAS y toucher par fromStorage dans sous-tâche 2. Vérifier.

Le helper computeCanonicalReanalyzeResult (ingestion.js) reste inchangé à cette étape. Il sera réécrit en utilisant fromStorage à l'étape B.

Tests de non-régression obligatoires :

T1 — Round-trip JSON : charger project/plans/test_floorplan_preprocessed.json via l'UI (Import préprocessé). Sauvegarder immédiatement via le bouton Save / devExportV3Json. Diff le JSON téléchargé vs l'original : il doit être identique (hors ordre des clés éventuel, faire un diff sémantique via un script Python si nécessaire).

T2 — Rendu pièce 917 (corridor south) inchangé avant/après patch. Capture d'écran comparative.

T3 — Rendu pièce 922 (corridor east) inchangé à ce stade (le fix visuel est pour l'étape C). Vérifier qu'il n'y a pas de régression pire que l'état actuel.

T4 — Re-analyze unitaire pièce 917 fonctionne comme avant.

T5 — Re-analyze batch (bouton floor) fonctionne comme avant.

Si un test échoue, ne pas forcer le commit — remonter à l'ARCHITECT avec le diff / screenshot.

Commit message attendu : "R-12 A.2 : frontières fromStorage/toStorage branchées (chargement + export + import)"

Résumé attendu au retour, 5 points max :
a) Fichiers modifiés avec nombre de lignes ajoutées/supprimées
b) Résultat des 5 tests T1-T5 (passé / échoué + détail si échec)
c) Difficultés rencontrées / décisions prises
d) Comportement du re-analyze (unitaire + batch) post-A.2
e) Prêt pour étape B ? (retrait des _canonicalizeRoom au rendu)

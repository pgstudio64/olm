# Guide utilisateur OLM

**Version** : 0.4.66 — 2026-05-14

OLM (Office Layout Matching) est un outil local d'aide a l'amenagement de
bureaux. Il analyse un plan d'etage, detecte les pieces, et propose des
amenagements de postes de travail a partir d'un catalogue de patterns.

Traitement 100 % local, pas d'internet, pas d'IA.

---

## 1. Installation et premier lancement

### 1.1 Prerequis

| Composant | Version minimale |
|---|---|
| Python | 3.10+ (3.11+ recommande) |
| pip | recent (>=23) |
| OS | Windows (machine pro, sans droits admin) ou macOS |

OLM fonctionne avec une installation Python utilisateur (pyenv, conda ou
venv). Aucun droit administrateur n'est requis.

### 1.2 Installation

```bash
git clone https://github.com/pgstudio64/olm.git
cd olm

python -m venv venv
source venv/bin/activate   # Linux / macOS
# venv\Scripts\activate    # Windows

pip install -e ".[ingestion,dev]"
```

Sur Windows, vous pouvez aussi utiliser `install.bat`.

Les dependances principales :

| Package | Role |
|---|---|
| flask | Serveur web local |
| numpy | Calcul (circulation, grilles) |
| opencv-python | Traitement image (ingestion) |
| Pillow | Lecture/ecriture images |
| jsonschema | Validation JSON v3 |
| pymupdf | Lecture PDF (optionnel) |

### 1.3 Premier lancement

```bash
python -m olm.server.app
```

Le serveur demarre sur `http://localhost:5051`. Ouvrir cette adresse dans
un navigateur.

Pour activer le **mode developpeur** (outils de diagnostic supplementaires) :

```bash
python -m olm.server.app --dev
```

Sur Windows, double-cliquer `launch.bat`.

### 1.4 Structure des fichiers

OLM attend un repertoire `project/` a cote du package `olm/` :

```
votre-projet/
+-- olm/                  <-- code (installe via pip)
+-- project/
|   +-- config.json       <-- parametres (standards, matching, desk)
|   +-- catalogue/
|   |   +-- patterns.json <-- catalogue de patterns
|   +-- plans/            <-- plans importes (images + JSON)
|   +-- standards/        <-- definitions des standards
+-- requirements.txt
+-- logs/                 <-- journaux (cree automatiquement)
```

Si `project/config.json` est absent, OLM demarre avec des valeurs par
defaut generiques.

---

## 2. Concepts

Cette section resume les concepts cles. Le vocabulaire complet est dans
[GLOSSARY.md](specs/GLOSSARY.md).

### 2.1 Piece et code 14

OLM detecte les **pieces** sur un plan d'etage. Seules les pieces portant
le **code 14** sont candidates a l'amenagement (bureaux). Les autres codes
(12 = sanitaires, 13 = couloirs, etc.) sont ignores.

Chaque piece est representee comme un rectangle avec des attributs :
dimensions (largeur x profondeur en cm), fenetres, portes, ouvertures
libres, zones d'exclusion.

### 2.2 Cartouche

Le **cartouche** est l'encadre sur le plan contenant le code piece, le nom
et la surface en m2. OLM le lit par OCR pour identifier chaque piece.

![Plan avec cartouches](../project/plans/test_floorplan_preprocessed.png)
*Plan d'etage avec cartouches : chaque piece affiche son code (14), son
type (REEL/THEO), sa surface et son numero.*

### 2.3 Repere canonique

Chaque piece est representee dans un **repere canonique** fixe :
- Fenetres principales au nord.
- Couloir au sud.
- Origine = coin nord-ouest.

Ce repere est independant de l'orientation du plan. Il permet de comparer
et matcher les pieces entre elles.

### 2.4 JSON v3

Le format de persistance des plans. Chaque plan importe genere un fichier
JSON dans `project/plans/` contenant la structure complete : metadonnees,
echelle, et dictionnaire des pieces avec leurs attributs.

### 2.5 Modes d'import

OLM propose deux modes d'import :

| Mode | Quand l'utiliser |
|---|---|
| **Preprocessed** | Plan deja prepare avec couleurs de segmentation (bleu = exterieur, vert = couloir, blanc = interieur). Fichier suffixe `-SD`. Detection la plus fiable. |
| **OCR** | Plan brut non prepare. OLM detecte les cartouches par OCR et calibre l'echelle automatiquement. Moins fiable, mais ne necessite pas de preparation. |

**Recommandation** : utiliser le mode preprocessed quand c'est possible.
Si vous utilisez le mode OCR, saisissez toujours l'echelle du plan
(`drawing_scale`) pour une detection optimale (voir section 6).

### 2.6 Standards d'amenagement

Trois standards d'espacement sont disponibles :

| Standard | Description |
|---|---|
| **AFNOR_ADVICE** | Normes NF X35-102. Reference ergonomique. |
| **GROUP** | Standard interne du groupe. |
| **SITE** | Standard specifique au site. |

Chaque standard definit 11 parametres d'espacement (debattement chaise,
largeur de passage, zone devant la porte, etc.). Voir
[CONSTRAINTS.md](specs/CONSTRAINTS.md) pour le detail.

---

## 3. Workflow type

Le workflow OLM suit 4 etapes : import, edition, matching, sauvegarde.

### 3.1 Import d'un plan

#### 3.1a Mode preprocessed (recommande)

1. **Preparer le plan `-SD`** : colorer le plan source avec les
   conventions de couleur :
   - **Bleu** : exterieur du batiment.
   - **Vert** : couloirs et circulations.
   - **Blanc** : interieur des pieces.
   - **Noir** : murs.

![Plan -SD preprocessed](../project/plans/test_floorplan_preprocessed-SD.png)
*Plan preprocessed (-SD) : bleu = exterieur, vert = couloirs, blanc =
pieces, noir = murs.*

2. **Importer** : dans l'interface, choisir "Import preprocessed" et
   selectionner le fichier `-SD`.

3. **Verifier** : le plan s'affiche en vue Floor avec les pieces
   detectees surlignees. Verifier que toutes les pieces code 14 sont
   presentes et correctement delimitees.

#### 3.1b Mode OCR

1. **Preparer le fichier** : aucun pre-traitement. Le plan brut suffit
   (PNG, JPEG, TIFF ou PDF).

![Plan OCR brut](../project/plans/test_floorplan_ocr.png)
*Plan brut pour import OCR : les cartouches sont lus automatiquement.*

2. **Saisir l'echelle** : dans le formulaire d'import, renseigner le
   champ `drawing_scale` (echelle du plan, ex. "1:200"). C'est la
   donnee la plus importante pour la qualite de la detection.

3. **Importer** : choisir "Import OCR" et selectionner le fichier.

4. **Verifier** : contrôler la detection en vue Floor. Les pieces code
   14 doivent etre surlignees.

#### 3.1c Verification sur la vue Floor

Apres l'import, la vue **Floor** affiche le plan entier :
- Les pieces detectees sont surlignees.
- Les fenetres (bleu), portes (arcs) et ouvertures sont rendues en
  overlay SVG.
- Naviguer avec la molette (zoom) et le clic-glisser (pan).

### 3.2 Edition d'une piece

#### 3.2a Selection

Selectionner une piece par :
- **Clic** sur la piece en vue Floor.
- **Fleches clavier** (gauche/droite) pour naviguer entre les pieces.

La piece selectionnee s'affiche en **vue Room** (repere canonique).

#### 3.2b Resize de la bbox

En vue Room, les 4 coins de la piece sont des poignees de
redimensionnement. Tirer un coin pour ajuster la bbox. Le snap est a
5 cm.

Apres un resize, le flag `walls_user_edited` passe a `true` : la piece
ne sera plus ecrasee par un Rescan All.

#### 3.2c Fenetres, portes, ouvertures

En vue Room, vous pouvez :
- **Ajouter** une fenetre, porte ou ouverture libre en cliquant sur une
  face de la piece.
- **Modifier** l'offset et la largeur d'un element existant.
- **Choisir le type** : window / door / opening.
- **Pour une porte** : choisir le sens d'ouverture (hinge_side :
  left / right).
- **Supprimer** un element.

Le snap est a 10 cm.

#### 3.2d Zones d'exclusion

Les zones d'exclusion sont des rectangles dans lesquels aucun poste ne
peut etre place (poteaux, gaines, decrochements). OLM les detecte
automatiquement, mais vous pouvez en ajouter ou supprimer manuellement.

#### 3.2e Re-analyze

Apres avoir modifie la bbox, vous pouvez relancer la detection sur
la piece seule via le bouton **Re-analyze**. La detection recalcule
fenetres, portes et ouvertures sur la nouvelle bbox.

### 3.3 Matching

#### 3.3a Selectionner le standard

Dans **Settings**, choisir le standard d'amenagement a appliquer
(AFNOR_ADVICE, GROUP ou SITE). Le standard determine les espacements
minimaux entre postes, murs, portes.

#### 3.3b Lancer le matching

Cliquer sur **Match** dans la barre du plan. OLM :
1. Selectionne les patterns candidats par front de Pareto.
2. Adapte chaque pattern a la piece (homothetie, suppression de postes).
3. Score chaque amenagement (densite + confort).
4. Retient le meilleur candidat.

#### 3.3c Lire les resultats (vue Office)

La vue **Office** affiche l'amenagement retenu pour la piece :

| Metrique | Description |
|---|---|
| Nombre de postes | Postes de travail places dans la piece |
| m2/poste | Surface par poste (indicateur de densite) |
| Grade circulation | A (excellent) a F (inaccessible) |
| Violations | Infractions AFNOR detectees |
| Score SC-V | Score de vue (acces fenetre) |
| Score SC-S | Score de surface |
| Score SC-E | Score d'ensoleillement |

Un grade de circulation **A** signifie que tous les postes sont
accessibles avec des detours minimaux. Un grade **F** indique des postes
inaccessibles ou des detours excessifs.

![Vue Room](../screenshot_latest.png)
*Vue Room : piece isolee dans son repere canonique avec grille metrique.*

### 3.4 Sauvegarde et export

#### 3.4a Save

Le bouton **Save** persiste l'etat courant du plan sur le disque (fichier
JSON v3 dans `project/plans/`). L'ecriture est atomique : un fichier
temporaire est ecrit puis renomme, avec backup `.bak` de la version
precedente.

#### 3.4b Reinit

Le bouton **Reinit** remet une piece dans son etat post-ingestion. Les
modifications manuelles (bbox, ouvertures ajoutees/supprimees) sont
perdues. Utile pour repartir d'une detection propre.

#### 3.4c Export

Le bouton **Export** telecharge un fichier JSON contenant les resultats
du matching pour toutes les pieces du plan.

> **A venir** : un export package (plan annote PNG/PDF + CSV des metriques)
> est prevu (cf. SRS EF-EX-02). Il n'est pas encore implemente.

---

## 4. Reglages courants (Settings)

Le panneau **Settings** (accessible depuis la barre laterale) permet de
configurer le comportement d'OLM.

### 4.1 Standards

- **Standard actif** : choisir parmi AFNOR_ADVICE, GROUP, SITE.
- Chaque standard definit 11 parametres d'espacement. Les valeurs sont
  editables dans l'onglet correspondant.

Les parametres cles :

| Code | Parametre | Description |
|---|---|---|
| ES-01 | `chair_clearance_cm` | Zone de debattement chaise |
| ES-06 | `passage_cm` | Largeur de passage inter-blocs |
| ES-08 | `door_exclusion_depth_cm` | Zone libre devant une porte |
| ES-09 | `desk_to_wall_cm` | Distance laterale bureau-mur |
| PS-04 | `main_corridor_cm` | Largeur du couloir principal |

### 4.2 Detection

Parametres influençant la detection des pieces et de leurs elements :

- **Seuil de binarisation** : sensibilite de la conversion N&B pour la
  detection des murs. Valeur par defaut : 110.
- **Echelle** (`drawing_scale`) : ratio cm/px du plan. Determine la
  conversion entre pixels et centimetres.
- **OCR cartouches** : active/desactive la lecture des cartouches par
  OCR.

### 4.3 Hide detection colors

Remplace les pixels bleus (exterieur) et verts (couloir) par du blanc
dans les trois vues (Floor, Room, Office). Utile pour une presentation
nettoyee ou un export.

Ce reglage est persistant (conserve dans `localStorage` du navigateur).

### 4.4 Mode dev

Visible uniquement si le serveur a ete lance avec `--dev`. Active des
outils de diagnostic :

- **Seeds** : affiche les points d'ancrage (seeds) de chaque piece.
- **V-rays** : affiche les rayons verticaux du peigne de detection.
- **H-rays** : affiche les rayons horizontaux.
- **Diagnostic piece** : informations detaillees sur la detection d'une
  piece.

Ces outils sont reserves au developpement et au depannage avance.

---

## 5. Depannage

### 5.1 Detection OCR peu fiable

**Symptome** : pieces mal detectees, fenetres absentes, bboxes imprecises.

**Solution** : verifier que le champ `drawing_scale` est renseigne a
l'import. Le mode OCR 2-pass automatique ne converge pas toujours vers
la bonne echelle (cf. section 6.2). Saisir l'echelle exacte du plan
(ex. "1:200", "1:350") ameliore radicalement la detection.

Si l'echelle du plan n'est pas connue, la mesurer sur le plan source :
relever la distance en cm entre deux points connus et comparer avec les
pixels correspondants.

### 5.2 Piece avec grade F surprenant

**Symptome** : une piece qui semble bien accessible obtient un grade F.

**Causes possibles** :
- Porte trop proche d'un bloc de postes : la zone de debattement de la
  chaise (`chair_clearance_cm` = 70 cm) reduit le passage a cote de la
  porte, isolant celle-ci dans le graphe de circulation.
- Seuils des grades potentiellement trop stricts pour des pieces
  amenagees : un seul bloc dans une grande piece peut generer des detours
  mathematiques importants (cf. TODO.md, observations P1.3).

**Action** : verifier la position de la porte par rapport aux blocs.
Ajuster la bbox si necessaire. Re-analyser la piece.

### 5.3 Plan trop volumineux

**Symptome** : erreur a l'upload (HTTP 413).

**Solution** : la taille maximale d'upload est fixee a **50 MB**
(`MAX_CONTENT_LENGTH`). Si votre plan depasse cette taille, reduire sa
resolution avant import.

Formats acceptes : PNG, JPEG, TIFF, PDF.

### 5.4 Logs et diagnostics

Les journaux du serveur sont disponibles dans :
- **Console** : messages temps reel dans le terminal.
- **Fichier** : `logs/olm.log` (rotation automatique : 5 MB x 5
  fichiers).

Chaque requete HTTP est tracee avec un identifiant unique (8 caracteres).
En cas de bug, relever cet identifiant dans la console et chercher la
trace complete dans `logs/olm.log`.

### 5.5 "OLM deja en cours d'utilisation"

**Symptome** : une page s'affiche indiquant qu'OLM est deja utilise par
une autre session.

**Cause** : OLM est mono-utilisateur. Un seul navigateur/onglet peut
ecrire sur les plans a la fois. Le verrou se libere automatiquement apres
30 minutes d'inactivite.

**Solutions** :
- Fermer l'autre onglet/navigateur.
- Cliquer sur **Prendre le controle** pour forcer la reprise.
- Redemarrer le serveur (le verrou est en memoire, il se reinitialise au
  redemarrage).

### 5.6 Rescan All ne detecte rien

**Symptome** : apres un Rescan All, les pieces perdent leurs fenetres ou
ouvertures.

**Cause possible** : le mode source (OCR ou preprocessed) est persisté
dans le JSON. Si le fichier `-SD` original n'est plus accessible, le
rescan echoue silencieusement.

**Solution** : verifier que le fichier `-SD` est bien present dans
`project/plans/` a cote du JSON. Reimporter le plan si necessaire.

![Plan -SD grande taille](../project/plans/test_floorplan_preprocessed_big-SD.png)
*Plan preprocessed plus grand : meme convention de couleurs (bleu, vert,
blanc, noir).*

---

## 6. Limitations connues

### 6.1 Mono-utilisateur

OLM est concu pour un utilisateur unique sur un poste local. Il n'y a
pas d'authentification, pas de gestion de droits, pas de partage reseau.
Le verrou de session empeche les conflits si deux onglets sont ouverts
simultanement.

Reference : D-188.

### 6.2 OCR et echelle automatique

Le pipeline OCR 2-pass calibre l'echelle a partir des surfaces annotees
sur le plan. Cette calibration ne converge pas toujours vers la valeur
exacte : sur un plan 1:350 / 300 DPI, le 2-pass produit un ecart de
~23 % par rapport a l'echelle reelle.

**Impact** : la detection des fenetres est particulierement sensible.
En 2-pass auto, 1 fenetre est detectee au lieu de 61 avec l'echelle
correcte.

**Recommandation** : **toujours saisir l'echelle** dans le champ
`drawing_scale` du formulaire d'import OCR. Le 2-pass auto sert de
filet de securite quand l'echelle est inconnue, pas de mode nominal.

Reference : D-191.

### 6.3 Export package

L'export actuel est un fichier JSON unique contenant les resultats du
matching. Un export package (plan annote PNG/PDF + CSV des metriques) est
prevu mais pas encore implemente.

Questions ouvertes :
- Format du plan annote (PNG ou PDF).
- Representation simplifiee des postes.
- Structure du CSV.
- Cartouche et legende.

Reference : SRS EF-EX-02, questions Q-EX-1 a Q-EX-5.

### 6.4 Pieces non rectangulaires

Les pieces en L, T ou U sont inscrites dans leur rectangle englobant.
Les zones excedentaires sont marquees comme zones d'exclusion. Cette
approximation peut generer des scores de circulation sous-optimaux.

### 6.5 Catalogue manuel

Le catalogue de patterns est constitue manuellement (ou via l'editeur
integre). OLM ne genere pas automatiquement de patterns — il matche les
pieces aux patterns existants.

---

## 7. Reference rapide

### Raccourcis clavier

| Touche | Action |
|---|---|
| Fleche gauche | Piece precedente |
| Fleche droite | Piece suivante |
| Molette | Zoom |
| Clic-glisser | Pan (deplacement) |

### Endpoints utiles (avance)

| URL | Role |
|---|---|
| `http://localhost:5051` | Interface principale |
| `http://localhost:5051/api/health` | Etat du serveur |
| `http://localhost:5051/api/plans` | Liste des plans |
| `http://localhost:5051/api/config` | Configuration |

### Fichiers importants

| Fichier | Role |
|---|---|
| `project/config.json` | Parametres metier |
| `project/catalogue/patterns.json` | Catalogue de patterns |
| `project/plans/*.json` | Plans importes (JSON v3) |
| `logs/olm.log` | Journal du serveur |

---

## 8. Pour aller plus loin

| Document | Contenu |
|---|---|
| [GLOSSARY.md](specs/GLOSSARY.md) | Vocabulaire complet du projet |
| [CONSTRAINTS.md](specs/CONSTRAINTS.md) | Contraintes normatives (AFNOR, espacements) |
| [SRS.md](SRS.md) | Specification fonctionnelle complete |
| [CHANGELOG.md](CHANGELOG.md) | Historique des versions |
| [README.md](../README.md) | Presentation generale et quick start |

---

*Guide utilisateur OLM v0.4.66. Derniere mise a jour : 2026-05-14.*

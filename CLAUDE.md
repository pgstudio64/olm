# CLAUDE.md — Office Layout Matching (OLM)

## Présentation du projet

Application Python **locale** d'aide à l'aménagement de bureaux.

- **Entrées** : image raster d'un plan d'étage (PNG/JPEG/PDF) + catalogue de patterns d'aménagement
- **Sorties** :
  - Interface web locale : revue pièce par pièce avec aménagements proposés par standard
  - Export JSON/CSV/PDF : résultats du matching, métriques, aménagements
- **Algorithme** : matching catalogue de patterns → pièces réelles, scoring densité/confort paramétrable, adaptation par homothétie et suppression de postes
- **Pas d'IA, pas d'internet** — traitement 100 % local au niveau de l'exécution

---

## Environnement d'exécution

| Paramètre | Valeur |
|---|---|
| OS | Windows (machine pro) |
| Droits | Pas de droits administrateur |
| Python | Anaconda (conda/pip sans admin) |
| Autres outils | Demander au cas par cas |

## Stack technique

| Composant | Choix |
|---|---|
| Langage | Python 3.10+ |
| Serveur web | Flask |
| Traitement image | Pillow |
| Calcul | numpy |
| OCR (optionnel) | easyocr |
| PDF (optionnel) | pymupdf |
| Sérialisation | JSON (stdlib) |
| Tests | pytest |

---

## Structure du projet

```
AI-OLM/
├── CLAUDE.md                      # Ce fichier
├── LICENSE                        # MIT
├── README.md
│
├── olm/                           # CODE PRODUIT (open source MIT)
│   ├── __init__.py
│   ├── core/                      # Modèles, matching, scoring, DSL
│   │   ├── pattern_generator.py   # Blocs canoniques, géométrie
│   │   ├── pattern_dsl.py         # DSL patterns (parse + export)
│   │   ├── room_model.py          # Dataclass RoomSpec
│   │   ├── room_dsl.py            # DSL pièces (parse + export)
│   │   ├── dsl_common.py          # Utilitaires DSL partagés
│   │   ├── spacing_config.py      # Standards d'espacement
│   │   ├── matching_config.py     # Constantes de matching
│   │   ├── catalogue_matcher.py   # Pipeline matching catalogue → pièce
│   │   ├── coverage_analysis.py   # Analyse de couverture
│   │   ├── circulation_analysis.py # Analyse circulation Dijkstra
│   │   └── types.py               # Types partagés (CellType)
│   ├── ingestion/                 # Pipeline extraction raster
│   │   └── extract.py             # Ray-cast 3 phases
│   ├── server/                    # Flask app + API
│   │   └── app.py                 # Serveur principal
│   ├── static/                    # JS partagé
│   │   ├── block_constants.js
│   │   ├── block_geometry.js
│   │   └── block_svg.js
│   ├── templates/                 # HTML
│   │   ├── pattern_editor.html
│   │   ├── matching_viewer.html
│   │   ├── blocks_preview.html
│   │   ├── desk_preview.html
│   │   └── reference_blocks_constraints.html
│   └── tests/
│       ├── test_catalogue_matcher.py
│       ├── test_pattern_dsl.py
│       ├── test_pattern_generator.py
│       ├── test_room_model.py
│       └── test_spacing_config.py
│
├── project/                       # DONNÉES SPÉCIFIQUES (non publié)
│   ├── config.json                # Paramètres métier (room_code, labels…)
│   ├── standards/                 # Définitions des standards
│   ├── catalogue/
│   │   └── patterns.json          # Catalogue de patterns
│   ├── plans/                     # Plans raster de test
│   └── test_rooms.json            # Jeu de pièces de test
│
└── docs/                          # DOCUMENTATION INTERNE (non publié)
    ├── TODO.md                    # Tâches et prochaines étapes
    ├── Decisions.md               # Journal des décisions D-XX
    ├── CHANGELOG.md
    ├── SDS.md, SRS.md
    └── specs/                     # Spécifications techniques
```

---

## Documentation du projet

| Document | Fichier | Rôle |
|---|---|---|
| TODO | `docs/TODO.md` | Tâches en cours et prochaines étapes |
| Decisions | `docs/Decisions.md` | Journal complet des décisions D-XX |
| SRS | `docs/SRS.md` | Contrat fonctionnel (quoi) |
| SDS | `docs/SDS.md` | Architecture technique (comment) |
| Changelog | `docs/CHANGELOG.md` | Journal de version |
| Contraintes | `docs/specs/CONSTRAINTS.md` | Contraintes normatives |
| Blocs | `docs/specs/BLOCS_SPEC.md` | Blocs canoniques + zones |
| Catalogue | `docs/specs/CATALOGUE_STRATEGY.md` | Stratégie peuplement |
| Extraction raster | `docs/specs/RASTER_EXTRACTION_SPEC.md` | Pipeline ingestion |

---

## Workflow dual-instance (ARCHITECT + IMPLEMENTER)

### Rôles

| Instance | Rôle | Fenêtre | Modèle |
|---|---|---|---|
| **ARCHITECT** | Raisonnement, conception, instructions explicites | VSCode (cette fenêtre) | claude-opus-4-6 (défaut) |
| **IMPLEMENTER** | Exécution des instructions reçues, écriture de code | Terminal | claude-sonnet-4-6, effort bas |

### Lancer l'IMPLEMENTER dans le terminal

```bash
alias claude-impl='claude --model claude-sonnet-4-6 --append-system-prompt "$(cat ~/AI-OLM/CLAUDE_IMPLEMENTER.md)"'
claude-impl
```

> **Note** : une fois l'instance lancée, taper `/fast` pour activer le mode rapide.

### Protocole de collaboration

1. L'**ARCHITECT** lit le code, raisonne, décide d'une approche
2. L'**ARCHITECT** rédige des instructions **explicites et complètes** (fichier cible, signature, comportement attendu)
3. L'**IMPLEMENTER** exécute sans décider d'architecture — il signale toute ambiguïté à l'ARCHITECT
4. L'**ARCHITECT** valide le résultat

### Format des prompts IMPLEMENTER

Les prompts destinés à l'IMPLEMENTER sont présentés dans **un seul bloc de code** sans sections imbriquées, afin de permettre un copier-coller en un clic. Pas de titres, pas de sous-blocs.

Contrainte : **ne jamais commencer une ligne par `#`** dans ces blocs — cela déclenche la protection de sécurité de l'IMPLEMENTER.

---

## Qualité de code — niveau prototype

Le projet est au stade **prototype** (pas maquette, pas produit industriel).
Conséquences concrètes :

- **Zéro valeur en dur** : toute constante est définie une seule fois dans un module dédié et importée partout
- **Réutilisation systématique** : quand une fonction existe, on l'utilise — pas de copier-coller ni de ré-implémentation locale
- **Refactoring obligatoire avant réutilisation** : quand du code existant doit être utilisé dans un nouveau contexte, **extraire d'abord une fonction commune paramétrable**, puis l'appeler depuis les deux contextes. Ne jamais dupliquer du code — toujours factoriser. Prendre le temps nécessaire pour le faire proprement.
- **La qualité prime sur la vitesse** : Claude est jugé sur la qualité de ce qu'il produit, pas sur le temps qu'il met à le produire. En cas de doute entre un raccourci rapide et un refactoring propre, toujours choisir le refactoring.
- **Les fondations avant les fonctionnalités** : l'utilisateur préfère poser des fondations propres (restructuration, nommage, arborescence) avant d'avancer fonctionnellement. Quand une restructuration est identifiée comme nécessaire, la faire en priorité plutôt que d'empiler des features sur une base bancale — même si la restructuration ne crée pas de valeur visible immédiate.
- **Pas de sur-ingénierie** : pas d'abstractions spéculatives, mais ce qui est écrit est propre et solide
- **Cohérence données/rendu** : toute modification de valeurs normatives doit être propagée à la représentation graphique. Vérifier systématiquement que le rendu utilise les valeurs du standard du pattern affiché, pas un standard par défaut.
- **Itération sans retour en arrière** : la propreté du proto garantit que chaque itération avance sans devoir refactorer les fondations

---

## Conventions de code

- PEP 8 strict, lignes max 100 caractères
- Python 3.10+ : annotations de type sur toutes les fonctions publiques
- Dataclasses pour toutes les entités métier
- Docstrings Google style sur toutes les fonctions publiques
- Constantes nommées, jamais de magic numbers
- `logging` uniquement (jamais `print()` hors des scripts de lancement)
- Imports depuis le package : `from olm.core.xxx import ...`

---

## Documentation = source unique de vérité

**Règle générale** : toute information utile à long terme (spec de format, décision d'architecture, structure de données, contrainte métier, convention interne) **doit vivre dans `docs/`** et nulle part ailleurs — pas dans la conversation, pas dans des notes externes, pas dans un fichier séparé côté utilisateur.

Conséquences :
- Quand l'utilisateur précise, modifie ou clarifie un format / une règle / une décision, **l'ARCHITECT met immédiatement à jour le fichier `docs/` concerné** (spec, Decisions.md, TODO.md) — sans attendre qu'on lui demande.
- L'utilisateur ne doit **rien avoir à noter de son côté**. Les fichiers du repo sont sa seule source de vérité, consultables et éditables directement.
- En cas de conflit entre un élément de conversation antérieur et le contenu actuel de `docs/`, **`docs/` fait foi**. Si une ancienne décision devient obsolète, la remplacer ou la marquer obsolète dans le fichier, pas la laisser implicite dans l'historique de chat.
- Les changements rapides de format ou de contrainte doivent déclencher une édition immédiate du fichier de spec concerné, même si la conversation continue sur d'autres sujets.

## Mise à jour automatique de Decisions.md

Après chaque interaction qui introduit une décision d'architecture (nouveau comportement, structure de données, choix de conception), ajouter immédiatement une entrée dans `docs/Decisions.md` :
- Numéro D-XX incrémental
- Date (AAAA-MM-JJ)
- Décision, Justification, Impact

Ne pas attendre que l'utilisateur le demande.

---

## Fichiers de référence clés

**NE PAS lire systématiquement au démarrage** — lire uniquement si la tâche le nécessite, pour économiser le contexte.

Ressources disponibles sur demande :
- `docs/TODO.md` — tâches en cours, chantiers R-01 à R-07
- `docs/Decisions.md` — décisions actives (D-61+) ; historique archivé en `docs/Decisions_archive.md`
- `docs/specs/CONSTRAINTS.md` — contraintes normatives
- `docs/specs/BLOCS_SPEC.md` — blocs canoniques + zones candidates
- `docs/specs/CATALOGUE_STRATEGY.md` — stratégie de peuplement du catalogue
- `docs/specs/RASTER_EXTRACTION_SPEC.md` — pipeline ingestion raster
- `olm/core/pattern_generator.py` — blocs, géométrie
- `olm/core/catalogue_matcher.py` — pipeline matching catalogue → pièce
- `olm/core/spacing_config.py` — 3 standards d'espacement
- `project/config.json` — paramètres spécifiques

---

## Lancement du serveur

```bash
cd ~/AI-OLM
python -m olm.server.app
# → http://localhost:5051
```

---

## Séparation open source / spécifique

| Répertoire | Licence | Contenu |
|---|---|---|
| `olm/` | MIT (publié) | Code générique, réutilisable |
| `project/` | Privé | Standards métier, catalogue, config, plans |
| `docs/` | Privé | Documentation interne (TODO, Decisions, SRS, SDS, specs) |

Le répertoire `olm/` ne doit **jamais** référencer `project/` ou `docs/` directement. Les chemins vers les données spécifiques sont résolus dans `olm/server/app.py` via `BASE_DIR`.

---

## Référence historique : AI-OLO

Le projet OLM est issu de AI-OLO (`~/AI-OLO/`). Les sous-projets R&D restent dans AI-OLO :
- `solver_lab/` — laboratoire CP-SAT (R&D, phases 2-3 conditionnelles)
- `raster_poc/` — POC ingestion raster (validé, code migré dans `olm/ingestion/`)

---

## Checklist pré-clear (avant chaque /clear ou fin de session)

Avant de perdre le contexte de conversation, vérifier systématiquement :

1. **`docs/Decisions.md`** — chaque décision d'architecture prise dans la session a une entrée D-XX
2. **`docs/TODO.md`** — tâches complétées cochées, nouvelles tâches ajoutées
3. **`docs/CHANGELOG.md`** — section ajoutée si du code a été modifié
4. **Commit** — tout le travail est commité (pas de modifications non sauvegardées)
5. **Mémoire** — informations utiles pour les sessions futures sauvegardées dans les memory files

Ne pas attendre que l'utilisateur demande — proposer proactivement la checklist avant un clear.

---

## Préférences de communication

- Répondre en **français**
- Proposer une approche avant de coder si la tâche est complexe
- Être sobre et concis dans les explications
- Toujours mettre à jour `docs/CHANGELOG.md` après chaque phase complétée
- Signaler toute décision d'architecture en la documentant dans `docs/Decisions.md`

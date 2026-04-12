# Implémentation du dual-mode ingestion (D-74)

**Objectif** : Ajouter support du Mode Préprocessé (JSON + PNG enhanced/overlay) en parallèle du Mode OCR existant.

**Fichiers cibles** :
- olm/core/types.py : enum IngestionMode
- olm/ingestion/extract.py : nouvelle fonction extract_rooms_from_preprocessed()
- olm/server/app.py : routes API /api/import/ocr et /api/import/preprocessed
- pattern_editor.html : dropdown Input Mode, deux panels upload distincts

---

## 1. olm/core/types.py — Ajouter enum IngestionMode

Après les imports existants, ajouter :

```python
from enum import Enum

class IngestionMode(Enum):
    OCR = "ocr"
    PREPROCESSED = "preprocessed"
```

Vérifier que RoomSpec importable depuis ce module pour les clients (app.py).

---

## 2. olm/ingestion/extract.py — Nouvelle fonction extract_rooms_from_preprocessed()

Signature :
```python
def extract_rooms_from_preprocessed(json_data: dict, enhanced_png_path: str, overlay_png_path: str) -> list[RoomSpec]:
    """
    Parse les pièces depuis un JSON préprocessé + PNG enhanced/overlay.
    
    Args:
        json_data: dict contenant une clé "rooms" = liste de dicts 
                   {
                     "room_id": str (ex: "14001"),
                     "area_cm2": float,
                     "seed_x": float (px),
                     "seed_y": float (px),
                     "width_cm": float (optionnel),
                     "depth_cm": float (optionnel)
                   }
        enhanced_png_path: chemin fichier PNG avec cartouches supprimés, extérieur bleu RGB(135,206,235), couloirs vert RGB(193,247,179)
        overlay_png_path: chemin fichier PNG overlay (plan officiel)
    
    Returns:
        list[RoomSpec] : liste des pièces
    
    Raises:
        ValueError: si JSON mal formé ou fichiers PNG manquants
    """
```

Implémentation :
- Valider structure JSON (présence clé "rooms", champs obligatoires par pièce)
- Pour chaque room, créer RoomSpec avec room_id, area, width/depth (si fournis, sinon calculer approximativement)
- Charger PNG enhanced et récupérer la seed position en pixels (conversion en cm nécessaire : seed_x/y à partir du JSON, les valeurs sont déjà en px, les convertir)
- Optionnel pour v1 : analyser PNG enhanced pour détecter couloirs/extérieur (à faire plus tard)
- Retourner la liste de RoomSpec

---

## 3. olm/server/app.py — Routes API

### Route POST /api/import/ocr (refactorisation de l'existant)

Renommer la route actuelle ou créer nouvelle route explicite :

```python
@app.route('/api/import/ocr', methods=['POST'])
def import_ocr():
    """
    Mode OCR : upload image + échelle.
    Retourne {
        "rooms": [...],
        "mode": "ocr",
        "image_path": "chemin fichier PNG chargé"
    }
    """
    # Récupérer image depuis request.files['floorplan_image']
    # Récupérer scale depuis request.form['scale_cm_per_px']
    # Appeler extract_rooms_from_raster_ocr()
    # Retourner JSON
```

### Route POST /api/import/preprocessed (nouveau)

```python
@app.route('/api/import/preprocessed', methods=['POST'])
def import_preprocessed():
    """
    Mode Préprocessé : upload JSON + PNG enhanced + PNG overlay.
    Retourne {
        "rooms": [...],
        "mode": "preprocessed",
        "overlay_path": "chemin PNG overlay",
        "enhanced_path": "chemin PNG enhanced"
    }
    """
    # Récupérer files depuis request.files
    # - rooms_json : fichier JSON ou textarea
    # - enhanced_png : fichier PNG "_enhanced"
    # - overlay_png : fichier PNG overlay
    # Parser JSON
    # Sauver PNGs temporaires
    # Appeler extract_rooms_from_preprocessed()
    # Retourner JSON
```

---

## 4. pattern_editor.html — Ajouter dropdown Input Mode

Dans le panel Settings > Ingestion, ajouter avant le formulaire actuel :

```html
<div class="settings-row">
  <label>Input Mode</label>
  <select id="cfgIngestionMode" class="settings-input">
    <option value="ocr">OCR (analyse d'image)</option>
    <option value="preprocessed">Préprocessé (données structurées)</option>
  </select>
</div>
```

Dans le JavaScript (pattern_editor.html ou init.js) :

```javascript
// Sauver le changement de mode
document.getElementById('cfgIngestionMode').addEventListener('change', (e) => {
  cfg.ingestionMode = e.target.value;
  renderImportPanel();  // Refresh le panel import en dessous
});

// Dans renderImportPanel(), afficher deux formulaires distincts :
if (cfg.ingestionMode === 'ocr') {
  // Afficher formulaire raster existant (image + scale)
} else {
  // Afficher formulaire préprocessé (JSON + enhanced PNG + overlay PNG)
}
```

---

## Validation

- Après chaque fonction, tester avec des données factices (JSON valide, PNG factice)
- Vérifier que les deux modes retournent une structure RoomSpec cohérente
- Pas de copier-coller entre extract_rooms_from_raster_ocr() et extract_rooms_from_preprocessed() : factoriser la partie commune si pertinent

---

## Notes d'implémentation

- Ne pas modifier le comportement du Mode OCR existant — garder la compatibilité backward.
- Les chemins PNG peuvent être temporaires (fichiers upload) — bien gérer le cleanup après import.
- Tester le changement de mode en Settings sans recharger la page.

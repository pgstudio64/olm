Implémente les modifications UI pour R-02 dans ~/AI-OLM/olm/templates/pattern_editor.html.

Toutes les modifications sont dans ce seul fichier. Ne touche à aucun autre fichier.

MODIFICATION 1 -- Ajouter loadAppConfig() et helpers

Juste AVANT la ligne "var SPACING_FIELDS = [" (vers ligne 4122), insérer ce bloc JS :

var APP_CONFIG = {};

async function loadAppConfig() {
  try {
    var resp = await fetch("/api/config");
    if (resp.ok) APP_CONFIG = await resp.json();
  } catch (e) { console.warn("Failed to load config:", e); }
}

function getStandards() {
  if (APP_CONFIG.spacing) return Object.keys(APP_CONFIG.spacing);
  return ["AFNOR_ADVICE", "GROUP", "SITE"];
}

function getStdLabel(key) {
  if (APP_CONFIG.standard_labels && APP_CONFIG.standard_labels[key]) {
    return APP_CONFIG.standard_labels[key];
  }
  return key;
}

async function saveConfigField(keyOrPath, value) {
  var body;
  if (Array.isArray(keyOrPath)) {
    body = { path: keyOrPath, value: value };
  } else {
    body = { key: keyOrPath, value: value };
  }
  try {
    var resp = await fetch("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!resp.ok) throw new Error(await resp.text());
    await loadAppConfig();
  } catch (e) {
    console.error("Config save error:", e);
  }
}


MODIFICATION 2 -- Remplacer les 3 occurrences de var stds = ["AFNOR_ADVICE", "GROUP", "SITE"]

Chercher chaque occurrence et remplacer par :
  var stds = getStandards();

Il y en a 3 :
  - dans loadAllBlockDefs() (vers ligne 3498)
  - dans renderSpacingSettings() (vers ligne 4139)
  - dans le handler btnResetSpacing (vers ligne 4227)


MODIFICATION 3 -- Remplacer les 3 occurrences de stdShort = { AFNOR_ADVICE: "AFNOR", ...}

Chercher chaque occurrence du dict littéral stdShort et remplacer :

Avant (3 endroits, vers lignes 1205, 2761, 3211) :
  const stdShort = { AFNOR_ADVICE: "AFNOR", GROUP: "GROUP", SITE: "SITE" };
  ou
  var stdShort = { AFNOR_ADVICE: "AFNOR", GROUP: "GROUP", SITE: "SITE" };

Après (dans les 3 endroits) : supprimer la ligne stdShort et utiliser getStdLabel() directement.

Pour chaque endroit, la ligne suivante qui utilise stdShort[xxx] doit être remplacée :
  - Ligne ~1206 : remplacer (stdShort[state.standard] || state.standard) par getStdLabel(state.standard)
  - Ligne ~2762 : remplacer (stdShort[p.standard] || p.standard || "?") par (getStdLabel(p.standard) || "?")
  - Ligne ~3212 : remplacer (stdShort[p.standard] || p.standard || "") par getStdLabel(p.standard)


MODIFICATION 4 -- Remplacer le header dans renderSpacingSettings()

Dans la fonction renderSpacingSettings(), remplacer :
  s.replace("_ADVICE", "")
par :
  getStdLabel(s)


MODIFICATION 5 -- Remplacer le summary hardcodé

Vers ligne 5064, remplacer :
  var summary = { AFNOR_ADVICE: { rooms: 0, total_desks: 0 }, GROUP: { rooms: 0, total_desks: 0 }, SITE: { rooms: 0, total_desks: 0 } };

Par :
  var summary = {};
  getStandards().forEach(function(s) { summary[s] = { rooms: 0, total_desks: 0 }; });


MODIFICATION 6 -- Ajouter loadAppConfig() dans init()

Dans la fonction init() (vers ligne 4189), ajouter en PREMIÈRE ligne du corps de la fonction :
  await loadAppConfig();


MODIFICATION 7 -- Enrichir le panneau Settings

Remplacer le contenu du div id="subtabOlSettings" (lignes 990-1003) par :

<div class="sub-tab-content" id="subtabOlSettings">
  <div class="fp-input-page" style="max-width:900px;">

    <div class="section-title">General</div>
    <div style="display:grid;grid-template-columns:200px 120px;gap:4px 12px;font-size:12px;margin-bottom:16px;">
      <label style="color:var(--text-dim);">Room code</label>
      <input type="text" id="cfgRoomCode" style="width:80px;background:var(--surface);border:1px solid var(--border);color:var(--text);font-family:var(--font-mono);font-size:12px;padding:2px 6px;">
      <label style="color:var(--text-dim);">Default door width (cm)</label>
      <input type="number" id="cfgDoorWidth" style="width:80px;background:var(--surface);border:1px solid var(--border);color:var(--text);font-family:var(--font-mono);font-size:12px;padding:2px 6px;">
      <label style="color:var(--text-dim);">Desk width (cm)</label>
      <input type="number" id="cfgDeskW" style="width:80px;background:var(--surface);border:1px solid var(--border);color:var(--text);font-family:var(--font-mono);font-size:12px;padding:2px 6px;">
      <label style="color:var(--text-dim);">Desk depth (cm)</label>
      <input type="number" id="cfgDeskD" style="width:80px;background:var(--surface);border:1px solid var(--border);color:var(--text);font-family:var(--font-mono);font-size:12px;padding:2px 6px;">
      <label style="color:var(--text-dim);">Grid cell (cm)</label>
      <input type="number" id="cfgGrid" style="width:80px;background:var(--surface);border:1px solid var(--border);color:var(--text);font-family:var(--font-mono);font-size:12px;padding:2px 6px;">
    </div>

    <div class="section-title">Standard labels</div>
    <div id="cfgStandardLabels" style="display:grid;grid-template-columns:200px 120px;gap:4px 12px;font-size:12px;margin-bottom:16px;">
    </div>

    <div class="section-title">Matching weights</div>
    <div style="display:grid;grid-template-columns:200px 120px;gap:4px 12px;font-size:12px;margin-bottom:16px;">
      <label style="color:var(--text-dim);">Density weight</label>
      <input type="number" id="cfgWDensity" step="0.1" min="0" max="1" style="width:80px;background:var(--surface);border:1px solid var(--border);color:var(--text);font-family:var(--font-mono);font-size:12px;padding:2px 6px;">
      <label style="color:var(--text-dim);">Comfort weight</label>
      <input type="number" id="cfgWComfort" step="0.1" min="0" max="1" style="width:80px;background:var(--surface);border:1px solid var(--border);color:var(--text);font-family:var(--font-mono);font-size:12px;padding:2px 6px;">
    </div>

    <div class="section-title">Spacing standards</div>
    <div style="margin-bottom:12px;color:var(--text-dim);font-size:11px;">
      Edit spacing values per standard. Changes are saved immediately and affect block geometry and rendering.
    </div>
    <div id="spacingSettingsGrid" style="display:grid;grid-template-columns:200px repeat(3,120px);gap:2px 8px;font-size:11px;font-family:var(--font-mono);">
    </div>
    <div style="margin-top:12px;">
      <button class="btn" id="btnResetSpacing" style="font-size:10px;">Reset to defaults</button>
      <span id="spacingSaveStatus" style="color:var(--text-dim);font-size:10px;margin-left:12px;"></span>
    </div>
  </div>
</div>


MODIFICATION 8 -- Ajouter la fonction pour remplir et wirer les Settings General/Matching

Juste APRÈS la fonction renderSpacingSettings(), ajouter :

function renderGeneralSettings() {
  if (!APP_CONFIG) return;

  var el;
  el = document.getElementById("cfgRoomCode");
  if (el) { el.value = APP_CONFIG.room_code || "14"; el.onchange = function() { saveConfigField("room_code", this.value); }; }

  el = document.getElementById("cfgDoorWidth");
  if (el) { el.value = APP_CONFIG.default_door_width_cm || 90; el.onchange = function() { saveConfigField("default_door_width_cm", parseInt(this.value)||90); }; }

  el = document.getElementById("cfgDeskW");
  if (el) { el.value = APP_CONFIG.desk_width_cm || 80; el.onchange = function() { saveConfigField("desk_width_cm", parseInt(this.value)||80); }; }

  el = document.getElementById("cfgDeskD");
  if (el) { el.value = APP_CONFIG.desk_depth_cm || 180; el.onchange = function() { saveConfigField("desk_depth_cm", parseInt(this.value)||180); }; }

  el = document.getElementById("cfgGrid");
  if (el) { el.value = APP_CONFIG.grid_cell_cm || 10; el.onchange = function() { saveConfigField("grid_cell_cm", parseInt(this.value)||10); }; }

  var matching = APP_CONFIG.matching || {};
  el = document.getElementById("cfgWDensity");
  if (el) { el.value = matching.w_density != null ? matching.w_density : 0.5; el.onchange = function() { saveConfigField(["matching", "w_density"], parseFloat(this.value)||0.5); }; }

  el = document.getElementById("cfgWComfort");
  if (el) { el.value = matching.w_comfort != null ? matching.w_comfort : 0.5; el.onchange = function() { saveConfigField(["matching", "w_comfort"], parseFloat(this.value)||0.5); }; }

  var labelsDiv = document.getElementById("cfgStandardLabels");
  if (labelsDiv) {
    var html = "";
    getStandards().forEach(function(s) {
      var label = getStdLabel(s);
      html += '<label style="color:var(--text-dim);">' + s + '</label>';
      html += '<input type="text" data-std-label="' + s + '" value="' + label +
        '" style="width:100px;background:var(--surface);border:1px solid var(--border);color:var(--text);font-family:var(--font-mono);font-size:12px;padding:2px 6px;">';
    });
    labelsDiv.innerHTML = html;
    labelsDiv.querySelectorAll("input[data-std-label]").forEach(function(inp) {
      inp.addEventListener("change", function() {
        var labels = APP_CONFIG.standard_labels || {};
        labels[inp.dataset.stdLabel] = inp.value;
        saveConfigField("standard_labels", labels);
      });
    });
  }
}


MODIFICATION 9 -- Appeler renderGeneralSettings() dans init()

Dans init(), juste après la ligne renderSpacingSettings(), ajouter :
  renderGeneralSettings();


MODIFICATION 10 -- Commit

  cd ~/AI-OLM
  git add -A
  git commit -m "R-02 UI: Settings panel enrichi — General, Standards, Matching, Spacing

  Ajout loadAppConfig(), getStandards(), getStdLabel() pour rendre les standards
  paramétriques. Panneau Settings étendu avec champs General (room_code, door,
  desk, grid), Standard labels, Matching weights (density/comfort).
  Suppression de toutes les références hardcodées AFNOR/GROUP/SITE dans le JS.

  Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"

Quand c'est fait, affiche un résumé : nombre de modifications effectuées, vérification que le serveur démarre sans erreur.

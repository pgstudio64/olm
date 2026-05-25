"use strict";
// ============================================================================
// INGESTION SERIALIZE — Unified rooms serializer (D-94 P4, R-12 C3, D-122 P5)
// ============================================================================
//
// Deux destinations, deux repères distincts :
//   • Matching   → POST `/api/floor-plan/match` en repère CANONIQUE
//                  (backend matcher suppose canonique — P5 acté).
//   • Storage v3 → écriture disque `<plan_id>.json` en repère ABSOLU
//                  (format fichier historique, voir PREPROCESSED_JSON_SPEC).
//
// `_canonRooms()` renvoie ingState.rooms tel quel (canonique).
// `_toAbsRooms()` applique `canonicalIO.toStorage` avant sérialisation.
// ============================================================================

(function () {

  // Source canonique : ingState.rooms tel quel (invariant post-fromStorage).
  function _canonRooms() {
    var ingState = window.ingState;
    if (!ingState || !ingState.rooms) return [];
    return ingState.rooms;
  }

  // Source absolue : canonicalIO.toStorage par pièce.
  // D-122 P1 : scale passé à toStorage pour rotation des offset_px / width_px.
  function _toAbsRooms() {
    var ingState = window.ingState;
    if (!ingState || !ingState.rooms) return [];
    var scale = ingState.scale || 0;
    return ingState.rooms.map(function (rC) {
      return (rC.corridor_face_abs !== undefined && window.canonicalIO)
        ? window.canonicalIO.toStorage(rC, scale)
        : rC;
    });
  }

  // ==========================================================================
  // Destination 1 : Matching (D-122 P5 — frontière canonique)
  // Consommée par prepareFpRooms / fpRematchRoom → `/api/floor-plan/match`.
  // Payload en repère CANONIQUE : le backend matcher suppose corridor-south,
  // aligné avec le catalogue lui-même canonique. Les portes sont fusionnées
  // dans `openings[]` via has_door=true (contrat OpeningSpec backend).
  // ==========================================================================
  function serializeForMatching() {
    var ingState = window.ingState;
    var scale = (ingState && ingState.scale) || 0;
    function _offCm(e) {
      return (e && e.offset_cm != null)
        ? Math.round(e.offset_cm)
        : Math.round(((e && e.offset_px) || 0) * scale);
    }
    function _widCm(e) {
      return (e && e.width_cm != null)
        ? Math.round(e.width_cm)
        : Math.round(((e && e.width_px) || 0) * scale);
    }
    var rooms = _canonRooms().map(function (r) {
      // D-141 : skip les entries non-enrichies (sans face). Cas d'un
      // JSON v3 Input minimal (doors avec seed_x/seed_y seulement) qui
      // n'a pas encore reçu l'enrichissement ray-cast. Sans ce filtre,
      // le backend match crash KeyError "face".
      var windows = (r.windows || []).filter(function (w) {
        return w && w.face;
      }).map(function (w) {
        return { face: w.face, offset_cm: _offCm(w), width_cm: _widCm(w) };
      });
      var openings = (r.openings || []).filter(function (o) {
        return o && o.face;
      }).map(function (o) {
        return {
          face: o.face,
          offset_cm: _offCm(o),
          width_cm: _widCm(o),
          has_door: false,
        };
      });
      (r.doors || []).forEach(function (d) {
        if (!d || !d.face) return;   // skip doors non-enrichies
        openings.push({
          face: d.face,
          offset_cm: _offCm(d),
          width_cm: _widCm(d),
          has_door: true,
          opens_inward: d.opens_inward !== false,
          hinge_side: d.hinge_side || 'left',
        });
      });
      return {
        name: r.name,
        width_cm: r.width_cm,       // canonique (post-swap pour east/west)
        depth_cm: r.depth_cm,
        windows: windows,
        openings: openings,
        exclusion_zones: (r.exclusion_zones || []).map(function (z) {
          return {
            x_cm: Math.round(z.x_cm), y_cm: Math.round(z.y_cm),
            width_cm: Math.round(z.width_cm), depth_cm: Math.round(z.depth_cm),
            origin: z.origin,
          };
        }),
        exterior_faces: r.exterior_faces,
        corridor_face: 'south',     // invariant canonique explicite
        corridor_face_abs: r.corridor_face_abs || '',
        bbox_px: r.bbox_px,
        seed_px: r.seed_px || r.seed,
        doors: r.doors || [],
      };
    });
    return { rooms: rooms };
  }

  // Wrapper UI : écrit la sortie dans le textarea d'édition.
  function populateRoomsJson() {
    var textarea = document.getElementById('fpRoomsJson');
    if (!textarea) return;
    textarea.value = JSON.stringify(serializeForMatching(), null, 2);
  }

  // ==========================================================================
  // Destination 2 : Storage v3
  // Format documenté dans `docs/specs/PREPROCESSED_JSON_SPEC.md` §5.
  // Offsets en px, portes séparées des openings, métadonnées scale / page.
  // ==========================================================================
  function serializeForStorage() {
    var ingState = window.ingState;
    if (!ingState || !ingState.rooms) return null;

    var hdr = document.getElementById('hdrCurrentPlanText');
    var planName = hdr ? hdr.textContent.trim() : '';
    var fileHint = planName ? (planName + '.png') : 'plan.png';

    // D-122 P1 : _toAbsRooms() passe scale à toStorage → offset_px /
    // width_px déjà rotés en cohérence avec offset_cm. Fallback vers 0
    // uniquement pour les legacy rooms sans offset_cm ni offset_px.
    function _px(v) {
      return (typeof v === 'number' && !isNaN(v)) ? Math.round(v) : 0;
    }

    var roomsDict = {};
    _toAbsRooms().forEach(function (r) {
      var roomId = r.name || '';
      if (!roomId) return;

      // Cartouche seed : prefer seed_px, else seed, else bbox center
      var seed;
      if (Array.isArray(r.seed_px) && r.seed_px.length === 2) {
        seed = [Math.round(r.seed_px[0]), Math.round(r.seed_px[1])];
      } else if (Array.isArray(r.seed) && r.seed.length === 2) {
        seed = [Math.round(r.seed[0]), Math.round(r.seed[1])];
      } else if (Array.isArray(r.bbox_px) && r.bbox_px.length === 4) {
        seed = [
          Math.round((r.bbox_px[0] + r.bbox_px[2]) / 2),
          Math.round((r.bbox_px[1] + r.bbox_px[3]) / 2),
        ];
      } else {
        seed = [0, 0];
      }

      // Surface en string "N.NN m2" — v3 garde la forme texte
      var surfaceStr = '';
      if (typeof r.surface_m2 === 'number' && r.surface_m2 > 0) {
        surfaceStr = r.surface_m2.toFixed(2) + ' m2';
      }

      var roomObj = { surface: surfaceStr, seed_x: seed[0], seed_y: seed[1] };

      if (Array.isArray(r.bbox_px) && r.bbox_px.length === 4) {
        roomObj.bbox_px = r.bbox_px.map(function (v) { return Math.round(v); });
      }

      // D-135 : flag user-edit de la géométrie des murs. Persistant pour que
      // la pièce rouverte pré-coche "Lock walls" et préserve le bbox réglé
      // à la main au prochain Rescan.
      if (r.walls_user_edited) roomObj.walls_user_edited = true;

      // canonical_top_face : recalculé à chaque export depuis la porte
      // principale (cohérence avec re-analyze qui modifie les portes).
      if (Array.isArray(r.doors) && r.doors.length > 0 && r.doors[0].face) {
        var OPPOSITE = { north: 'south', south: 'north', east: 'west', west: 'east' };
        roomObj.canonical_top_face = OPPOSITE[r.doors[0].face] || 'north';
      }

      // D-204: door_seeds[] is immutable preprocessing input.
      if (Array.isArray(r.door_seeds) && r.door_seeds.length > 0) {
        roomObj.door_seeds = r.door_seeds.map(function (ds) {
          return { seed_x: Math.round(ds.seed_x), seed_y: Math.round(ds.seed_y) };
        });
      }
      // D-204: doors[] contains only typed doors (with face).
      if (Array.isArray(r.doors) && r.doors.length > 0) {
        roomObj.doors = r.doors.filter(function (d) { return !!d.face; })
          .map(function (d) {
          var o = {
            face: d.face,
            offset_px: _px(d.offset_px),
            width_px:  _px(d.width_px),
          };
          if (d.hinge_side) o.hinge_side = d.hinge_side;
          if (typeof d.opens_inward === 'boolean') o.opens_inward = d.opens_inward;
          if (d.origin) o.origin = d.origin;
          return o;
        });
        if (roomObj.doors.length === 0) delete roomObj.doors;
      }
      if (Array.isArray(r.openings) && r.openings.length > 0) {
        roomObj.openings = r.openings.map(function (o) {
          var out = {
            face: o.face,
            offset_px: _px(o.offset_px),
            width_px:  _px(o.width_px),
          };
          if (o.origin) out.origin = o.origin;
          return out;
        });
      }
      if (Array.isArray(r.windows) && r.windows.length > 0) {
        roomObj.windows = r.windows.map(function (w) {
          var out = {
            face: w.face,
            offset_px: _px(w.offset_px),
            width_px:  _px(w.width_px),
          };
          if (w.origin) out.origin = w.origin;
          return out;
        });
      }
      if (Array.isArray(r.exclusion_zones) && r.exclusion_zones.length > 0) {
        roomObj.exclusion_zones = r.exclusion_zones.map(function (z) {
          var out = {
            x_cm: Math.round(z.x_cm),
            y_cm: Math.round(z.y_cm),
            width_cm: Math.round(z.width_cm),
            depth_cm: Math.round(z.depth_cm),
          };
          if (z.origin) out.origin = z.origin;
          return out;
        });
      }
      // D-245: persist layout amendment (saved or amended) for reload.
      var _amend = (window.fpAmendments || {})[roomId];
      if (_amend) {
        roomObj.saved_layout = JSON.parse(JSON.stringify(_amend));
      }

      roomsDict[roomId] = roomObj;
    });

    var out = {
      file: fileHint,
      page_width_px: ingState.planW || 0,
      page_height_px: ingState.planH || 0,
      rooms: roomsDict,
    };

    // Métadonnées floor (PREPROCESSED_JSON_SPEC §1). Persistées seulement
    // si renseignées pour respecter la convention d'omission.
    if (ingState.buildingId) out.building_id = ingState.buildingId;
    if (ingState.floorId)    out.floor_id    = ingState.floorId;
    if (typeof ingState.northAngleDeg === 'number' &&
        ingState.northAngleDeg !== 0) {
      out.north_angle_deg = ingState.northAngleDeg;
    }

    // D-135 : persiste "au moins un scan a été effectué". Sert de défaut
    // pour la case Lock walls de la toolbar Floor au prochain chargement.
    if (ingState.firstScanDone) out.first_scan_done = true;

    // D-95 : persistance de l'échelle dans les deux champs.
    if (ingState.scale && ingState.scale > 0) {
      var dpiExp = window.olmScale.getRenderDpi();
      if (dpiExp > 0) {
        // D-274 Lot 1 : formule « 1:N » centralisée (units.js).
        var scaleTxtExp = window.cmPerPxToScaleText(ingState.scale, dpiExp);
        if (scaleTxtExp) out.drawing_scale_text = scaleTxtExp;
      }
      out.drawing_scale_measured = ingState.scale.toFixed(4) + ' cm/px';
    }

    return { payload: out, planName: planName };
  }

  // Save to disk via server endpoint.
  var _saveFlashTimer = null;
  function _flashSaveBtn(text, color) {
    var btn = document.getElementById('btnSavePlan');
    if (!btn) return;
    // Capture the resting label once. Overlapping flashes (e.g. a second save
    // within the 2 s window) must NOT restore a transient "Saved"/green state
    // as if it were the baseline — otherwise the button stays green.
    if (btn.dataset.restText === undefined) btn.dataset.restText = btn.textContent;
    if (_saveFlashTimer) clearTimeout(_saveFlashTimer);
    btn.textContent = text;
    btn.style.color = color || '';
    _saveFlashTimer = setTimeout(function () {
      btn.textContent = btn.dataset.restText;
      btn.style.color = '';
      _saveFlashTimer = null;
    }, 2000);
  }

  function savePlanToDisk() {
    var ingState = window.ingState;
    if (!ingState || !ingState.rooms || ingState.rooms.length === 0) {
      alertModal('No rooms to save. Load a floor plan first.');
      return;
    }
    var res = serializeForStorage();
    if (!res || !res.planName) {
      alertModal('Cannot determine plan name.');
      return;
    }
    var planId = res.planName;
    var statusEl = document.getElementById('ingStatus');
    if (statusEl) statusEl.textContent = 'Saving...';
    fetch('/api/plans/' + encodeURIComponent(planId) + '/save', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(res.payload),
    })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.error) {
          alertModal('Save error: ' + data.error);
          if (statusEl) statusEl.textContent = 'Save failed';
          _flashSaveBtn('Save failed', 'var(--bad)');
        } else {
          if (statusEl) statusEl.textContent = 'Saved';
          _flashSaveBtn('Saved', 'var(--ok)');
        }
      })
      .catch(function (e) {
        alertModal('Save error: ' + e);
        if (statusEl) statusEl.textContent = 'Save failed';
        _flashSaveBtn('Save failed', 'var(--bad)');
      });
  }

  // Wrapper UI : déclenche le téléchargement du JSON v3.
  function devExportV3Json() {
    var ingState = window.ingState;
    if (!ingState || !ingState.rooms || ingState.rooms.length === 0) {
      alertModal('No rooms to export. Load a floor plan first.');
      return;
    }
    var res = serializeForStorage();
    if (!res) return;
    var json = JSON.stringify(res.payload, null, 2);
    var blob = new Blob([json], { type: 'application/json' });
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url;
    var stem = res.planName || 'plan';
    a.download = stem + '.json';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  // ==========================================================================
  // Destination 3 : Export plan (D-196)
  // POST /api/floor-plan/export/<fmt> — backend writes image + CSV to disk.
  // ==========================================================================

  /**
   * Enrich candidate.desks with chair_side by walking candidate.pattern.
   * Desk order matches compute_desk_positions: rows → blocks → desks.
   */
  function _enrichDesksWithChairSide(candidate) {
    if (!candidate || !candidate.desks || !candidate.pattern) return;
    var idx = 0;
    var rows = candidate.pattern.rows || [];
    for (var ri = 0; ri < rows.length; ri++) {
      var blocks = rows[ri].blocks || [];
      for (var bi = 0; bi < blocks.length; bi++) {
        var b = blocks[bi];
        var rects = getDeskRects(b.type);
        var orient = b.orientation || 0;
        if (orient !== 0) {
          var g0 = getBlockGeom(b.type);
          rects = transformDeskRects(rects, g0.eo, g0.ns, orient);
        }
        for (var di = 0; di < rects.length; di++) {
          if (idx < candidate.desks.length) {
            candidate.desks[idx].chair_side = rects[di].chairSide;
          }
          idx++;
        }
      }
    }
  }

  // Build one room's export payload. D-237 : only an explicitly committed
  // layout ships its desks — either *saved* (Save layout button) or
  // *amended* (edited in the layout editor, D-259). `useBestFallback`
  // (opt-in, D-246) lets a room without a committed layout export its best
  // matching candidate instead.
  function _buildExportRoom(r, useBestFallback) {
    var fpAmendments = window.fpAmendments || {};
    var saved = fpAmendments[r.name];
    var candidate = null;
    var isAmended = false;
    if (saved && (saved.saved || saved.amended)) {
      candidate = JSON.parse(JSON.stringify(saved));
      isAmended = true;
    } else if (useBestFallback && r.all_candidates && r.all_candidates.length) {
      // Best candidate for the current standard, else first available.
      var std = (typeof getCurrentStandard === 'function')
        ? getCurrentStandard() : '';
      var best = null;
      var bestName = (std && r.by_standard) ? r.by_standard[std] : null;
      if (bestName) {
        best = r.all_candidates.find(function (c) {
          return c.pattern_name === bestName && c.standard === std;
        });
      }
      if (!best) best = r.all_candidates[0];
      if (best) candidate = JSON.parse(JSON.stringify(best));
    }
    if (candidate && candidate.desks && candidate.desks.length
        && candidate.pattern) {
      _enrichDesksWithChairSide(candidate);
    }
    return {
      name: r.name,
      width_cm: r.width_cm,
      depth_cm: r.depth_cm,
      bbox_px: r.bbox_px,
      corridor_face_abs: r.corridor_face_abs || '',
      is_amended: isAmended,
      candidate: candidate,
    };
  }

  // Build the full export/preview payload from current state.
  // useBestFallback: if true, rooms without a saved layout get the best
  // matching candidate instead (D-246 fallback mode).
  function _buildExportPayload(planId, scaleCmPerPx, useBestFallback) {
    var rooms = fpData.rooms.map(function (r) {
      return _buildExportRoom(r, useBestFallback);
    });
    return {
      plan_id: planId,
      scale_cm_per_px: scaleCmPerPx,
      rooms: rooms,
    };
  }

  function _postExport(fmt, planId, scaleCmPerPx, rooms) {
    showModal('Exporting ' + fmt.toUpperCase() + '...');
    fetch('/api/floor-plan/export/' + encodeURIComponent(fmt), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        plan_id: planId,
        scale_cm_per_px: scaleCmPerPx,
        rooms: rooms,
      }),
    })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        hideModal();
        if (data.error) {
          alertModal('Export failed: ' + data.error);
        } else {
          var folder = data.exports_dir
            ? 'exports/' + data.exports_dir.split(/[\\/]/).pop()
            : 'exports/';
          alertModal(
            'Exported successfully (' + (data.n_rooms || '?') +
            ' rooms).\nFiles saved in ' + folder
          );
        }
      })
      .catch(function (e) {
        hideModal();
        console.error('Export error:', e);
        alertModal('Export failed: ' + e);
      });
  }

  function exportPlan(fmt) {
    var ingState = window.ingState;
    var fpData = window.fpData;
    if (!fpData || !fpData.rooms || !fpData.rooms.length) {
      alertModal('No floor plan loaded.');
      return;
    }
    var hdr = document.getElementById('hdrCurrentPlanText');
    var planId = hdr ? hdr.textContent.trim() : '';
    if (!planId) {
      alertModal('Cannot determine plan name.');
      return;
    }
    var scaleCmPerPx = (ingState && ingState.scale) || 0;
    if (!scaleCmPerPx || scaleCmPerPx <= 0) {
      alertModal('Scale not available.');
      return;
    }

    // D-237 : export only rooms with an explicitly saved layout.
    var fpAmendments = window.fpAmendments || {};
    var nSaved = fpData.rooms.filter(function (r) {
      var s = fpAmendments[r.name];
      return s && s.saved;
    }).length;

    // D-246 : no saved layout → warn instead of producing a desk-less plan,
    // and offer to export the best matching candidate of each room.
    if (nSaved === 0) {
      confirmModal(
        'No room has a saved layout — the export would contain no ' +
        'workstations.\n\nExport the best matching candidate for each ' +
        'room instead?'
      ).then(function (ok) {
        if (!ok) return;
        var go = function () {
          var payload = _buildExportPayload(planId, scaleCmPerPx, true);
          _postExport(fmt, planId, scaleCmPerPx, payload.rooms);
        };
        // Best candidate needs every room matched (lazy matching, A).
        if (typeof window.ensureAllMatched === 'function') {
          showModal('Matching rooms...');
          window.ensureAllMatched(function () { hideModal(); go(); });
        } else {
          go();
        }
      });
      return;
    }

    var payload = _buildExportPayload(planId, scaleCmPerPx, false);
    _postExport(fmt, planId, scaleCmPerPx, payload.rooms);
  }

  // Preview: same payload as export, rendered as PNG in a lightbox.
  // Skips the D-246 confirmModal but replicates its fallback logic.
  function previewPlan() {
    var ingState = window.ingState;
    var fpData = window.fpData;
    if (!fpData || !fpData.rooms || !fpData.rooms.length) {
      alertModal('No floor plan loaded.');
      return;
    }
    var hdr = document.getElementById('hdrCurrentPlanText');
    var planId = hdr ? hdr.textContent.trim() : '';
    if (!planId) {
      alertModal('Cannot determine plan name.');
      return;
    }
    var scaleCmPerPx = (ingState && ingState.scale) || 0;
    if (!scaleCmPerPx || scaleCmPerPx <= 0) {
      alertModal('Scale not available.');
      return;
    }

    var fpAmendments = window.fpAmendments || {};
    var nSaved = fpData.rooms.filter(function (r) {
      var s = fpAmendments[r.name];
      return s && (s.saved || s.amended);
    }).length;

    var btn = document.getElementById('btnPreviewPlan');
    if (btn) btn.disabled = true;

    var doPreview = function (useBestFallback) {
      showModal('Generating preview...');
      var payload = _buildExportPayload(planId, scaleCmPerPx, useBestFallback);
      fetch('/api/floor-plan/preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
        .then(function (r) {
          if (!r.ok) {
            return r.json().then(function (e) {
              return Promise.reject(e.error || 'Preview failed');
            });
          }
          return r.blob();
        })
        .then(function (blob) {
          hideModal();
          var blobUrl = URL.createObjectURL(blob);
          // Load image to get natural dimensions
          var tmpImg = new Image();
          tmpImg.onload = function () {
            window.openPreviewLightbox(blobUrl, tmpImg.naturalWidth, tmpImg.naturalHeight);
          };
          tmpImg.onerror = function () {
            URL.revokeObjectURL(blobUrl);
            alertModal('Failed to decode preview image.');
          };
          tmpImg.src = blobUrl;
        })
        .catch(function (e) {
          hideModal();
          alertModal('Preview failed: ' + e);
        })
        .finally(function () {
          if (btn) btn.disabled = false;
        });
    };

    if (nSaved === 0) {
      // No saved layout: use best fallback, ensure all rooms matched first.
      if (typeof window.ensureAllMatched === 'function') {
        showModal('Generating preview...');
        window.ensureAllMatched(function () {
          hideModal();
          doPreview(true);
        });
      } else {
        doPreview(true);
      }
    } else {
      doPreview(false);
    }
  }

  // ==========================================================================
  // API publique
  // ==========================================================================
  window.olmSerialize = {
    serializeForMatching: serializeForMatching,
    serializeForStorage:  serializeForStorage,
  };
  window.populateRoomsJson = populateRoomsJson;
  window.savePlanToDisk    = savePlanToDisk;
  window.devExportV3Json   = devExportV3Json;
  window.exportPlan        = exportPlan;
  window.previewPlan       = previewPlan;
})();

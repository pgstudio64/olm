// door_arc_runner.js — non-régression rendu d'arc de porte (doorSvg).
//
// Exécute renderShared.doorSvg sur les 16 combinaisons
// (face × hinge_side × opens_inward) et, pour chaque arc SVG produit,
// calcule son CENTRE géométrique réel (conversion endpoint→center du W3C)
// puis vérifie qu'il coïncide avec la charnière attendue. Un arc « à
// l'envers » (sweep flag faux) a son centre sur le coin opposé : c'est le
// bug corrigé sur la face ouest (cf. Decisions D-322).
//
// Usage: node olm/tests/js/door_arc_runner.js
// Requires: Node.js (aucune dépendance npm).

"use strict";

var fs = require("fs");
var path = require("path");

// Shim browser globals — render_shared.js n'a besoin que de window.
global.window = {};

var jsPath = path.join(__dirname, "..", "..", "static", "render_shared.js");
eval(fs.readFileSync(jsPath, "utf-8"));  // eslint-disable-line no-eval

var doorSvg = global.window.renderShared && global.window.renderShared.doorSvg;
if (typeof doorSvg !== "function") {
  process.stderr.write("ERROR: renderShared.doorSvg introuvable\n");
  process.exit(1);
}

// --- parse "M x y A rx ry rot large sweep ex ey" ---
function parseArc(p) {
  var re = /M\s+([-\d.]+)\s+([-\d.]+)\s+A\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+([01])\s+([01])\s+([-\d.]+)\s+([-\d.]+)/;
  var m = p.match(re);
  if (!m) throw new Error("pas d'arc dans: " + p);
  return { x1: +m[1], y1: +m[2], rx: +m[3], ry: +m[4],
           large: +m[6], sweep: +m[7], x2: +m[8], y2: +m[9] };
}

// --- conversion endpoint→center (W3C SVG, cas rx=ry, rotation=0) ---
function arcCenter(a) {
  var x1p = (a.x1 - a.x2) / 2, y1p = (a.y1 - a.y2) / 2, r = a.rx;
  var d2 = x1p * x1p + y1p * y1p;
  var radicand = Math.max(0, (r * r - d2) / d2);
  var coef = (a.large !== a.sweep ? 1 : -1) * Math.sqrt(radicand);
  return { cx: coef * y1p + (a.x1 + a.x2) / 2,
           cy: coef * (-x1p) + (a.y1 + a.y2) / 2 };
}

// Pièce de référence (cm = px). Porte offset=100, largeur=80.
var ROOMW = 600, ROOMD = 400, OFF = 100, WID = 80;

// Dérivation hinge/free identique à editor.js renderRoomElements.
function coords(face, swing) {
  var dw = WID, hingeAtStart = (swing === "left");
  var along = OFF, wallCoord;
  if (face === "south") wallCoord = ROOMD;
  else if (face === "north") wallCoord = 0;
  else if (face === "east") wallCoord = ROOMW;
  else wallCoord = 0;  // west
  return {
    hingeCoord: hingeAtStart ? along : along + dw,
    freeCoord: hingeAtStart ? along + dw : along,
    wallCoord: wallCoord, dw: dw,
  };
}
// Point charnière attendu en coords SVG (axe « along » = x pour N/S, y pour E/W).
function hingePoint(face, c) {
  return (face === "south" || face === "north")
    ? { x: c.hingeCoord, y: c.wallCoord }
    : { x: c.wallCoord, y: c.hingeCoord };
}
function near(a, b) { return Math.abs(a - b) < 0.6; }

var results = [];
["north", "south", "east", "west"].forEach(function (face) {
  ["left", "right"].forEach(function (swing) {
    [true, false].forEach(function (inward) {
      var c = coords(face, swing);
      var parts = doorSvg(face, c.hingeCoord, c.freeCoord, c.wallCoord,
                          swing, inward, 1.5);
      var ctr = arcCenter(parseArc(parts[0]));
      var H = hingePoint(face, c);
      results.push({
        face: face, swing: swing, inward: inward,
        center_at_hinge: near(ctr.cx, H.x) && near(ctr.cy, H.y),
      });
    });
  });
});

process.stdout.write(JSON.stringify(results, null, 2) + "\n");

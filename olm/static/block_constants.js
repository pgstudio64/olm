"use strict";

const COLOR_DESK_FILL    = "#d0d0d0";
const COLOR_DESK_STROKE  = "#888888";
const COLOR_NSUP_FILL    = "#3b7dc9";      // zones fixes débattement chaise (non-superposable) — bleu
const COLOR_NSUP_STROKE  = "#4a90d9";
const COLOR_NSUP_OPACITY = 0.40;
const COLOR_CAND_FILL    = "#2e2e2e";      // zones minimales de circulation (obligatoires, extensibles) — anthracite
const COLOR_CAND_STROKE  = "#333333";
const COLOR_CAND_OPACITY = 1.0;
const COLOR_BLOCK_BORDER = "#333333";
const COLOR_GRID         = "#2a2826";
const COLOR_GRID_METER   = "#3a3836";
const COLOR_RULER        = "#6e6a62";
const COLOR_GAP_LABEL    = "#c8a050";
const COLOR_LABEL        = "#555555";
const COLOR_SCREEN       = "#1a1a1a";
const COLOR_CHAIR        = "#8B6914";
const COLOR_CHAIR_BACK   = "#6a4e0e";
const COLOR_CHAIR_ARM    = "#7a5c10";

const DESK_W = 80;   // cm, largeur poste axe regard
const DESK_D = 180;  // cm, profondeur poste
const CHAIR_W_CM = 65;   // cm, largeur assise fauteuil
const CHAIR_D_CM = 60;   // cm, profondeur assise fauteuil

const FACE_ROTATE_MAP = {
  90:  { north: "west", east: "north", south: "east", west: "south" },
  180: { north: "south", east: "west", south: "north", west: "east" },
  270: { north: "east", east: "south", south: "west", west: "north" },
};

const SIDE_ROTATE_MAP = {
  90:  { N: "E", E: "S", S: "W", W: "N" },
  180: { N: "S", S: "N", E: "W", W: "E" },
  270: { N: "W", W: "S", S: "E", E: "N" },
};

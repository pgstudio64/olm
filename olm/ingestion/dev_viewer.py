import os, sys, io, time

_BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _BASE)
sys.path.insert(0, os.path.join(_BASE, 'olm', 'ingestion'))

from flask import Flask, send_file, render_template_string, request

app = Flask(__name__)

HTML = """<!DOCTYPE html>
<html><head><title>OLM Ingestion</title>
<style>
body{font-family:sans-serif;background:#1a1a2e;color:#eee;margin:0;padding:20px}
h1{color:#e8b04a}
.controls{display:flex;gap:20px;margin:15px 0;flex-wrap:wrap;align-items:center}
.controls label{cursor:pointer;display:flex;align-items:center;gap:6px;
  padding:6px 12px;border-radius:6px;border:1px solid #333}
.controls label:hover{background:#16213e}
.controls label.active{background:#16213e;border-color:#e8b04a}
.controls input[type=checkbox]{accent-color:#e8b04a;width:16px;height:16px}
.swatch{display:inline-block;width:20px;height:6px;border-radius:2px}
.key{font-size:11px;color:#888;margin-left:4px}
img{max-width:100%;border:2px solid #333;border-radius:4px;margin-top:10px}
</style></head><body>
<h1>OLM Ingestion Viewer</h1>
<div class="controls">
  <label><input type="checkbox" id="cb_bbox" checked>
    <span class="swatch" style="background:#dc1e1e"></span> Room bbox <span class="key">(R)</span></label>
  <label><input type="checkbox" id="cb_window" checked>
    <span class="swatch" style="background:#64b4ff"></span> Windows <span class="key">(W)</span></label>
  <label><input type="checkbox" id="cb_door" checked>
    <span class="swatch" style="background:#1eb41e"></span> Doors <span class="key">(D)</span></label>
  <label><input type="checkbox" id="cb_opening" checked>
    <span class="swatch" style="background:#ffa032"></span> Openings <span class="key">(O)</span></label>
  <label><input type="checkbox" id="cb_names" checked>
    <span class="swatch" style="background:#dc1e1e"></span> Names <span class="key">(N)</span></label>
  <label><input type="checkbox" id="cb_vrays">
    <span class="swatch" style="background:#0c8"></span> V-Rays <span class="key">(V)</span></label>
  <label><input type="checkbox" id="cb_hrays">
    <span class="swatch" style="background:#c40"></span> H-Rays <span class="key">(H)</span></label>
  <label><input type="checkbox" id="cb_candidates">
    <span class="swatch" style="background:#ff0"></span> Candidates <span class="key">(C)</span></label>
</div>
<div style="margin:10px 0">
  <label>Room: <input type="text" id="room_input" placeholder="ex: 916" style="width:80px;padding:4px;background:#16213e;color:#eee;border:1px solid #e8b04a44;border-radius:4px"></label>
  <span class="key">(vide = plan complet)</span>
</div>
<img id="plan" src="">
<script>
const keys = {r:'bbox', w:'window', d:'door', o:'opening', n:'names', v:'vrays', h:'hrays', c:'candidates'};
function refresh() {
  const p = new URLSearchParams();
  for (const id of ['bbox','window','door','opening','names','vrays','hrays','candidates'])
    p.set(id, document.getElementById('cb_'+id).checked ? '1' : '0');
  const room = document.getElementById('room_input').value.trim();
  if (room) p.set('room', room);
  p.set('_', Date.now());
  document.getElementById('plan').src = '/img?' + p.toString();
}
document.getElementById('room_input').addEventListener('change', refresh);
for (const cb of document.querySelectorAll('input[type=checkbox]'))
  cb.addEventListener('change', refresh);
document.addEventListener('keydown', function(e) {
  const id = keys[e.key.toLowerCase()];
  if (id) { const cb = document.getElementById('cb_'+id); cb.checked = !cb.checked; refresh(); }
});
refresh();
</script>
</body></html>"""


@app.route('/')
def index():
    return render_template_string(HTML)


@app.route('/img')
def img():
    show_bbox = request.args.get('bbox', '1') == '1'
    show_window = request.args.get('window', '1') == '1'
    show_door = request.args.get('door', '1') == '1'
    show_opening = request.args.get('opening', '1') == '1'
    show_names = request.args.get('names', '1') == '1'
    show_vrays = request.args.get('vrays', '0') == '1'
    show_hrays = request.args.get('hrays', '0') == '1'
    show_candidates = request.args.get('candidates', '0') == '1'

    import numpy as np
    from PIL import Image, ImageDraw, ImageFont
    from olm.ingestion.extract import binarize, remove_non_ortho, _classify_wall_direct
    from test_comb import (load_image, find_seeds_by_ocr, erase_cartouches,
                           binarize as comb_binarize, remove_non_ortho as comb_rno,
                           detect_room, comb_collect_hits, largest_rect_no_hits,
                           snap_through_white, expand_door_arcs,
                           COMB_STEP_PX)

    plan_path = os.path.join(_BASE, 'project', 'plans', 'test_floorplan3.png')
    img_gray = load_image(plan_path)
    seeds, cart_bboxes = find_seeds_by_ocr(img_gray)
    gray_arr = np.array(img_gray)
    cleaned = erase_cartouches(gray_arr, cart_bboxes)
    comb_bin = comb_binarize(cleaned)
    # Single binarization for everything (comb + wall classification + display)
    binary_d = comb_bin  # same threshold for wall classification
    binary_r = comb_bin

    rooms = {}
    room_seeds = {}
    room_hits = {}
    room_candidates = {}
    all_seed_positions = list(seeds.values())
    for name, (cx, cy) in seeds.items():
        other = [(ox, oy) for ox, oy in all_seed_positions if (ox, oy) != (cx, cy)]
        all_hits, dir_hits = comb_collect_hits(comb_bin, cx, cy, COMB_STEP_PX,
                                               other_seeds=other)
        best, candidates = largest_rect_no_hits(all_hits, cx, cy, return_all=True)
        if best is None:
            best = (cx - 1, cy - 1, cx + 1, cy + 1)
        rect = snap_through_white(comb_bin, best)
        rect, doors = expand_door_arcs(comb_bin, rect, all_hits, cx, cy)
        rooms[name] = rect
        room_seeds[name] = (cx, cy)
        room_hits[name] = all_hits
        room_candidates[name] = candidates
        rooms[name + '__doors'] = doors  # keyed separately

    # Background = binarized image (what the algorithm actually uses)
    bin_rgb = np.stack([~comb_bin * 255] * 3, axis=-1).astype(np.uint8)
    out = Image.fromarray(bin_rgb)
    draw = ImageDraw.Draw(out)
    BBOX_COLOR = (220, 30, 30)
    COLORS = {'window': (100, 180, 255), 'door': (30, 180, 30), 'opening': (255, 160, 50)}
    SHOW = {'window': show_window, 'door': show_door, 'opening': show_opening}
    LINE_W = 6
    OFFSET = 3
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 14)
    except Exception:
        font = ImageFont.load_default()

    for name in sorted(k for k in rooms if '__' not in k):
        bbox = rooms[name]
        x0, y0, x1, y1 = bbox
        if show_bbox:
            draw.rectangle([x0, y0, x1, y1], outline=BBOX_COLOR, width=2)
        if show_names:
            mid_x, mid_y = (x0 + x1) // 2, (y0 + y1) // 2
            tb = draw.textbbox((0, 0), name, font=font)
            draw.text((mid_x - (tb[2] - tb[0]) // 2, mid_y - (tb[3] - tb[1]) // 2),
                      name, fill=BBOX_COLOR, font=font)
        for face in ('north', 'south', 'east', 'west'):
            segs, _ = _classify_wall_direct(binary_d, binary_r, bbox, face, 5)
            for seg in segs:
                if seg.kind not in COLORS or not SHOW.get(seg.kind):
                    continue
                color = COLORS[seg.kind]
                sp, ep = seg.start_px, seg.end_px
                if face == 'north':
                    draw.line([(x0 + sp, y0 - OFFSET), (x0 + ep, y0 - OFFSET)],
                              fill=color, width=LINE_W)
                elif face == 'south':
                    draw.line([(x0 + sp, y1 + OFFSET), (x0 + ep, y1 + OFFSET)],
                              fill=color, width=LINE_W)
                elif face == 'west':
                    draw.line([(x0 - OFFSET, y0 + sp), (x0 - OFFSET, y0 + ep)],
                              fill=color, width=LINE_W)
                elif face == 'east':
                    draw.line([(x1 + OFFSET, y0 + sp), (x1 + OFFSET, y0 + ep)],
                              fill=color, width=LINE_W)

    # Draw detected doors (green: opening line + jamb ticks + arc indication)
    if show_door:
        DOOR_COLOR = (30, 220, 30)
        for name in sorted(k for k in rooms if '__' not in k):
            door_list = rooms.get(name + '__doors', [])
            x0, y0, x1, y1 = rooms[name]
            for d in door_list:
                face = d['face']
                jh = d['jamb_hinge_px']  # absolute position
                jf = d['jamb_free_px']
                wall = d['wall_px']
                # Draw door opening line (on the expanded wall)
                if face == 'north':
                    draw.line([(jh, wall), (jf, wall)], fill=DOOR_COLOR, width=3)
                    # Jamb ticks (connecting rectangle edge to door wall)
                    draw.line([(jh, y0), (jh, wall)], fill=DOOR_COLOR, width=2)
                    draw.line([(jf, y0), (jf, wall)], fill=DOOR_COLOR, width=2)
                elif face == 'south':
                    draw.line([(jh, wall), (jf, wall)], fill=DOOR_COLOR, width=3)
                    draw.line([(jh, y1), (jh, wall)], fill=DOOR_COLOR, width=2)
                    draw.line([(jf, y1), (jf, wall)], fill=DOOR_COLOR, width=2)
                elif face == 'west':
                    draw.line([(wall, jh), (wall, jf)], fill=DOOR_COLOR, width=3)
                    draw.line([(x0, jh), (wall, jh)], fill=DOOR_COLOR, width=2)
                    draw.line([(x0, jf), (wall, jf)], fill=DOOR_COLOR, width=2)
                elif face == 'east':
                    draw.line([(wall, jh), (wall, jf)], fill=DOOR_COLOR, width=3)
                    draw.line([(x1, jh), (wall, jh)], fill=DOOR_COLOR, width=2)
                    draw.line([(x1, jf), (wall, jf)], fill=DOOR_COLOR, width=2)

    # Draw rays if enabled
    room_filter = request.args.get('room', '')
    if show_vrays or show_hrays:
        real_rooms = [k for k in rooms if '__' not in k]
        ray_rooms = [room_filter] if room_filter and room_filter in rooms else real_rooms
        for name in ray_rooms:
            scx, scy = room_seeds[name]
            for hx, hy in room_hits[name]:
                if hy < scy and show_vrays:       # north: vertical
                    draw.line([(hx, scy), (hx, hy)], fill=(0, 200, 0), width=1)
                elif hy > scy and show_vrays:     # south: vertical
                    draw.line([(hx, scy), (hx, hy)], fill=(0, 150, 200), width=1)
                elif hx < scx and show_hrays:     # west: horizontal
                    draw.line([(scx, hy), (hx, hy)], fill=(200, 0, 0), width=1)
                elif hx > scx and show_hrays:     # east: horizontal
                    draw.line([(scx, hy), (hx, hy)], fill=(200, 100, 0), width=1)
            # Hits as yellow dots
            for hx, hy in room_hits[name]:
                is_v = (hy != scy)
                is_h = (hx != scx)
                if (is_v and show_vrays) or (is_h and show_hrays):
                    draw.ellipse([hx - 2, hy - 2, hx + 2, hy + 2], fill=(255, 255, 0))
            # Seed as green dot
            draw.ellipse([scx - 3, scy - 3, scx + 3, scy + 3], fill=(0, 255, 0))

    # Draw candidate rectangles (top N by area)
    if show_candidates:
        real_rooms2 = [k for k in rooms if '__' not in k]
        cand_rooms = [room_filter] if room_filter and room_filter in rooms else real_rooms2
        for name in cand_rooms:
            candidates = room_candidates.get(name, [])
            # Draw top 10 candidates (largest first), fading opacity
            for idx, (crect, carea) in enumerate(candidates[:10]):
                cx0, cy0, cx1, cy1 = crect
                alpha = max(40, 255 - idx * 25)
                color = (255, 255, 0) if idx == 0 else (200, 200, 100)
                w = 3 if idx == 0 else 1
                draw.rectangle([cx0, cy0, cx1, cy1], outline=color, width=w)

    # Crop to single room if requested
    if room_filter and room_filter in rooms:
        rx0, ry0, rx1, ry1 = rooms[room_filter]
        m = 60
        out = out.crop((max(0, rx0 - m), max(0, ry0 - m),
                        min(out.width, rx1 + m), min(out.height, ry1 + m)))

    buf = io.BytesIO()
    out.save(buf, format='PNG')
    buf.seek(0)
    return send_file(buf, mimetype='image/png')


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5070, debug=False)

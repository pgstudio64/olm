import os
import tempfile
from flask import Flask, send_file, render_template_string

app = Flask(__name__)

_TMP = tempfile.gettempdir()

IMAGES = {
    "source": (os.path.join(_TMP, "source_plan.png"), "Source plan"),
    "cartouches": (os.path.join(_TMP, "cartouche_boxes.png"), "Cartouches (red boxes)"),
    "bin80": (os.path.join(_TMP, "binarized_80.png"), "Threshold 80"),
    "cleaned": (os.path.join(_TMP, "cleaned_plan.png"), "Cleaned plan"),
    "raycast": (os.path.join(_TMP, "raycast_debug.png"), "Ray-cast debug"),
    "filtered": (os.path.join(_TMP, "extraction_filtered.png"), "Comparison"),
    "flood": (os.path.join(_TMP, "exterior_flood.png"), "Exterior flood fill"),
    "comb": (os.path.join(_TMP, "comb_all.png"), "Adaptive comb (all rooms)"),
    "comb916": (os.path.join(_TMP, "comb_916.png"), "Comb 916 (detail)"),
    "comb901": (os.path.join(_TMP, "comb_901_debug.png"), "Comb 901"),
    "comb904": (os.path.join(_TMP, "comb_904_debug.png"), "Comb 904"),
    "comb909": (os.path.join(_TMP, "comb_909_debug.png"), "Comb 909"),
    "comb919": (os.path.join(_TMP, "comb_919_debug.png"), "Comb 919"),
    "ortho": (os.path.join(_TMP, "ortho_plan.png"), "Ortho only (no arcs)"),
    "walls": (os.path.join(_TMP, "wall_classification.png"), "Wall classification"),
}

HTML = """<!DOCTYPE html>
<html><head><title>OLM Ingestion</title>
<style>
body{font-family:sans-serif;background:#1a1a2e;color:#eee;margin:0;padding:20px}
h1{color:#e8b04a}.nav{display:flex;gap:10px;margin:15px 0;flex-wrap:wrap}
.nav a{background:#16213e;color:#e8b04a;padding:8px 16px;border-radius:6px;text-decoration:none;border:1px solid #e8b04a44}
.nav a:hover,.nav a.active{background:#e8b04a;color:#1a1a2e}
img{max-width:100%;border:2px solid #333;border-radius:4px;margin-top:10px}
</style></head><body>
<h1>OLM Ingestion Viewer</h1>
<div class="nav">{% for key,(path,label) in images.items() %}<a href="/view/{{key}}" {% if key==current %}class="active"{% endif %}>{{label}}</a>{% endfor %}</div>
{% if current %}<h2>{{images[current][1]}}</h2><img src="/img/{{current}}">{% endif %}
</body></html>"""


@app.route("/")
def index():
    return render_template_string(HTML, images=IMAGES, current="cartouches")


@app.route("/view/<key>")
def view(key):
    return render_template_string(HTML, images=IMAGES, current=key)


@app.route("/img/<key>")
def img(key):
    if key in IMAGES:
        return send_file(IMAGES[key][0], mimetype="image/png")
    return "Not found", 404


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5070, debug=False)

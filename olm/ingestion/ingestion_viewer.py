from flask import Flask, send_file, render_template_string
app = Flask(__name__)
IMAGES = {
    "source": ("/tmp/source_plan.png", "Plan source"),
    "cartouches": ("/tmp/cartouche_boxes.png", "Cartouches (rectangles rouges)"),
    "bin80": ("/tmp/binarized_80.png", "Seuil 80"),
    "cleaned": ("/tmp/cleaned_plan.png", "Plan nettoyé"),
    "raycast": ("/tmp/raycast_debug.png", "Ray-cast debug"),
    "filtered": ("/tmp/extraction_filtered.png", "Comparaison"),
    "flood": ("/tmp/exterior_flood.png", "Flood fill extérieur"),
    "comb": ("/tmp/comb_all.png", "Peigne adaptatif (toutes)"),
    "comb916": ("/tmp/comb_916.png", "Peigne 916 (détail)"),
    "comb901": ("/tmp/comb_901_debug.png", "Peigne 901"),
    "comb904": ("/tmp/comb_904_debug.png", "Peigne 904"),
    "comb909": ("/tmp/comb_909_debug.png", "Peigne 909"),
    "comb919": ("/tmp/comb_919_debug.png", "Peigne 919"),
    "closed": ("/tmp/closed_plan.png", "Fermeture morpho"),
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
def index(): return render_template_string(HTML,images=IMAGES,current="cartouches")
@app.route("/view/<key>")
def view(key): return render_template_string(HTML,images=IMAGES,current=key)
@app.route("/img/<key>")
def img(key):
    if key in IMAGES: return send_file(IMAGES[key][0],mimetype="image/png")
    return "Not found",404
if __name__=="__main__": app.run(host="0.0.0.0",port=5070,debug=False)

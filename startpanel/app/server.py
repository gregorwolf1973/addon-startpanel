import os
import json
import base64
import logging
from flask import Flask, render_template, jsonify, request, Response
from werkzeug.middleware.proxy_fix import ProxyFix
import requests

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_prefix=1)

SUPERVISOR_TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")
SUPERVISOR_URL = "http://supervisor"
HEADERS = {"Authorization": f"Bearer {SUPERVISOR_TOKEN}"}
PORT = 8099
SETTINGS_FILE = "/data/settings.json"
CUSTOM_ICON_DIR = "/data/custom_icons"

log.info("=== Startpanel booting, SUPERVISOR_TOKEN present: %s ===", bool(SUPERVISOR_TOKEN))

_icon_cache: dict[str, bytes] = {}
_ha_urls: dict[str, str] = {}

_FALLBACK_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


# ── Settings persistence ──────────────────────────────────────────
def load_settings() -> dict:
    try:
        with open(SETTINGS_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_settings(data: dict):
    os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
    with open(SETTINGS_FILE, "w") as f:
        json.dump(data, f, indent=2)


# ── HA URLs ───────────────────────────────────────────────────────
def get_ha_urls() -> dict:
    global _ha_urls
    if not _ha_urls:
        data = supervisor_get("/core/info").get("data", {})
        _ha_urls = {
            "internal_url": data.get("internal_url", ""),
            "external_url": data.get("external_url", ""),
        }
        log.info("HA URLs: internal=%s, external=%s", _ha_urls["internal_url"], _ha_urls["external_url"])
    return _ha_urls


# ── Supervisor API ────────────────────────────────────────────────
def supervisor_get(path: str) -> dict:
    try:
        r = requests.get(f"{SUPERVISOR_URL}{path}", headers=HEADERS, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log.error("Supervisor API error %s: %s", path, e)
        return {}


def build_addon_list() -> tuple[list, list]:
    raw = supervisor_get("/addons")
    addons_raw = raw.get("data", {}).get("addons", [])

    running, stopped = [], []

    for a in addons_raw:
        slug = a.get("slug", "")
        state = a.get("state", "unknown")
        has_ingress = bool(a.get("ingress"))

        detail = supervisor_get(f"/addons/{slug}/info").get("data", {})
        network_raw = detail.get("network") or {}
        ingress_port = detail.get("ingress_port")
        ports = []
        for key, val in network_raw.items():
            if val is None:
                continue
            try:
                container_port = int(key.split("/")[0])
                host_port = int(val)
                if ingress_port and container_port == int(ingress_port):
                    continue
                ports.append(host_port)
            except (ValueError, AttributeError):
                pass

        entry = {
            "slug": slug,
            "name": a.get("name", slug),
            "version": a.get("version", ""),
            "state": state,
            "has_ingress": has_ingress,
            "has_icon": _addon_has_icon(slug),
            "ports": ports,
        }

        if state == "started":
            running.append(entry)
        else:
            stopped.append(entry)

    running.sort(key=lambda x: x["name"].lower())
    stopped.sort(key=lambda x: x["name"].lower())
    return running, stopped


def _addon_has_icon(slug: str) -> bool:
    custom_path = os.path.join(CUSTOM_ICON_DIR, f"{slug}.png")
    if os.path.isfile(custom_path):
        return True
    try:
        r = requests.head(f"{SUPERVISOR_URL}/addons/{slug}/icon", headers=HEADERS, timeout=5)
        return r.status_code == 200
    except Exception:
        return False


# ── Routes ────────────────────────────────────────────────────────
@app.route("/")
def index():
    running, stopped = build_addon_list()
    ha_urls = get_ha_urls()
    settings = load_settings()
    custom_cards = settings.get("customCards", [])
    return render_template("index.html", running=running, stopped=stopped, ha_urls=ha_urls, custom_cards=custom_cards)


@app.route("/icon/<slug>")
def icon(slug: str):
    # Check custom icon first
    custom_path = os.path.join(CUSTOM_ICON_DIR, f"{slug}.png")
    if os.path.isfile(custom_path):
        with open(custom_path, "rb") as f:
            return Response(f.read(), mimetype="image/png")

    if slug in _icon_cache:
        return Response(_icon_cache[slug], mimetype="image/png")
    try:
        r = requests.get(f"{SUPERVISOR_URL}/addons/{slug}/icon", headers=HEADERS, timeout=10)
        if r.status_code == 200:
            _icon_cache[slug] = r.content
            return Response(r.content, mimetype="image/png")
    except Exception as e:
        log.warning("Icon fetch failed for %s: %s", slug, e)
    return Response(_FALLBACK_PNG, mimetype="image/png")


@app.route("/api/icon/<slug>", methods=["POST"])
def upload_icon(slug: str):
    if "file" not in request.files:
        return jsonify(ok=False, error="No file"), 400
    file = request.files["file"]
    if not file.filename:
        return jsonify(ok=False, error="Empty filename"), 400
    os.makedirs(CUSTOM_ICON_DIR, exist_ok=True)
    save_path = os.path.join(CUSTOM_ICON_DIR, f"{slug}.png")
    file.save(save_path)
    # Clear cached supervisor icon if any
    _icon_cache.pop(slug, None)
    log.info("Custom icon saved for %s", slug)
    return jsonify(ok=True)


@app.route("/api/icon/<slug>", methods=["DELETE"])
def delete_icon(slug: str):
    custom_path = os.path.join(CUSTOM_ICON_DIR, f"{slug}.png")
    if os.path.isfile(custom_path):
        os.remove(custom_path)
        _icon_cache.pop(slug, None)
        log.info("Custom icon removed for %s", slug)
    return jsonify(ok=True)


@app.route("/api/has-custom-icon/<slug>")
def has_custom_icon(slug: str):
    custom_path = os.path.join(CUSTOM_ICON_DIR, f"{slug}.png")
    return jsonify(hasCustomIcon=os.path.isfile(custom_path))


@app.route("/api/refresh")
def api_refresh():
    global _ha_urls
    _icon_cache.clear()
    _ha_urls = {}
    running, stopped = build_addon_list()
    ha_urls = get_ha_urls()
    settings = load_settings()
    custom_cards = settings.get("customCards", [])
    return jsonify(running=running, stopped=stopped, ha_urls=ha_urls, customCards=custom_cards)


@app.route("/api/settings", methods=["GET"])
def get_settings():
    return jsonify(load_settings())


@app.route("/api/settings", methods=["POST"])
def post_settings():
    data = request.get_json(force=True)
    save_settings(data)
    return jsonify(ok=True)


if __name__ == "__main__":
    log.info("Flask starting on port %s", PORT)
    app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False)

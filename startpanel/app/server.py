import os
import logging
from flask import Flask, render_template, jsonify, Response
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

log.info("=== Startpanel booting, SUPERVISOR_TOKEN present: %s ===", bool(SUPERVISOR_TOKEN))

# Simple in-memory icon cache
_icon_cache: dict[str, bytes] = {}


def supervisor_get(path: str) -> dict:
    try:
        r = requests.get(f"{SUPERVISOR_URL}{path}", headers=HEADERS, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log.error("Supervisor API error %s: %s", path, e)
        return {}



def build_addon_list() -> tuple[list, list]:
    """Return (running_addons, stopped_addons) with all relevant fields."""
    raw = supervisor_get("/addons")
    addons_raw = raw.get("data", {}).get("addons", [])

    running, stopped = [], []

    for a in addons_raw:
        slug = a.get("slug", "")
        state = a.get("state", "unknown")

        # Fetch detailed info for port mappings and ingress token
        detail_raw = supervisor_get(f"/addons/{slug}/info")
        detail = detail_raw.get("data", {})

        # Network: maps container_port/proto -> host_port (or None)
        # Supervisor returns e.g. {"7277/tcp": 7277} or {"7277/tcp": null}
        network_raw = detail.get("network") or {}
        ports = {}
        for key, val in network_raw.items():
            if val is not None:
                try:
                    ports[str(key.split("/")[0])] = int(val)
                except (ValueError, AttributeError):
                    pass
        if not ports:
            log.debug("No ports for %s. network=%s", slug, network_raw)

        has_ingress = bool(detail.get("ingress"))
        ingress_entry = detail.get("ingress_entry") or ""

        entry = {
            "slug": slug,
            "name": a.get("name", slug),
            "description": a.get("description", ""),
            "version": a.get("version", ""),
            "state": state,
            "has_ingress": has_ingress,
            "ingress_entry": ingress_entry,
            "ports": ports,
            "has_icon": _addon_has_icon(slug),
        }

        if state == "started":
            running.append(entry)
        else:
            stopped.append(entry)

    running.sort(key=lambda x: x["name"].lower())
    stopped.sort(key=lambda x: x["name"].lower())

    return running, stopped


def _addon_has_icon(slug: str) -> bool:
    try:
        r = requests.head(
            f"{SUPERVISOR_URL}/addons/{slug}/icon",
            headers=HEADERS,
            timeout=5,
        )
        return r.status_code == 200
    except Exception:
        return False


@app.route("/")
def index():
    running, stopped = build_addon_list()
    return render_template("index.html", running=running, stopped=stopped)


@app.route("/icon/<slug>")
def icon(slug: str):
    if slug in _icon_cache:
        return Response(_icon_cache[slug], mimetype="image/png")
    try:
        r = requests.get(
            f"{SUPERVISOR_URL}/addons/{slug}/icon",
            headers=HEADERS,
            timeout=10,
        )
        if r.status_code == 200:
            _icon_cache[slug] = r.content
            return Response(r.content, mimetype="image/png")
    except Exception as e:
        log.warning("Icon fetch failed for %s: %s", slug, e)
    # Return transparent 1x1 PNG as fallback
    import base64
    fallback = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
    )
    return Response(fallback, mimetype="image/png")


@app.route("/api/refresh")
def api_refresh():
    _icon_cache.clear()
    running, stopped = build_addon_list()
    return jsonify(running=running, stopped=stopped)


if __name__ == "__main__":
    log.info("Flask starting on port %s", PORT)
    app.run(host="0.0.0.0", port=PORT, debug=True, use_reloader=False)

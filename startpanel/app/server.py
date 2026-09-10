import os
import json
import base64
import logging
import threading
import time
from urllib.parse import urlparse
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
REFRESH_INTERVAL = 60  # seconds between background supervisor polls

log.info("=== Startpanel booting, SUPERVISOR_TOKEN present: %s ===", bool(SUPERVISOR_TOKEN))

_icon_cache: dict[str, bytes] = {}
_has_icon_cache: dict[str, bool] = {}
_host_info: dict[str, str] = {}

# Cached addon list, refreshed by the background poller and on demand
_cache: dict = {"running": [], "stopped": [], "snapshot": [], "ts": 0.0}
_cache_lock = threading.Lock()
_settings_lock = threading.RLock()

_FALLBACK_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


# ── Settings persistence ──────────────────────────────────────────
def load_settings() -> dict:
    with _settings_lock:
        try:
            with open(SETTINGS_FILE) as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}


def save_settings(data: dict):
    with _settings_lock:
        os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
        tmp = SETTINGS_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, SETTINGS_FILE)


# ── Supervisor API ────────────────────────────────────────────────
def supervisor_get(path: str) -> dict:
    try:
        r = requests.get(f"{SUPERVISOR_URL}{path}", headers=HEADERS, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log.error("Supervisor API error %s: %s", path, e)
        return {}


# ── Host detection ────────────────────────────────────────────────
def _detect_host_ip() -> str:
    """Primary IPv4 of the HA host via the Supervisor network API."""
    net = supervisor_get("/network/info").get("data", {})
    interfaces = net.get("interfaces") or []
    # Prefer the primary interface, then any connected one
    ordered = sorted(interfaces, key=lambda i: (not i.get("primary"), not i.get("connected")))
    for iface in ordered:
        if not (iface.get("enabled") or iface.get("connected")):
            continue
        for addr in (iface.get("ipv4") or {}).get("address") or []:
            ip = str(addr).split("/")[0]
            if ip and not ip.startswith("127.") and not ip.startswith("169.254."):
                return ip
    return ""


def get_host_info(force: bool = False) -> dict:
    """Auto-detected host addresses: HA internal/external URL and host IP."""
    global _host_info
    if _host_info and not force:
        return _host_info
    core = supervisor_get("/core/info").get("data", {})
    internal_url = (core.get("internal_url") or "").rstrip("/")
    external_url = (core.get("external_url") or "").rstrip("/")
    host_ip = _detect_host_ip()
    if not host_ip and internal_url:
        host_ip = urlparse(internal_url).hostname or ""
    _host_info = {
        "host_ip": host_ip,
        "internal_url": internal_url,
        "external_url": external_url,
    }
    log.info("Host info: ip=%s internal=%s external=%s", host_ip, internal_url, external_url)
    return _host_info


def effective_hosts(settings: dict) -> dict:
    """Merge detected host info with the user's manual overrides from settings."""
    info = get_host_info()
    glob = settings.get("global") or {}
    override_host = (glob.get("internalHost") or "").strip().rstrip("/")
    override_ext = (glob.get("externalBase") or "").strip().rstrip("/")

    if override_host:
        # Accept "192.168.1.5", "host.local" or a full "http://host:8123"
        parsed = urlparse(override_host if "://" in override_host else f"http://{override_host}")
        internal_host = parsed.hostname or override_host
        ha_port = parsed.port or urlparse(info["internal_url"]).port or 8123
        internal_base = f"{parsed.scheme or 'http'}://{internal_host}:{ha_port}"
    else:
        internal_host = info["host_ip"] or urlparse(info["internal_url"]).hostname or ""
        internal_base = info["internal_url"] or (f"http://{internal_host}:8123" if internal_host else "")

    external_base = override_ext or info["external_url"]
    if external_base and "://" not in external_base:
        external_base = f"https://{external_base}"

    return {
        "internal_host": internal_host,
        "internal_base": internal_base,
        "external_base": external_base,
    }


# ── URL detection per addon ───────────────────────────────────────
def detect_urls(entry: dict, hosts: dict) -> dict:
    """Candidate URLs for an addon plus the chosen internal/external default.

    Internal: ingress if available, else the first mapped host port on the host IP.
    External: ingress via the external base (most likely reachable), else host + port.
    """
    slug = entry["slug"]
    ports = entry.get("ports") or []
    has_ingress = entry.get("has_ingress", False)
    c = {"ingressInternal": "", "portInternal": "", "ingressExternal": "", "portExternal": ""}

    if has_ingress and hosts["internal_base"]:
        c["ingressInternal"] = f"{hosts['internal_base']}/hassio/ingress/{slug}"
    if ports and hosts["internal_host"]:
        c["portInternal"] = f"http://{hosts['internal_host']}:{ports[0]}"
    if hosts["external_base"]:
        if has_ingress:
            c["ingressExternal"] = f"{hosts['external_base']}/hassio/ingress/{slug}"
        if ports:
            p = urlparse(hosts["external_base"])
            if p.hostname:
                c["portExternal"] = f"{p.scheme or 'https'}://{p.hostname}:{ports[0]}"

    return {
        "internalUrl": c["ingressInternal"] or c["portInternal"],
        "externalUrl": c["ingressExternal"] or c["portExternal"],
        "candidates": c,
        "hostIp": hosts["internal_host"],
        "ports": ports,
        "portMap": entry.get("port_map") or [],
        "hasIngress": has_ingress,
    }


def sync_detected(running: list, stopped: list, settings: dict | None = None) -> tuple[dict, list]:
    """Store detected addresses for every installed addon in settings.json.

    Manual URLs (internalUrl/externalUrl) are never touched – they override the
    detected values as long as they are non-empty. Returns (settings, new_slugs).
    """
    with _settings_lock:
        settings = settings if settings is not None else load_settings()
        addons = settings.setdefault("addons", {})
        hosts = effective_hosts(settings)
        now = int(time.time())
        first_run = not any(isinstance(v, dict) and "detected" in v for v in addons.values())
        changed = False
        new_slugs = []

        for e in running + stopped:
            s = addons.setdefault(e["slug"], {})
            if "firstSeen" not in s:
                s["firstSeen"] = now
                changed = True
                if not first_run:
                    new_slugs.append(e["slug"])
            det = detect_urls(e, hosts)
            det["name"] = e["name"]
            det["state"] = e["state"]
            old = dict(s.get("detected") or {})
            old.pop("updatedAt", None)
            if old != det:
                det["updatedAt"] = now
                s["detected"] = det
                changed = True

        if changed:
            save_settings(settings)
        if new_slugs:
            log.info("New addons detected: %s", ", ".join(new_slugs))
        return settings, new_slugs


# ── Addon list ────────────────────────────────────────────────────
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
        ports, port_map = [], []
        for key, val in network_raw.items():
            if val is None:
                continue
            try:
                container_port = int(key.split("/")[0])
                host_port = int(val)
                if ingress_port and container_port == int(ingress_port):
                    continue
                ports.append(host_port)
                port_map.append({"container": key, "host": host_port})
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
            "port_map": port_map,
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
    if slug in _has_icon_cache:
        return _has_icon_cache[slug]
    try:
        r = requests.head(f"{SUPERVISOR_URL}/addons/{slug}/icon", headers=HEADERS, timeout=5)
        _has_icon_cache[slug] = r.status_code == 200
    except Exception:
        _has_icon_cache[slug] = False
    return _has_icon_cache[slug]


def _snapshot(running: list, stopped: list) -> list:
    return [{"slug": e["slug"], "name": e["name"], "state": e["state"]} for e in running + stopped]


def refresh_cache() -> list:
    """Poll the supervisor, sync detected addresses and update the cache. Returns new slugs."""
    running, stopped = build_addon_list()
    if not running and not stopped:
        # Supervisor unreachable – keep the last good list
        log.warning("Supervisor returned no addons, keeping cached list")
        return []
    _, new_slugs = sync_detected(running, stopped)
    with _cache_lock:
        _cache.update(running=running, stopped=stopped, snapshot=_snapshot(running, stopped), ts=time.time())
    return new_slugs


def get_cached(max_age: float = REFRESH_INTERVAL) -> dict:
    with _cache_lock:
        stale = (time.time() - _cache["ts"]) > max_age or not _cache["snapshot"]
    if stale:
        try:
            refresh_cache()
        except Exception as e:
            log.error("Refresh failed: %s", e)
    with _cache_lock:
        return {k: (list(v) if isinstance(v, list) else v) for k, v in _cache.items()}


def _poller():
    while True:
        time.sleep(REFRESH_INTERVAL)
        try:
            refresh_cache()
        except Exception as e:
            log.error("Background refresh failed: %s", e)


threading.Thread(target=_poller, name="startpanel-poller", daemon=True).start()


# ── Routes ────────────────────────────────────────────────────────
@app.route("/")
def index():
    data = get_cached()
    settings = load_settings()
    custom_cards = settings.get("customCards", [])
    return render_template(
        "index.html",
        running=data["running"],
        stopped=data["stopped"],
        snapshot=data["snapshot"],
        host_info=get_host_info(),
        custom_cards=custom_cards,
    )


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
    _has_icon_cache.pop(slug, None)
    log.info("Custom icon saved for %s", slug)
    return jsonify(ok=True)


@app.route("/api/icon/<slug>", methods=["DELETE"])
def delete_icon(slug: str):
    custom_path = os.path.join(CUSTOM_ICON_DIR, f"{slug}.png")
    if os.path.isfile(custom_path):
        os.remove(custom_path)
        _icon_cache.pop(slug, None)
        _has_icon_cache.pop(slug, None)
        log.info("Custom icon removed for %s", slug)
    return jsonify(ok=True)


@app.route("/api/has-custom-icon/<slug>")
def has_custom_icon(slug: str):
    custom_path = os.path.join(CUSTOM_ICON_DIR, f"{slug}.png")
    return jsonify(hasCustomIcon=os.path.isfile(custom_path))


@app.route("/api/addons")
def api_addons():
    """Cheap poll endpoint: cached addon list + snapshot for change detection."""
    data = get_cached()
    return jsonify(running=data["running"], stopped=data["stopped"], snapshot=data["snapshot"], ts=data["ts"])


@app.route("/api/refresh")
def api_refresh():
    _icon_cache.clear()
    _has_icon_cache.clear()
    get_host_info(force=True)
    new_slugs = refresh_cache()
    data = get_cached(max_age=float("inf"))
    settings = load_settings()
    return jsonify(
        running=data["running"],
        stopped=data["stopped"],
        snapshot=data["snapshot"],
        host_info=get_host_info(),
        customCards=settings.get("customCards", []),
        newSlugs=new_slugs,
    )


@app.route("/api/settings", methods=["GET"])
def get_settings():
    return jsonify(load_settings())


@app.route("/api/settings", methods=["POST"])
def post_settings():
    incoming = request.get_json(force=True) or {}
    with _settings_lock:
        current = load_settings()
        # Server-owned fields win over whatever copy the browser sent
        cur_addons = current.get("addons") or {}
        for slug, s in (incoming.get("addons") or {}).items():
            if not isinstance(s, dict):
                continue
            old = cur_addons.get(slug) or {}
            for key in ("detected", "firstSeen"):
                if key in old:
                    s[key] = old[key]
                else:
                    s.pop(key, None)
        # Re-derive detected URLs (host overrides may have changed) from the cached list
        with _cache_lock:
            running, stopped = list(_cache["running"]), list(_cache["stopped"])
        save_settings(incoming)
        if running or stopped:
            incoming, _ = sync_detected(running, stopped, incoming)
    return jsonify(ok=True, settings=incoming)


if __name__ == "__main__":
    log.info("Flask starting on port %s", PORT)
    app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False, threaded=True)

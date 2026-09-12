import os
import json
import base64
import ipaddress
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


def public_settings(settings: dict) -> dict:
    """Copy for the browser: the NPM password is replaced by a flag."""
    out = json.loads(json.dumps(settings))
    glob = out.get("global") or {}
    if "npmPassword" in glob:
        glob["npmPasswordSet"] = bool(glob.pop("npmPassword"))
        out["global"] = glob
    return out


# ── Supervisor API ────────────────────────────────────────────────
def supervisor_get(path: str) -> dict:
    try:
        r = requests.get(f"{SUPERVISOR_URL}{path}", headers=HEADERS, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log.error("Supervisor API error %s: %s", path, e)
        return {}


def supervisor_post(path: str, timeout: int = 90, payload: dict | None = None) -> dict:
    try:
        r = requests.post(f"{SUPERVISOR_URL}{path}", headers=HEADERS, timeout=timeout, json=payload)
        try:
            body = r.json()
        except ValueError:
            body = {}
        if r.status_code >= 400 or body.get("result") == "error":
            return {"result": "error", "message": body.get("message") or f"HTTP {r.status_code}"}
        return body or {"result": "ok"}
    except Exception as e:
        log.error("Supervisor API error POST %s: %s", path, e)
        return {"result": "error", "message": str(e)}


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
    info = {
        "host_ip": host_ip,
        "internal_url": internal_url,
        "external_url": external_url,
    }
    if any(info.values()):
        _host_info = info
        log.info("Host info: ip=%s internal=%s external=%s", host_ip, internal_url, external_url)
    else:
        # Supervisor/Core not ready yet (e.g. right after a reboot) – don't cache
        # the empty result, the next refresh retries the detection.
        log.warning("Host detection returned nothing – will retry on next refresh")
    return info


# Fallback derived from how the browser reaches Home Assistant (X-Forwarded-Host
# through ingress). Used only when the Supervisor gives us no host information.
_seen_hosts: dict[str, str] = {}


_HASSIO_NET = ipaddress.ip_network("172.30.32.0/23")  # supervisor-internal docker network


def _is_local_host(hostname: str) -> bool:
    try:
        return ipaddress.ip_address(hostname).is_private
    except ValueError:
        return hostname.endswith(".local") or "." not in hostname


def _remember_request_host() -> bool:
    """Record the origin the current request came through. Returns True if it changed."""
    fwd_host = (request.headers.get("X-Forwarded-Host") or "").split(",")[0].strip()
    via_ingress = bool(request.headers.get("X-Ingress-Path"))
    if via_ingress and not fwd_host:
        return False  # proxied, but we don't know the address the browser used
    host = fwd_host or request.host or ""
    hostname = urlparse(f"//{host}").hostname or ""
    if not hostname or hostname in ("localhost", "127.0.0.1"):
        return False
    try:
        if ipaddress.ip_address(hostname) in _HASSIO_NET:
            return False
    except ValueError:
        pass
    scheme = request.scheme if via_ingress else "http"
    if via_ingress:
        base = f"{scheme}://{host}"
    else:
        # Direct access on the addon port – the HA UI lives on the same host, port 8123
        base = f"http://{hostname}:8123"
    key = "internal" if _is_local_host(hostname) else "external"
    new = {f"{key}_base": base, f"{key}_host": hostname}
    if all(_seen_hosts.get(k) == v for k, v in new.items()):
        return False
    _seen_hosts.update(new)
    log.info("Remembered %s host from request: %s", key, base)
    return True


# ── Nginx Proxy Manager ───────────────────────────────────────────
# Proxy hosts of the NPM addon are matched against the addons: a domain that
# forwards to an addon (by container name or host IP + exposed port) becomes
# its external URL, a domain that forwards to HA itself (port 8123) is used as
# external base for ingress URLs.
NPM_SLUGS = ("a0d7b954_nginxproxymanager",)
NPM_TIMEOUT = 5
_npm: dict = {"hosts": [], "ok": False, "status": "not configured", "token": "", "base": "", "creds": ""}
_npm_lock = threading.Lock()


def _npm_base_urls(settings: dict) -> list[str]:
    glob = settings.get("global") or {}
    override = (glob.get("npmUrl") or "").strip().rstrip("/")
    if override:
        return [override if "://" in override else f"http://{override}"]
    urls = []
    # 1) the addon's own hostname on the Supervisor network (admin UI listens on 81)
    for slug in NPM_SLUGS:
        urls.append(f"http://{slug.replace('_', '-')}:81")
    # 2) host IP + the host port mapped to the admin UI
    with _cache_lock:
        entries = list(_cache["running"]) + list(_cache["stopped"])
    host = effective_hosts(settings, with_proxy=False)["internal_host"]
    for e in entries:
        if e["slug"] not in NPM_SLUGS or not host:
            continue
        for pm in e.get("port_map") or []:
            if str(pm.get("container", "")).startswith("81/"):
                urls.append(f"http://{host}:{pm['host']}")
    return urls


def _npm_login(base: str, user: str, password: str) -> str:
    r = requests.post(f"{base}/api/tokens", json={"identity": user, "secret": password}, timeout=NPM_TIMEOUT)
    if r.status_code in (401, 403):
        raise PermissionError("login failed – check username / password")
    r.raise_for_status()
    token = (r.json() or {}).get("token") or ""
    if not token:
        raise RuntimeError("no token in login response")
    return token


def _npm_parse_hosts(raw: list) -> list[dict]:
    hosts = []
    for h in raw or []:
        if not isinstance(h, dict) or not h.get("enabled", True):
            continue
        domains = [d for d in (h.get("domain_names") or []) if d]
        if not domains:
            continue
        try:
            port = int(h.get("forward_port") or 0)
        except (TypeError, ValueError):
            port = 0
        hosts.append({
            "domains": domains,
            "forward_host": str(h.get("forward_host") or "").strip().lower(),
            "forward_port": port,
            "https": bool(h.get("certificate_id")) or bool(h.get("ssl_forced")),
        })
    return hosts


def npm_refresh(settings: dict) -> dict:
    """Fetch the proxy hosts from Nginx Proxy Manager (if credentials are configured)."""
    glob = settings.get("global") or {}
    user = (glob.get("npmUser") or "").strip()
    password = glob.get("npmPassword") or ""
    with _npm_lock:
        if not user or not password:
            _npm.update(hosts=[], ok=False, status="not configured", token="", base="", creds="")
            return dict(_npm)
        creds = "\n".join((user, password, glob.get("npmUrl") or ""))
        if creds != _npm["creds"]:
            _npm.update(token="", base="", creds=creds)

        bases = _npm_base_urls(settings)
        if _npm["base"] in bases:  # try the last working address first
            bases.remove(_npm["base"])
            bases.insert(0, _npm["base"])
        last_err = "no address for Nginx Proxy Manager found"
        for base in bases:
            try:
                token = _npm["token"] if base == _npm["base"] else ""
                for attempt in (1, 2):
                    if not token:
                        token = _npm_login(base, user, password)
                    r = requests.get(f"{base}/api/nginx/proxy-hosts",
                                     headers={"Authorization": f"Bearer {token}"}, timeout=NPM_TIMEOUT)
                    if r.status_code in (401, 403) and attempt == 1:
                        token = ""  # expired token – log in again
                        continue
                    r.raise_for_status()
                    break
                hosts = _npm_parse_hosts(r.json())
                if _npm["base"] != base or not _npm["ok"]:
                    log.info("Nginx Proxy Manager: %d proxy hosts via %s", len(hosts), base)
                _npm.update(hosts=hosts, ok=True, token=token, base=base,
                            status=f"connected – {len(hosts)} proxy hosts ({base})")
                return dict(_npm)
            except PermissionError as e:
                last_err = str(e)
                break  # wrong credentials: no point trying other addresses
            except Exception as e:
                last_err = f"{base}: {e}"
        _npm.update(hosts=[], ok=False, token="", status=f"error – {last_err}")
        log.warning("Nginx Proxy Manager unreachable: %s", last_err)
        return dict(_npm)


def npm_public() -> dict:
    with _npm_lock:
        return {"ok": _npm["ok"], "status": _npm["status"], "count": len(_npm["hosts"])}


def npm_hosts() -> list[dict]:
    with _npm_lock:
        return list(_npm["hosts"])


def effective_hosts(settings: dict, with_proxy: bool = True) -> dict:
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
        if not internal_base and _seen_hosts.get("internal_base"):
            # Last resort: the address the browser itself uses to reach HA
            internal_base = _seen_hosts["internal_base"]
            internal_host = internal_host or _seen_hosts["internal_host"]

    # Names under which a proxy host may address the HA host itself
    ha_names = {n.lower() for n in (
        internal_host, info["host_ip"], urlparse(info["internal_url"]).hostname or "",
        _seen_hosts.get("internal_host", ""), "homeassistant", "homeassistant.local",
        "172.30.32.1", "127.0.0.1", "localhost", "host.docker.internal") if n}

    proxy_hosts = npm_hosts() if with_proxy else []
    npm_ha_base = ""
    for ph in proxy_hosts:
        if ph["forward_host"] in ha_names and ph["forward_port"] == 8123:
            npm_ha_base = f"{'https' if ph['https'] else 'http'}://{ph['domains'][0]}"
            break

    external_base = override_ext or info["external_url"] or npm_ha_base or _seen_hosts.get("external_base", "")
    if external_base and "://" not in external_base:
        external_base = f"https://{external_base}"

    return {
        "internal_host": internal_host,
        "internal_base": internal_base,
        "external_base": external_base,
        "ha_names": ha_names,
        "proxy_hosts": proxy_hosts,
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
    c = {"ingressInternal": "", "portInternal": "", "ingressExternal": "", "portExternal": "", "proxyExternal": ""}

    # A proxy host in Nginx Proxy Manager that forwards to this addon – either by
    # its container name or by HA host + one of its exposed ports
    addon_names = {slug.lower(), slug.lower().replace("_", "-"), f"addon_{slug.lower()}"}
    for ph in hosts.get("proxy_hosts") or []:
        fh = ph["forward_host"]
        if fh in addon_names or (fh in hosts.get("ha_names", ()) and ph["forward_port"] in ports):
            c["proxyExternal"] = f"{'https' if ph['https'] else 'http'}://{ph['domains'][0]}"
            break

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
        "externalUrl": c["proxyExternal"] or c["ingressExternal"] or c["portExternal"],
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
        detail = supervisor_get(f"/addons/{slug}/info").get("data", {})
        # The /addons list carries no ingress flag – only the per-addon info does
        has_ingress = bool(detail.get("ingress", a.get("ingress")))
        network_raw = detail.get("network") or {}
        ingress_port = detail.get("ingress_port")
        ingress_panel = bool(detail.get("ingress_panel")) if has_ingress else False
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
            "ingress_panel": ingress_panel,
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
    with _cache_lock:
        _cache.update(running=running, stopped=stopped, snapshot=_snapshot(running, stopped), ts=time.time())
    npm_refresh(load_settings())
    _, new_slugs = sync_detected(running, stopped)
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
@app.before_request
def _track_request_host():
    if not _remember_request_host():
        return
    # A new fallback host may complete addon URLs that were empty so far
    with _cache_lock:
        running, stopped = list(_cache["running"]), list(_cache["stopped"])
    if running or stopped:
        try:
            sync_detected(running, stopped)
        except Exception as e:
            log.error("Re-sync after host change failed: %s", e)


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
        npm_info=npm_public(),
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


def _set_sidebar(slug: str, show: bool) -> dict:
    """Set the Supervisor option ingress_panel for an addon and verify it took effect."""
    res = supervisor_post(f"/addons/{slug}/options", timeout=30, payload={"ingress_panel": show})
    log.info("Supervisor options %s ingress_panel=%s -> %s", slug, show, res)
    if res.get("result") != "ok":
        return res
    info = supervisor_get(f"/addons/{slug}/info").get("data", {})
    if "ingress_panel" in info and bool(info["ingress_panel"]) != show:
        return {"result": "error",
                "message": f"Supervisor accepted the change but still reports ingress_panel={info['ingress_panel']}"}
    return res


def sidebar_diag(slug: str) -> dict:
    """What the Supervisor knows about an addon's sidebar panel – for troubleshooting."""
    info = supervisor_get(f"/addons/{slug}/info").get("data", {})
    panels = supervisor_get("/ingress/panels").get("data", {}).get("panels", {})
    return {
        "slug": slug,
        "state": info.get("state"),
        "ingress": info.get("ingress"),
        "ingress_panel": info.get("ingress_panel"),
        "panel_seen_by_home_assistant": panels.get(slug),
        "supervisor_token_present": bool(SUPERVISOR_TOKEN),
    }


def _addon_flag(slug: str, key: str, value):
    """Store (or remove, when value is None) a per-addon flag in settings.json."""
    with _settings_lock:
        settings = load_settings()
        s = settings.setdefault("addons", {}).setdefault(slug, {})
        if value is None:
            s.pop(key, None)
        else:
            s[key] = value
        save_settings(settings)


@app.route("/api/addons/<slug>/sidebar", methods=["POST"])
def api_addon_sidebar(slug: str):
    """Show or hide an ingress addon in the Home Assistant sidebar (ingress_panel option)."""
    body = request.get_json(silent=True) or {}
    show = bool(body.get("show"))
    with _cache_lock:
        known = {e["slug"]: e for e in _cache["running"] + _cache["stopped"]}
    entry = known.get(slug)
    if not entry:
        return jsonify(ok=False, error="Unknown addon"), 404
    if not entry.get("has_ingress"):
        return jsonify(ok=False, error="Addon has no ingress – cannot be shown in the sidebar"), 400
    log.info("Addon %s: sidebar %s", slug, "on" if show else "off")
    res = _set_sidebar(slug, show)
    if res.get("result") != "ok":
        log.warning("Sidebar toggle of %s failed: %s", slug, res.get("message"))
        return jsonify(ok=False, error=res.get("message") or "Sidebar toggle failed", diag=sidebar_diag(slug)), 502
    if not show:
        # Explicitly hidden – don't bring it back automatically on the next start
        _addon_flag(slug, "sidebarOnStart", None)
    try:
        refresh_cache()
    except Exception as e:
        log.error("Refresh after sidebar toggle failed: %s", e)
    return jsonify(ok=True, show=show, diag=sidebar_diag(slug))


@app.route("/api/addons/<slug>/diag")
def api_addon_diag(slug: str):
    """Troubleshooting view: addon info + the ingress panel list HA reads from the Supervisor."""
    return jsonify(sidebar_diag(slug))


ADDON_ACTIONS = ("start", "stop", "restart")


@app.route("/api/addons/<slug>/<action>", methods=["POST"])
def api_addon_action(slug: str, action: str):
    """Start, stop or restart an addon via the Supervisor."""
    if action not in ADDON_ACTIONS:
        return jsonify(ok=False, error="Unknown action"), 400
    with _cache_lock:
        known = {e["slug"]: e for e in _cache["running"] + _cache["stopped"]}
    entry = known.get(slug)
    if not entry:
        return jsonify(ok=False, error="Unknown addon"), 404
    running = entry["state"] == "started"
    if action == "start" and running:
        return jsonify(ok=True, alreadyRunning=True)
    if action == "stop" and not running:
        return jsonify(ok=True, alreadyStopped=True)
    log.info("Addon %s: %s", slug, action)
    res = supervisor_post(f"/addons/{slug}/{action}")
    if res.get("result") != "ok":
        log.warning("%s of %s failed: %s", action, slug, res.get("message"))
        return jsonify(ok=False, error=res.get("message") or f"{action} failed"), 502

    # A stopped addon disappears from the HA sidebar; it comes back when it is
    # started again from here (unless it was hidden explicitly in the meantime).
    sidebar = None
    if entry.get("has_ingress"):
        if action == "stop" and entry.get("ingress_panel"):
            r = _set_sidebar(slug, False)
            if r.get("result") == "ok":
                _addon_flag(slug, "sidebarOnStart", True)
                sidebar = False
            else:
                log.warning("Could not hide %s from the sidebar: %s", slug, r.get("message"))
        elif action == "start" and (load_settings().get("addons", {}).get(slug) or {}).get("sidebarOnStart"):
            r = _set_sidebar(slug, True)
            if r.get("result") == "ok":
                _addon_flag(slug, "sidebarOnStart", None)
                sidebar = True
            else:
                log.warning("Could not restore %s in the sidebar: %s", slug, r.get("message"))
    try:
        refresh_cache()
    except Exception as e:
        log.error("Refresh after %s failed: %s", action, e)
    return jsonify(ok=True, sidebar=sidebar)


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
        npm=npm_public(),
        customCards=settings.get("customCards", []),
        newSlugs=new_slugs,
    )


@app.route("/api/settings", methods=["GET"])
def get_settings():
    return jsonify(public_settings(load_settings()))


@app.route("/api/settings", methods=["POST"])
def post_settings():
    incoming = request.get_json(force=True) or {}
    with _settings_lock:
        current = load_settings()
        cur_glob = current.get("global") or {}
        glob = incoming.get("global")
        if not isinstance(glob, dict):
            glob = incoming["global"] = {}
        # The browser never receives the NPM password – keep the stored one unless
        # a new one was typed; clearing the username drops the password as well.
        glob.pop("npmPasswordSet", None)
        if not glob.get("npmPassword"):
            if (glob.get("npmUser") or "").strip():
                glob["npmPassword"] = cur_glob.get("npmPassword", "")
            else:
                glob.pop("npmPassword", None)
        npm_changed = any(glob.get(k, "") != cur_glob.get(k, "") for k in ("npmUrl", "npmUser", "npmPassword"))
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
        if npm_changed:
            npm_refresh(incoming)
        if running or stopped:
            incoming, _ = sync_detected(running, stopped, incoming)
    return jsonify(ok=True, settings=public_settings(incoming), npm=npm_public())


if __name__ == "__main__":
    log.info("Flask starting on port %s", PORT)
    app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False, threaded=True)

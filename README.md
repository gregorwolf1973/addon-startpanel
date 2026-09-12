# Startpanel – Home Assistant Addon Repository

[![GitHub Release](https://img.shields.io/github/v/release/gregorwolf1973/addon-startpanel)](https://github.com/gregorwolf1973/addon-startpanel/releases)

[!["Buy Me A Coffee"](https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png)](https://buymeacoffee.com/gregorwolf1973)

A Home Assistant addon that shows all installed addons as a visual dashboard with icons and direct links.

<img width="1891" height="911" alt="image" src="https://github.com/user-attachments/assets/6712d561-ce42-43b7-919b-1bc6748a6cf9" />

---

## 🇩🇪 Deutsch

### Was macht Startpanel?

Startpanel zeigt alle installierten Home Assistant Addons auf einer Übersichtsseite:

- **Laufende Addons** oben (grüner Punkt)
- **Installierte, nicht aktive Addons** unten (mit Trennlinie)
- Icons, Name und Version für jedes Addon
- Klick öffnet das Addon direkt

### Funktionen

- **Automatische Erkennung** – Host-IP, interne/externe HA-URL, Ingress und freigegebene Ports jedes Addons werden selbständig ermittelt und als interne/externe Adresse hinterlegt
- **Neue Addons werden erkannt** – Installierte, entfernte oder gestartete Addons erscheinen ohne Zutun (Hintergrund-Abgleich alle 60 s)
- **Intern/Extern Umschalter** – Wähle ob Links intern oder extern geöffnet werden sollen
- **Bearbeitungsmodus (✎)** – Erkannte Adressen pro Addon manuell überschreiben (Badge *auto* / *manual*, ↺ setzt zurück), Addons ausblenden
- **Host-Overrides** – Host-IP und externe Basis-URL in den Einstellungen manuell festlegen
- **Nginx Proxy Manager** – Proxy-Hosts des NPM-Addons werden ausgelesen: eine Domain, die auf ein Addon zeigt, wird dessen externe Adresse; eine Domain auf HA selbst (Port 8123) wird die externe Basis für Ingress-Links
- **Start / Stop / Restart** – Jede Addon-Karte hat eine Aktionsleiste; ein Klick auf ein gestopptes Addon startet es ebenfalls
- **Eigene Karten** – Beliebige Links mit Name, URL und Icon hinzufügen
- **Dauerhaft gespeichert** – Alle Einstellungen liegen serverseitig in `/data/settings.json`

### Installation

1. **Einstellungen → Add-ons → Add-on Store → ⋮ → Repositories**
2. URL eintragen: `https://github.com/gregorwolf1973/addon-startpanel`
3. Addon **Startpanel** installieren und starten

---

## 🇬🇧 English

### What does Startpanel do?

Startpanel displays all installed Home Assistant addons on a visual overview page:

- **Running addons** at the top (green dot)
- **Installed but inactive addons** below (with separator)
- Icon, name, and version for each addon
- Click to open the addon directly

### Features

- **Auto-detection** – Host IP, internal/external HA URL, ingress and exposed ports of every addon are detected automatically and stored as internal/external address
- **New addons are picked up** – Installed, removed, started or stopped addons show up on their own (background sync every 60 s)
- **Internal/External toggle** – Choose whether links open via internal or external address
- **Edit mode (✎)** – Override the detected addresses per addon (badge *auto* / *manual*, ↺ resets), hide addons from the panel
- **Host overrides** – Set host IP and external base URL manually in the settings
- **Nginx Proxy Manager** – Proxy hosts of the NPM addon are read: a domain that forwards to an addon becomes its external URL; a domain for HA itself (port 8123) becomes the external base for ingress links
- **Start / Stop / Restart** – Every addon card has an action bar; clicking a stopped addon starts it as well
- **Custom cards** – Add any link with name, URL and icon
- **Persistent settings** – Everything is stored server-side in `/data/settings.json`

### Installation

1. **Settings → Add-ons → Add-on Store → ⋮ → Repositories**
2. Enter URL: `https://github.com/gregorwolf1973/addon-startpanel`
3. Install and start the **Startpanel** addon

### First-time setup

Nothing to configure – host IP and HA URLs are detected from the Supervisor. If the detection does not match your setup, click the **⚙ gear button** and override:
- **Internal host / IP**: e.g. `192.168.178.37`
- **External base URL**: e.g. `https://your-domain.duckdns.org` (defaults to the external URL configured in HA)
- **Nginx Proxy Manager**: enter the username (e-mail) and password of your NPM admin login. The addon is found automatically (`a0d7b954_nginxproxymanager`, admin API on port 81); set the URL only if it runs elsewhere. Proxy hosts are matched by container name (e.g. `a0d7b954-nodered`) or by HA host + exposed port. The password is stored in `/data/settings.json` and never sent back to the browser.

Then use the **✎ edit button** to adjust individual addon URLs if needed.

---

## License

MIT

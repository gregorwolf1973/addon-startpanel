# Startpanel – Home Assistant Addon Repository

[![GitHub Release](https://img.shields.io/github/v/release/gregorwolf1973/addon-startpanel)](https://github.com/gregorwolf1973/addon-startpanel/releases)

[!["Buy Me A Coffee"](https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png)](https://buymeacoffee.com/gregorwolf1973)

A Home Assistant addon that shows all installed addons as a visual dashboard with icons and direct links.

---

## 🇩🇪 Deutsch

### Was macht Startpanel?

Startpanel zeigt alle installierten Home Assistant Addons auf einer Übersichtsseite:

- **Laufende Addons** oben (grüner Punkt)
- **Installierte, nicht aktive Addons** unten (mit Trennlinie)
- Icons, Name und Version für jedes Addon
- Klick öffnet das Addon direkt

### Funktionen

- **Intern/Extern Umschalter** – Wähle ob Links intern oder extern geöffnet werden sollen
- **Bearbeitungsmodus (✎)** – Eigene URLs pro Addon eintragen, Addons ausblenden
- **Referenz-URLs** – Ingress-Adressen werden angezeigt und können per Klick kopiert werden
- **Dauerhaft gespeichert** – Alle Einstellungen bleiben im Browser erhalten

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

- **Internal/External toggle** – Choose whether links open via internal or external address
- **Edit mode (✎)** – Enter custom URLs per addon, hide addons from the panel
- **Reference URLs** – Ingress addresses are shown and can be copied with one click
- **Persistent settings** – All settings are saved in the browser (localStorage)

### Installation

1. **Settings → Add-ons → Add-on Store → ⋮ → Repositories**
2. Enter URL: `https://github.com/gregorwolf1973/addon-startpanel`
3. Install and start the **Startpanel** addon

### First-time setup

After starting, click the **⚙ gear button** to enter your base URLs:
- **Internal**: e.g. `http://192.168.178.37:8123`
- **External**: e.g. `https://your-domain.duckdns.org`

Then use the **✎ edit button** to configure individual addon URLs if needed.

---

## License

MIT

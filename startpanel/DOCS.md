# Startpanel – Dokumentation

## Übersicht

Startpanel ist ein Home Assistant Addon, das alle installierten Addons auf einer übersichtlichen Dashboard-Seite anzeigt. Laufende Addons erscheinen oben, installierte aber nicht aktive Addons darunter – jeweils mit Icon, Name und Version.

## Installation

1. In Home Assistant: **Einstellungen → Add-ons → Add-on Store → ⋮ → Repositories**
2. URL eintragen: `https://github.com/gregorwolf1973/addon-startpanel`
3. Addon **Startpanel** installieren und starten
4. Das Panel erscheint automatisch in der Seitenleiste

## Erste Schritte

Nach dem ersten Start erscheint ein Hinweis, die interne Basis-URL einzutragen.

### Intern / Extern Umschalter

- **Intern**: Öffnet Addons über die interne HA-Adresse (z. B. `http://192.168.178.37:8123`)
- **Extern**: Öffnet Addons über die externe Adresse (z. B. `https://meine-domain.duckdns.org`)

## Bearbeitungsmodus (✎)

Der Stift-Button in der Kopfzeile aktiviert den Bearbeitungsmodus (Button leuchtet orange). Im Bearbeitungsmodus:

- **Klick auf ein Addon-Icon** öffnet das Bearbeitungs-Modal
- Dort können eingetragen werden:
  - **Interne URL**: Direkte Adresse für das Addon (z. B. `http://192.168.178.37:8080`)
  - **Externe URL**: Externe Adresse (z. B. `https://meine-domain.de:8080`)
  - **Addon ausblenden**: Blendet das Icon im normalen Modus aus
- Die **HA Adressen (Referenz)**-Zeilen zeigen die automatisch ermittelte Ingress-URL – ein Klick kopiert die vollständige URL in die Zwischenablage

### URL-Logik

| Situation | Verwendete URL |
|-----------|---------------|
| Eigene interne URL eingetragen | Eingetragene interne URL |
| Nur Ingress verfügbar | `{Interne Basis}/hassio/ingress/{slug}` |
| Externer Modus, externe URL eingetragen | Eingetragene externe URL |
| Externer Modus, nur Ingress | `{Externe Basis}/hassio/ingress/{slug}` |

### Ausgeblendete Addons

- Im normalen Modus: komplett unsichtbar
- Im Bearbeitungsmodus: grau und gestrichelt dargestellt
- Beim Deaktivieren des Bearbeitungsmodus verschwinden sie sofort

## Einstellungen werden dauerhaft gespeichert

Alle URLs und Ausblend-Einstellungen werden im Browser (`localStorage`) gespeichert und bleiben nach einem Neustart erhalten.

## Aktualisieren (↺)

Der Refresh-Button lädt die Addon-Liste neu vom Supervisor. Nützlich nach Installation oder Deinstallation von Addons.

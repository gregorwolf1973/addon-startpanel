# Startpanel – Dokumentation

[!["Buy Me A Coffee"](https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png)](https://buymeacoffee.com/gregorwolf1973)

## Übersicht

Startpanel ist ein Home Assistant Addon, das alle installierten Addons auf einer übersichtlichen Dashboard-Seite anzeigt. Laufende Addons erscheinen oben, installierte aber nicht aktive Addons darunter – jeweils mit Icon, Name und Version.

## Installation

1. In Home Assistant: **Einstellungen → Add-ons → Add-on Store → ⋮ → Repositories**
2. URL eintragen: `https://github.com/gregorwolf1973/addon-startpanel`
3. Addon **Startpanel** installieren und starten
4. Das Panel erscheint automatisch in der Seitenleiste

## Automatische Erkennung

Startpanel ermittelt beim Start und danach alle 60 Sekunden selbständig über die Supervisor-API:

- **Host-IP** des Home-Assistant-Rechners (primäres Netzwerk-Interface) sowie die in HA konfigurierte **interne** und **externe URL**
- pro Addon: **Ingress** (ja/nein) und alle **freigegebenen Ports** (Host-Port ← Container-Port)

Daraus werden für jedes Addon eine interne und eine externe Adresse abgeleitet und in `/data/settings.json` hinterlegt:

| Typ | Regel |
|-----|-------|
| Intern | Ingress über die interne HA-Basis, sonst `http://{Host-IP}:{erster Port}` |
| Extern | Ingress über die externe HA-Basis, sonst `https://{Domain}:{erster Port}` |

### Neue Addons

Neu installierte, entfernte oder gestartete/gestoppte Addons werden automatisch erkannt: Die Seite fragt alle 30 Sekunden nach und lädt sich mit einem Hinweis („New addon detected: …“) neu – aber nicht, solange ein Bearbeitungs-Dialog geöffnet oder der Bearbeitungsmodus aktiv ist.

## Intern / Extern Umschalter

- **Intern**: Öffnet Addons über die interne Adresse (Host-IP / interne HA-URL)
- **Extern**: Öffnet Addons über die externe Adresse (externe HA-URL)

## Bearbeitungsmodus (✎)

Der Stift-Button in der Kopfzeile aktiviert den Bearbeitungsmodus (Button leuchtet orange). Im Bearbeitungsmodus:

- **Klick auf ein Addon-Icon** öffnet das Bearbeitungs-Modal
- **Detected Addresses** zeigt alle erkannten Varianten (Ingress intern, IP + Port, Ingress extern, Domain + Port). Ein Klick auf **→ Int** / **→ Ext** übernimmt die Variante in das jeweilige Feld
- **Interne URL / Externe URL** sind mit der erkannten Adresse vorbelegt und können frei bearbeitet werden:
  - Badge **auto** (grün): Feld entspricht der Erkennung und folgt ihr auch bei Änderungen (z. B. neuer Port)
  - Badge **manual** (orange): eigener Wert, der die Erkennung dauerhaft überschreibt
  - **↺** setzt das Feld auf den erkannten Wert zurück
  - Leeres Feld = immer automatisch
- **Addon ausblenden**: Blendet das Icon im normalen Modus aus
- Die Meta-Zeile zeigt Slug, erkannte Host-IP und Port-Zuordnung

### Ausgeblendete Addons

- Im normalen Modus: komplett unsichtbar
- Im Bearbeitungsmodus: grau und gestrichelt dargestellt
- Beim Deaktivieren des Bearbeitungsmodus verschwinden sie sofort

## Einstellungen (⚙)

- **Dark theme** / **Hide inactive addons**
- **Internal host / IP**: Überschreibt die erkannte Host-IP (z. B. `192.168.178.37` oder `http://homeassistant.local:8123`)
- **External base URL**: Überschreibt die externe HA-URL (z. B. `https://meine-domain.duckdns.org`)

- **Nginx Proxy Manager**: Benutzername (E-Mail) und Passwort des NPM-Admin-Logins. Das Addon wird automatisch gefunden (Admin-API auf Port 81); eine URL ist nur nötig, wenn NPM woanders läuft. Eine Domain, die auf ein Addon zeigt, wird dessen externe Adresse; eine Domain auf HA selbst (Port 8123) wird die externe Basis für Ingress-Links. Das Passwort wird in `/data/settings.json` gespeichert und nie an den Browser zurückgegeben.

Leere Felder bedeuten „automatisch“. Nach einer Änderung werden alle erkannten Addon-Adressen sofort neu abgeleitet; manuell gesetzte Addon-URLs bleiben unberührt.

## Start / Stop / Restart und Seitenleiste

- Jede Addon-Karte hat eine Aktionsleiste mit **Start**, **Stop** und **Restart**; ein Klick auf ein gestopptes Addon startet es ebenfalls
- Bei Ingress-Addons blendet der Knopf **Sidebar** das Addon in der HA-Seitenleiste ein oder aus; ein gestopptes Addon verschwindet aus der Seitenleiste und kehrt beim nächsten Start zurück

## Health-Check (⚕)

Prüft alle Addons auf Fehlerzustand, Fehlerzeilen im Log, nicht antwortende Ports und verwaiste Seitenleisten-Einträge. Das Addon-Log lässt sich per Klick anzeigen.

## Eigene Karten (Custom)

Im Bearbeitungsmodus erscheint der Abschnitt **Custom** mit einer **+ Add card**-Kachel. Damit lassen sich beliebige Links (Router, NAS, Webseiten …) mit Name, URL und eigenem Icon anlegen.

## Einstellungen werden dauerhaft gespeichert

Alle URLs, Overrides, Reihenfolge und Ausblend-Einstellungen werden serverseitig in `/data/settings.json` gespeichert und bleiben nach einem Neustart erhalten. Die erkannten Adressen (`detected`) werden vom Addon selbst gepflegt.

## Aktualisieren (↺)

Der Refresh-Button erzwingt eine sofortige Neuabfrage des Supervisors (Addon-Liste, Host-Adressen, Icons).

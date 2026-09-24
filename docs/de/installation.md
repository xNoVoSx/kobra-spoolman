# Installation

[English](../installation.md) · [Zurück zur README](../../README.de.md)

Diese Anleitung führt von null bis zum fertigen Ablauf. Rechne mit etwa einer Stunde – das meiste
davon ist der erste OrcaSlicer-Build, den GitHub für dich erledigt.

**Überblick**

1. [Drucker: Rinkhals und Moonraker](#1-drucker-rinkhals-und-moonraker)
2. [Spoolman und seine Zusatzfelder](#2-spoolman-und-seine-zusatzfelder)
3. [ace-lane-bridge](#3-ace-lane-bridge)
4. [OrcaSlicer (orca-kobra-Build)](#4-orcaslicer-orca-kobra-build)
5. [Orca-Plugin „Kobra Spoolman“](#5-orca-plugin-kobra-spoolman)
6. [Prüfen, ob alles läuft](#6-prüfen-ob-alles-läuft)

---

## 1. Drucker: Rinkhals und Moonraker

- [Rinkhals](https://github.com/jbatonnet/Rinkhals) auf dem Kobra S1 installieren. Moonraker muss unter
  `http://<drucker-ip>:7125` erreichbar sein (im Browser `http://<drucker-ip>:7125/server/info` testen).
- **Moonrakers eigene Spoolman-Anbindung bleibt aus** (kein Abschnitt `[spoolman]` in
  `moonraker.conf`), sonst wird doppelt gebucht. Die Bridge warnt, falls sie an ist.
- Dem Drucker eine feste IP geben (DHCP-Reservierung) – alles andere zeigt darauf.

## 2. Spoolman und seine Zusatzfelder

Spoolman ab 0.26. Läuft es noch nicht, kommt es am besten in denselben Stack wie die Bridge
(siehe [bridge/compose.yaml](../../bridge/compose.yaml)).

Dann einmalig die Zusatzfelder und Materialvorlagen anlegen:

```bash
python3 spoolman/spoolman_setup.py --url http://<spoolman-host>:7912 --dry-run   # Plan anzeigen
python3 spoolman/spoolman_setup.py --url http://<spoolman-host>:7912             # anlegen
```

Das Skript legt nur **neu** an, ändert oder löscht nie vorhandene Felder oder Filamente – mehrfaches
Ausführen schadet nicht. Es legt an:

- **Filament-Felder** für alle Orca-Einstellungen, die man üblicherweise anpasst: erste Schicht,
  glatte PEI, Kammer, Bauteillüfter min/max, Lüfter aus in den ersten Schichten, Überhang-Lüfter,
  Hilfslüfter, Luftfilterung und Abluft, Flow Ratio, Pressure Advance, max. Volumenstrom,
  Retraction, Z-Hop, ein freies Feld *Orca-Overrides*, dazu *Orca-Basisprofil* und *Vorlage*.
  Vollständige Liste: [spoolman-fields.md](../spoolman-fields.md).
- **Spulen-Feld** *NFC-Kennung* (für Etappe 4).
- Einen Hersteller **„Vorlage“** mit sieben Vorlagen (PLA, PLA Silk, PETG, ASA, TPU, PLA-CF, PETG-CF),
  vorbelegt aus Orcas Generic-Profilen.

## 3. ace-lane-bridge

### Variante A – Docker-Image (empfohlen)

Den Dienst in deinen Stack aufnehmen (Portainer → Stacks, oder `docker compose`):

```yaml
  ace-lane-bridge:
    image: ghcr.io/xnovosx/ace-lane-bridge:latest
    container_name: ace-lane-bridge
    restart: unless-stopped
    ports:
      - "7913:7913"
    volumes:
      - ./bridge-data:/data          # z.B. /docker/ace-lane-bridge/data
    environment:
      MOONRAKER_URL: "http://<drucker-ip>:7125"
      SPOOLMAN_URL: "http://spoolman:8000"   # Servicename im selben Stack
      TZ: Europe/Berlin
    depends_on:
      - spoolman
```

### Variante B – direkt aus dem Quellcode

Praktisch beim Entwickeln. `bridge/app/` auf den Docker-Host kopieren (z.B. nach
`/docker/ace-lane-bridge/app`) und so einbinden:

```yaml
  ace-lane-bridge:
    image: python:3.12-slim
    container_name: ace-lane-bridge
    restart: unless-stopped
    entrypoint: ["sh", "/app/entrypoint.sh"]
    ports:
      - "7913:7913"
    volumes:
      - /docker/ace-lane-bridge/app:/app:ro
      - /docker/ace-lane-bridge/data:/data
    environment:
      MOONRAKER_URL: "http://<drucker-ip>:7125"
      SPOOLMAN_URL: "http://spoolman:8000"
      TZ: Europe/Berlin
```

Beim ersten Start legt das Entrypoint-Skript eine Python-Umgebung in `data/venv` an (braucht einmal
Internet). Aktualisieren = neuen `app/`-Ordner kopieren und den Container neu starten.

### Prüfen

- `http://<docker-host>:7913` zeigt die **Slot-Seite** mit vier Slots und grünen Punkten bei
  Drucker und Spoolman.
- `http://<docker-host>:7913/api/health` liefert Version und beide Verbindungen.
- Alle Einstellungen: [configuration.md](../configuration.md).

## 4. OrcaSlicer (orca-kobra-Build)

Das Plugin braucht Orcas Plugin-System (Nightly 2.5.0-dev). Die **automatische Profilwahl** braucht
zusätzlich einen kleinen Patch, der noch nicht in Orca übernommen ist
([PR #14423](https://github.com/OrcaSlicer/OrcaSlicer/pull/14423)). Das Repo
[orca-kobra](https://github.com/xNoVoSx/orca-kobra) baut damit jede Nacht ein Linux-AppImage und
bringt einen Starter mit, der sich selbst aktualisiert:

```bash
git clone https://github.com/xNoVoSx/orca-kobra && cd orca-kobra
tools/install.sh        # lädt das neueste AppImage, legt „OrcaSlicer (Kobra)“ im Menü an
```

Es nutzt den normalen Orca-Datenordner (`~/.config/OrcaSlicer`), deine Drucker und Profile bleiben.
Eigener Build gewünscht? orca-kobra forken – der Workflow baut ihn für dich.

In Orca:

- Den Drucker wie gewohnt anlegen (Anycubic Kobra S1 0.4 nozzle) und mit `http://<drucker-ip>` verbinden.
- **Druckereinstellungen → Grundlegende Informationen → Erweitert** (Expertenmodus):
  **Printer Agent = Moonraker**.

> [!TIP]
> Ohne den orca-kobra-Build funktioniert alles andere trotzdem (Profile, Panel, Rücksync,
> Verbrauch) – die `SM…`-Profile wählst du dann in den Filament-Feldern selbst aus.

## 5. Orca-Plugin „Kobra Spoolman“

Bei geschlossenem Orca:

```bash
mkdir -p ~/.config/OrcaSlicer/orca_plugins/kobra_spoolman
curl -fsSLo ~/.config/OrcaSlicer/orca_plugins/kobra_spoolman/kobra_spoolman.py \
  https://raw.githubusercontent.com/xNoVoSx/kobra-spoolman/main/orca-plugin/kobra_spoolman.py
```

1. Orca starten, den **Plugins**-Dialog öffnen und **Kobra Spoolman** aktivieren.
2. Reiter **Konfiguration** des Plugins: Bridge-Adresse eintragen, z.B. `http://192.168.1.10:7913`.
3. Rechts öffnet sich das Panel **Kobra Spoolman** und legt im Hintergrund die Profile an. Fragt Orca,
   ob das Plugin die Bridge erreichen darf, mit Ja bestätigen.
4. **Orca einmal neu starten** – Orca liest Profile nur beim Start. Deine Filamente stehen jetzt als
   `Hersteller Name (SM000010)` in den Filamentlisten.

## 6. Prüfen, ob alles läuft

- [ ] Slot-Seite: alle vier Slots zugeordnet, keine Warnungen.
- [ ] Orca-Panel: Bridge verbunden, vier Slots mit Spulennamen.
- [ ] Orca: **Sync-Knopf** bei den Filamenten → die `SM…`-Profile stehen in Filament 1–4, das Panel zeigt *passt* für jeden Slot.
- [ ] Einen Wert in einem `SM…`-Profil ändern und speichern → Frage *Nach Spoolman übernehmen?* → der Wert steht in Spoolman.
- [ ] Nach einem Druck: Die Slot-Seite zeigt *Letzter Druck* pro Slot, und Spoolmans Restgewicht ist um genau diesen Wert gesunken.

Weiter: [Alltag](usage.md).

# Im Alltag

[English](../usage.md) · [Zurück zur README](../../README.de.md)

## Weboberfläche und App

Alles, was du am Drucker machst, läuft über die **Weboberfläche** (`http://<docker-host>:7913`) oder
die **Android-App**. Beide zeigen dieselben Daten der Bridge; die App kann zusätzlich NFC-Tags lesen
und schreiben. Spoolmans eigene Oberfläche brauchst du nur noch für Dinge, die die Bridge nicht
abdeckt (z.B. einen Hersteller umbenennen).

| Bildschirmbreite | Aufbau |
|---|---|
| Handy | Leiste unten: *Slots*, *Regal*, *Drucke*, *Mehr* – wie in der App |
| Desktop | Seitenleiste links, Seiten für Übersicht, Regal, Filamente, Drucke, Trockner, Geräte, Einstellungen |
| Ultrawide (ab 3000 px, z.B. 5120×1440) | die Übersicht zeigt alles nebeneinander: Drucker, Slots, Regal, Spulendetails, Drucke |

Tastatur (Desktop): `/` suchen, `n` neue Spule, `↑` `↓` im Regal wählen, `Esc` schließen.
Rechtsklick auf eine Spule → in einen Slot legen, ins Regal, archivieren.

Die Weboberfläche fragt einmal pro Browser nach dem Koppeln ([Installation](installation.md#4-das-erste-gerät-koppeln)).
*Nur ansehen* überspringt das – alles ist sichtbar, Knöpfe, die etwas ändern, führen zum Koppeln.

## Ein neues Filament kommt

In der Weboberfläche unter **Filamente → Neu** anlegen, in der App über **Neu → Nicht dabei? Neues Filament**
oder direkt in Spoolman.

| Feld | Eintrag |
|---|---|
| Hersteller, Name | z.B. *Sunlu*, *PETG 2.0 Lavendel* – die Farbe gehört in den Namen |
| Material | `PLA`, `PETG`, `PLA Silk` … (der Grundtyp bestimmt den Orca-Filamenttyp) |
| Farbe | Hex-Farbe; bei Anycubic-Spulen die Farbe nehmen, die die ACE meldet, damit der Slot-Abgleich passt |
| Dichte, Durchmesser, Gewicht, Preis | vom Etikett / aus dem Shop |
| **Vorlage** *oder* **Orca-Basisprofil** | siehe unten |
| Alles andere | nur, was du abweichend willst – leere Felder zeigen den geerbten Wert grau als Platzhalter |

**Vorlage oder Basisprofil?**

- **Vorlage** (`Vorlage PETG`, …): allgemeine Startwerte, gepflegt in Spoolman. Passt für die meisten
  Fremd-Filamente. Leer lassen → die Vorlage wird nach Material gewählt.
- **Orca-Basisprofil**: der genaue Name eines Orca-Systemprofils, z.B.
  `Anycubic PLA Silk @Anycubic Kobra S1 0.4 nozzle`. Der Editor bietet die Namen an, die das
  Orca-Plugin gemeldet hat. Nimm es, wenn Orca schon ein abgestimmtes Profil mitbringt – die Vorlage
  wird dann komplett ignoriert.

Reihenfolge (später gewinnt): *Orca-Basisprofil* ← *Vorlage* ← *Filament-Felder* ← *Orca-Overrides*.
Feldübersicht: [spoolman-fields.md](../spoolman-fields.md) (englisch).

**Gleiches Produkt, andere Farbe:** Filament öffnen und **Neue Farbe** drücken – alle Werte werden
übernommen, du gibst nur Name und Farbe ein.

Das Orca-Plugin legt beim nächsten Orca-Start das Profil `Hersteller Name (SM0000xx)` an. Läuft Orca
schon? Im Panel **Profile aktualisieren** drücken, dann Orca neu starten. Orcas Filament-**Sync**-Knopf
setzt die Profile danach in die Filament-Felder (siehe unten).

<p align="center"><img src="../images/web-filament.png" width="760" alt="Filament-Editor"></p>

## Eine neue Spule

**Neue Spule** (oben rechts oder `n`): Filament wählen, Gewichte prüfen (Vorgaben kommen vom
Filament), wahlweise **Gleich einlegen** in einen Slot. In der App kannst du vorher einen NFC-Tag
scannen – die neue Spule wird damit verknüpft, oder die App schreibt ihr einen ACE-tauglichen Tag
([android-app.md](../android-app.md), englisch).

## Spule in die ACE einlegen

Auf der Slot-Karte **Spule wechseln** (bei leerem Slot **Spule zuordnen**) drücken und die Spule
wählen. Spulen, die zu dem passen, was die ACE vom Tag liest, stehen oben und sind mit *passt* markiert.

**Spulen ohne Anycubic-Tag:** Der Drucker kennt ihr Material nicht. Ordnest du so eine Spule zu, gibt
die Bridge Material und Farbe aus Spoolman an die ACE – das Druckerdisplay zeigt sie sofort an (vor
dem Einlegen zugeordnet: sobald die Spule drin ist; während eines Drucks: danach). Nur die Zuordnung
macht das; zum erneuten Senden die Spule nochmal zuordnen. Ohne das (Bridge aus,
`SET_ACE_SLOT_INFO=false`) am Display eintragen, sonst bricht der Druck beim Start ab
(`index out of range`). Weboberfläche, App und Orca-Panel warnen bei solchen Slots.

Spule herausnehmen: Meldet die ACE einen Slot eine Weile als leer, kommt die Spule automatisch ins
Regal (während eines Drucks erst danach). Oder auf der Slot-Karte **Leeren** drücken.

## Das Regal

**Regal** zeigt alle aktiven Spulen mit Restgewicht, Ort und Tag-Nummer; filtern nach Material,
*im ACE* oder *fast leer* (< 200 g), oder suchen. Spule wählen, um sie zu bearbeiten:

- **Spule**: Restgewicht (nach dem Wiegen), Leerspule, Netto neu, Preis, Charge, Notiz und – bei
  Spulen im Regal – der Lagerort.
- **Filament**: der Filament-Editor, direkt dort.
- **Verbrauch**: erste und letzte Benutzung und jeder aufgezeichnete Druck mit dieser Spule.

<p align="center"><img src="../images/web-shelf.png" width="760" alt="Regal mit Spulendetails"></p>

## Trocknen (ACE-Trockner)

Die Trockner-Karte zeigt Feuchte und Temperatur der ACE und den Zustand. **Trocknen** / **Stoppen**
geht von Hand; **Regeln** stellt die Automatik ein: Start, wenn die Feuchte über eine Schwelle steigt
(Standard 20 %), Stopp unter einer zweiten (Standard 10 %) oder nach einer Höchstdauer, danach eine
Pause; wahlweise auch während eines Drucks.

Die Temperatur liegt **nie über dem, was das empfindlichste eingelegte Filament verträgt** – Feld
*Trocknen max.* am Filament, sonst an der Vorlage, sonst ein vorsichtiger Wert pro Material
(PLA 45 °C, PETG 60 °C, …) – und nie über dem, was die ACE kann (ACE 2 Pro 65 °C, ACE Pro 55 °C).
Wird beim Trocknen eine empfindlichere Spule eingelegt, senkt die Bridge die Temperatur sofort. Die
Seite **Trockner** zeigt, welcher Slot die Grenze setzt.

## Einen Druck beobachten

Die Druckerkarte zeigt **Modell** – die Druckdatei, von der Bridge gezeichnet in den Farben deiner
eingelegten Spulen, Gedrucktes kräftig, der Rest als Schatten, mit aktueller Schicht – und **Kamera**,
die Druckerkamera live (nur auf gekoppelten Geräten), mit der Bildrate in der Ecke. Unter dem Bild:
Düse und Bett (ist/soll), Bauteil-, Gehäuse- und Luftfilterlüfter, Tempo und Fluss, Schicht –
geheizte Werte und veränderte Faktoren sind hervorgehoben. Bild antippen für Vollbild.

Die Bridge **verteilt die Kamera weiter** (Restream): Egal wie viele Browser und Handys zuschauen, der
Drucker liefert einen einzigen Stream, und nur solange jemand zuschaut. Damit Mainsail keinen zweiten
Stream öffnet, trag dort auch die Bridge ein: **Geräte → Kamera-Link** zeigt eine Stream- und eine
Einzelbild-Adresse. In Mainsail *Einstellungen → Webcams*, die Webcam bearbeiten, Dienst
*MJPEG-Streamer* wählen und die beiden Adressen einfügen. Der Link zeigt nur die Kamera; *Neu erzeugen*
ersetzt ihn (der alte funktioniert dann nicht mehr).

## ACE-Einstellungen und Spülen

Die Seite **ACE** (App: Trockner-Karte antippen) zeigt, was das Druckerdisplay versteckt:

- **Spül-Multiplikator** – wie viel die ACE bei einem Farbwechsel spült (`× 1,0` ist der Standard
  der Firmware; Minimal 0,1 / Normal 1,0 / Maximum 3,0 oder ein eigener Wert). Daneben das Spülen
  für jeden Wechsel zwischen deinen eingelegten Spulen, mit dem aktuellen und dem neuen Wert, in mm
  und Gramm. Weniger Spülen spart Filament, kann aber Farben vermischen – an einem kleinen Druck testen.
- **Automatisch nachladen** (Ersatzspule, wenn eine leer ist) und **Leer-Erkennung**.
- **Trocknen planen** – ein Start zu einer festen Zeit, z.B. heute um 22:00.

Während eines Drucks sind die Felder gesperrt; **Freischalten** gibt sie nach einem Warnhinweis frei.
Ein neuer Multiplikator gilt ab dem nächsten Farbwechsel.

## Slicen und Drucken

1. In Orca den Filament-**Sync**-Knopf drücken. Mit dem orca-kobra-Build werden die `SM…`-Profile für
   Slot 1–4 automatisch gewählt; das Panel zeigt pro Slot *Filament N in Orca: passt* und warnt, wenn
   ein Filament-Feld nicht zum Slot passt.
2. Slicen. Oben im Panel zeigt **Geplanter Verbrauch** eine Zeile pro Slot: *Bedarf / Rest g* und
   ✓ (reicht), ⚠ (*knapp*) oder ✗ (*reicht nicht*). Reicht eine Spule nicht, warnt auch Orca.
   *Details* klappt die Aufschlüsselung auf (unten).
3. Wie gewohnt drucken (Printer Agent *Moonraker*).
4. Während des Drucks zeigen Druckerkarte und Slot-Karten den bisherigen Verbrauch (*dieser Druck*).
   Die Bridge bucht bei jedem Farbwechsel, alle 5 Minuten und am Ende in Spoolman. Fertige Drucke
   stehen unter **Drucke** mit Gramm pro Spule.

Die Weboberfläche *zeigt* den Drucker nur an – Pause, Abbrechen und alles andere bleiben in
Mainsail/Fluidd (*In Mainsail öffnen* auf der Druckerkarte).

### So wird die Verbrauchsvorschau berechnet

Unter *Details* stehen zwei Tabellen, alle Werte in Gramm.

| Spalte | Quelle |
|---|---|
| *Modell*, *Stützen*, *Gereinigt*, *Turm*, *Gesamt* | Genau Orcas Vorschau-Legende (Vorschau → Filament): Modell, Stützen, Spülen und Reinigungsturm pro Filament, *Gesamt* ist die Summe. Leere Spalten fehlen wie in Orca. |
| *Laden* | Spülen der Firmware beim Laden durch die ACE – Orca kennt es nicht. Gerechnet wird **pro Farbwechsel** genau wie die Firmware: Orcas Farbformel für die beiden Slot-Farben (so wie die ACE sie meldet) + 107 mm³, mal dem Multiplikator am Druckerdisplay; der erste Ladevorgang eines Drucks ist fest ≈ 95 mm. Den Multiplikator liest die Bridge vom Drucker, die kleinen Konstanten misst sie an jedem fertigen Orca-Druck nach. Die Wechsel (von → nach) zählt Orca; mit älterem orca-kobra-Build werden die Farben gemittelt, ohne Spül-Modell der Bridge gilt ein gemessener Mittelwert pro Ladevorgang. |
| *Bedarf* | *Gesamt* + *Laden* |
| *Rest* | Restgewicht der dem Slot zugeordneten Spule, aus Spoolman |

Filament N in Orca zählt gegen Slot N – dieselbe Zuordnung, die der Sync-Knopf setzt. Die Vorschau
braucht den orca-kobra-Build (Patch 0003); sie verschwindet, wenn das Slice-Ergebnis nicht mehr gilt
(Modell oder Einstellungen geändert).

## Offene Posten

Wurde ein Slot ohne zugeordnete Spule benutzt oder seine Spule gelöscht, bleibt der Verbrauch als
**offener Posten** stehen (Karte *Offene Buchungen*, Zahl bei *Drucke*). **Buchen** drücken und die
Spule wählen, oder **Verwerfen**. War Spoolman nicht erreichbar, holt die Bridge die Buchung selbst nach.

## Ein Profil in Orca ändern

Ein `SM…`-Profil ändern und speichern. Das Plugin fragt *Nach Spoolman übernehmen?*:

- **Ja** – bekannte Werte landen in ihren Spoolman-Feldern, alles andere in *Orca-Overrides*.
- **Nein** – der nächste Sync setzt das Profil auf die Spoolman-Werte zurück (Spoolman bleibt die Quelle).

Dafür muss das Plugin gekoppelt sein; sonst sagt es Bescheid. Um für einen einzelnen Wert zur Vorlage
zurückzukehren, das Feld im Filament-Editor leeren (oder `POST /api/orca/reset`, siehe [api.md](../api.md)).

## Wenn ein Filament leer ist

**Archivieren** an der Spule (Regal, App oder Spoolman). Filamente ohne aktive Spule verlieren beim
nächsten Sync ihr Orca-Profil; Profile, die das Plugin nicht selbst angelegt hat, bleiben unangetastet.

## Geräte

**Geräte** listet jeden gekoppelten Browser, jedes Handy und Orca-Plugin mit dem Zeitpunkt der letzten
Nutzung. **Gerät hinzufügen** zeigt Code und QR-Code für ein neues Gerät; **Entfernen** sperrt einen
Schlüssel sofort (z.B. bei einem verlorenen Handy). *Entkoppeln* beim eigenen Browser vergisst dessen Schlüssel.

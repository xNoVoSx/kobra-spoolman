# Im Alltag

[English](../usage.md) · [Zurück zur README](../../README.de.md)

## Ein neues Filament kommt

In Spoolman mit **Add spools** eintragen (das Filament lässt sich im selben Dialog anlegen).

| Feld | Eintrag |
|---|---|
| Hersteller, Name | z.B. *Sunlu*, *PETG 2.0 Lavendel* – die Farbe gehört in den Namen |
| Material | `PLA`, `PETG`, `PLA Silk` … (der Grundtyp bestimmt den Orca-Filamenttyp) |
| Farbe | der Hex-Wert; bei Anycubic-Spulen den Wert, den die ACE meldet, dann passt der Slot-Abgleich |
| Dichte, Durchmesser, Gewicht, Preis | vom Etikett / aus dem Shop |
| Düsen-/Betttemperatur | die Werte, die du in Orca willst |
| **Orca-Basisprofil** *oder* **Vorlage** | siehe unten |
| Alles andere | nur, was du abweichend haben willst |

**Vorlage oder Basisprofil?**

- **Vorlage** (`Vorlage PETG`, …): allgemeine Startwerte, gepflegt in Spoolman. Passt für die meisten
  Fremdfilamente. Leer lassen → die Vorlage wird über das Material gewählt.
- **Orca-Basisprofil**: der genaue Name eines Orca-Systemprofils, z.B.
  `Anycubic PLA Silk @Anycubic Kobra S1 0.4 nozzle`. Nimm das, wenn Orca für genau dieses Filament
  schon ein abgestimmtes Profil mitbringt – die Vorlage wird dann komplett ignoriert.

Rangfolge (später gewinnt): *Orca-Basisprofil* ← *Vorlage* ← *Felder am Filament* ← *Orca-Overrides*.
Feldübersicht: [spoolman-fields.md](../spoolman-fields.md).

Beim nächsten Orca-Start legt das Plugin das Profil `Hersteller Name (SM0000xx)` an. Läuft Orca schon?
Im Panel **Profile synchronisieren** drücken und Orca neu starten.

## Spule in die ACE legen

Die Slot-Seite (`http://<docker-host>:7913`) auf dem Handy öffnen, beim Slot **Spule wählen** tippen und
die Spule auswählen. Spulen, die zum ACE-Tag passen, sind markiert: *passt zur ACE* (Material **und**
Farbe) oder *Material passt, Farbe nicht*.

Spule rausnehmen: Meldet die ACE einen Slot eine Weile leer, wandert die Spule automatisch ins Regal
(während eines Drucks erst danach). Oder **Ins Regal** drücken.

## Slicen und drucken

1. In Orca den **Sync-Knopf** bei den Filamenten drücken. Mit dem orca-kobra-Build werden die
   `SM…`-Profile für Slot 1–4 automatisch gewählt; das Panel zeigt pro Slot *Filament N in Orca: passt*
   und warnt, wenn ein Filament-Feld nicht zu seinem Slot passt.
2. Slicen. Oben im Panel steht jetzt **Geplanter Verbrauch** mit einer Zeile pro Slot:
   *Bedarf / Rest in g* und ✓ (reicht), ⚠ (knapp) oder ✗ (reicht nicht). Reicht eine Spule nicht,
   warnt Orca zusätzlich mit einem Hinweis. *Details* klappt die Aufschlüsselung auf (siehe unten).
3. Drucken wie gewohnt (Printer Agent *Moonraker*).
4. Während des Drucks zeigt die Slot-Seite *Dieser Druck: x g* pro Slot. Die Bridge bucht in Spoolman
   bei jedem Farbwechsel, alle 5 Minuten und am Ende.

### So rechnet die Verbrauchsvorschau

Unter *Details* stehen zwei Tabellen, alle Werte in Gramm.

| Spalte | Herkunft |
|---|---|
| *Modell*, *Stützen*, *Gereinigt*, *Turm*, *Gesamt* | Genau Orcas Vorschau-Legende (Vorschau → Filament): Modell, Stützen, Spülen und Reinigungsturm pro Filament, *Gesamt* ist die Summe. Leere Spalten fehlen wie in Orca. |
| *Laden* | Spülen der Firmware, wenn die ACE das Filament lädt. Das kennt Orca nicht; die Bridge misst es bei jedem fertigen Druck (Mittel pro Ladevorgang). Bis zum ersten gemessenen Druck gilt ein Schätzwert von 0,32 m pro Ladevorgang. Wie oft jedes Filament geladen wird, zählt Orca (erste Benutzung plus jeder Wechsel zurück); mit einem älteren orca-kobra-Build werden die Filamentwechsel gleichmäßig auf die benutzten Filamente verteilt. |
| *Bedarf* | *Gesamt* + *Laden* |
| *Rest* | Restgewicht der Spule im Slot, aus Spoolman |

Filament N in Orca zählt gegen Slot N – dieselbe Zuordnung, die der Sync-Knopf setzt. Die
Vorschau braucht den orca-kobra-Build (Patch 0003); sie verschwindet, sobald das Slice-Ergebnis
nicht mehr gilt (Modell oder Einstellungen geändert). Die Reserve für *knapp* stellst du in den
Plugin-Einstellungen ein (Standard 5 g).

## Offene Posten

Wurde ein Slot ohne zugeordnete Spule benutzt, oder gibt es dessen Spule nicht mehr, bleibt der
Verbrauch als **offener Posten** oben auf der Slot-Seite stehen (*Nicht gebucht*). Einer Spule zuordnen
oder verwerfen. War Spoolman nicht erreichbar, holt die Bridge die Buchung automatisch nach.

## Ein Profil in Orca ändern

Ein `SM…`-Profil ändern und speichern. Das Plugin fragt *Nach Spoolman übernehmen?*:

- **Ja** – bekannte Einstellungen landen in ihren Spoolman-Feldern, alles andere in *Orca-Overrides*.
- **Nein** – der nächste Sync setzt das Profil auf die Spoolman-Werte zurück (Spoolman bleibt die Quelle).

Einen einzelnen Wert wieder von der Vorlage holen: das Feld in Spoolman leeren (oder
`POST /api/orca/reset`, siehe [api.md](../api.md)).

## Filament leer

Die Spule in Spoolman archivieren. Filamente ohne aktive Spule verlieren beim nächsten Sync ihr
Orca-Profil; Profile, die das Plugin nicht selbst angelegt hat, fasst es nie an.

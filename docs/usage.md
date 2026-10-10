# Daily use

[Deutsch](de/usage.md) · [Back to README](../README.md)

## Web UI and app

Everything you do at the printer goes through the **web UI** (`http://<docker-host>:7913`) or the
**Android app**. Both show the same data from the bridge; the app can additionally read and write
NFC tags. Spoolman's own UI is only needed for things the bridge does not cover (e.g. editing a vendor).

| Screen width | Layout |
|---|---|
| Phone | bar at the bottom: *Übersicht*, *Filament*, *Drucke*, *Mehr* |
| Desktop | side bar on the left: *Übersicht*, *Filament* (spools and filament types), *Drucke*, *ACE*, *Terminal*, *Logs*, devices, settings |
| Ultrawide (≥ 3000 px, e.g. 5120×1440) | the overview fits on one screen: printer with a large camera, slots with dryer and ACE, messages and status |

The **overview** is the printer monitor: the camera (the model only while printing), print status,
printer data, **Meldungen** and the four slots with dryer and ACE settings. Managing spools, filament
types and the print history has its own pages.

**Meldungen** lists, most important first, what needs attention: printer paused or in error, a slot
without material at the printer, a spool that **won't last for the running print** (the bridge reads
the print file: what each tool still prints plus the purge of the colour changes still to come,
5 % reserve), a spool almost empty (< 100 g), bookings not yet in Spoolman, Spoolman unreachable,
high humidity with the automation off, a print that just finished. Below it, **Status**: printer,
Spoolman, camera (frame rate, viewers), the paired app and Orca plugin (last seen) and the bridge.

Keyboard (desktop): `/` search, `n` new spool, `↑` `↓` select a spool, `Esc` close.
Right-click on a spool → put it into a slot, back on the shelf, archive.

The web UI asks for pairing once per browser ([installation](installation.md#4-pair-your-first-device)).
*Nur ansehen* skips it — everything is visible, but buttons that change something lead to the pairing screen.

## A new filament arrives

Create it in the web UI under **Filamente → Neu**, in the app with **Neu → Nicht dabei? Neues Filament**, or in
Spoolman directly.

| Field | What to enter |
|---|---|
| Vendor, Name | e.g. *Sunlu*, *PETG 2.0 Lavender* — the name includes the colour |
| Material | `PLA`, `PETG`, `PLA Silk` … (the base type decides the Orca filament type) |
| Colour | hex colour; for Anycubic spools use what the ACE reports so the slot check matches |
| Density, diameter, weight, price | from the label / shop |
| **Template** *or* **Orca base profile** | see below |
| Everything else | only what you want to override — empty fields show the inherited value as a grey placeholder |

**Template or base profile?**

- **Template** (`Vorlage PETG`, …): generic starting values maintained in Spoolman. Good for most
  third-party filaments. Leave empty → the template is picked by material.
- **Orca base profile**: the exact name of an Orca system profile, e.g.
  `Anycubic PLA Silk @Anycubic Kobra S1 0.4 nozzle`. The editor offers the names the Orca plugin
  reported. Use it when Orca already ships a tuned profile — the template is then ignored completely.

Order of precedence (later wins): *Orca base profile* ← *template* ← *filament fields* ← *Orca overrides*.
Field reference: [spoolman-fields.md](spoolman-fields.md).

**Same product, another colour:** open the filament and press **Neue Farbe** — all values are copied,
you only enter name and colour.

The Orca plugin creates the profile `Vendor Name (SM0000xx)` the next time Orca starts. Already
running? Press **Profile aktualisieren** in the panel, then restart Orca. Orca's filament **sync**
button then puts the profiles into the filament slots (see below).

<p align="center"><img src="images/web-filament.png" width="760" alt="Filament editor"></p>

## A new spool

**Neue Spule** (top right, or `n`): pick the filament, check the weights (defaults come from the
filament), optionally **Gleich einlegen** into a slot. In the app you can also scan an NFC tag first
— the new spool is linked to it, or the app writes an ACE-compatible tag for it
([android-app.md](android-app.md)).

## Loading a spool into the ACE

On the slot card press **Spule wechseln** (or **Spule zuordnen** for an empty slot) and pick the
spool. Spools that match what the ACE reads from the tag are on top and marked *passt*.

**Spools without a tag:** the ACE does not know their material. When you assign such a spool, the
bridge passes material, colour and temperature from Spoolman to the ACE driver (`ACE_SET_SLOT`; assigned
before loading: as soon as the spool is in; during a print: afterwards). Only the assignment does
this; to push the values again, assign the spool again. ACEPRO needs them for endless spool and for the
load temperature.

Removing a spool: if the ACE reports a slot empty for a while, the spool is moved to the shelf
automatically (during a print only after it ends). You can also press **Leeren** on the slot card.

**Spools with our tags are assigned automatically.** When the ACE reads one of our stickers
(`AHPEBK-<number>`, number ≥ 1000) in a slot, the bridge assigns the spool with that tag number — the
previous spool goes to the shelf, also during a print (consumption continues on the new spool). A
spool already loaded when the bridge starts is recognised too. The slot card then says *RFID*.
An unknown number shows up under *Meldungen*; assign the spool by hand once and the bridge remembers
the number on it (if it has none yet). Original Anycubic tags (102, 107, …) name a filament type, not a
spool — those stay manual. A manual assignment is not overridden until the tag in the slot changes.

## Spools and filament types

**Filament** has two views, switched at the top: **Spulen** (spools) and **Sorten** (filament types).
A filament type lists its spools; tapping one opens it under *Spulen*.

**Spulen** lists every active spool with remaining weight, location and tag number; filter by material,
*im ACE* or *fast leer* (< 200 g), or search. Select a spool to edit it:

- **Spule**: remaining weight (after weighing), empty spool weight, net weight, price, lot, note and —
  for spools on the shelf — the storage location.
- **Filament**: the filament editor, right there.
- **Verbrauch**: first and last use and every recorded print with this spool.

<p align="center"><img src="images/web-shelf.png" width="760" alt="Shelf with spool details"></p>

## Drying (ACE dryer)

The dryer card shows the ACE's humidity and its current temperature; while drying also the set point,
the filament that limits it and the time left. **Trocknen** /
**Stoppen** works by hand; **Regeln** sets the automation: start when the humidity rises above a
threshold (default 20 %) — and has stayed above it for *Warten* minutes (default 15), so opening
the lid for a moment starts nothing — stop below a second one (default 10 %) or after a maximum time,
then a pause; optionally also while printing. A run started **by hand, by plan or because a spool was
loaded** always lasts its full time, however dry the ACE reports; if the ACE stops early, the bridge
starts it again with the remaining time. Only the automation stops on low humidity.

The temperature is **never higher than the most sensitive loaded filament allows** — the field
*Trocknen max.* on the filament, else on its template, else a cautious default per material
(PLA 55 °C, PETG 60 °C, TPU 55 °C, …) — and never higher than the ACE can do (ACE 2 Pro 65 °C, ACE Pro 55 °C).
If a more sensitive spool is loaded while drying, the bridge lowers the temperature at once and keeps
the remaining time. The **ACE** page lists the limit of every slot.

**Feuchte-Verlauf** (ACE page, in the app in the dryer sheet) shows the ACE humidity over 6 h to
30 days, the ACE temperature, the set point while drying, the automation thresholds as dashed lines
and every print and drying as a band. Below it every drying with who started it (automation, by hand,
planned, spool loaded, printer display/Mainsail) and why, its temperatures and the humidity before and after.

<p align="center"><img src="images/web-humidity.png" width="760" alt="Humidity history with dryings"></p>

## Spool moisture

Nobody can measure how wet a spool is — but the bridge can follow where it was. Every spool gets a
**moisture estimate**: it rises with the humidity around the spool (ACE sensor while loaded, the
storage room on the shelf) and falls while drying. 100 % means *trocknen empfohlen*. How fast a
material takes up water and how long it needs to dry come from the material (open at 50 % RH: PLA ~14 days,
PETG ~5, ABS/ASA ~21, TPU ~2, PA/PVA less) and can be set per filament (*Offen bis Trocknen*,
*Trocknen Dauer*).

- **Loading a spool that needs drying** — also a new spool without history — starts the ACE dryer by
  itself: temperature of the most sensitive loaded spool, time of the wettest one.
- **Print start check**: when a print starts, the bridge compares every tool of the file with its
  slot — empty slot, other material, clearly different colour, no spool assigned, or a spool that
  needs drying — and shows it under *Meldungen*. By default it only warns; *Druckstart mit feuchter
  Spule → Druck sofort pausieren* pauses the print once instead.
- The spool card has a **Feuchte** tab with the estimate, where the spool is, the last drying and its
  history; **Außerhalb getrocknet …** records drying in another dryer. The spool list can filter
  *trocknen*.
- The storage room counts with 50 % humidity until a **room sensor** is connected through MQTT (see
  [configuration](configuration.md#home-assistant-mqtt)); dry boxes get their own value per Spoolman
  location (`Trockenbox=15`).

<p align="center"><img src="images/web-spool-moisture.png" width="760" alt="Moisture tab of a spool"></p>

## Watching a print in 3D

While printing, **Modell** shows the print file in 3D like OrcaSlicer's preview — grey background, the
Kobra S1 plate with its 10 mm grid, every line as a lit strand with its real width and layer height in
the colours of the loaded spools: printed part solid, the rest as you choose under *Rest* — *Durchsichtig*,
*Voll* (the whole model in full colour, like Orca) or *Aus* — and the nozzle position live. Below the picture,
*Benutzt* lists the slots the file uses with the total amount and what is still to print, purge included. Drag to rotate, two fingers or right mouse button
to move, wheel or pinch to zoom; *3D*, *Oben*, *Vorne* jump to a view. The layer slider looks at any
layer (*nur Schicht* shows only that one, *Live* returns to the running layer). How it is drawn depends on
the device (*Einstellungen → Dieses Gerät → 3D-Modell*, in the app *Einstellungen → 3D-Modell*):
*Volumen* (shaded strands), *Linien* (light on the graphics), *Bild der Bridge* (for weak devices)
or *Automatisch*, which picks by what the device can do.

<p align="center"><img src="images/web-3d.png" width="760" alt="3D view of the running print"></p>

## Watching a print

The printer card shows **Modell** — the print file drawn by the bridge in the colours of your
loaded spools, printed part solid, the rest as a shadow, with the current layer — and **Kamera**,
the printer camera live (only on paired devices), with the frame rate in the corner. Below the image:
nozzle and bed (actual/target), part, enclosure and air filter fans, speed and flow factor, layer —
values with a target or a changed factor are highlighted. Tap the image for full screen. Below the
progress bar: how long the print has been running, about how long it still takes and the estimated
finish time (*~17:35*, *morgen ~02:10*), estimated from the progress so far.

The bridge **restreams** the camera: however many browsers and phones watch, it fetches single images
from the printer only once — and only while someone is watching. The rate (up to 10 fps) adapts to the
printer's CPU; *gedrosselt* in the corner means the bridge is holding back so the print comes first. Point Mainsail at the bridge too, so it does not open
a second stream: **Geräte → Kamera-Link** shows a stream and a snapshot URL. In Mainsail open
*Settings → Webcams*, edit the webcam, choose the service *MJPEG-Streamer* and paste the two URLs.
The link only shows the camera; *Neu erzeugen* replaces it (the old one stops working).

## ACE settings

The **ACE** page (app: tap the dryer card) shows what the printer display hides:

- **Endlosspule** (endless spool) — when a spool runs out, the ACE loads a matching one and the print
  goes on. *Welche Spule passt?*: same colour and material, same material, or simply the next spool.
  Allowed while printing; applies at the next runout. The consumption follows the new slot.
- **Trocknen planen** — one start at a set time, e.g. tonight at 22:00.
- **Pressure Advance**, **Fortsetzen nach Stromausfall** and **Verstopfung erkennen** — the switches of
  the printer's Klipper modules, see the sections below. Each card only shows when the printer has the
  module; every switch is stored in the printer.

The purge per colour change is set in Orca (flushing volumes next to *Filament*); the printer profile's
change-filament G-code passes it to the ACE driver, see [installation](installation.md#orca-printer-profile).

## Resume after a power loss

With the Klipper module `kobra_resume` (not part of this repo) the printer keeps saving the position it has really
printed. After a power loss the overview shows **Druck unterbrochen** with the live picture (and the app raises an
alarm): check that the part is still stuck to the bed, then **Fortsetzen** — the printer heats the bed, homes X/Y,
probes the height on the last printed line with the load cell (instead of homing Z onto the part), purges and continues
where it stopped, slower for the first minute. If the probed height does not fit it stops instead of guessing.
**Verwerfen** drops it. Nothing happens without your confirmation. Switch: ACE page → *Fortsetzen nach Stromausfall*.

## Clog detection

With the Klipper module `kobra_clog` (not part of this repo) the printer compares, while printing, how much filament
the extruder fed with what the encoder at the filament inlet saw. If the encoder sees far too little twice in a row,
the overview and the app show **Verstopfung?** with the numbers — check the nozzle and the filament path. By default it
only warns; ACE page → *Verstopfung erkennen* switches it off or to *Pausieren*. Tool changes are not checked (the ACE
moves the filament itself).

## Z offset per filament

Some filaments want the first layer a little higher or lower (e.g. PETG). Enter it in Spoolman as **Z-Versatz** (mm,
+ = farther from the bed) on the filament or on its template; the bridge gives the values of the loaded slots to the
printer and the print start adds the start filament's value to the first layer (shown in the console as
`Filament T0 +0.020`). Empty = 0. Off: *Einstellungen → Erste Schicht*, or `use_filament_z: False` in `KOBRA_START`.

## Pressure advance (Auto-PA)

With the Klipper module `kobra_pa` (not part of this repo) the printer measures pressure advance with the load cell
in the print head, like Anycubic's stock firmware, but only once per filament: if the filament of a slot has no PA in
Spoolman yet, the printer measures it at the start of the print or after the colour change (~2 minutes, about 120 mm
into the purge chute) and the bridge stores the result on the filament — a table with K per speed (*PA-Tabelle*) and K
at 200 mm/s in *Pressure Advance*, which Orca's profile picks up. Klipper then applies K per move speed.

The card **Pressure Advance** on the ACE page (app: ACE sheet) shows K per slot and has two switches that live in the
printer: **Auto-PA** (off = Klipper uses Orca's PA) and **Automatisch messen**. *Messen* measures the loaded slot now
(not while printing), *Neu messen* deletes the value so the next print measures again. A value you enter by hand
(Spoolman or Orca) counts as fixed PA and is not measured; changing PA in Orca replaces a measured table. A failed
measurement never stops the print — it continues with the previous PA. *Einstellungen → Pressure Advance* turns off the
link to Spoolman entirely.

## Slicing and printing

1. In Orca press the filament **sync** button. With the orca-kobra build the `SM…` profiles are
   selected for slots 1–4 automatically; the panel shows *Filament N in Orca: passt* per slot and
   warns if a filament box does not match its slot.
2. Slice. At the top of the panel, **Geplanter Verbrauch** (planned usage) shows one line per slot:
   *need / remaining g* and ✓ (enough), ⚠ (*knapp*, tight) or ✗ (*reicht nicht*, too short). If a
   spool is too short, Orca also shows a warning. *Details* expands the breakdown (below).
3. Print as usual (printer agent *Moonraker*).
4. During the print the printer card and the slot cards show the consumption so far
   (*dieser Druck*). The bridge books into Spoolman at every colour change, every 5 minutes and at
   the end. Finished prints appear under **Drucke** with grams per spool.

Pause, cancel and fine-tuning work from the printer card ([below](#controlling-a-print)); files,
macros and starting a print stay in Mainsail/Fluidd (*Mainsail* on the printer card).

### How the usage preview is calculated

The *Details* table is Orca's own preview legend (Preview → Filament), all values in grams.

| Column | Source |
|---|---|
| *Modell*, *Stützen*, *Gereinigt*, *Turm*, *Gesamt* | model, support, flush and prime tower per filament, *Gesamt* is their sum; empty columns are left out, as in Orca. *Gereinigt* contains the ACE's load (85 mm) and purge at every colour change — the printer profile reports it to Orca (`EXTERNAL_PURGE`). If it is missing although the print changes colour, the panel says so. |
| *Rest* | remaining weight of the spool assigned to the slot, from Spoolman |

Filament N in Orca is counted against slot N — the same mapping the sync button sets. The
preview needs the orca-kobra build (patch 0003); it disappears when the slice result is no longer
valid (model or settings changed).

## Open items

If a slot without an assigned spool was used, or its spool was deleted, the consumption is kept as
an **open item** (card *Offene Buchungen*, badge on *Drucke*). Press **Buchen**, pick the spool, or
**Verwerfen**. If Spoolman was unreachable, bookings are retried automatically.

## Changing a profile in Orca

Edit an `SM…` profile and save it. The plugin asks *Nach Spoolman übernehmen?*:

- **Yes** — known settings go to their Spoolman fields, everything else to *Orca overrides*.
- **No** — the next sync resets the profile to the Spoolman values (Spoolman stays the source of truth).

This needs the plugin to be paired; otherwise it tells you so. To go back to the template for a
single value, clear that field in the filament editor (or use `POST /api/orca/reset`, see [api.md](api.md)).

## When a filament is used up

**Archivieren** on the spool (shelf, app or Spoolman). Filaments without any active spool lose their
Orca profile on the next sync; profiles the plugin did not create are never touched.

## Controlling a print

Below the print status (web UI and app, paired devices only): **Pause** / **Weiter**, **Abbrechen**
(asks first, a cancelled print cannot be resumed), **Nachjustieren** — speed, flow, the three fans and
the nozzle/bed target, also without a print (e.g. to preheat) — and **Not-Aus**: hold it for two
seconds, then confirm. After an emergency stop (or a Klipper error) the bar shows **Klipper neu laden**
(`FIRMWARE_RESTART`, asks first); home the axes again afterwards.

## The printer's own display

`http://<docker-host>:7913/display` is a view made for the Kobra S1's touchscreen (800×480, fingers): a kiosk
browser on the Klipper Pi shows it on the original display (setup outside this repo). Left bar: *Start*, *Druck*,
*Schalter* and the light.

- **Start** — nozzle, bed, ACE humidity, the four slots with their spool colour and weight, the dryer.
- **Druck** — opens by itself when a print starts: the file's preview picture, progress, layer, running/remaining/
  finish time, temperatures, speed and flow, the slots the file uses; pause/resume, *Nachjustieren* (speed, flow),
  cancel (asks first).
- **Schalter** — every switch of the printer's Klipper modules in three tabs (*Drucken*, *Überwachung*,
  *Licht & Töne*), plus the AI. They are stored in the printer, so web UI, app and Mainsail show the same.
- **Steuerung** — temperatures (presets from the loaded spools or the number pad), moving (home, jog with 0.1–50 mm
  steps, motors off), filament (load a slot through the ACE, unload, extrude when hot), fans, *Bettnetze messen*,
  Klipper restart and an emergency stop you hold for 1.5 s. Moving and loading are locked while printing.
- **Dateien** — the print files on the printer with preview, time and colours; tap one to see its tools next to the
  slots and start it. After a print: *Erneut drucken*.
- **Nachjustieren** (while printing) — speed and flow, the first layer's height (±0.01–0.05 mm, *Für … übernehmen*
  adds it to the filament's *Z-Versatz* in Spoolman) and *Objekte* to skip a failed part.
- **System** — all messages, IP and versions, Klipper restart, Pi reboot/shutdown. Macro prompts (e.g. filament
  runout) and a Klipper error appear over everything.
- Pause has no confirmation; *Abbrechen* appears once paused and asks first; the emergency stop always asks first.
- After a power loss the whole screen asks whether to resume ([see above](#resume-after-a-power-loss)).

Reading needs no key; to switch something the display is paired once like any device: create a code under
*Geräte → Gerät hinzufügen* and type it on the display's number pad.

## Notifications on the phone

<p align="center"><img src="images/app-notification.png" width="420" alt="Print notification"></p>

The app watches the printer in the background and replaces the OctoApp companion (which on the Kobra S1
took about two thirds of the printer's CPU). It only asks the bridge, so the printer does not notice.

- **While printing** the print is a *Live Update* (Android 16+): always at the top of the shade, on
  the lock screen and as *48 %* in the status bar, with progress, remaining and finish time and layer.
  Android allows no picture there; on older phones, or if you switch Live Updates off for the app, it
  is a normal notification with a camera picture.
- **Own sounds**, so you can tell them from other apps: print started, first layer done, print
  finished, alarm, hint.
- **Alarm** (with a camera picture): printer error, a pause or cancel you did not make yourself (a
  pause from the web UI or the app is no alarm), a stuck colour change, a falling nozzle temperature,
  printer or bridge gone during a print, a spool that won't last, an interrupted print after a power
  loss, a suspected clog.
- **Hint**: only what you can act on — an unknown tag in a slot, a slot without material, Spoolman
  unreachable for more than 5 minutes. Printer CPU, *fast leer*, open bookings and humidity stay in
  the app's *Meldungen*.

*Einstellungen → Töne* plays every sound and sends a test notification per kind (checks volume and
*Do not disturb*). Switch monitoring off under *Einstellungen*; each kind is a separate channel in
Android's notification settings.

**Widget:** *Einstellungen → Widget auf den Startbildschirm* puts the print on the home screen — camera
picture, progress, remaining and finish time; tapping it opens the app.

## Settings

*Einstellungen* in the web UI changes the bridge while it runs — camera, print preview, slots and RFID,
spool moisture, notices, consumption, data — no restart and no Portainer. The stack's environment
only gives the start values; *zurücksetzen* goes back to them. See [configuration](configuration.md#changing-settings-at-runtime).
At the bottom, *Neu in der Bridge* lists the changes of the last ten versions (all of them: [changelog](../CHANGELOG.md)).

<p align="center"><img src="images/web-settings.png" width="760" alt="Bridge settings"></p>

## Home Assistant

With `MQTT_HOST` set, the bridge sends printer, slots, ACE, messages and AI to your MQTT broker and
Home Assistant creates the device *Kobra S1 (ace-lane-bridge)* by itself — the printer gets no extra
client. Details in [configuration](configuration.md#home-assistant-mqtt).

## AI print-failure detection

With [kobra-vision](vision.md) running, the bridge sends a camera picture to the AI every 10 s while
printing and watches the score over the print. When a print turns into spaghetti you get a red message
**KI: wahrscheinlich Fehldruck** — in the web UI with **Fehlalarm** / **Stimmt**, on the phone as an
alarm with camera picture and **Pausieren** / **Stimmt** / **Fehlalarm**. The camera image shows the found spots as
boxes. *Fehlalarm* silences the AI for the rest of this print. The first ~5 minutes of a print never
alarm. By default the AI only warns; it can pause by itself once you trust it (`VISION_ACTION=pause`).
The pictures are collected (up to 5 GB) to teach the next stages: plate check and knocked-over parts.

Everything is controlled in the **KI** tab: sensitivity, report or pause, quiet hours, areas to ignore
(e.g. the purge chute), the baseline, all events, and the picture collection to label, delete or
download — details in [vision.md](vision.md#the-ki-tab). In the app: *Mehr → KI*.

<p align="center"><img src="images/app-ai-alarm.png" width="360" alt="AI alarm on the phone"></p>

## Terminal and logs

**Terminal** shows what the printer answers and every command sent through the bridge, with who sent
it (a browser, the dryer, the ACE card, a slot assignment). Type G-code or a macro: `Tab` completes
from the printer's command list, `↑` `↓` browse your history. Risky commands — emergency stop,
`SAVE_CONFIG`, restarts, a nozzle above 260 °C, moves during a print — ask first. Sending needs a
paired device.

**Logs**: *Bridge* is the bridge's own log (filter by level, search, download — no detour through
Portainer); *Drucker* shows the end of the printer's log files (`moonraker.log`, …; only the last
200 KB, more on request); *Druck-Aufzeichnungen* are the raw recordings of each print for download.

<p align="center"><img src="images/web-terminal.png" width="760" alt="Terminal"></p>

## Devices

**Geräte** lists every paired browser, phone and Orca plugin with the time it was last seen.
**Gerät hinzufügen** shows a code and QR code for a new device; **Entfernen** revokes a key at once
(e.g. a lost phone). *Entkoppeln* on your own browser forgets its key.

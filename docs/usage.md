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

**Spools without an Anycubic tag:** the printer does not know their material. When you assign such a
spool, the bridge passes material and colour from Spoolman to the ACE — the printer display shows
them right away (assigned before loading: as soon as the spool is in; during a print: afterwards).
Only the assignment does this; to push the values again, assign the spool again. Without it (bridge
off, `SET_ACE_SLOT_INFO=false`) enter them at the display, otherwise the print fails at the start
(`index out of range`). The web UI, the app and the Orca panel warn about such slots.

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
threshold (default 20 %), stop below a second one (default 10 %) or after a maximum time, then a
pause; optionally also while printing.

The temperature is **never higher than the most sensitive loaded filament allows** — the field
*Trocknen max.* on the filament, else on its template, else a cautious default per material
(PLA 55 °C, PETG 60 °C, TPU 55 °C, …) — and never higher than the ACE can do (ACE 2 Pro 65 °C, ACE Pro 55 °C).
If a more sensitive spool is loaded while drying, the bridge lowers the temperature at once and keeps
the remaining time. The **ACE** page lists the limit of every slot.

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

## ACE settings and purge

The **ACE** page (app: tap the dryer card) shows what the printer display hides:

- **Purge multiplier** — how much the ACE flushes at a colour change (`× 1,0` is the firmware
  default; Minimal 0,1 / Normal 1,0 / Maximum 3,0 or any value). Next to it the purge of every
  change between your loaded spools, with the current and the new value, in mm and grams. Less purge
  saves filament but can mix colours — try it on a small print.
- **Automatisch nachladen** (backup spool when one runs out) and **Leer-Erkennung** (runout detection).
- **Trocknen planen** — one start at a set time, e.g. tonight at 22:00.

During a print the fields are locked; **Freischalten** unlocks them after a warning. A new
multiplier applies from the next colour change.

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

The *Details* section has two tables, all values in grams.

| Column | Source |
|---|---|
| *Modell*, *Stützen*, *Gereinigt*, *Turm*, *Gesamt* | Exactly Orca's preview legend (Preview → Filament): model, support, flush and prime tower per filament, *Gesamt* is their sum. Empty columns are left out, as in Orca. |
| *Laden* | Firmware purge when the ACE loads the filament — Orca does not know about it. Computed **per colour change** exactly like the firmware does it: Orca's colour formula for the two slot colours (as the ACE reports them) + 107 mm³, times the multiplier set at the printer display; the first load of a print is a fixed ≈ 95 mm. The bridge reads the multiplier from the printer and refines the small constants on every finished Orca print. Orca counts the changes (from → to); with an older orca-kobra build the colours are averaged, without the bridge's purge model a measured average per load is used. |
| *Bedarf* | *Gesamt* + *Laden* |
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
seconds, then confirm. After an emergency stop the printer has to be switched off and on again;
Rinkhals blocks a firmware restart because GoKlipper would hang.

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
  printer or bridge gone during a print, a spool that won't last.
- **Hint**: only what you can act on — an unknown tag in a slot, a slot without material, Spoolman
  unreachable for more than 5 minutes. Printer CPU, *fast leer*, open bookings and humidity stay in
  the app's *Meldungen*.

*Einstellungen → Töne* plays every sound and sends a test notification per kind (checks volume and
*Do not disturb*). Switch monitoring off under *Einstellungen*; each kind is a separate channel in
Android's notification settings.

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

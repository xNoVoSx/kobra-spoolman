# Changelog

All notable changes. Versions: **bridge** = ace-lane-bridge (also the repo tag),
**plugin** = Orca plugin "Kobra Spoolman". Plugin-only releases have no repo tag.
The bridge follows [semantic versioning](https://semver.org/): x.y.**Z** = bug fixes, x.**Y**.0 = new features,
**X**.0.0 = major changes.
Changes to the Orca patches and build: [orca-kobra CHANGELOG](https://github.com/xNoVoSx/orca-kobra/blob/main/CHANGELOG.md). Format based on [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

## [4.1.0] – 2026-10-19

### Added
- **Direct feed** — filament inserted by hand straight into the toolhead (e.g. TPU) while the ACE stays on and
  connected (drying, slots). Switched in the web UI (*ACE* page), the app (ACE sheet), the printer display or
  `POST /api/direct` with the spool you inserted; it stays on until switched off and shows a **red bar** on every page
  (web, app home screen, display) and in Mainsail. While it is on the bridge books the consumption on that spool (no
  open item), gives its Auto PA and Z offset for every tool, and the print start check compares the file with it — a
  multi-colour file is paused at once with a message. Needs kobra-klipper's `kobra_direct` module (Klipper + ACEPRO);
  without it nothing changes. `direct` in `/api/app/state`, `GET/POST /api/direct`. The same request came from a user
  on Discord (book a direct-feed spool without an open item).
- Clog detection: *Log only* as a third reaction (web, app, `POST /api/clog/switch` with `"action": "log"`) — kobra-
  klipper's default since 18.10.

### Changed
- Auto PA texts: a measurement now takes ~5 minutes (each step is pushed three times and the median taken — kobra-klipper).

### Fixed
- ACE humidity and firmware showed *–* after a Klipper restart (e.g. `SAVE_CONFIG`) while Mainsail was open. The ACE
  driver reports them only once the ACE is connected; Moonraker subscribes Klipper with the union of all clients, and
  Mainsail asks for all fields, so Klipper froze the field list without them – the bridge's explicit field list from
  3.13 could not prevent that. The bridge now queries these fields once a minute and subscribes again when the
  subscription misses a value the printer has.

### Documentation
- README: orca-kobra now carries three patches; the first-layer temperatures in the G-code header are in Orca itself
  since [#16422](https://github.com/OrcaSlicer/OrcaSlicer/pull/16422).

## [4.0.2] – 2026-10-14

### Fixed
- Web UI on a phone: a slot card with a long spool name plus the moisture and *active* chips ran over the right edge;
  the name now gives way.

### Documentation
- README: the first image now shows the ACE slots with their Spoolman spools instead of the camera; new screenshots
  from a clean Rinkhals demo (English names, no error messages), the phone image shows the slots.

## [4.0.1] – 2026-10-14

### Fixed
- Slot cards: the hint *ACE reports the slot as empty* showed on every slot (and as a warning) while the printer was on
  and the ACE switched off. It now shows only for a slot taken out by hand; with the ACE off the cards say
  *Offline – last known* or show no hint. Reported by MineTech13.

## [4.0.0] – 2026-10-14

The first release meant for everyone, not only for the author's printer. No breaking change: an update from 3.x keeps
every setting, device and booking — the major number marks that the project is now documented and tested for others.

### What kobra-spoolman is (for newcomers)
- **Spoolman as the single source** for an Anycubic printer with an ACE: Orca filament profiles made from Spoolman,
  consumption booked per spool to the millimetre (also for multi-colour prints), a web UI, an Android app with NFC tags,
  ACE dryer automation with a moisture estimate per spool, a printer monitor with camera and notifications, Home
  Assistant over MQTT.
- **Supported printers:** Kobra S1 + ACE 2 Pro (Rinkhals and Klipper + ACEPRO, tested), Kobra 3 + ACE Pro (Rinkhals,
  confirmed with a user's prints), other Rinkhals printers with an ACE should work — see
  [Supported printers](README.md#supported-printers).
- **Install:** Docker next to Spoolman, or on Home Assistant OS the community add-on
  [MineTech13/ha-addons](https://github.com/MineTech13/ha-addons). Start with [docs/start.md](docs/start.md).

### Added
- Documentation for newcomers: supported printers with what is tested, the Home Assistant add-on in the quick start,
  a check list *Is it working?*, a table *What works without what*, troubleshooting for spools moved to the shelf and
  for the printer name (EN + DE).
- Diagnostics (*Logs → Report a bug*) name the printer and the ACE model.

### Upgrading from 3.x
- Pull the new image (Portainer: *Re-pull image* and redeploy; the add-on updates in Home Assistant). Nothing to change.
- Image pinned to a version (`ghcr.io/xnovosx/ace-lane-bridge:3.19` or `:3.19.0`)? Change it to `4.0`, `4.0.0` or
  `latest` — a pinned 3.x tag does not move to 4.
- Older than 3.18.1? Switching the printer or the ACE off moved all spools to the shelf — fixed; their slots stay.
- The app 1.18.0 comes through the app's update card; the Orca plugin 0.7.2 is in the release assets.

## [3.19.0] – 2026-10-14

### Added
- Slot cards while the printer or the ACE is off: they keep the spool Spoolman has in the slot and show it dimmed
  with *Offline – last known* (web, app, display), until the ACE reports again. `live` per slot in `/api/slots` and
  `/api/app/state`. (Since 3.18.1 switching off moves no spool to the shelf any more.)
- Printer and ACE name instead of a fixed *Kobra S1* / *ACE 2 Pro* (web header, display, app, widget, status bar,
  Home Assistant device): `PRINTER_NAME` (setting *Printer name*), else the model Orca writes into the print file
  (`printerinfo.py` reads only the file's last 128 KB at a print start, `data/printer.json`), else *Printer*. The ACE
  comes from the driver (ACEPRO `model`, Rinkhals `filament_model`). `printer_name` and `ace_model` in `/api/health`
  and `/api/app/state`.

### Tests
- Replay of a real print on a **Kobra 3 with ACE Pro** under Rinkhals (shared by MineTech13, 9 h, 94.4 m, 6 colour
  changes): every spool booked like the printer's counter, never below zero, and the firmware purge model within 10 %
  of the measured extra use. Switching the printer off and on moves no spool to the shelf.

## [3.18.2] – 2026-10-13

### Fixed
- Purge log (`/api/purge`, `/api/jobs` → `transitions`): `purge_mm` stayed empty for every change so far. Capturing
  works, but no Klipper print had a colour change from Orca's change G-code yet – the changes logged were the load of
  the print start – and under Rinkhals the firmware purges by itself without reporting a length. Every change now
  carries `purge_source`: `orca` (the change G-code set it), `firmware` (Rinkhals, the length from the firmware's
  formula in `purge.py`) or `other` (nothing set: print start, endless spool, by hand). `/api/purge` counts them per
  pair in `sources`; older entries count as `orca` with a length, else `unknown`.

## [3.18.1] – 2026-10-13

From the second Rinkhals test print (pause, resume, cancel, bridge restart).

### Fixed
- Pause, resume and cancel under Rinkhals: the firmware lowers the nozzle to 140 °C while paused and heats it up
  again before it resumes (~50 s); cancelling unloads first (~45 s). The bridge waited 30 s, the app only 15 s — the
  app said *bridge not reachable* although it worked, and *Resume* stayed on screen. Now the bridge answers after at
  most 8 s (**202**, `pending: true`) and `printer.pending_action` makes web and app show *Resuming – heating up …*
  (or *Pausing …*, *Cancelling …*) until the printer is there. The console says *still working on it* instead of a
  `TimeoutError`.
- Switching the ACE off (e.g. to clear a dryer fault) made every slot look empty: the bridge moved all spools to the
  shelf, the tags put them back, and the moisture model took that for spools being inserted and started drying. When
  every slot is empty at once nothing is moved now.

## app 1.19.0 – 2026-10-19

### Added
- Direct feed: red bar on the home screen while it is on (with *Switch off*), section in the ACE sheet to switch it on
  with the spool you inserted (optionally unloading the ACE filament first).
- Clog detection: *Log only*.

## app 1.18.0 – 2026-10-14

### Added
- Slots while the printer or the ACE is off: the card keeps its spool, dimmed with *Offline – last known*.
- The printer's name from the bridge (e.g. *Kobra 3*) in the header, widget and status bar instead of *Kobra S1*.

## app 1.17.1 – 2026-10-13

### Fixed
- *Pause*/*Resume*/*Cancel* on a slow printer: *Sent – the printer is still working on it* instead of *bridge not
  reachable*, and *Resuming …* instead of a second *Resume* button.

## plugin 0.7.2 – 2026-10-13

### Changed
- Works with orca-kobra builds after Orca's review of `slice_statistics` (#16423): no `require_valid` argument any
  more, the slice result is valid already when *SlicingJobComplete* arrives, `loads` is gone (the plugin counts loads
  from `transitions`). Older builds keep working.

## plugin 0.7.1 – 2026-10-13

### Fixed
- Usage details (*Details (like Orca's legend)*): the columns had no gap in Orca's narrow side panel and the numbers
  ran together (*12.0516.90422.8*). Columns are spaced now, *Rest* in whole grams, and the table scrolls sideways
  when the panel is narrower still.

## [3.18.0] – 2026-10-13

From the Rinkhals test print: the lid of the ACE was open while it dried, and afterwards its heater reported a fault.

### Added
- Dryer: when the ACE is still more than 10 °C below its target 30 minutes into a run, web and app say *lid open?*
  (the app as a notification), and the run keeps the minutes it was too cold (`lid_open_now`, `lid_minutes` in
  `/api/humidity`). Switch: `DRYER_LID_CHECK`.
- *Discard* on every ended drying run (web: humidity history, app: dryer sheet,
  `POST /api/humidity/sessions/{id}/discard`): its spools go back to the moisture estimate from before it, also in
  Spoolman (an emptied *last dried* is removed there).
- Print card: *x of y still to print* plus what is left on the spool (`spool_g` in `uses`); before it read
  *~y, x left*, which looked like the spool's rest. The app shows the printer's CPU under Rinkhals too.

### Changed
- Moisture estimate: while drying, a spool approaches the humidity the ACE measures instead of always drying — with
  the lid open (44 °C, 41 %) hardly anything counts, closed and hot (~5 %) it is as before. Switch: `MOISTURE_ACE_RH`.

### Fixed
- A dryer fault reported by the ACE (`PTC_err`, heater) was taken for "stopped early": the bridge restarted the run
  three times. Now it stops — no restart, no automation, no planned start — and shows a red message; `error` in
  `/api/dryer`. Starting by hand still works.
- Rinkhals: at every unload GoKlipper's counter drops by 53 mm (retract and cut) and comes back +50 before the next
  slot. An interim booking in that moment gave the spool −53 mm in Spoolman. Interim bookings now only go forward;
  at a change and at the end a correction takes back at most what the print booked on that spool, and a net retract
  never becomes an open item. Replay test of the real print (56 changes, `tests/test_replay_rinkhals.py`).

## app 1.17.0 – 2026-10-13

### Added
- Dryer sheet: *lid open?* / *x min too cold* on a drying run, *Discard* for an ended run; *lid open?* comes as a
  notification.
- Printer card: *x of y still to print* and what is left on the spool; the printer's CPU under Rinkhals.

## [3.17.0] – 2026-10-13

From the Rinkhals test on the real printer.

### Added
- Original Anycubic tags (product code like `AHPEBK-102`, which names a filament type, not a spool): if exactly one
  spool on the shelf has the same material, colour and vendor, it is assigned automatically, once per insertion; with
  several (or none) a message asks. Switch: *Settings → Slots and RFID*, `AUTO_ASSIGN_BY_KIND` (default on).
- Rinkhals: the printer card (web) shows the printer's CPU all the time; `printer.printer_cpu` in `/api/app/state`,
  `printer_cpu` and `stream_ignored` in `/api/camera`.

### Fixed
- Rinkhals: the loaded slot is read from GoKlipper's `filament_hub.current_filament` (`"0-2"` = slot 3). Before, a slot
  with `gate_status -1` counted as loaded — but that only means *busy* (rolling back, feeding), and after loading all
  slots report `1`, so the loaded slot was not recognised at all.
- Camera: switching *continuous stream* off did not take effect while someone was watching — the old stream stayed
  open (printer CPU 100 % under Rinkhals). The reader now ends on every change. Under Rinkhals the stream setting is
  ignored altogether: the bridge only fetches snapshots by the printer's CPU.

## [3.16.1] – 2026-10-13

### Changed
- AI print-failure detection is marked *experimental*: on the Features page (web and app), on *Start here* and in
  `docs/vision.md`, which says what is proven (Obico's model) and what is not yet (no real failed print on a Kobra seen
  yet, thresholds from little data, nozzle off after an AI pause untested).

## app 1.16.1 – 2026-10-13

### Changed
- *Features*: the AI print-failure detection shows *experimental*.

## [3.16.0] – 2026-10-13

A simpler start: new installations start with the core and a setup page, existing ones keep everything, and one page
shows and switches every feature.

### Added
- `features.py`, `GET /api/features`, `POST /api/features/<key>` (paired): every feature of the system with what it
  does, what it needs, whether it is on, where its switch lives and a link to the docs — built on the existing switches
  (bridge settings, printer modules), nothing is switched twice. What the installation sets (environment variables, HA
  add-on options) is shown and never changed there.
- Web UI page *Features* (side bar, *More* on the phone, *Settings → More settings*).
- `setup.py`, `GET /api/setup`, `POST /api/setup/done`: at the first start the bridge decides once whether it is a new
  or an existing installation. New: the core is on (spools, slots, bookings, RFID, camera, print preview, the printer
  modules that are installed), automatic drying, drying new spools and print recordings start off, and the web UI
  opens the setup page after pairing — found / choose / what is left to set up by hand. Existing: nothing changes, the
  overview shows a one-time hint on the Features page. What the installation sets always wins.
- ACE page: a printer module that is switched off (resume after power loss, clog detection, Auto PA) disappears, with a
  link to switch it on under *Features*.
- Docs: *Start here* (`docs/start.md`, `docs/de/start.md`) by goal — the core in about 5 minutes, then every extension
  with what it gives, what it needs, how to switch it on, what it costs the printer and which setup it runs on.

## app 1.16.0 – 2026-10-13

### Added
- *More → Features*: every feature of the system with what it does, what it needs and one switch each – the same as
  the web UI's page.
- Setup after pairing: a freshly paired app opens it right away – what the bridge found, NFC and notifications on this
  phone, the printer's messages on, then choose the features and see what is left to set up on another device.
- An app that was paired before shows a one-time hint on the new Features page instead; nothing changes.

## [3.15.0] – 2026-10-13

Pause and cancel work during the print start. Until now the start sequence (`G9111`, up to half an hour with the heat
soak) held Klipper's G-code lock, so Pause and Cancel waited until it was done — only the emergency stop helped.

### Added
- `startseq.py`: with the printer module `kobra_seq` (Klipper + ACEPRO setup) every pause/resume/cancel of the bridge —
  web UI, app, display, AI, damp spool check, clog — goes to its endpoint `printer.kobra_seq.control` while the start
  sequence runs; that endpoint does not wait for the G-code lock. The start holds at the next safe point (before a step
  or while waiting for a temperature) and lifts the nozzle; cancel switches the heaters off and ends the print as
  cancelled.
- `/api/app/state`: `printer.start_seq` (`paused`, `requested`, `step`, …); a paused start sequence reports
  `printer.state` `paused` and the phase *Start sequence paused · <step>*; message *Start sequence paused – continue or
  cancel*.

### Unchanged
- Without the module, with it switched off, or with Rinkhals: pause/cancel as before.

## [3.14.0] – 2026-10-13

Bug reports that can be reproduced: the bridge collects what a report needs, the GitHub forms ask for it.

### Added
- `diagnostics.py`, `GET /api/diagnostics` (paired devices): versions (bridge, Python, Klipper, Moonraker, Spoolman,
  update manager), setup (Rinkhals or Klipper + ACEPRO, ACE objects), connections, slots, settings, warnings and the
  last log lines as Markdown. Host names, IP addresses, e-mail addresses and keys are removed, secrets only show as
  `set`/`not set`.
- Web UI *Logs → Report a bug*: shows and copies the diagnostics and opens the GitHub form with the bridge version
  filled in.

### Changed
- Bug report forms (this repo and orca-kobra) ask for what is needed to reproduce, like OrcaSlicer's: latest version
  checked, setup, printer, versions, steps / what happened / what was expected, diagnostics, logs, project file.
  orca-kobra asks whether the problem also happens in the official OrcaSlicer nightly.

## [3.13.0] – 2026-10-12

The web UI runs behind **Home Assistant ingress** as it is — the community add-on
[MineTech13/ha-addons](https://github.com/MineTech13/ha-addons) no longer needs to patch it.

### Added
- `ingress.py`: a request through HA's ingress proxy (`X-Ingress-Path` from `172.30.32.2`) gets a start page with
  `<meta name="ingress">`; the camera then asks for one image after the other and copyable links point at the direct
  address.
- `GET /api/camera/frame.jpg?after=<n>`: the next camera image (long poll, header `X-Frame`) — live view where an MJPEG
  stream does not get through. Rides on the one connection to the printer like a stream viewer.
- `HA_INGRESS_TRUST` (default `false`): requests from HA's ingress proxy count as the paired device *Home Assistant
  (ingress)*; the header alone is never trusted.
- `BRIDGE_PUBLIC_URL`: the direct address for camera links and the app's pairing QR code under ingress (default: the HA
  host on `HTTP_PORT`). `CAMERA_INGRESS_SNAPSHOTS` (default `true`) switches the single-image camera off.
- Docs: Home Assistant add-on as installation option B.

### Changed
- The web UI uses relative paths only (API calls, printer log, AI test image, display thumbnails); a test keeps it so.
- Slot card: the spool name opens the spool under *Filament → Spools* (on the overview the click showed nothing). Idea
  from MineTech13's add-on.

## [3.12.0] – 2026-10-12

**Rinkhals is back.** One bridge for both setups: the stock firmware with
[Rinkhals](https://github.com/rinkhals-community/Rinkhals) and Klipper on a Raspberry Pi with ACEPRO. The bridge detects
the firmware from Moonraker; nothing to configure. Use with plugin 0.7.0 and app 1.15.0 (older apps keep working, without
the new ACE card). **English is the main language now**, German is a second language per device.

Upgrading from 2.21.1 (Rinkhals): switch the image tag to `latest` / `3.12.0` and the plugin to 0.7.0. The data folder
is the same format as in 3.x (the 2.x → 3.0 upgrade carried devices and history over) — keep a copy of it anyway, this
path was tested with replays and a simulated printer, not yet on a real Rinkhals printer.

### Added
- **Rinkhals support** in the current line (`acemodel.py`): slots, tags and the loaded slot from Rinkhals' `mmu` and
  GoKlipper's `filament_hub`; slot info for untagged spools with `MMU_GATE_MAP`; dryer with `MMU_DRYER_START/STOP`;
  consumption with the debounce Rinkhals' flickering gate needs; tool → slot from `ttg_map` for the print check and the
  3D view; the subscription only asks for objects the printer has (GoKlipper can panic on unknown ones).
- **ACE card on Rinkhals** (web UI, app): endless spool (`auto_refill`), runout detection and the firmware's purge
  multiplier (presets 0.1×/1×/3×, slider) with the purge in mm and g for every pair of loaded colours. Changes during a
  print need a confirmation (`confirm_printing`, else 409). API: `GET /api/ace` → `settings.variant`,
  `settings.options`, `purge` (`?multiplier=` for "what if"); `POST /api/ace/flush_multiplier` as in 2.x.
- **Firmware purge model** again (`purge.py`): Orca's colour formula × multiplier from GoKlipper's configuration, offset
  and first load learned from finished Orca prints; `/api/orca/state` carries it for the plugin (`purge`, `driver`).
- Camera on Rinkhals: the frame rate follows the printer's CPU (`CAMERA_CPU_LOW` / `CAMERA_CPU_HIGH`, 90 / 97 %); the web
  UI shows *throttled* next to the frame rate.
- `printer.platform` (`klipper` / `rinkhals`) and `printer.can_restart` in `/api/app/state`.
- **Languages:** every user-facing text is English with a German catalog; the language follows `?lang=`, `X-Lang`,
  the browser, else `UI_LANGUAGE` (default `en`, changeable at runtime). The web UI has a language switch per browser,
  the printer display follows `UI_LANGUAGE` (or `/display?lang=de`),
  the app follows the phone (or *Settings → Language*), the plugin follows the bridge (or its *Language* setting).
- Demo printer with `DEMO_PLATFORM=rinkhals` (development tool, not shipped).

### Changed
- Code, comments, logs, API texts and docs are English. German stays as a second language everywhere.
- Spoolman names: a new install gets the shelf location `Shelf` and the template vendor `Template`; an existing
  install with `Regal` / `Vorlage` keeps them (`SHELF_LOCATION` / `TEMPLATE_VENDOR` empty = detect). `spoolman_setup.py`
  creates English field names, `--language de` German ones.
- Docs: README and installation for both setups (what works where), AI notice, Rinkhals troubleshooting, API for the
  ACE card, architecture (firmware detection, languages), field list with keys and both names.
- Web routes are English (`#/filament`, `#/prints`, `#/settings` …); old German bookmarks still work.

### Fixed
- On Rinkhals the bridge no longer sends `SET_GCODE_VARIABLE MACRO=KOBRA_START` (the Z offset needs Klipper).
- `FIRMWARE_RESTART` is refused on Rinkhals (the firmware blocks it) and the UIs hide the button.

## plugin 0.7.0 – 2026-10-12

### Added
- English and German; setting *Language* (`auto` = the bridge's language, `en`, `de`).
- Rinkhals: the usage preview adds the firmware's own purge per filament (column *Firmware purge*) from the bridge's
  model and Orca's transitions, and warns about a loaded slot without material (the firmware would cancel the print).

### Changed
- All texts and logs English by default.

## app 1.15.0 – 2026-10-12

### Added
- English and German: follows the phone's language, *Settings → Language* or Android's per-app language overrides it.
- ACE card on Rinkhals: runout detection and the firmware's purge multiplier with a preview per colour pair; asks first
  during a print.

### Changed
- The Klipper reload button is hidden when the printer cannot restart (Rinkhals); the pressure advance card explains
  that Auto-PA needs Klipper.

## [3.11.2] – 2026-10-12

### Fixed
- Orca profiles: when neither the filament nor its template names an *Orca base profile*, `base` is now
  `Generic <material> @System` (material as Orca types it, e.g. PLA+ → PLA) instead of empty;
  `base_source` (`filament` / `template` / `fallback`) says where it came from
  ([#1](https://github.com/xNoVoSx/kobra-spoolman/issues/1)).

## plugin 0.6.1 – 2026-10-12

### Fixed
- No base profile in Spoolman: the plugin falls back to `Generic <material> @System` itself (also with
  older bridges) and, if even that is impossible, says *no Orca base profile in Spoolman* instead of
  „–“ nicht gefunden ([#1](https://github.com/xNoVoSx/kobra-spoolman/issues/1)).
- Base profile names match ignoring case and an optional `@System` (`eSun PLA+` → `eSUN PLA+ @System`) (#1).
- Profiles whose base has different values per extruder variant (e.g. `filament_max_volumetric_speed`
  in *Bambu PLA Basic*) were rewritten on every sync — so Orca asked for a restart after every start —
  and back-sync offered them as changes: both sides are now reduced to the active variant before
  comparing. Found and patched by @MineTech13 ([#2](https://github.com/xNoVoSx/kobra-spoolman/issues/2)).
- The same fixes for the 2.x line (bridge 2.21.1, Rinkhals): plugin **0.5.3** on branch `maint/2.x`.

## [3.11.1] – 2026-10-12

### Fixed
- The bridge could stop processing for 15 s at a time (web UI frozen, buttons without effect, *Verwerfen* of a
  power-loss offer not arriving): status handlers that sent G-code ran inside the WebSocket reader and waited for an
  answer only that reader could read. Status is now processed in its own task, in order (`Moonraker._dispatch`); the
  first status of a subscription is queued before the updates Moonraker sends right after it.
- During the print start Klipper runs API G-code only after the start macro; the pressure-advance sync timed out after
  15 s and resent its values every ~17 s, piling up dozens of requests in Klipper (a PAUSE waited behind them). The PA
  and Z-offset syncs now keep at most one request in flight with a long deadline (`gcodepush.py`).
- `pa.last.speeds`/`pa.last.k` were `null` after a failed measurement; app 1.14.0 then rejected the whole state
  (“Antwort der Bridge nicht lesbar … at path: $.pa.last.k”). They are always lists now.

## app 1.14.1 – 2026-10-12

### Fixed
- A `null` in a field that has a default no longer makes the whole bridge answer unreadable (`coerceInputValues`).

## [3.11.0] – 2026-10-11

### Added
- USB tunnel watchdog in the web UI (card on the *ACE* page) and the app (section in the ACE window): state, last
  event, the three switches. `/api/app/state` has `usb` (the `/api/usb` view, `null` without a watchdog).

### Changed
- *ACE* page: dryer, power-loss resume, clog detection and USB tunnel on the left, ACE and pressure advance on the right.
- Internal: `web.py` (1226 lines) split into areas `api_*.py` with shared helpers in `webcommon.py` (same routes, same
  order); every state file is written through `storage.py` (temporary file, fsync, rename — before, only the usage
  files were synced to disk).

## app 1.14.0 – 2026-10-11

### Added
- ACE window: section *USB-Tunnel* with the watchdog's state and its three switches (needs bridge 3.11.0).

## [3.10.0] – 2026-10-11

### Added
- USB tunnel watchdog (a service on the Klipper computer that reconnects the printer's USB link after a power cycle and
  reloads Klipper): `GET /api/usb`, status line *USB-Tunnel*, an error message when it gives up, a tile under
  display → *System* and a hint on the display's Klipper error screen. Its switches (`usb_watch`, `usb_auto_restart`,
  `usb_full_speed`) are in `/api/switches`, stored in Moonraker's database (`kobra_usb`). `acebridge/usb.py`.
- Purge log: every colour change with the purge length Orca set for it (console `ACE: Purge settings updated`), kept
  across prints in `data/usage/purge.jsonl`; `GET /api/purge` groups it per colour/material pair; `transitions` in
  `/api/jobs` carry `purge_mm`. Groundwork for learning purge volumes.
- Replay test of a real print under Klipper + ACEPRO (`tests/test_replay_acepro.py`, the bridge's own recording of
  10.10.): bookings per spool must match what was booked in Spoolman.

### Changed
- Display switches: new tab *System* (USB watchdog, *Diagnose-Protokoll*); *Überwachung* fits without scrolling again.
  Switch groups without items are left out of `/api/switches`.

### Removed
- Leftovers of the flush multiplier from the GoKlipper era: `POST /api/ace/flush` and the app-1.8 fields
  `auto_refill`, `runout_detect`, `flush_multiplier`, `presets`, `purge` in `/api/ace` (no client uses them).
- The bridge no longer subscribes to the filament encoder (`encoder_pulse`, `filament_distance` changed on every
  pulse while printing and were unused) or the head/RDM sensor fields.

## [3.9.0] – 2026-10-11

### Added
- Print phase instead of just *Druckt*: `phase` and `phase_key` in `/api/app/state` → `printer` (and `phase` in the
  MQTT `printer` topic, Home Assistant sensor *Druckphase*). Text such as *Heizt Bett 63/100 °C*, *Vorheizen 5/15 min*,
  *Wischt Düse*, *Tastet Z*, *Misst Bettnetz*, *Heizt Düse*, *Wechsel auf Slot 2 · lädt*, *Spült*,
  *Misst Pressure Advance*, *Druckt · Schicht 34/120*. Sources, all from the existing subscription: the Klipper module
  `kobra_phase` (start sequence, heat soak, tool changes, resume), `kobra_pa.measuring`, `ace.target_index`, the
  ACEPRO console messages (sub-step of a tool change) and `print_stats.info` (layer). `acebridge/phase.py`.
- Web: the printer card shows the phase in place of the state; display: in the status chip at the top (every page).

### Fixed
- Display: the top-left corner stays free. The printer's KlipperScreen viewer app swallows every touch that starts in
  its 60×60 px hold-to-exit corner (`VIEWER_EXIT_CORNER_PX`), so the *Start* button there was hard to hit. The rail now
  starts below it (only a status dot in the corner); the light button moved to the header next to the clock.

## app 1.13.0 – 2026-10-11

### Added
- Print phase on the home screen, in the live notification and in the widget (needs bridge 3.9.0).

## [3.8.0] – 2026-10-10

### Added
- Print log: *Logs → Druck-Aufzeichnungen → Protokoll* renders each recorded print readably (console messages of the
  start sequence, tool changes, Auto-PA, plus state changes: print state, tool, target temperatures, layer, Auto-PA,
  clog, resume). `GET /api/telemetry/{file}/log`.
- The print recordings now include the printer console (G-code responses, commands sent, errors), without the
  temperature reports.
- Switch `debug` (*Diagnose-Protokoll*): the Klipper modules' detailed log (`KOBRA_DEBUG`), on during development.

## [3.7.0] – 2026-10-10

### Added
- Display: *Dateien* — the printer's print files (newest first, preview picture, time, weight, colours per tool,
  page buttons instead of swiping); tapping one shows its tools next to the slots (material and colour hints) and
  starts it after confirmation. *Erneut drucken* on the finished/cancelled screen.
- Display: *Nachjustieren* has tabs *Tempo & Fluss*, *Erste Schicht (Z)* (live Z offset ±0.01/0.025/0.05 mm; the
  sum of this print can be added to the loaded filament's *Z-Versatz* in Spoolman) and *Objekte* (skip one object,
  `EXCLUDE_OBJECT`).
- Display: macro prompts (`action:prompt_*`, e.g. *Filament Runout*) with their buttons; a large Klipper error screen
  with *Klipper neu laden*; *System* with all messages, IP and versions, Pi reboot/shutdown (confirmation, not while
  printing).
- API: `GET /api/files`, `/api/files/thumb`, `/api/files/check`, `POST /api/files/start` (paired, confirmation);
  `POST /api/machine/zadjust`, `/api/machine/exclude`, `/api/machine-z/save`; `prompt` in `/api/app/state`,
  `POST /api/prompt`, `/api/prompt/close`; `GET /api/system`, `POST /api/system/reboot|shutdown`.

### Changed
- Display: no mouse cursor; an off button per heater; *Abbrechen* only appears once the print is paused; the
  emergency stop asks for confirmation everywhere (no more holding).

## [3.6.1] – 2026-10-10

### Fixed
- ACE humidity and firmware stayed empty after a printer restart when the ACE connected later than Klipper: the
  bridge subscribed to the ACE objects with "all fields", and Klipper freezes that field list at the first query.
  The fields are now subscribed explicitly.

## [3.6.0] – 2026-10-10

### Added
- Display: *Steuerung* — temperatures (presets from the loaded spools, number pad), moving (home all/XY/Z, jog
  0.1–50 mm, Z at most 10 mm per tap, motors off, position), filament (load a slot through the ACE, unload, extrude
  ±10/50 mm when hot), fans, a fixed set of macros (*Bettnetze messen*), Klipper restart and an emergency stop you hold.
- `GET /api/machine` (position and homed axes, queried only while the page is open), `POST /api/machine/{action}`
  (`home`, `jog`, `motors_off`, `extrude`, `load`, `unload`, `macro`; paired). Only fixed commands with limits;
  moving, loading and macros are refused while printing, extruding is allowed when paused. Long actions run in the
  background. Temperatures and fans keep using `/api/print/tune`.

## [3.5.1] – 2026-10-10

### Fixed
- Display: the slot cards show the spool's name as in Spoolman (names that start with the material, such as
  "ASA+ Grau", were split into "ASA + Grau").

## [3.5.0] – 2026-10-10

### Added
- View for the printer's own touchscreen: `GET /display` (800×480, made for fingers) — start screen with slots and
  dryer, a print screen that opens by itself when a print starts (the file's preview picture, progress, times,
  temperatures, pause/resume, fine-tuning, cancel), every switch, and the power-loss question. Shown by a kiosk
  browser on the Klipper Pi; pairs with a code like any device (device kind `display`).
- `GET /api/switches`, `POST /api/switch`: every switch of the Klipper modules in one list (Auto-PA, Z offset per
  filament, endless spool, power-loss resume, clog detection, light and sounds of the `kobra_io` module). The bridge
  only sends the command listed for a key.

## [3.4.0] – 2026-10-10

### Added
- Clog detection (Klipper module `kobra_clog`, not part of this repo): while printing, Klipper compares what the
  extruder fed with what the filament encoder saw. A suspected clog shows up as an alarm until the filament moves
  normally again; Klipper either only warns (default) or also pauses. Switch and reaction on the ACE page, API
  `/api/clog`, `/api/clog/switch`.

## app 1.12.0 – 2026-10-10

- ACE-Fenster: Schalter „Verstopfung erkennen“ mit Auswahl „Nur warnen“/„Pausieren“

## [3.3.0] – 2026-10-10

### Added
- Resume after a power loss (Klipper module `kobra_resume`, not part of this repo): an interrupted print shows up as an
  alarm and a card with the live camera picture; *Fortsetzen* (confirmation required) lets the printer probe the part's
  height with the load cell and continue where it stopped, *Verwerfen* drops it. API `/api/resume`, switch on the ACE page.

## app 1.11.0 – 2026-10-10

- Startseite: Karte „Druck unterbrochen“ nach einem Stromausfall – fortsetzen (mit Rückfrage) oder verwerfen
- ACE-Fenster: Schalter „Fortsetzen nach Stromausfall“

## [3.2.2] – 2026-10-10

### Fixed
- Right after the bridge starts (Spoolman not loaded yet) or while Spoolman is unreachable, the bridge no longer
  overwrites `lane_data` with slots without `filament_id`, and no longer reports all slots as empty to Auto-PA and the
  Z offsets — Orca's sync could pick wrong profiles in that window.

## [3.2.1] – 2026-10-09

### Fixed
- Docker images (bridge, kobra-vision) take the official Python base image from the AWS ECR Public mirror — Docker Hub
  rate-limited the CI (`429 Too Many Requests`), so 3.2.0 got no image. Same content as 3.2.0 otherwise.

## [3.2.0] – 2026-10-09

### Added
- Z offset per filament: Spoolman field *Z-Versatz* (`z_offset`, mm; inherited from the template). The bridge gives the
  values of the loaded slots to the printer macro `KOBRA_START` (`slot_z`), the print start adds the start filament's
  value to the first layer. Setting `FILAMENT_Z_SYNC`.

### Changed
- Installation: the change-filament G-code lets the ACE purge nothing extra when Orca's *Purge in prime tower* is on
  (Orca then purges into the tower) — never purged twice. Not recommended: it cost more filament in our tests.

## [3.1.0] – 2026-10-09

### Added
- Auto-PA: pressure advance measured by the printer's load cell (Klipper module `kobra_pa`, not part of this repo)
  and kept per filament in Spoolman. The bridge sends each slot's PA to Klipper (table per speed, fixed value or
  "not measured yet" — then the printer measures at the next print with it) and writes results back (`pa_table`,
  `pressure_advance` = K at 200 mm/s, so Orca uses it too). API `/api/pa`, card *Pressure Advance* on the ACE page,
  messages for measurements. Switches: Auto-PA and automatic measuring (in the printer), setting `PA_SYNC`.
- Changing PA in Orca (back-sync or reset) drops a measured table.

### Fixed
- `lane_data`: entries the bridge did not write (ACEPRO's own `lane1`…`lane4` from before its sync was switched
  off) are removed after every reconnect — Orca saw every slot twice, partly without `filament_id`.

## app 1.10.0 – 2026-10-09

- ACE: Abschnitt „Pressure Advance“ – Auto-PA und automatisches Messen an/aus, PA je Slot, jetzt messen, neu messen

## [3.0.0] – 2026-10-09

**Breaking:** the printer now runs **Klipper on a Raspberry Pi** (USB tunnel to the Kobra S1's
controllers) with the **ACEPRO** ACE driver instead of the stock firmware with Rinkhals (GoKlipper).
`MOONRAKER_URL` points at the Pi. Set `[ace] moonraker_lane_sync_enabled: False` in `printer.cfg` and use
the new change-filament G-code in Orca ([installation](docs/installation.md)). Stay on 2.21.1 for the
stock firmware. Use with plugin 0.6.0 and app 1.9.0 (app 1.8.0 keeps working, without the new switches).

### Changed
- Slots, RFID tags and the active slot come from ACEPRO's `ace` / `ace_instance_0` objects. Assigning a
  spool without tag sends material, colour and temperature with `ACE_SET_SLOT`.
- Consumption: `print_stats.filament_used` is booked to the slot ACEPRO reports as loaded; during a
  tool change after the unload to the incoming slot (load to the nozzle and purge). No debounce needed.
  Needs the ACEPRO patch that syncs `gcode_move` after its direct extruder moves.
- G-code targets per slot come from the bridge's own parse of the print file.
- "Spool won't last" counts 85 mm load plus the purge the file sets per change (50 mm without).
- Dryer via `ACE_START_DRYING` / `ACE_STOP_DRYING`. Runs started by hand, by plan or on insert last their
  full time and are restarted with the remaining time if the ACE stops early (at most 3 times); only the
  automation stops on low humidity. The automation starts only after the humidity has stayed above the
  threshold for `start_delay_minutes` (default 15), so opening the lid starts nothing.
- ACE card: endless spool on/off and its mode (`exact`, `material`, `next`), allowed while printing.
- Camera: no CPU-based throttling any more (the printer has headroom now); the status shows the CPU of
  the Klipper host.
- Mainsail link defaults to port 80 on the Moonraker host.

### Added
- Print control: `firmware_restart` (*Klipper neu laden*) after an emergency stop or a Klipper error.
- `moonraker_connected` and `klippy_ready` in the printer state.

### Removed
- GoKlipper-only parts: `mmu` subscription, firmware purge model (`purge.py`, `usage.purge`), flush
  multiplier (`POST /api/ace/flush` answers 410), `runout_detect`, the `spoolman_support` check,
  targets from `virtual_sdcard`.

## plugin 0.6.0 – 2026-10-09

For bridge 3.0 (Klipper + ACEPRO).

### Changed
- Consumption preview shows Orca's own numbers (same as Orca's legend). The ACE purge per colour
  change is part of "Flushed": the printer profile's change-filament G-code reports load + purge to
  Orca with `; EXTERNAL_PURGE`. If a print changes colour but Orca reports no purge, the panel says
  the printer profile is outdated.

### Removed
- Own purge model (firmware formula, measured average per load) and the slot hint "no material on
  the printer" — both GoKlipper-only.

## app 1.9.0 – 2026-10-09

- ACE: Endlosspule an/aus und Modus (gleiche Farbe, gleiches Material, nächste Spule); Spül-Multiplikator
  entfällt (Spülmengen kommen aus Orca)
- Trockner: „Warten (min)“ – Automatik startet erst, wenn die Feuchte so lange über der Schwelle liegt;
  Hinweis, wenn ein Durchgang von Hand, geplant oder nach dem Einlegen bis zum Ende läuft
- Steuerung: „Klipper neu laden“ nach Not-Aus oder Fehler

## [2.21.1] – 2026-10-06

Use with plugin 0.5.2.

### Fixed
- Bridge: back-sync never clears a Spoolman field because a value cannot be read. A list per extruder
  variant sent as text (plugin 0.5.1) was converted to "no value" and deleted the nozzle temperature;
  such a list now counts as its first entry, anything else unreadable is reported as ignored.

## plugin 0.5.2 – 2026-10-06

### Fixed
- Back-sync of a value Orca stores per extruder variant: Orca's settings page only changes the
  active variant (*Direct Drive Standard* on the Kobra S1), so the list differed per variant and was
  sent as text — the bridge then deleted the field (a nozzle temperature set to 255 °C was gone and
  the profile fell back to 260 °C). The plugin now sends the value of the active variant.

## plugin 0.5.1 – 2026-10-06

### Fixed
- A profile saved in Orca 2.5 and synced back to Spoolman stopped loading (Orca logged
  `Invalid value provided for parameter activate_air_filtration_during_print`), although the
  plugin reported it as written. Orca 2.5 stores many filament values once per extruder variant
  (six entries) and adds about 80 of its own defaults when saving. The back-sync took all of them
  as changes and stored the lists as text in `orca_overrides`; writing the profile then wrapped
  that text in a one-element list, which Orca rejects.
  - Back-sync only compares keys the plugin wrote (the full base profile); keys Orca adds on save
    are its defaults, not edits.
  - A list whose entries are all equal counts as that single value; only real per-variant
    differences are sent as a list.
  - Writing a profile turns a list stored as text back into a list, so profiles from the broken
    state load again without touching Spoolman.
- The panel docked a few pixels wide on start: fixed in the Orca build (orca-kobra patch 0004).

## [2.21.0] – 2026-10-04

Ships app 1.8.0.

### Added
- **Benutzt** line under the print (web UI and app): the slots the running file uses, with the total amount and
  what is still to print, purge included (`uses` in `/api/print/info` and `/api/app/state`).
- 3D view: **Rest** switch in the window — *Durchsichtig*, *Voll* (whole model in full colour, like Orca) or
  *Aus*; remembered per device.

### Changed
- 3D view of large files: connected pieces of a line are **merged** instead of every n-th segment being left out —
  no more holes in infill and jagged walls. A 3.4 M segment print fits under the 1.5 M limit at 0.1 mm deviation.
- KI tab: the value under each picture is called *Funde* (sum of the confidences in that picture) instead of *p*;
  number fields styled like the rest of the settings.

### Fixed
- KI tab: events whose picture was deleted with its print show *Bild gelöscht* instead of a broken image.

## app 1.8.0 – 2026-10-04

- Startseite: Zeile „Benutzt“ mit den Slots der Druckdatei, Gesamtmenge und was noch kommt
- 3D-Ansicht: Umschalter „Rest“ (Durchsichtig, Voll, Aus)

## [2.20.0] – 2026-10-03

### Changed
- **3D view looks like OrcaSlicer's preview** (own implementation, no Orca code or assets): grey background,
  the Kobra S1 plate with thickness, rounded corners and a 10 mm grid, every line as a lit strand with a
  rounded cross-section in its real width and layer height, the unchanged filament colours with top and front
  light and a slight sheen, the rest of the print transparent, a cone at the nozzle, X/Y axes at the origin.
- Geometry format version 2: the strand width per segment (from extrusion, length and layer height; the
  filament diameter comes from the file). `/api/print/info` adds `filament_colours`.

## [2.19.0] – 2026-10-03

Ships app 1.7.0. Run `spoolman_setup.py` once more for the new Spoolman fields (see below).

### Added
- **3D view** of the running print: the bridge sends the toolpaths (`/api/print/geometry.bin`, compact
  binary, gzip) and the web UI draws them with its own WebGL2 renderer — printed part solid, the rest
  faint, live nozzle position, layer slider, *3D*/*Oben*/*Vorne*. Rendering per device: *Volumen*,
  *Linien*, *Bild der Bridge* or *Automatisch* (by what the device can do). `/viewer` serves the view as
  a page of its own for the app. `GEOMETRY_MAX_SEGMENTS` limits the detail.
- **Settings at runtime**: the web UI's *Einstellungen* changes camera, preview, slots and RFID,
  moisture, notices, consumption and data settings without a restart (`/api/settings`, stored in
  `settings.json`; the environment gives the start values).
- **Humidity history** of the ACE (one point per minute, `HUMIDITY_DAYS`, default 30) with every drying:
  who started it and why, set points, humidity before and after (`/api/humidity`).
- **Spool moisture estimate** from where each spool was (ACE, storage room, dry box locations) and how
  it was dried, with per-material absorption and drying times (Spoolman fields *Offen bis Trocknen*,
  *Trocknen Dauer*). Spools that need drying — and new spools — start the ACE dryer when loaded
  (`AUTO_DRY_ON_INSERT`, `NEW_SPOOLS_DRY`). The bridge writes *Feuchte-Schätzung*, *Zuletzt im ACE*,
  *Zuletzt getrocknet* to Spoolman. `/api/spool/{id}/moisture`, `/api/spool/{id}/dried`.
- **Print start check**: every tool of the file against its slot (empty, material, colour, no spool,
  needs drying) as messages; `WET_PRINT_ACTION=pause` pauses once for a wet spool.
- **Home Assistant via MQTT** (`MQTT_HOST` …): retained topics for printer, ACE, slots, messages and AI,
  discovery as the device *Kobra S1 (ace-lane-bridge)*, availability with last will. **Room sensor**
  (`ROOM_SENSOR_TOPIC`, e.g. Zigbee2MQTT) replaces `ROOM_RH` in the moisture estimate while it is fresh.
- Settings `LOW_SPOOL_G` and `REACH_RESERVE_PCT` for the *fast leer* and *reicht nicht* messages.

## app 1.7.0 – 2026-10-03

- 3D-Ansicht des laufenden Drucks (drehen, Schicht-Regler, Vollbild); Darstellung unter Einstellungen → 3D-Modell
- Trockner-Fenster: Feuchte-Verlauf mit Soll beim Trocknen und Liste aller Trocknungen
- Spulenkarte: Feuchte-Schätzung, letzte Trocknung, „Außerhalb getrocknet …“
- Widget für den Startbildschirm: Kamerabild, Fortschritt, Rest- und Fertig-Zeit

## [2.18.0] – 2026-10-03

Ships app 1.6.0.

### Added
- **KI tab** (web UI) to see and control the AI ([vision.md](docs/vision.md#the-ki-tab)): live state with
  score curve, *Jetzt prüfen* and testing an uploaded picture, *Diesen Druck nicht überwachen*;
  settings stored in the bridge (sensitivity, report or pause, nozzle off after an AI pause, phone alarm
  level, quiet hours, interval, learning time, collection limit — the `VISION_*` variables are only start
  values); **areas to ignore** drawn on the camera picture; the baseline with reset and all events with
  verdicts; the picture collection per print with filters, labels for later training, delete and ZIP export.
- API: `/api/vision/settings`, `/mute`, `/test`, `/baseline/reset`, `/jobs`, `/label`, `/export.zip`,
  deleting prints and pictures; `vision.muted_reason`.

### Changed
- AI: the baseline does not learn while an alarm is open — a failure running unnoticed for hours no
  longer becomes "normal" (seen in the test environment).
- AI: suspicious pictures are collected at most every 30 s (an unattended failure filled 4.8 GB in the
  test environment); the gallery loads in pages.

### Fixed
- Event pictures from 2.17.0 were not found anymore after the storage change.

## app 1.6.0 – 2026-10-03

- Düsen-Alarm nur noch, wenn die Düse ihr Soll schon erreicht hatte und dann 60 s deutlich darunter liegt, erst ab
  Schicht 1 – Aufheizen und das Abtasten bei 140 °C in der Vorbereitung lösen keinen Alarm mehr aus
- Druckerfehler erst, wenn er 10 s bleibt (GoKlipper meldet in der Vorbereitung kurz „error“)
- Neue Seite Mehr → KI: Zustand, Einstellungen, „Diesen Druck nicht überwachen“, Ereignisse mit Bild und Bewertung
- KI-Alarm hat jetzt auch „Stimmt“
- Die App stürzt bei einer unerwarteten Antwort der Bridge nicht mehr ab, sondern meldet es

## [2.17.0] – 2026-10-03

Ships app 1.5.0. New optional service **kobra-vision** 0.1.0 (`ghcr.io/xnovosx/kobra-vision`).

### Added
- **AI print-failure detection** ([docs/vision.md](docs/vision.md)): while printing the bridge sends a
  camera picture every 10 s (`VISION_INTERVAL_S`) to kobra-vision — Obico's failure model on ONNX
  Runtime, ~50 ms per picture on the CPU, unloaded when idle — and judges the result over time like
  Obico (safe start, EWM against a baseline). Messages `ai-warn` / `ai-fail` with the app alarm, boxes
  over the camera image, *Fehlalarm* / *Stimmt* in the web UI, status line *KI*. Only warns by default;
  `VISION_ACTION=pause` pauses on a clear failure. The printer does not notice: the AI reuses the
  newest frame or fetches one single snapshot.
- Picture collection for the next stages (plate check, knocked-over parts): start, every minute,
  suspicious pictures, alarms and end of every print with scores and your feedback, up to 5 GB
  (`VISION_DATASET_GB`), oldest prints deleted first.
- API: `GET /api/vision`, `GET /api/vision/event/{id}.jpg`, `POST /api/vision/feedback`; `vision` in
  `/api/app/state`.
- CI runs the kobra-vision tests; the Docker workflow builds `kobra-vision` (amd64, arm64) and checks
  the model's SHA-256 while building.

## app 1.5.0 – 2026-10-03

- KI-Alarm mit Kamerabild und den Knöpfen „Pausieren“ und „Fehlalarm“ direkt in der Benachrichtigung
- „Wahrscheinlich Fehldruck“ ersetzt die vorige „verdächtig“-Benachrichtigung statt sich darunter zu stapeln

## [2.16.0] – 2026-10-03

Ships app 1.4.0 (reworked notifications with own sounds).

### Changed
- Messages: the printer CPU is no longer a message (nothing to do about it during a print; a printer
  that really hangs shows up as "Drucker nicht erreichbar"). It stays a status line, now yellow from
  90 % and red from 97 % — during a print the S1 sits at 75–89 % from GoKlipper alone.

### Added
- `/api/app/state` has `last_control` (`action`, `source`, `at`): the last pause/resume/cancel sent
  through the bridge, so the app does not raise an alarm for a pause you made yourself.

## app 1.4.0 – 2026-10-03

- Druck läuft: ab Android 16 als Live-Update – immer ganz oben, auf dem Sperrbildschirm und als „48 %“ in der
  Statusleiste (vorher rutschte er unter „Weitere Benachrichtigungen“)
- Eigene Töne: Druck gestartet, erste Schicht, Druck fertig, Alarm und Hinweis klingen unterschiedlich – und
  anders als andere Apps
- Einstellungen → Töne: jeden Ton anhören und eine Probe-Benachrichtigung schicken
- Alarme kommen mit Kamerabild; deine eigene Pause oder dein Abbruch (Web/App) ist kein Alarm mehr
- Nur noch, was man tun kann: CPU, fast leer, offene Buchung und Feuchte kommen nicht mehr aufs Handy;
  unbekannter Tag, Slot ohne Material, Spoolman länger als 5 min weg schon
- Dieselbe Meldung kommt nicht mehr bei jeder neuen Zahl erneut
- Update-Installation auf Android 10–12 abgesichert

## [2.15.3] – 2026-10-03

### Fixed
- Web: on a phone the finish time ("morgen ~01:37") was cut off; the print times now wrap instead.

## [2.15.2] – 2026-10-03

### Fixed
- Dryer: the ACE reports the remaining time in **seconds**, the bridge read it as minutes — the web UI
  showed e.g. "Noch 278 h" for 4.6 h, and when the bridge lowered a running drying for a more
  sensitive spool it restarted it for up to 24 h instead of the time left.
- Web: the dryer card shows the ACE's current temperature while drying too, next to set point and limit
  (before only the set point).

### Docs
- New screenshots of the web UI (overview, ACE, terminal, logs …) and the app (start, slots, spool
  card, notification); README, usage and app pages brought up to date (app released, print control,
  RFID automatic, purge per colour change done).

## [2.15.1] – 2026-10-02

### Changed
- Dryer: default maximum temperatures raised to what dryer makers recommend (Bambu, Sunlu, Polymaker):
  PLA, PLA-CF, TPU and PEBA 45/50 → 55 °C, PVA/BVOH 45 → 50 °C, unknown material 45 → 50 °C. PETG
  stays at 60 °C (Sunlu PETG can fuse on the spool at 65 °C over hours). The Spoolman setup templates
  follow; a value in the filament's *Trocknen max.* field still wins.

### Fixed
- Web: the camera image stuck to the left on wide, low windows (the 16:10 box shrank its width under
  the height cap); it is centred now.

## [2.15.0] – 2026-10-02

Ships app 1.3.0 (print notifications on the phone).

### Changed
- Camera: the CPU regulation no longer chokes the camera during a print. GoKlipper alone keeps the S1 at
  75–89 % while printing and snapshots cost next to nothing, so the defaults are now 90 % (go up) and
  97 % (go down), steps of 1 fps instead of halving, CPU averaged over 10 s.

### Fixed
- Camera: a viewer closing the stream (aiohttp "Connection lost", broken pipe) was logged as an error
  with a traceback every time; it is normal and now only logged at debug level.

## app 1.3.0 – 2026-10-02

- Druck im Hintergrund überwachen (ersetzt den OctoApp-Companion, der auf dem Drucker 64 % CPU brauchte):
  Fortschritt mit Kamerabild in der Leiste, Ton bei Start, erster Schicht und Ende, Alarm bei Pause, Abbruch,
  Fehler, hängendem Farbwechsel, fallender Düsentemperatur, Drucker/Bridge weg, Spule reicht nicht
- Fragt nur die Bridge ab (5 s im Druck, sonst 30 s); Schalter in den Einstellungen; startet nach einem
  Neustart des Handys wieder; Kanäle Fortschritt/Druck/Alarm/Hinweise einzeln einstellbar

## [2.14.1] – 2026-10-02

### Fixed
- RFID automatic: at bridge start a loaded spool was reported as "unknown tag" because the spool list
  from Spoolman was not loaded yet, and was never checked again. The bridge now waits for Spoolman and
  re-checks unknown numbers on every pass.

## [2.14.0] – 2026-10-02

Ships app 1.2.0.

### Added
- **RFID automatic:** a spool with one of our tags in a slot is assigned automatically (old spool to the
  shelf, also during a print; also at bridge start for spools already loaded). Unknown numbers show
  as a message and are remembered when you assign by hand. Original Anycubic tags (< 1000) stay
  manual. Slot cards show *RFID*. `AUTO_ASSIGN_BY_TAG` (default on).

## app 1.2.0 – 2026-10-02

- Leerer Sticker gescannt: die App bietet „Neue Spule“ oder „Vorhandene Spule“ an und beschreibt ihn
  gleich (dann der zweite für die andere Seite) – statt ihn nur zu verknüpfen, wobei er leer blieb
- Verknüpfen gibt es nur noch für schon beschriebene Tags (z. B. Original-Anycubic)

## [2.13.0] – 2026-10-02

Ships app 1.1.0 (two tags per spool).

### Added
- Two NFC tags per spool (ACE 2 Pro reads only the side facing its reader): the bridge keeps up to two
  tag IDs per spool (`nfc_uids`; `nfc_uid` stays the first for older apps), a scan finds the spool by
  either; `POST /api/app/tag/link` takes `reset: false` to add the second. Web UI shows the tag count.

## app 1.1.0 – 2026-10-02

- Tags schreiben in zwei Schritten: beide Sticker bekommen denselben Inhalt, je einer pro Spulenseite
- Derselbe Sticker zählt nicht als zweiter; „2. Tag schreiben“, wenn bei einer Spule nur einer fehlt

## [2.12.0] – 2026-10-01

Ships app 1.0.0 — the first signed app release (APK on this release and inside the Docker image).

### Added
- Release builds a **signed app APK** (`kobra-spoolman-app-<version>.apk` on the GitHub release) and
  puts it into the Docker image; the bridge offers it to the app as an update (`/api/app/update`).

## app 1.0.0 – 2026-10-01

First release build of the Android app (own version, independent of the bridge).
- Start: camera, print status with printer data, controls, slots, ACE
- Meldungen, Filament (spools and filament types), Mehr (ACE & dryer, prints, Protokoll, devices, settings)
- Updates from the bridge: shows new versions and installs them after a tap

## [2.11.0] – 2026-10-01

### Added
- Web UI and app: **print control** — pause/resume, cancel (asks first), emergency stop (hold 2 s,
  then confirm; power cycle needed afterwards), and *Nachjustieren*: speed, flow, part/enclosure/
  air-filter fan, nozzle and bed target (also without a print). Bridge: `/api/print/pause|resume|
  cancel|emergency_stop|tune`.

### Fixed
- Web UI: the overview's ACE card has the multiplier field again (with the 0.1–3.0 check), not only
  the presets.
- Web UI: the *ACE* page shows the full ACE card again (field, purge preview per colour change,
  automatic refill, runout detection) — it showed the compact card, so "Vorschau und weitere
  Einstellungen" led to a page without them.

## [2.10.1] – 2026-10-01

### Changed
- Camera: the bridge no longer holds the printer's MJPEG stream — on the Kobra S1 one stream alone
  takes 100 % CPU (measured). It fetches single snapshots like Mainsail's *adaptive* mode and
  restreams them; the rate (1–10 fps) follows the printer CPU that Moonraker pushes anyway
  (`CAMERA_FPS_MIN/MAX`, `CAMERA_CPU_LOW/HIGH`; `CAMERA_STREAM=true` for the old behaviour).
  *Status* shows the printer CPU, a message warns after a minute above 90 %, the web UI shows
  *gedrosselt* when the camera holds back.

### Fixed
- Camera: a webcam entry in Moonraker that points to the bridge's own camera link (Mainsail set up
  with the restream) is never taken as the camera source — that would loop.

## [2.10.0] – 2026-10-01

### Added
- Web UI: **Terminal** — printer responses and every command sent through the bridge with its
  source; send G-code and macros with completion and history; risky commands and moves during a
  print ask first. **Logs** — the bridge log (levels, search, download), the end of the printer's
  log files (range request, no multi-MB download) and the per-print recordings.
- App: tidied up — tabs *Start · Meldungen · Filament · Mehr*. Start shows the camera first, the
  print with printer data below it, then slots and ACE; *Meldungen* has its own tab with a counter;
  *Filament* holds spools and filament types; *Mehr* has ACE & dryer, print history, a read-only
  *Protokoll* (commands with source, printer answers, bridge log), devices and settings.

### Fixed
- Web UI: after an update the browser no longer keeps the old page (no more Ctrl+Shift+R). Files are
  served under a fingerprint, the start page is never cached, and an open page reloads itself when
  the bridge has a new UI (waits while a dialog or editor is open).

## [2.9.0] – 2026-10-01

### Added
- Web UI and app: **Meldungen & Status** on the overview — printer paused/error, slot without
  material, **spool won't last for the running print** (from the print file: what each tool still
  prints plus the purge of the changes still to come), spool almost empty, open bookings, Spoolman
  unreachable, high humidity, print just finished; status of printer, Spoolman, camera, paired app
  and Orca plugin, bridge.

### Changed
- Web UI: the overview is the **printer monitor** — camera as the main view (the model only while
  printing), messages and status, slots, dryer and ACE. Shelf, spool details and print history left
  the overview; on ultrawide everything fits on one screen.
- Web UI: **Filament** replaces *Regal* and *Filamente* — one page with *Spulen | Sorten*; a filament
  type lists its spools. Old links (`#/regal`, `#/filamente`) still work.
- App: overview with messages and status, camera first, model only while printing.

## [2.8.1] – 2026-10-01

### Changed
- Web UI: tidier overview — the printer card reads top to bottom (status and progress, times, image
  with printer data, active slot); dryer and ACE stacked next to it instead of leaving a gap; the
  image no longer grows taller than 400 px on wide screens; on phones the times stay in one row and
  the print list uses the full width.

## [2.8.0] – 2026-10-01

New dependency: Pillow (in the image). After the update, point Mainsail's webcam at the bridge's
*camera link* (*Geräte → Kamera-Link*) so the printer serves only one camera stream.

### Added
- Bridge, web UI and app: **ACE settings** the printer display hides — purge multiplier (presets
  and any value 0.1–3.0, with the purge of every change between the loaded spools before/after),
  automatic refill and runout detection. Locked during a print until *Freischalten*.
- Bridge, web UI and app: **print view** — the bridge downloads the running file once (throttled)
  and draws it itself in the ACE colours, with progress, layer and nozzle; plus the slicer
  thumbnail. **Camera restream**: the bridge holds at most one stream connection to the printer
  (only while someone watches, closed 20 s after the last viewer) and hands the frames to every
  viewer — web UI, app and, through a view-only *camera link*, Mainsail or any MJPEG client. Live
  frame rate in the corner of the image. Paired devices or camera link only. Full screen on tap.
- Web UI and app: **printer data below the image** — nozzle and bed temperature (actual/target),
  part, enclosure and air filter fans, speed and flow factor, layer. The bridge subscribes only these
  fields over its existing Moonraker connection.
- Web UI and app: print time — running for, about how long still and the **estimated finish
  time** (e.g. *~17:35*, *morgen ~02:10*).
- Dryer: **plan a start** (e.g. tonight 22:00), kept across restarts, capped like a manual start.

### Changed
- Web UI: the printer card has a proper *Mainsail* button; the *Trockner* page is now *ACE*.
- Android app: the dryer sheet is the ACE sheet (dryer, plan, purge and settings).

## [2.7.0] – 2026-10-01

Ships plugin 0.5.0. The per-change preview needs the orca-kobra build from 2026-10-01 or later.

### Added
- Bridge: **purge model of the ACE** — the firmware's purge per colour change is computed like the
  firmware does it (Orca's colour formula on the ACE colours + `flush_volume_min`, limits, times
  `flush_multiplier`). The bridge reads the flush settings from GoKlipper every 10 minutes, records
  every load of a print with its colours and refines the offset per change and the first load from
  finished Orca prints. Provided as `usage.purge.model` in `/api/orca/state` and `/api/usage`.
- Plugin 0.5.0: the usage preview computes the purge **per colour change** from the slot colours
  (needs the orca-kobra build with the extended patch 0003 for the order of the changes; older
  builds average the colours, older bridges keep the measured average per load).

### Fixed
- Bridge: the measured average purge per load ignores AnycubicSlicer files (their G-code header
  contains the slicer's flush volume, which made the average far too low).

## [2.6.0] – 2026-10-01

Ships plugin 0.4.0 — **update the plugin together with the bridge and pair it once**, otherwise
back-sync to Spoolman is refused. The Android app stays a preview (debug APK from CI).

### Added
- Bridge: **pairing devices** — the bridge issues a key per device (app, browser, Orca
  plugin), stores only its hash, and lists/removes devices. Pairing with a 6-digit code (5 min,
  single use) or a QR code; the first device uses a setup code from the bridge log. `APP_TOKEN`
  keeps working during the transition.
- Android app: pair by QR scan (CameraX + ZXing) or code, device list with *Gerät hinzufügen*
  (QR + code) and *Entfernen*; detects a key the bridge no longer knows.
- Bridge: **new web UI** replacing the slot page, same design as the app and nearly the same
  features (everything but NFC): printer status, slots, dryer with rules, open items, shelf with
  search/filters and spool editing, filaments with all Orca fields (create, edit, new colour),
  print history, devices (pairing code + QR for the app), bridge info. Layouts for phones, desktops
  and ultrawide screens (≥ 3000 px: everything side by side). Keyboard: `/` search, `n` new spool,
  arrow keys in the shelf, right-click on a spool to move it. Asks for pairing once per browser.
  Fonts and libraries (Preact + htm, qrcode-generator) are bundled — no internet needed.
- Bridge: `PATCH /api/app/spool/{id}` (weights, price, lot, comment, shelf location);
  `/api/app/state` includes open items and the running print's usage.
- Plugin 0.4.0: **pairing** in the panel (6-digit code once, key stored next to the plugin);
  back-sync tells you when the plugin is not paired.

### Changed
- Bridge: **everything that writes or triggers something now needs a paired device** — slot
  assignment, dryer, open items and the Orca back-sync / base-profile report, like the app API
  before. Reading stays open. Update the Orca plugin to 0.4.0 and pair it once, otherwise
  back-sync is refused.
- Bridge: the warning about double booking accepts every spelling of "off" for the firmware's
  `spoolman_support` (`off`, `false`, `0`).
- Android app: hints talk about pairing instead of the app key; device dates in German format.
- Documentation rewritten for the web UI, pairing and the app, with new screenshots (EN + DE).

### Removed
- The old slot page (replaced by the web UI at the same address).

## [2.5.0] – 2026-10-01

### Added
- Bridge: **ACE dryer** — humidity, temperature and dryer state (from GoKlipper's `filament_hub`,
  in the existing subscription), start/stop by hand and an automation (start above / stop below a
  humidity, max. time, pause, optionally while printing). The temperature never exceeds what the most
  sensitive loaded filament allows (new Spoolman field *Trocknen max.*, else template, else a
  cautious default per material) or what the ACE can do; loading a more sensitive spool while drying
  lowers it at once. On the slot page and in the Android app.

## [2.4.0] – 2026-09-30

Ships plugin 0.3.4. The Android app is a preview (debug APK from CI), not part of this release.

### Added
- Android app (in development, `android/`): slots with printer status and active slot, spool card
  with actions, NFC scan → spool, new spool from an existing filament with the scanned tag,
  settings. Debug builds have virtual tags for the emulator. See [android/README.md](android/README.md).
- Android app: create filaments on the phone (wizard with all Orca fields, template values as
  placeholders only, copy a product line for a new colour, new vendors).
- Android app: write ACE-compatible NFC tags (own encoder, verified byte for byte against an
  original Anycubic tag), link them to the spool; original Anycubic tags are recognised as
  write-protected.
- CI: builds and tests the Android app; the debug APK is attached to every run.

### Added
- Bridge: API for the Android app (`/api/app/…`, [reference](docs/api.md#app-and-web-ui)): printer status
  with active slot, catalog (vendors, templates, filaments, extra fields with Orca keys, Orca base
  profiles), create vendors/filaments/spools, copy a product line in a new colour, move/archive
  spools, reserve tag numbers and link NFC tags. Writing needs `APP_TOKEN`. Only fields the user sets
  are stored — template values are never copied into a filament.
- Bridge: creates the spool extra fields `nfc_uid` and `tag_nr` in Spoolman when first needed
  (also in `spoolman_setup.py`).
- Plugin 0.3.4: reports the names of Orca's filament base profiles to the bridge, so the app can
  offer them as a list.

## [2.3.0] – 2026-09-30

Ships plugin 0.3.3.

### Added
- Bridge: loaded slots without material at the printer get a hint on the slot page and in
  `/api/orca/state` — a print using such a slot fails at the start
  (`index out of range [0] with length 0`, see [findings](docs/findings.md#print-start-and-ace-slot-info-2026-09-30)).
- Bridge: assigning a spool on the slot page gives its material and colour from Spoolman to the ACE
  via Rinkhals' `MMU_GATE_MAP` — spools without an Anycubic tag no longer need to be entered at the
  printer's display. Only the assignment triggers it (once, after the spool is loaded, never while
  printing); restarts, display entries and Spoolman changes never overwrite a slot. Slots with an
  RFID tag (`gate_spool_id` set) are never written — the tag decides. Tested on the printer; `SET_ACE_SLOT_INFO=false` turns it off.
- Plugin 0.3.3: the slot card and the usage preview warn when a slot has no material at the printer
  (*Druck bricht ab*); the warning after slicing includes it.

## [2.2.2] – 2026-09-30

Ships plugin 0.3.2 (see below).

### Fixed
- Bridge: the filament colour is sent as `default_filament_colour` instead of `filament_colour`.
  Orca drops `filament_colour` from filament presets (log: *"incorrect keys: filament_colour, which
  were removed"*) and takes the colour of a manually selected preset from `default_filament_colour`.
  Back-sync (`POST /api/orca/backsync`) accepts both keys and writes them to `color_hex`.

### Changed
- Docs: Rinkhals links point to [rinkhals-community/Rinkhals](https://github.com/rinkhals-community/Rinkhals),
  where development continues. The installation guide links to the new orca-kobra installation
  guide for launcher details.
- Docs: [findings](docs/findings.md) on the firmware purge — measured purge per colour change and
  how AnycubicSlicer passes its flush matrix in the G-code header (`project_info`).

## plugin 0.3.2 – 2026-09-30

Works with bridge 2.2.1 and newer.

### Fixed
- Plugin 0.3.2: profiles carry the Spoolman colour as `default_filament_colour`, so a manually
  selected `SM…` profile shows the right colour. A `filament_colour` from an older bridge is
  written as `default_filament_colour`; `filament_colour` never ends up in a profile.
  Existing profiles are rewritten on the next profile update.

### Changed
- Panel button *Profile synchronisieren* is now **Profile aktualisieren** (menu action and
  settings accordingly); a hint below it says that the profiles only get into Orca's filament
  slots via Orca's sync icon. The panel's refresh button is now *Neu laden* (reload) to tell the two apart.

## plugin 0.3.1 – 2026-09-25

Bridge unchanged (2.2.1). Needs orca-kobra build `kobra-20260924-2257-87a5d20` or newer for the
exact per-filament loads.

### Fixed
- Plugin 0.3.1: the usage preview now shows the **same numbers as Orca's preview legend**
  (model, support, flush, tower, total). 0.3.0 used Orca's `total_volumes_per_extruder`, which
  attributes the prime tower differently at tool changes, so single filaments were off by up to ~1 g.
- Firmware purge ("Laden") uses the **real number of loads per filament** counted by Orca
  (orca-kobra patch 0003, updated) instead of spreading all filament changes evenly over the slots.
  Older builds keep the even split and the panel says so.

### Changed
- Usage preview is a compact block at the top of the panel (*Geplanter Verbrauch*: need / remaining
  per slot, ✓ ⚠ ✗); the breakdown with Orca's column names sits under *Details*. The duplicate
  line in each slot card is gone.

## plugin 0.3.0 – 2026-09-24

Bridge unchanged (2.2.1).

### Added
- Plugin 0.3.0: **usage preview after slicing**. Per slot the panel shows what the sliced plate
  needs — Orca's statistics (model, support, prime tower, flush) plus the firmware purge per load
  measured by the bridge — next to the spool's remaining weight, marked *reicht* / *knapp* /
  *reicht nicht*. If a spool is too short, Orca shows a warning notification.
  Needs `orca.host.slice_statistics` from orca-kobra patch 0003; without it only the preview is missing.
- Plugin settings: reserve in grams (threshold for *knapp*), warn after slicing on/off.
- Tests for the preview calculation.

### Decided
- Reloading profiles without restarting Orca is **deferred**: Orca skips presets it already
  knows, so a clean reload means removing and reloading all user presets, which can reset the
  selected printer. See [findings](docs/findings.md#orcaslicer-plugin-api-250-dev-commit-9859d788).

## [2.2.1] – 2026-09-24

First public release of the repository.

### Added
- Repository with bridge, Orca plugin, Spoolman setup script, English and German documentation.
- Docker image `ghcr.io/xnovosx/ace-lane-bridge` (amd64/arm64), CI, release workflow.
- Test suite: replay of a real two-colour print through the consumption tracker, restart and
  outage scenarios, Orca profile mapping, back-sync, plugin profile builder.
- Plugin 0.2.0: settings page (bridge address, user folder, options) in Orca's Plugins dialog;
  hint in the panel when the bridge is unreachable.

### Changed
- Bridge: `MOONRAKER_URL` is required (no hard-coded address anymore).
- Plugin: default bridge address `http://localhost:7913` — set yours in the plugin settings.
- `spoolman_setup.py`: default URL from `SPOOLMAN_URL` or `http://localhost:7912`.

## [2.2.0] – 2026-09-24 · plugin 0.1.0–0.1.2

### Added
- Orca profile API: values per filament (`/api/orca/profiles`), panel state (`/api/orca/state`),
  back-sync (`/api/orca/backsync`), reset to template (`/api/orca/reset`).
- Orca plugin "Kobra Spoolman": profiles from Spoolman, side panel, slot check, back-sync with confirmation.
- Plugin 0.1.1: panel reliably opens at Orca start. 0.1.2: base profiles are also found inside the AppImage.

## [2.1.1] – 2026-09-24

### Added
- Slot page footer (version, uptime, links) and info dialog with all settings and connections.

## [2.1.0] – 2026-09-24

### Added
- Consumption per slot measured from `filament_used` and booked into Spoolman (at colour changes,
  every 5 min, at the end), restart-safe state and journal, open items, target comparison with the
  G-code header, print history, purge statistics.
- Warning if Moonraker or the firmware would book into Spoolman as well.

### Changed
- Moonraker updates are reduced to fields that actually changed (the ACE sends the full `mmu` object
  twice per second); telemetry shrinks from ~25 MB to ~1 MB per print.

## [2.0.1] – 2026-09-24

### Fixed
- "passt zur ACE" checks material **and** colour, with the same rule as the slot hints.

### Changed
- A filament's own Orca base profile replaces the template completely.

## [2.0.0] – 2026-09-24

### Added
- Rewrite: Moonraker WebSocket, Spoolman connection, slot assignment via mobile page, `lane_data`, telemetry.

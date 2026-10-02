# Changelog

All notable changes. Versions: **bridge** = ace-lane-bridge (also the repo tag),
**plugin** = Orca plugin "Kobra Spoolman". Plugin-only releases have no repo tag.
Changes to the Orca patches and build: [orca-kobra CHANGELOG](https://github.com/xNoVoSx/orca-kobra/blob/main/CHANGELOG.md). Format based on [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

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

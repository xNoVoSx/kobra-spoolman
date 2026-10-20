# Start here

[Deutsch](de/start.md) · [Back to README](../README.md)

Start with the core and add what you want, when you want it. Every feature can be switched on and off later on the
**Features** page (web UI, or *More → Features* in the app); the full step-by-step guide is
[installation.md](installation.md).

## Goal 1 — Spoolman knows what is in the ACE and what each print used (about 5 minutes)

You need an Anycubic printer with an ACE that Moonraker can reach — a Kobra S1 or Kobra 3 on the stock firmware with
[Rinkhals](https://github.com/rinkhals-community/Rinkhals), or a Kobra S1 with Klipper and ACEPRO on a Raspberry Pi
([supported printers](../README.md#supported-printers)) — and a running [Spoolman](https://github.com/Donkie/Spoolman).
Running **Home Assistant OS**? Install the community add-on
[MineTech13/ha-addons](https://github.com/MineTech13/ha-addons) instead of step 1 (its own guide; same bridge) and
continue with step 2 in the HA sidebar.

1. **Add the bridge** to the stack that runs Spoolman ([example](../bridge/compose.yaml)):
   ```yaml
     ace-lane-bridge:
       image: ghcr.io/xnovosx/ace-lane-bridge:latest
       restart: unless-stopped
       ports: ["7913:7913"]
       volumes: ["./bridge-data:/data"]
       environment:
         MOONRAKER_URL: "http://<printer-ip>:7125"   # Rinkhals; Klipper: http://<pi-ip>:7125
         SPOOLMAN_URL: "http://spoolman:8000"
   ```
2. **Pair your browser:** open `http://<docker-host>:7913` and enter the setup code from the bridge log
   (`Setup code: …`).
3. **Setup:** the web UI opens the setup page. It shows what the bridge found — printer and setup, ACE, Spoolman,
   camera — and lets you add more right away or later. Choose nothing more and you are done.

**What you have now:** assign spools to the ACE slots (material and colour go to the ACE), the consumption of every
print booked per spool, the camera and the print preview, and the data Orca's sync button reads. Spools that carry one
of our RFID tags are assigned by themselves when you insert them — the tags are written with the app (goal 2).

**Is it working?** Within a minute of the start:

- [ ] The overview's *Status* list (or `/api/health`) shows the printer and Spoolman as connected, and the header shows your printer's
      name after the first print (or *Printer* until then; set it under *Settings → Printer name*).
- [ ] The four slot cards show what the ACE reports (material, colour) — assign your spools to them.
- [ ] After a print, *Prints* lists it with the millimetres per slot, and the spools' used weight in Spoolman went up by
      the same amount. No card *Open bookings* on the overview.

## Goal 2 and more — add what you want

| Feature | What you get | Needs | Switch it on | Load on the printer | Rinkhals | Klipper |
|---|---|---|---|---|---|---|
| Android app | writes the RFID tags, the printer's messages on the phone, everything of the web UI | Android with NFC | *Devices → Add device*, scan the QR code with the app ([app](android-app.md)) | none – the app only asks the bridge | yes | yes |
| Printer display | the web UI made for the printer's touch screen | the Klipper computer runs the kiosk | install the kiosk ([display](usage.md#the-printers-own-display)) | none | – | yes |
| Orca plugin | Spoolman profiles in Orca, usage preview after slicing, back sync | OrcaSlicer, the [orca-kobra](https://github.com/xNoVoSx/orca-kobra) build for the preview | install the plugin ([installation](installation.md#6-orca-plugin-kobra-spoolman)) | none | yes | yes |
| Camera | the printer camera in web, app and display | a camera at the printer | on by default; *Features* | one connection to the printer, however many watch | yes | yes |
| Print preview | 3D model, remaining amount per spool, layer progress | – | on by default; *Features* | reads the print file once from Moonraker | yes | yes |
| Drying automatically | damp spools are dried when they are inserted | ACE with dryer | *Features* | none | yes | yes |
| Print recordings | raw data of every print to check the bookings later | – | *Features* | none | yes | yes |
| Home Assistant / MQTT | printer, slots and spools as Home Assistant devices | an MQTT broker | `MQTT_HOST` and login ([configuration](configuration.md)), or the [HA add-on](installation.md#option-b--home-assistant-add-on) | none | yes | yes |
| AI print-failure detection | **experimental** – warns or pauses on spaghetti and failed prints | the kobra-vision container and the camera | `VISION_URL` ([AI detection](vision.md)) | none – the bridge looks at the camera images | yes | yes |
| Auto PA | pressure advance per speed from Spoolman, measured when missing | Klipper setup with our printer modules | on when the module is installed; *Features* | a ~2 minute measurement per new filament | – | yes |
| Z offset per filament | first-layer Z offset from the filament in Spoolman | Klipper setup, macro `KOBRA_START` | on when installed; *Features* | none | – | yes |
| Resume after a power loss | continues an interrupted print at the right height | Klipper setup, module `kobra_resume` | on when installed; *Features* | writes the print position regularly | – | yes |
| Clog detection | compares the extruder with the filament encoder, warns or pauses | Klipper setup, module `kobra_clog` | on when installed; *Features* | none | – | yes |
| Swappable hotends | PID, nozzle size and Z correction per hotend, Auto PA per nozzle, a file for the wrong nozzle is stopped | Klipper setup, module `kobra_nozzle` | on when installed; *Features* | none | – | yes |
| Endless spool | when a spool runs out, the ACE loads a matching other one | ACEPRO (Klipper) or the firmware (Rinkhals) | Klipper: *Features*; Rinkhals: the ACE card | none | yes | yes |
| Ask for another spool | no matching spool when one runs out → the print waits over the waste chute and asks which loaded spool to continue with | Klipper setup, module `kobra_spare` (with the endless spool) | on when installed; *Features* | none | – | yes |
| Light and sounds | printer light and beeper on events, quiet at night | Klipper setup, kobra-io app on the printer | on when installed; *Features* | none | – | yes |

What the installation sets (environment variables of the container, options of the Home Assistant add-on) is shown on
the *Features* page and changed there — never on the page itself.

## What works without what

| Without … | What still works | What you miss |
|---|---|---|
| the Orca plugin | everything in the bridge: bookings, slots, dryer, app, camera; Orca's sync button still reads the slots' material and colour | Orca profiles made from Spoolman (and so the matching profile per slot), the side panel, back-sync |
| the orca-kobra build (official Orca) | the plugin: profiles, side panel, back-sync | the usage preview after slicing, the automatic profile on Orca's sync button (until Orca merges the patches) |
| the app | the web UI on the phone does the same, apart from NFC | writing RFID tags, notifications in the background, the widget |
| NFC tags | assign spools by hand in web or app (matching spools come first) | spools that assign themselves when inserted |
| a camera | everything else | the picture in web, app and display, the AI detection |
| MQTT / Home Assistant | everything else | the devices in Home Assistant |
| our Klipper modules (setup B) | everything of setup A | Auto PA, Z offset per filament, resume after power loss, clog detection |

## Already running an older version?

Nothing changes after an update: every switch stays as it was. The overview (and the app once) shows a hint on the new
*Features* page, and the setup can be run any time from there.

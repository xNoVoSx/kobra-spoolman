"""ace-lane-bridge v3 - Kobra S1 / ACE 2 Pro <-> Spoolman <-> OrcaSlicer."""

from .i18n import tr

__version__ = "3.11.2"
__app_name__ = "ace-lane-bridge"
__description__ = "Kobra S1 with ACE 2 Pro ↔ Spoolman ↔ OrcaSlicer"

# Newest version first, shown in the web UI under "Settings" (the last 10 versions; the full history is in
# CHANGELOG.md). Texts in English, German in locale/de.json.
CHANGELOG = [
    ("3.11.2", "2026-10-12", [
        tr("Orca profiles: if neither the filament nor its template names an Orca base profile, “Generic <material> "
           "@System” applies (before, the plugin reported “–” not found)"),
        tr("Plugin 0.6.1: base profile names ignoring case and with an optional “@System”, a clear message without a "
           "base profile, profiles are no longer rewritten at every Orca start (values per nozzle variant)"),
    ]),
    ("3.11.1", "2026-10-12", [
        tr("Fixed: the bridge hung at times (web UI frozen, buttons without effect, “discard” did not work) – it "
           "waited for its own answers to Klipper and processed nothing meanwhile"),
        tr("Fixed: during the print start the bridge resent the PA values every 15 s; dozens of commands piled up in "
           "Klipper (a pause waited behind them). Now at most one request stays open"),
        tr("Fixed: app 1.14.0 showed “answer of the bridge unreadable” after a failed PA measurement"),
        tr("App 1.14.1: also survives missing values in an answer of the bridge in the future"),
    ]),
    ("3.11.0", "2026-10-11", [
        tr("USB tunnel now also in the web UI (ACE page) and the app (ACE window): state, last event and the three "
           "switches"),
        tr("ACE page: dryer, resume, clog and USB tunnel on the left, ACE and pressure advance on the right"),
        tr("Internal cleanup: the interface split into areas, all state files are written equally safely"),
        tr("App 1.14.0: section USB tunnel in the ACE window"),
    ]),
    ("3.10.0", "2026-10-11", [
        tr("USB tunnel between printer and Klipper computer: status line (connected, printer off, connecting … "
           "attempt n), a message when the watchdog gives up, a tile under display → System, a hint in the Klipper "
           "error message"),
        tr("Display: new switch tab “System” with the three switches of the USB watchdog and the diagnostic log – "
           "“Monitoring” fits without scrolling again"),
        tr("Purge log: every colour change with the purge length from Orca, per colour pair across all prints (basis "
           "for learning purge lengths)"),
        tr("Cleanup: leftovers of the purge multiplier from the GoKlipper days removed, the unneeded subscription of "
           "the filament encoder (changed constantly while printing) dropped"),
    ]),
    ("3.9.0", "2026-10-11", [
        tr("Print phase instead of just “Printing”: web, app, display and Home Assistant show what the printer is "
           "doing – “Heating bed 63/100 °C”, “Heat soak 5/15 min”, “Wiping nozzle”, “Probing Z”, “Measuring bed "
           "mesh”, “Change to slot 2 · loading”, “Purging”, “Measuring pressure advance”, “Printing · layer 34/120”"),
        tr("Needs kobra-klipper with the module kobra_phase (new print start); without it, change, PA and layer remain"),
        tr("App 1.13.0: print phase on the home page, in the live notification and in the widget"),
        tr("Display: the top left corner stays free – the viewer app on the printer swallows every touch there (hold "
           "5 s = exit), so the home button was hard to press; light button now top right next to the clock"),
    ]),
    ("3.8.0", "2026-10-10", [
        tr("Print log: Logs → print recordings → “Log” shows every print readably – start sequence, filament "
           "changes, auto PA, console messages, temperatures, layer, clog, resume"),
        tr("The recordings now also contain the printer console (without temperature reports)"),
        tr("Switch “Diagnostic log” (monitoring): detailed Klipper log of our modules, on during development"),
    ]),
    ("3.7.0", "2026-10-10", [
        tr("Display: files on the printer with thumbnails, start a print with a look at the slots, “Print again” "
           "after the print"),
        tr("Display: fine-tune the first layer while printing (Z ±0.01–0.05 mm) and save it for the filament in "
           "Spoolman; skip single objects"),
        tr("Display: macro prompts (e.g. filament runout), Klipper errors large with “Reload Klipper”, all messages, "
           "IP and versions, reboot/shut down the Pi"),
        tr("Display: no mouse cursor, off button per heater, cancel only while paused, emergency stop everywhere "
           "with confirmation"),
    ]),
    ("3.6.1", "2026-10-10", [
        tr("ACE humidity and firmware were missing after a printer restart when the ACE connected later than Klipper"),
    ]),
    ("3.6.0", "2026-10-10", [
        tr("Display: new area Control – temperatures (quick choice from the loaded spools, number pad), moving "
           "(home, jog 0.1–50 mm, motors off), filament (load, unload a slot, extrude), fans, measure bed meshes, "
           "reload Klipper, emergency stop (press and hold)"),
        tr("Moving, loading and macros are blocked while printing; the bridge sends only fixed commands with limits"),
    ]),
    ("3.5.1", "2026-10-10", [
        tr("Display: spool name as in Spoolman (\"ASA+ Grau\" instead of \"ASA + Grau\")"),
    ]),
]

# Kobra Spoolman — Android app

Status: **preview** — see [docs/android-app.md](../docs/android-app.md). Not released yet; CI attaches a debug APK to every run.

The app talks only to the [ace-lane-bridge](../bridge) (`/api/app/…`, [API](../docs/api.md#app-and-web-ui)).
UI texts are German, like the plugin and the web UI.

## What works

- Slots with printer status (state, file, progress, remaining time, active slot) and the shelf
- Spool card: remaining weight, temperatures, last prints; move to slot 1–4, shelf, archive
- Scan: NFC tag → spool card; unknown tag → new spool or link to an existing one
- New spool from an existing filament (weights, straight into a slot, link the scanned tag)
- Settings: pairing with the bridge by QR code or 6-digit code; device list (add, remove)
- New filament (stage 3): 7-step wizard — vendor (or a new one), name, material, template, own Orca
  base profile (list reported by the Orca plugin), colour, weights, temperatures, cooling,
  extrusion/retraction, Orca overrides. Template values are shown as placeholders and never stored;
  *Werte übernehmen von …* copies a product line's own values for a new colour.

- Write ACE tags: tag number from the bridge, pages 4–31 in the ACE layout (verified against an
  original Anycubic tag), read back, UID linked to the spool. After creating a spool the app goes
  straight to writing its tag.

- ACE dryer: humidity/temperature card on the start screen; start/stop and the automation settings.

Next: first test with real NTAG215 stickers on the phone; does the ACE report our tag number?

## Build

Needs JDK 17+ and the Android SDK (platform 37). With `ANDROID_HOME` set or `local.properties`
(`sdk.dir=…`):

```bash
cd android
./gradlew testDebugUnitTest assembleDebug     # APK: app/build/outputs/apk/debug/app-debug.apk
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

The debug build has **virtual tags** in the scan sheet, for testing on the emulator (no NFC).

## Notes

- Android 17 (API 37) blocks the local network unless the app holds `ACCESS_LOCAL_NETWORK`
  ("Nearby devices"). The app asks for it on first start; without it every connection to the
  bridge hangs until it times out.
- The bridge runs without TLS in the home network, so cleartext HTTP is allowed.
- Fonts: Space Grotesk and IBM Plex (SIL Open Font License, see [`licenses/`](licenses)).

# Kobra Spoolman — Android app

Status: **released** — see [docs/android-app.md](../docs/android-app.md). Every release carries the signed APK; the bridge offers it to the app as an update. CI attaches a debug APK to every run.

The app talks only to the [ace-lane-bridge](../bridge) (`/api/app/…`, [API](../docs/api.md#app-and-web-ui)).
UI texts are English or German (the phone's language, or *Settings → Language*; Android 13+ also per-app language).

## What it does

Everything in detail: [docs/android-app.md](../docs/android-app.md). In short:

- Printer with camera, 3D view, print phase and controls (pause, cancel, tune, emergency stop)
- Notifications in the background with own sounds, the running print as a Live Update, home-screen widget
- Slots, shelf and spool card; new spools and filaments (7-step wizard with every Orca field)
- NFC: writes ACE-compatible tags (two per spool), finds spools by tag; Spoolman QR codes
- ACE dryer with humidity history, spool moisture, ACE settings and the switches of the Klipper modules
  (Auto PA, resume, clog detection, direct feed, hotends, eject, USB tunnel)
- Features page and setup, devices, pairing by QR code, updates through the bridge
- Away from home through a VPN or Home Assistant (*Settings → Remote access*)

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

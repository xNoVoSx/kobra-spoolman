# Daily use

[Deutsch](de/usage.md) · [Back to README](../README.md)

## A new filament arrives

Enter it in Spoolman with **Add spools** (you can create the filament in the same dialog).

| Field | What to enter |
|---|---|
| Vendor, Name | e.g. *Sunlu*, *PETG 2.0 Lavender* — name includes the colour |
| Material | `PLA`, `PETG`, `PLA Silk` … (the base type decides the Orca filament type) |
| Colour | the hex colour; for Anycubic spools use what the ACE reports so the slot check matches |
| Density, Diameter, Weight, Price | from the label / shop |
| Nozzle / bed temperature | the values you want in Orca |
| **Orca base profile** *or* **Template** | see below |
| Everything else | only what you want to override |

**Template or base profile?**

- **Template** (`Vorlage PETG`, …): generic starting values maintained in Spoolman. Good for
  most third-party filaments. Leave empty → the template is picked by material.
- **Orca base profile**: the exact name of an Orca system profile, e.g.
  `Anycubic PLA Silk @Anycubic Kobra S1 0.4 nozzle`. Use it when Orca already ships a tuned profile
  for that filament — the template is then ignored completely.

Order of precedence (later wins): *Orca base profile* ← *template* ← *filament fields* ← *Orca overrides*.
Field reference: [spoolman-fields.md](spoolman-fields.md).

The next time Orca starts, the plugin creates the profile `Vendor Name (SM0000xx)`.
Already running? Press **Profile synchronisieren** in the panel, then restart Orca.

## Loading a spool into the ACE

Open the slot page (`http://<docker-host>:7913`) on your phone, tap **Spule wählen** on the slot
and pick the spool. Spools that match what the ACE reads from the tag are marked
*passt zur ACE* (material **and** colour) or *Material passt, Farbe nicht*.

Removing a spool: if the ACE reports a slot empty for a while, the spool is moved to the shelf
automatically (during a print only after it ends). You can also press **Ins Regal**.

## Slicing and printing

1. In Orca press the filament **sync** button. With the orca-kobra build the `SM…` profiles are
   selected for slots 1–4 automatically; the panel shows *Filament N in Orca: passt* per slot and
   warns if a filament box does not match its slot.
2. Slice and print as usual (printer agent *Moonraker*).
3. During the print the slot page shows *Dieser Druck: x g* per slot. The bridge books consumption
   into Spoolman at every colour change, every 5 minutes and at the end.

## Open items

If a slot without an assigned spool was used, or its spool was deleted, the consumption is kept as
an **open item** at the top of the slot page (*Nicht gebucht*). Assign it to a spool or discard it.
If Spoolman was unreachable, bookings are retried automatically.

## Changing a profile in Orca

Edit an `SM…` profile and save it. The plugin asks *Nach Spoolman übernehmen?*:

- **Yes** — known settings go to their Spoolman fields, everything else to *Orca overrides*.
- **No** — the next sync resets the profile to the Spoolman values (Spoolman stays the source of truth).

To go back to the template for a single value, clear that field in Spoolman (or use
`POST /api/orca/reset`, see [api.md](api.md)).

## When a filament is used up

Archive the spool in Spoolman. Filaments without any active spool lose their Orca profile on the
next sync; profiles the plugin did not create are never touched.

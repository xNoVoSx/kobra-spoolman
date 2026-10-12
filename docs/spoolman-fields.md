# Spoolman fields → Orca settings

[Back to README](../README.md)

Created by [`spoolman_setup.py`](../spoolman/spoolman_setup.py). The **key** is what the bridge, the plugin and the
app use; the name shown in Spoolman is English, or German with `--language de` (installs before 3.12 have the German
names) — the bridge works with either.
Empty fields inherit: *Orca base profile* ← *template* ← *filament* ← *Orca overrides*.
Mapping in code: `FIELD_MAP` in [`bridge/app/acebridge/orca_profiles.py`](../bridge/app/acebridge/orca_profiles.py).

## Standard Spoolman fields

| Spoolman | Orca key | Note |
|---|---|---|
| Material | `filament_type` | base type (`PLA Silk` → `PLA`) |
| Color | `default_filament_colour` | Orca drops `filament_colour` from filament presets |
| Density | `filament_density` | |
| Diameter | `filament_diameter` | |
| Price (+ weight) | `filament_cost` | converted to price per kg |
| Vendor | `filament_vendor` | |
| Extruder temp | `nozzle_temperature` | |
| Bed temp | `textured_plate_temp` | textured PEI (Kobra S1 default plate) |
| *(Filament ID)* | `filament_id` | always `SM` + 6-digit Spoolman filament ID |

## Extra fields (filament)

| Key | Name (en) | Name (de) | Orca key | Unit / note |
|---|---|---|---|---|
| `orca_basis` | Orca base profile | Orca-Basisprofil | *(base profile name)* | e.g. `Anycubic PLA Silk @Anycubic Kobra S1 0.4 nozzle` |
| `vorlage` | Template | Vorlage | *(template name)* | empty = chosen by material |
| `nozzle_temp_first_layer` | Nozzle first layer | Düse erste Schicht | `nozzle_temperature_initial_layer` | °C |
| `bed_temp_first_layer` | Bed first layer | Bett erste Schicht | `textured_plate_temp_initial_layer` | °C |
| `bed_temp_smooth` | Bed smooth PEI | Bett glatte PEI | `hot_plate_temp` | °C |
| `bed_temp_smooth_first_layer` | Bed smooth PEI first layer | Bett glatte PEI erste Schicht | `hot_plate_temp_initial_layer` | °C |
| `chamber_temp` | Chamber temperature | Kammertemperatur | `chamber_temperature` | °C |
| `dry_temp` | Dry max. | Trocknen max. | *(ACE dryer, not Orca)* | °C — highest drying temperature for this material |
| `dry_hours` | Dry duration | Trocknen Dauer | *(ACE dryer)* | h — minimum drying time at *Dry max.* (empty = value of the material) |
| `open_days` | Open until drying | Offen bis Trocknen | *(moisture estimate)* | days at 50 % RH until *drying recommended* (empty = value of the material) |
| `fan_min` | Part fan min | Bauteillüfter min | `fan_min_speed` | % |
| `fan_max` | Part fan max | Bauteillüfter max | `fan_max_speed` | % |
| `fan_off_first_layers` | Fan off first layers | Lüfter aus erste Schichten | `close_fan_the_first_x_layers` | layers |
| `overhang_fan` | Overhang fan | Überhang-Lüfter | `overhang_fan_speed` | % |
| `aux_fan` | Auxiliary fan | Hilfslüfter | `additional_cooling_fan_speed` | % |
| `air_filtration` | Air filtration (exhaust) | Luftfilterung (Abluft) | `activate_air_filtration` | on/off |
| `exhaust_fan_print` | Exhaust during print | Abluft während Druck | `during_print_exhaust_fan_speed` | % |
| `exhaust_fan_done` | Exhaust after print | Abluft nach Druck | `complete_print_exhaust_fan_speed` | % |
| `flow_ratio` | Flow ratio | Flow Ratio | `filament_flow_ratio` | |
| `pressure_advance` | Pressure advance | Pressure Advance | `pressure_advance` (+ `enable_pressure_advance`) | |
| `pa_table` | PA table (auto PA) | PA-Tabelle (Auto-PA) | – | K per speed for Klipper; the bridge writes it, see [usage](usage.md#pressure-advance-auto-pa) (Klipper only) |
| `z_offset` | Z offset | Z-Versatz | – | mm, + = farther from the bed; first layer of the start filament, given to `KOBRA_START` by the bridge; inherited from the template (Klipper only) |
| `max_volumetric_speed` | Max. volumetric speed | Max. Volumenstrom | `filament_max_volumetric_speed` | mm³/s |
| `retraction_length` | Retraction length | Retraction Länge | `filament_retraction_length` | mm |
| `retraction_speed` | Retraction speed | Retraction Geschwindigkeit | `filament_retraction_speed` | mm/s |
| `z_hop` | Z hop | Z-Hop | `filament_z_hop` | mm |
| `orca_overrides` | Orca overrides | Orca-Overrides | *any Orca key* | one `key = value` per line |

## Extra fields (spool)

| Key | Name (en) | Name (de) | Note |
|---|---|---|---|
| `nfc_uid` | NFC ID | NFC-Kennung | UID of the spool's NFC tag (set by the app) |
| `tag_nr` | Tag number | Tag-Nummer | number in the SKU of a self-written tag (set by the bridge) |
| `moisture` | Moisture estimate | Feuchte-Schätzung | % — 100 = drying recommended (set by the bridge) |
| `last_in_ace` | Last in the ACE | Zuletzt im ACE | when it was taken out of the ACE (set by the bridge) |
| `last_dried` | Last dried | Zuletzt getrocknet | last drying (set by the bridge) |
| `last_dried_info` | Last dried with | Zuletzt getrocknet mit | its temperature and duration (set by the bridge) |

The keys `orca_basis` and `vorlage` are German for historical reasons; they are stable API names and stay.

## Back-sync

When you save an `SM…` profile in Orca, changed keys from the table above are written to their
Spoolman field. Any other changed key is stored in **Orca overrides**. Identity keys
(`filament_id`, `filament_type`, `filament_vendor`, name, compatibility) are never written back.

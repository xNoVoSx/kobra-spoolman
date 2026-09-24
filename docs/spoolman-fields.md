# Spoolman fields → Orca settings / Spoolman-Felder → Orca-Einstellungen

[Back to README](../README.md)

Created by [`spoolman_setup.py`](../spoolman/spoolman_setup.py). Field names in the Spoolman UI are German.
Empty fields inherit: *Orca base profile* ← *template* ← *filament* ← *Orca overrides*.
Mapping in code: `FIELD_MAP` in [`bridge/app/acebridge/orca_profiles.py`](../bridge/app/acebridge/orca_profiles.py).

## Standard Spoolman fields / Standardfelder

| Spoolman | Orca key | Note |
|---|---|---|
| Material | `filament_type` | base type (`PLA Silk` → `PLA`) |
| Farbe / Color | `filament_colour` | |
| Dichte / Density | `filament_density` | |
| Durchmesser / Diameter | `filament_diameter` | |
| Preis / Price (+ Gewicht / Weight) | `filament_cost` | converted to price per kg |
| Hersteller / Vendor | `filament_vendor` | |
| Düsentemperatur / Extruder temp | `nozzle_temperature` | |
| Betttemperatur / Bed temp | `textured_plate_temp` | textured PEI (Kobra S1 default plate) |
| *(Filament ID)* | `filament_id` | always `SM` + 6-digit Spoolman filament ID |

## Extra fields / Zusatzfelder

| Spoolman field (German UI) | Orca key | Unit |
|---|---|---|
| Orca-Basisprofil | *(base profile name)* | e.g. `Anycubic PLA Silk @Anycubic Kobra S1 0.4 nozzle` |
| Vorlage | *(template name)* | empty = chosen by material |
| Düse erste Schicht | `nozzle_temperature_initial_layer` | °C |
| Bett erste Schicht | `textured_plate_temp_initial_layer` | °C |
| Bett glatte PEI | `hot_plate_temp` | °C |
| Bett glatte PEI erste Schicht | `hot_plate_temp_initial_layer` | °C |
| Kammertemperatur | `chamber_temperature` | °C |
| Bauteillüfter min | `fan_min_speed` | % |
| Bauteillüfter max | `fan_max_speed` | % |
| Lüfter aus erste Schichten | `close_fan_the_first_x_layers` | layers |
| Überhang-Lüfter | `overhang_fan_speed` | % |
| Hilfslüfter | `additional_cooling_fan_speed` | % |
| Luftfilterung (Abluft) | `activate_air_filtration` | on/off |
| Abluft während Druck | `during_print_exhaust_fan_speed` | % |
| Abluft nach Druck | `complete_print_exhaust_fan_speed` | % |
| Flow Ratio | `filament_flow_ratio` | |
| Pressure Advance | `pressure_advance` (+ `enable_pressure_advance`) | |
| Max. Volumenstrom | `filament_max_volumetric_speed` | mm³/s |
| Retraction Länge | `filament_retraction_length` | mm |
| Retraction Geschwindigkeit | `filament_retraction_speed` | mm/s |
| Z-Hop | `filament_z_hop` | mm |
| Orca-Overrides | *any Orca key* | one `key = value` per line |
| NFC-Kennung *(spool)* | — | stage 4 |

## Back-sync / Rücksync

When you save an `SM…` profile in Orca, changed keys from the table above are written to their
Spoolman field. Any other changed key is stored in **Orca-Overrides**. Identity keys
(`filament_id`, `filament_type`, `filament_vendor`, name, compatibility) are never written back.

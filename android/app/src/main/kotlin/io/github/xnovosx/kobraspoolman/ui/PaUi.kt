package io.github.xnovosx.kobraspoolman.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import io.github.xnovosx.kobraspoolman.data.PaSlot
import io.github.xnovosx.kobraspoolman.data.PaState
import io.github.xnovosx.kobraspoolman.ui.theme.K
import io.github.xnovosx.kobraspoolman.ui.theme.PlexMono

private fun k3(v: Double?) = Format.decimal(v, 3)

/**
 * Auto-PA (Klipper-Modul kobra_pa): Schalter, PA je Slot aus Spoolman, jetzt messen / beim naechsten Druck neu messen.
 * Beide Schalter liegen im Drucker und bleiben dort gespeichert.
 */
@Composable
fun PaSection(
    pa: PaState, printing: Boolean,
    onSwitch: (Boolean?, Boolean?) -> Unit, onCalibrate: (Int) -> Unit, onForget: (Int) -> Unit,
) {
    var ask by remember { mutableStateOf<Pair<String, PaSlot>?>(null) }
    SectionLabel("Pressure Advance", Modifier.padding(top = 12.dp))
    if (!pa.present) {
        Hint("Auto-PA ist in Klipper nicht eingerichtet (Modul kobra_pa) oder Klipper ist nicht bereit.")
        return
    }
    PaSwitch("Auto-PA", "PA je Geschwindigkeit aus Spoolman anwenden; aus = Klipper nimmt das PA aus Orca",
        pa.enabled == true) { onSwitch(it, null) }
    PaSwitch("Automatisch messen", "Hat ein Filament noch kein PA, misst der Drucker beim Druckstart bzw. Farbwechsel (~2 min)",
        pa.auto == true, enabled = pa.enabled == true) { onSwitch(null, it) }
    if (pa.patched == false) Hint("Klipper ohne Auto-PA-Patch: nur festes PA, messen geht nicht.")
    if (!pa.sync) Hint("Verbindung zu Spoolman ist aus (Einstellungen → Pressure Advance).")
    if (pa.measuring || pa.calibrating != null) Text("Misst gerade …", color = K.Accent, style = MaterialTheme.typography.bodyMedium)
    val ready = pa.enabled == true && pa.patched == true && !pa.measuring && pa.calibrating == null && !printing
    pa.slots.filter { it.filamentId != null }.forEach { s ->
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Column(Modifier.weight(1f)) {
                Text("Slot ${s.slot} · ${s.name ?: ""}" + if (s.active) " · aktiv" else "", style = MaterialTheme.typography.bodyLarge)
                Text(when {
                    s.k.size > 1 -> s.k.joinToString(" / ") { k3(it) } + " bei " + s.speeds.joinToString(" / ") { it.toInt().toString() } + " mm/s"
                    s.source == "manual" -> "fest ${k3(s.k.firstOrNull())} (von Hand)"
                    s.state == "failed" -> "Messung gescheitert – bisheriges PA gilt"
                    else -> "kein PA – misst beim nächsten Druck"
                }, style = MaterialTheme.typography.bodySmall, color = if (s.state == "failed") K.DangerText else K.Muted)
            }
            Text(k3(s.kRef), fontFamily = PlexMono, style = MaterialTheme.typography.bodyLarge)
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            SecondaryButton("Jetzt messen", { ask = "measure" to s }, enabled = ready)
            if (s.k.isNotEmpty()) SecondaryButton("Neu messen", { ask = "forget" to s })
        }
    }
    Text("Der Wert bei 200 mm/s steht auch in Spoolman (Pressure Advance) und damit im Orca-Profil.",
        style = MaterialTheme.typography.bodySmall, color = K.Faint)
    ask?.let { (what, s) ->
        AlertDialog(onDismissRequest = { ask = null }, containerColor = K.Surface,
            title = { Text(if (what == "measure") "PA für Slot ${s.slot} messen?" else "PA verwerfen?") },
            text = { Text(if (what == "measure") "${s.name}: Der Drucker heizt auf Drucktemperatur und drückt etwa 120 mm in den " +
                "Abfallschacht (~2 Minuten). Das Ergebnis landet in Spoolman."
                else "${s.name}: Der PA-Wert wird in Spoolman gelöscht. Beim nächsten Druck misst der Drucker neu " +
                    "(wenn „Automatisch messen“ an ist).") },
            confirmButton = { TextButton(onClick = {
                ask = null
                if (what == "measure") onCalibrate(s.slot) else s.filamentId?.let(onForget)
            }) { Text(if (what == "measure") "Messen" else "Verwerfen", color = K.Accent) } },
            dismissButton = { TextButton(onClick = { ask = null }) { Text("Zurück") } })
    }
}

@Composable
private fun PaSwitch(title: String, hint: String, value: Boolean, enabled: Boolean = true, onChange: (Boolean) -> Unit) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f)) {
            Text(title, style = MaterialTheme.typography.bodyLarge)
            Text(hint, style = MaterialTheme.typography.bodySmall, color = K.Muted)
        }
        Switch(value, onChange, enabled = enabled,
            colors = SwitchDefaults.colors(checkedTrackColor = K.Accent, checkedThumbColor = K.OnAccent))
    }
}

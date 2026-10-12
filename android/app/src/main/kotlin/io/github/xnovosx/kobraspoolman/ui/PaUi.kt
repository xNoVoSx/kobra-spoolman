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
import io.github.xnovosx.kobraspoolman.data.tr

private fun k3(v: Double?) = Format.decimal(v, 3)

/**
 * Auto PA (Klipper module kobra_pa): switches, PA per slot from Spoolman, measure now / measure again at the next
 * print. Both switches live in the printer and stay stored there.
 */
@Composable
fun PaSection(
    pa: PaState, printing: Boolean, rinkhals: Boolean = false,
    onSwitch: (Boolean?, Boolean?) -> Unit, onCalibrate: (Int) -> Unit, onForget: (Int) -> Unit,
) {
    var ask by remember { mutableStateOf<Pair<String, PaSlot>?>(null) }
    SectionLabel(tr("Pressure advance"), Modifier.padding(top = 12.dp))
    if (!pa.present) {
        Hint(if (rinkhals) tr("Auto PA needs Klipper with the load cell module kobra_pa – not available with the Anycubic firmware. Orca's PA from the filament profile applies.")
             else tr("Auto PA is not set up in Klipper (module kobra_pa) or Klipper is not ready."))
        return
    }
    PaSwitch(tr("Auto PA"), tr("Apply PA per speed from Spoolman; off = Klipper takes the PA from Orca"),
        pa.enabled == true) { onSwitch(it, null) }
    PaSwitch(tr("Measure automatically"), tr("If a filament has no PA yet, the printer measures at print start or colour change (~2 min)"),
        pa.auto == true, enabled = pa.enabled == true) { onSwitch(null, it) }
    if (pa.patched == false) Hint(tr("Klipper without the auto PA patch: fixed PA only, measuring does not work."))
    if (!pa.sync) Hint(tr("The connection to Spoolman is off (Settings → Pressure advance)."))
    if (pa.measuring || pa.calibrating != null) Text(tr("Measuring …"), color = K.Accent, style = MaterialTheme.typography.bodyMedium)
    val ready = pa.enabled == true && pa.patched == true && !pa.measuring && pa.calibrating == null && !printing
    pa.slots.filter { it.filamentId != null }.forEach { s ->
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Column(Modifier.weight(1f)) {
                Text(tr("Slot {slot}", "slot" to s.slot) + " · " + (s.name ?: "") + if (s.active) " · " + tr("active") else "", style = MaterialTheme.typography.bodyLarge)
                Text(when {
                    s.k.size > 1 -> tr("{k} at {speeds} mm/s", "k" to s.k.joinToString(" / ") { k3(it) }, "speeds" to s.speeds.joinToString(" / ") { it.toInt().toString() })
                    s.source == "manual" -> tr("fixed {k} (by hand)", "k" to k3(s.k.firstOrNull()))
                    s.state == "failed" -> tr("Measurement failed – the previous PA applies")
                    else -> tr("no PA – measures at the next print")
                }, style = MaterialTheme.typography.bodySmall, color = if (s.state == "failed") K.DangerText else K.Muted)
            }
            Text(k3(s.kRef), fontFamily = PlexMono, style = MaterialTheme.typography.bodyLarge)
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            SecondaryButton(tr("Measure now"), { ask = "measure" to s }, enabled = ready)
            if (s.k.isNotEmpty()) SecondaryButton(tr("Measure again"), { ask = "forget" to s })
        }
    }
    Text(tr("The value at 200 mm/s is also in Spoolman (pressure advance) and so in the Orca profile."),
        style = MaterialTheme.typography.bodySmall, color = K.Faint)
    ask?.let { (what, s) ->
        AlertDialog(onDismissRequest = { ask = null }, containerColor = K.Surface,
            title = { Text(if (what == "measure") tr("Measure PA for slot {slot}?", "slot" to s.slot) else tr("Discard PA?")) },
            text = { Text(if (what == "measure") tr("{name}: the printer heats to printing temperature and pushes about 120 mm into the waste chute (~2 minutes). The result goes to Spoolman.", "name" to s.name)
                else tr("{name}: the PA value is deleted in Spoolman. At the next print the printer measures again (if “Measure automatically” is on).", "name" to s.name)) },
            confirmButton = { TextButton(onClick = {
                ask = null
                if (what == "measure") onCalibrate(s.slot) else s.filamentId?.let(onForget)
            }) { Text(if (what == "measure") tr("Measure") else tr("Discard"), color = K.Accent) } },
            dismissButton = { TextButton(onClick = { ask = null }) { Text(tr("Back")) } })
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

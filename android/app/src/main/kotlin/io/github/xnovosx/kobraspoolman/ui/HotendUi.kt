package io.github.xnovosx.kobraspoolman.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.RadioButton
import androidx.compose.material3.RadioButtonDefaults
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
import io.github.xnovosx.kobraspoolman.data.NozzleState
import io.github.xnovosx.kobraspoolman.data.tr
import io.github.xnovosx.kobraspoolman.ui.theme.K
import java.util.Locale

// Swappable hotends (bridge nozzle.py, Klipper kobra_nozzle): which hotend is in, PID per hotend (measure once), the
// print start check. Section in the ACE sheet; the Z correction per hotend is set in the web interface.

private fun mm(d: Double?): String = d?.let { String.format(Locale.getDefault(), if (Math.round(it * 100) % 10 == 0L) "%.1f mm" else "%.2f mm", it) } ?: "–"
private fun pid(v: List<Double>): String = v.joinToString(" / ") { String.format(Locale.getDefault(), "%.3f", it) }

@Composable
fun HotendSection(n: NozzleState, printing: Boolean, canWrite: Boolean, onSelect: (String) -> Unit, onPid: () -> Unit,
                  onCheck: (Boolean) -> Unit) {
    if (!n.available || !n.enabled) return
    var ask by remember { mutableStateOf(false) }
    val locked = printing || n.measuring || !canWrite
    Column(Modifier.padding(top = 12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Text(tr("Hotend"), style = MaterialTheme.typography.bodyLarge)
        Text(tr("Which hotend is in the printer? Klipper takes its PID, nozzle size and Z correction at once; Auto PA keeps its values per nozzle."),
            style = MaterialTheme.typography.bodySmall, color = K.Muted)
        n.hotends.forEach { h ->
            Row(verticalAlignment = Alignment.CenterVertically,
                modifier = Modifier.fillMaxWidth().clickable(enabled = !locked && h.id != n.active) { onSelect(h.id) }) {
                RadioButton(h.id == n.active, { if (h.id != n.active) onSelect(h.id) }, enabled = !locked || h.id == n.active,
                    colors = RadioButtonDefaults.colors(selectedColor = K.Accent))
                Column(Modifier.weight(1f)) {
                    Text(h.name + " · " + mm(h.diameter), style = MaterialTheme.typography.bodyMedium)
                    Text(when {
                        h.pid -> tr("PID measured")
                        h.default -> tr("PID from the Klipper configuration")
                        else -> tr("PID not measured")
                    }, style = MaterialTheme.typography.bodySmall, color = K.Muted)
                }
            }
        }
        n.warning?.let { Hint(it, danger = true) }
        n.error?.let { Hint(tr("PID measurement failed: {error}", "error" to it), danger = true) }
        Text(tr("PID") + ": " + (if (n.measuring) tr("measuring PID …") else if (n.pid.isNotEmpty()) pid(n.pid) else "–") +
            " · " + (if (n.pidMeasured) tr("measured for this hotend") else tr("from the Klipper configuration")),
            style = MaterialTheme.typography.bodySmall)
        if (canWrite) OutlinedButton(onClick = { ask = true }, enabled = !locked) {
            Text(if (n.pidMeasured) tr("Measure again") else tr("Measure PID"))
        }
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(tr("Check the nozzle at print start"), style = MaterialTheme.typography.bodyMedium)
                Text(tr("Stops a print that was sliced for another nozzle, before anything heats up"),
                    style = MaterialTheme.typography.bodySmall, color = K.Muted)
            }
            Switch(n.check, onCheck, enabled = canWrite,
                colors = SwitchDefaults.colors(checkedTrackColor = K.Accent, checkedThumbColor = K.OnAccent))
        }
    }
    if (ask) AlertDialog(
        onDismissRequest = { ask = false },
        containerColor = K.Surface,
        title = { Text(tr("Measure the PID of {name}?", "name" to (n.name ?: "–"))) },
        text = {
            Text(tr("The printer homes if needed, moves over the waste chute and heats the nozzle to {temp} °C several times (a few minutes). Stay near the printer. The values apply at once and are saved for this hotend.",
                "temp" to 250), style = MaterialTheme.typography.bodySmall)
        },
        confirmButton = { TextButton(onClick = { ask = false; onPid() }) { Text(tr("Measure")) } },
        dismissButton = { TextButton(onClick = { ask = false }) { Text(tr("Back")) } },
    )
}

package io.github.xnovosx.kobraspoolman.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CheckboxDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.RadioButton
import androidx.compose.material3.RadioButtonDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.unit.dp
import io.github.xnovosx.kobraspoolman.data.DirectState
import io.github.xnovosx.kobraspoolman.data.SpoolInfo
import io.github.xnovosx.kobraspoolman.data.tr
import io.github.xnovosx.kobraspoolman.ui.theme.K

// Direct feed: filament by hand straight in the toolhead (e.g. TPU), the ACE is passed by (bridge direct.py,
// Klipper kobra_direct). Red bar on the home screen while it is on, a section in the ACE sheet to switch it.

/** Red bar on the home screen while direct feed is on. */
@Composable
fun DirectBanner(d: DirectState, canSwitchOff: Boolean, onOff: () -> Unit) {
    Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(14.dp)).background(K.DangerSoft)
        .border(1.dp, K.DangerLine, RoundedCornerShape(14.dp)).padding(14.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text(tr("Direct feed is on") + " – " + tr("the ACE is passed by."), color = K.DangerText,
            style = MaterialTheme.typography.titleSmall)
        Text(tr("Spool:") + " " + (d.label ?: "–") + (d.material?.let { " · $it" } ?: ""), color = K.DangerText,
            style = MaterialTheme.typography.bodyMedium)
        if (canSwitchOff) OutlinedButton(onClick = onOff) { Text(tr("Switch off")) }
    }
}

/** Section in the ACE sheet: explanation and switch, switching on asks for the spool. */
@Composable
fun DirectSection(d: DirectState, spools: List<SpoolInfo>, aceLoadedSlot: Int?, printing: Boolean, canWrite: Boolean,
                  onSet: (Boolean, Int?, Boolean) -> Unit) {
    if (!d.available) return
    var ask by remember { mutableStateOf(false) }
    Column(Modifier.padding(top = 12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Text(tr("Direct feed"), style = MaterialTheme.typography.bodyLarge)
        Text(tr("For filament you insert by hand straight into the toolhead (e.g. TPU). The ACE stays on (drying, slots), the print passes it by. The consumption is booked on the spool you choose."),
            style = MaterialTheme.typography.bodySmall, color = K.Muted)
        if (d.active) {
            Hint(tr("On – spool:") + " " + (d.label ?: "–") + (d.material?.let { " · $it" } ?: ""), danger = true)
            if (canWrite) OutlinedButton(onClick = { onSet(false, null, false) }, enabled = !printing) { Text(tr("Switch off")) }
        } else if (canWrite) {
            OutlinedButton(onClick = { ask = true }, enabled = !printing) { Text(tr("Switch on …")) }
        }
    }
    if (ask) DirectDialog(spools, aceLoadedSlot, onDismiss = { ask = false }) { id, unload -> ask = false; onSet(true, id, unload) }
}

@Composable
private fun DirectDialog(spools: List<SpoolInfo>, aceLoadedSlot: Int?, onDismiss: () -> Unit, onOk: (Int, Boolean) -> Unit) {
    var pick by remember { mutableStateOf<Int?>(null) }
    var unload by remember { mutableStateOf(aceLoadedSlot != null) }
    val sorted = spools.sortedWith(compareBy<SpoolInfo> { if (it.slot != null) 1 else 0 }.thenBy { it.displayName })
    AlertDialog(
        onDismissRequest = onDismiss,
        containerColor = K.Surface,
        title = { Text(tr("Switch on direct feed")) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(tr("Which spool do you insert into the toolhead? Its consumption, PA and Z offset are used. Direct feed stays on until you switch it off."),
                    style = MaterialTheme.typography.bodySmall, color = K.Muted)
                aceLoadedSlot?.let { slot ->
                    Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.clickable { unload = !unload }) {
                        Checkbox(unload, { unload = it }, colors = CheckboxDefaults.colors(checkedColor = K.Accent))
                        Text(tr("Unload the ACE filament from slot {slot} first (heats up over the waste chute)", "slot" to slot),
                            style = MaterialTheme.typography.bodySmall)
                    }
                }
                LazyColumn(Modifier.heightIn(max = 320.dp)) {
                    items(sorted, key = { it.spoolId }) { s ->
                        Row(verticalAlignment = Alignment.CenterVertically,
                            modifier = Modifier.fillMaxWidth().clickable { pick = s.spoolId }.padding(vertical = 4.dp)) {
                            RadioButton(pick == s.spoolId, { pick = s.spoolId }, colors = RadioButtonDefaults.colors(selectedColor = K.Accent))
                            Column(Modifier.weight(1f)) {
                                Text(s.displayName.ifBlank { s.name }, style = MaterialTheme.typography.bodyMedium)
                                Text(listOfNotNull(s.material.ifBlank { null }, s.vendor.ifBlank { null }, "#${s.spoolId}",
                                    s.slot?.let { tr("is in slot {slot}", "slot" to it) }).joinToString(" · "),
                                    style = MaterialTheme.typography.bodySmall, color = K.Muted)
                            }
                        }
                    }
                }
            }
        },
        confirmButton = { TextButton(onClick = { pick?.let { onOk(it, unload) } }, enabled = pick != null) { Text(tr("Switch on")) } },
        dismissButton = { TextButton(onClick = onDismiss) { Text(tr("Cancel")) } },
    )
}

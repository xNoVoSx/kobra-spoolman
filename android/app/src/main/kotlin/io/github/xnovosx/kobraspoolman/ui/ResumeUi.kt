package io.github.xnovosx.kobraspoolman.ui

import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
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
import io.github.xnovosx.kobraspoolman.data.ClogState
import io.github.xnovosx.kobraspoolman.data.UsbState
import io.github.xnovosx.kobraspoolman.data.ResumeState
import io.github.xnovosx.kobraspoolman.ui.theme.K
import kotlin.math.roundToInt
import io.github.xnovosx.kobraspoolman.data.tr

/** After a power loss: resume the print (with confirmation) or discard it. The camera image is right above. */
@Composable
fun ResumeCard(r: ResumeState, canWrite: Boolean, onResume: (Boolean) -> Unit) {
    var ask by remember { mutableStateOf<Boolean?>(null) }
    val p = r.pending
    Column(Modifier.fillMaxWidth().border(1.dp, K.DangerText, RoundedCornerShape(18.dp)).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text(if (r.running) tr("Resuming the print …") else tr("Print interrupted"), style = MaterialTheme.typography.titleMedium)
        p?.let {
            Text(it.file + " · " + (it.layers?.let { n -> tr("layer {layer} of {layers}", "layer" to (it.layer ?: "?"), "layers" to n) } ?: tr("layer {layer}", "layer" to (it.layer ?: "?"))) +
                " · ${((it.progress ?: 0.0) * 100).roundToInt()} %", style = MaterialTheme.typography.bodySmall, color = K.Muted)
            Text(tr("Check in the camera image above whether the part is still stuck to the bed."), style = MaterialTheme.typography.bodySmall)
        }
        r.error?.let { Text(tr("Resume cancelled: {error}", "error" to it), style = MaterialTheme.typography.bodySmall, color = K.DangerText) }
        if (p != null && !r.running && canWrite) Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            PrimaryButton(tr("Resume …"), { ask = true }, Modifier.weight(1f))
            SecondaryButton(tr("Discard"), { ask = false }, Modifier.weight(1f))
        }
    }
    ask?.let { start ->
        AlertDialog(onDismissRequest = { ask = null }, containerColor = K.Surface,
            title = { Text(if (start) tr("Resume the print?") else tr("Discard the interrupted print?")) },
            text = { Text(if (start) tr("Is the part still stuck? The printer heats the bed, homes X/Y, probes the height on the part and continues printing there (a few minutes). If the height does not fit, it stops.")
                else tr("{file} is not resumed; the saved state is deleted.", "file" to p?.file)) },
            confirmButton = { TextButton(onClick = { ask = null; onResume(start) }) {
                Text(if (start) tr("Resume print") else tr("Discard"), color = if (start) K.Accent else K.DangerText) } },
            dismissButton = { TextButton(onClick = { ask = null }) { Text(tr("Back")) } })
    }
}

/** Switch in the ACE sheet: resume after power loss on/off (stored in the printer). */
@Composable
fun PowerlossSwitch(r: ResumeState, onSwitch: (Boolean) -> Unit) {
    if (!r.present) return
    Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(top = 12.dp)) {
        Column(Modifier.weight(1f)) {
            Text(tr("Resume after power loss"), style = MaterialTheme.typography.bodyLarge)
            Text(tr("The printer keeps saving the position while printing and asks after switching on whether to continue"),
                style = MaterialTheme.typography.bodySmall, color = K.Muted)
        }
        Switch(r.enabled == true, onSwitch,
            colors = SwitchDefaults.colors(checkedTrackColor = K.Accent, checkedThumbColor = K.OnAccent))
    }
}

/** Switch in the ACE sheet: clog detection on/off, on suspicion only log, warn or pause. */
@Composable
fun ClogSwitch(c: ClogState, onSwitch: (Boolean) -> Unit, onAction: (String) -> Unit) {
    if (!c.present) return
    Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(top = 12.dp)) {
        Column(Modifier.weight(1f)) {
            Text(tr("Detect clogs"), style = MaterialTheme.typography.bodyLarge)
            Text(tr("Compares, while printing, what the extruder pushes with the encoder at the filament inlet"),
                style = MaterialTheme.typography.bodySmall, color = K.Muted)
        }
        Switch(c.enabled == true, onSwitch,
            colors = SwitchDefaults.colors(checkedTrackColor = K.Accent, checkedThumbColor = K.OnAccent))
    }
    if (c.enabled == true) {
        Column(Modifier.padding(top = 8.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text(tr("On suspicion"), style = MaterialTheme.typography.bodySmall, color = K.Muted)
            Segmented(listOf("log" to tr("Log only"), "warn" to tr("Warn only"), "pause" to tr("Pause")), c.action ?: "warn") {
                if (it != c.action) onAction(it)
            }
        }
    }
    if (c.available == false) {
        Text(tr("No encoder found – detection inactive"), style = MaterialTheme.typography.bodySmall,
            color = K.DangerText, modifier = Modifier.padding(top = 4.dp))
    }
    c.lastRatio?.let { r ->
        Text(tr("Last measured: {pct} % (limit {min} %)", "pct" to (100 * r).roundToInt(), "min" to (100 * (c.minRatio ?: 0.0)).roundToInt()),
            style = MaterialTheme.typography.bodySmall, color = K.Muted, modifier = Modifier.padding(top = 4.dp))
    }
}

private val USB_SWITCHES get() = listOf(
    Triple("usb_watch", "watch", tr("Reconnect USB automatically") to tr("Printer on but not connected → the Klipper computer reconnects itself")),
    Triple("usb_auto_restart", "auto_restart", tr("Reload Klipper afterwards") to tr("When Klipper lost the boards (never during a print)")),
    Triple("usb_full_speed", "full_speed", tr("Slow, robust USB (12 Mbit/s)") to tr("Only if the connection often fails despite the watchdog")),
)

/** ACE sheet: USB tunnel printer <-> Klipper computer - state and the three switches of the watchdog. */
@Composable
fun UsbSection(u: UsbState, onSwitch: (String, Boolean) -> Unit) {
    if (!u.available) return
    val colour = when (u.state) {
        "ok" -> K.Ok
        "bad" -> K.DangerText
        "warn" -> K.Accent
        else -> K.Muted
    }
    Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(top = 16.dp)) {
        Text(tr("USB tunnel"), style = MaterialTheme.typography.bodyLarge, modifier = Modifier.weight(1f))
        Text(u.detail, style = MaterialTheme.typography.bodySmall, color = colour)
    }
    USB_SWITCHES.forEach { (key, field, texts) ->
        Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(top = 8.dp)) {
            Column(Modifier.weight(1f)) {
                Text(texts.first, style = MaterialTheme.typography.bodyMedium)
                Text(texts.second, style = MaterialTheme.typography.bodySmall, color = K.Muted)
            }
            Switch(u.switches[field] == true, { onSwitch(key, it) }, enabled = u.alive,
                colors = SwitchDefaults.colors(checkedTrackColor = K.Accent, checkedThumbColor = K.OnAccent))
        }
    }
}

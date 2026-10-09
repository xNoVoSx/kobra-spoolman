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
import io.github.xnovosx.kobraspoolman.data.ResumeState
import io.github.xnovosx.kobraspoolman.ui.theme.K
import kotlin.math.roundToInt

/** Nach einem Stromausfall: Druck fortsetzen (mit Rueckfrage) oder verwerfen. Das Kamerabild steht direkt darueber. */
@Composable
fun ResumeCard(r: ResumeState, canWrite: Boolean, onResume: (Boolean) -> Unit) {
    var ask by remember { mutableStateOf<Boolean?>(null) }
    val p = r.pending
    Column(Modifier.fillMaxWidth().border(1.dp, K.DangerText, RoundedCornerShape(18.dp)).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text(if (r.running) "Druck wird fortgesetzt …" else "Druck unterbrochen", style = MaterialTheme.typography.titleMedium)
        p?.let {
            Text("${it.file} · Schicht ${it.layer ?: "?"}" + (it.layers?.let { n -> " von $n" } ?: "") +
                " · ${((it.progress ?: 0.0) * 100).roundToInt()} %", style = MaterialTheme.typography.bodySmall, color = K.Muted)
            Text("Prüf im Kamerabild oben, ob das Teil noch fest auf dem Bett ist.", style = MaterialTheme.typography.bodySmall)
        }
        r.error?.let { Text("Fortsetzen abgebrochen: $it", style = MaterialTheme.typography.bodySmall, color = K.DangerText) }
        if (p != null && !r.running && canWrite) Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            PrimaryButton("Fortsetzen …", { ask = true }, Modifier.weight(1f))
            SecondaryButton("Verwerfen", { ask = false }, Modifier.weight(1f))
        }
    }
    ask?.let { start ->
        AlertDialog(onDismissRequest = { ask = null }, containerColor = K.Surface,
            title = { Text(if (start) "Druck fortsetzen?" else "Unterbrochenen Druck verwerfen?") },
            text = { Text(if (start) "Ist das Teil noch fest? Der Drucker heizt das Bett, fährt X/Y nach Hause, tastet die " +
                "Höhe auf dem Teil an und druckt an der Stelle weiter (einige Minuten). Passt die Höhe nicht, bricht er ab."
                else "${p?.file} wird nicht fortgesetzt; die Sicherung wird gelöscht.") },
            confirmButton = { TextButton(onClick = { ask = null; onResume(start) }) {
                Text(if (start) "Fortsetzen" else "Verwerfen", color = if (start) K.Accent else K.DangerText) } },
            dismissButton = { TextButton(onClick = { ask = null }) { Text("Zurück") } })
    }
}

/** Schalter im ACE-Fenster: Fortsetzen nach Stromausfall an/aus (im Drucker gespeichert). */
@Composable
fun PowerlossSwitch(r: ResumeState, onSwitch: (Boolean) -> Unit) {
    if (!r.present) return
    Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(top = 12.dp)) {
        Column(Modifier.weight(1f)) {
            Text("Fortsetzen nach Stromausfall", style = MaterialTheme.typography.bodyLarge)
            Text("Der Drucker sichert im Druck laufend die Stelle und fragt nach dem Einschalten, ob er weitermacht",
                style = MaterialTheme.typography.bodySmall, color = K.Muted)
        }
        Switch(r.enabled == true, onSwitch,
            colors = SwitchDefaults.colors(checkedTrackColor = K.Accent, checkedThumbColor = K.OnAccent))
    }
}

/** Schalter im ACE-Fenster: Verstopfung erkennen an/aus, bei Verdacht nur warnen oder pausieren. */
@Composable
fun ClogSwitch(c: ClogState, onSwitch: (Boolean) -> Unit, onAction: (String) -> Unit) {
    if (!c.present) return
    Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(top = 12.dp)) {
        Column(Modifier.weight(1f)) {
            Text("Verstopfung erkennen", style = MaterialTheme.typography.bodyLarge)
            Text("Vergleicht im Druck die Förderung des Extruders mit dem Encoder am Filament-Eingang",
                style = MaterialTheme.typography.bodySmall, color = K.Muted)
        }
        Switch(c.enabled == true, onSwitch,
            colors = SwitchDefaults.colors(checkedTrackColor = K.Accent, checkedThumbColor = K.OnAccent))
    }
    if (c.enabled == true) {
        Column(Modifier.padding(top = 8.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text("Bei Verdacht", style = MaterialTheme.typography.bodySmall, color = K.Muted)
            Segmented(listOf("warn" to "Nur warnen", "pause" to "Pausieren"), c.action ?: "warn") {
                if (it != c.action) onAction(it)
            }
        }
    }
    if (c.available == false) {
        Text("Kein Encoder gefunden – Erkennung inaktiv", style = MaterialTheme.typography.bodySmall,
            color = K.DangerText, modifier = Modifier.padding(top = 4.dp))
    }
    c.lastRatio?.let { r ->
        Text("Zuletzt gemessen: ${(100 * r).roundToInt()} % (Grenze ${(100 * (c.minRatio ?: 0.0)).roundToInt()} %)",
            style = MaterialTheme.typography.bodySmall, color = K.Muted, modifier = Modifier.padding(top = 4.dp))
    }
}

package io.github.xnovosx.kobraspoolman.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
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
import androidx.compose.ui.draw.clip
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import io.github.xnovosx.kobraspoolman.data.AceSettings
import io.github.xnovosx.kobraspoolman.data.Dryer
import io.github.xnovosx.kobraspoolman.ui.theme.K
import kotlinx.serialization.json.JsonPrimitive
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.LocalTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter

private val MODE_LABEL = mapOf("exact" to "Gleiche Farbe", "material" to "Gleiches Material", "next" to "Nächste Spule")

/**
 * Einstellungen des ACE-Treibers, die das Druckerdisplay nicht zeigt: Endlosspule und ihr Modus. Beides gilt erst
 * beim naechsten leeren Slot und darf auch waehrend eines Drucks geaendert werden. Die Spuelmengen kommen aus Orca.
 */
@Composable
fun AceSection(ace: AceSettings, onOption: (String, JsonPrimitive) -> Unit) {
    SectionLabel("Einstellungen der ACE", Modifier.padding(top = 12.dp))
    if (!ace.present) {
        Hint("Der ACE-Treiber meldet keine verbundene ACE.")
        return
    }
    OptionRow("Endlosspule", "Ist eine Spule leer, lädt die ACE eine passende andere und druckt weiter",
        ace.endlessSpool, true) { onOption("endless_spool", JsonPrimitive(it)) }
    if (ace.endlessSpool == true) {
        Text("Welche Spule passt?", style = MaterialTheme.typography.bodySmall, color = K.Muted)
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            ace.endlessModes.keys.forEach { key ->
                val on = ace.endlessMode == key
                Text(MODE_LABEL[key] ?: key,
                    style = MaterialTheme.typography.labelMedium, color = if (on) K.Accent else K.Muted,
                    modifier = Modifier.clip(RoundedCornerShape(50)).border(1.dp, if (on) K.Accent else K.LineStrong, RoundedCornerShape(50))
                        .background(if (on) K.AccentSoft else K.Surface)
                        .clickable(enabled = !on, role = Role.Button) { onOption("endless_mode", JsonPrimitive(key)) }
                        .padding(horizontal = 12.dp, vertical = 8.dp))
            }
        }
    }
    Text("Spülmengen pro Farbwechsel stellst du in Orca ein (Spülmengen-Dialog neben „Filament“)." +
        (ace.firmware?.let { " ACE-Firmware $it." } ?: ""), style = MaterialTheme.typography.bodySmall, color = K.Faint)
}

@Composable
private fun OptionRow(title: String, hint: String, value: Boolean?, enabled: Boolean, onChange: (Boolean) -> Unit) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f)) {
            Text(title, style = MaterialTheme.typography.bodyLarge)
            Text(hint, style = MaterialTheme.typography.bodySmall, color = K.Muted)
        }
        Switch(value == true, onChange, enabled = enabled && value != null,
            colors = SwitchDefaults.colors(checkedTrackColor = K.Accent, checkedThumbColor = K.OnAccent))
    }
}

/** Einmaliges Trocknen planen (heute/morgen, Uhrzeit, optional Temperatur und Dauer). */
@Composable
fun DryPlanSection(d: Dryer, onPlan: (Double, Int?, Double?) -> Unit, onClear: () -> Unit) {
    val zone = ZoneId.systemDefault()
    var tomorrow by remember { mutableStateOf(LocalTime.now().isAfter(LocalTime.of(21, 30))) }
    var time by remember { mutableStateOf("22:00") }
    var temp by remember { mutableStateOf("") }
    var hours by remember { mutableStateOf(Format.decimal(d.config.maxHours, 0)) }

    SectionLabel("Trocknen planen", Modifier.padding(top = 12.dp))
    d.schedule?.let { s ->
        val at = LocalDateTime.ofInstant(java.time.Instant.ofEpochMilli((s.at * 1000).toLong()), zone)
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("Geplant: ${at.format(DateTimeFormatter.ofPattern("dd.MM. HH:mm"))}" +
                (s.temp?.let { " · ${it.toInt()} °C" } ?: "") + (s.hours?.let { " · ${Format.decimal(it, 1)} h" } ?: ""),
                style = MaterialTheme.typography.bodyMedium, color = K.Accent, modifier = Modifier.weight(1f))
            TextButton(onClick = onClear) { Text("Löschen", color = K.DangerText) }
        }
    }
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        listOf(false to "Heute", true to "Morgen").forEach { (v, label) ->
            Text(label, style = MaterialTheme.typography.labelMedium, color = if (tomorrow == v) K.Accent else K.Muted,
                modifier = Modifier.clip(RoundedCornerShape(50))
                    .border(1.dp, if (tomorrow == v) K.Accent else K.LineStrong, RoundedCornerShape(50))
                    .clickable(role = Role.Button) { tomorrow = v }.padding(horizontal = 14.dp, vertical = 8.dp))
        }
    }
    val t = runCatching { LocalTime.parse(time.trim().padStart(5, '0')) }.getOrNull()
    val day = LocalDate.now().plusDays(if (tomorrow) 1 else 0)
    val atEpoch = t?.let { LocalDateTime.of(day, it).atZone(zone).toEpochSecond().toDouble() }
    val h = Format.parseDecimal(hours)
    val ok = atEpoch != null && atEpoch > System.currentTimeMillis() / 1000.0 && h != null && h in 0.5..24.0
    Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        OutlinedTextField(time, { time = it.filter { c -> c.isDigit() || c == ':' }.take(5) }, label = { Text("Uhrzeit") },
            singleLine = true, modifier = Modifier.weight(1f), shape = RoundedCornerShape(12.dp), isError = t == null)
        OutlinedTextField(temp, { temp = it.filter(Char::isDigit) }, label = { Text("°C") }, singleLine = true,
            placeholder = { Text("auto", color = K.Faint) }, modifier = Modifier.weight(1f), shape = RoundedCornerShape(12.dp),
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number))
        OutlinedTextField(hours, { hours = it.filter { c -> c.isDigit() || c == ',' || c == '.' } }, label = { Text("Stunden") },
            singleLine = true, modifier = Modifier.weight(1f), shape = RoundedCornerShape(12.dp),
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal))
    }
    PrimaryButton(if (d.schedule != null) "Plan ersetzen" else "Planen",
        { atEpoch?.let { onPlan(it, temp.toIntOrNull(), h) } }, Modifier.fillMaxWidth(), enabled = ok)
}

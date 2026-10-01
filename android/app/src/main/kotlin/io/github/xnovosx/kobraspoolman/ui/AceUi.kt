package io.github.xnovosx.kobraspoolman.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
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
import io.github.xnovosx.kobraspoolman.data.PurgePreview
import io.github.xnovosx.kobraspoolman.ui.theme.K
import io.github.xnovosx.kobraspoolman.ui.theme.PlexMono
import io.github.xnovosx.kobraspoolman.ui.theme.spoolColor
import kotlinx.coroutines.delay
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.LocalTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import kotlin.math.abs

private val PRESET_LABEL = mapOf("minimal" to "Minimal", "normal" to "Normal", "maximum" to "Maximum")

/**
 * Einstellungen der ACE, die das Druckerdisplay versteckt: Spuel-Multiplikator mit Vorschau fuer die
 * eingelegten Farben, automatisches Nachladen, Leer-Erkennung. Waehrend eines Drucks erst nach "Freischalten".
 */
@Composable
fun AceSection(
    ace: AceSettings,
    preview: PurgePreview?,
    onPreview: (Double?) -> Unit,
    onSetFlush: (Double, Boolean) -> Unit,
    onOption: (String, Boolean, Boolean) -> Unit,
) {
    var unlocked by remember(ace.printing) { mutableStateOf(false) }
    var text by remember(ace.flushMultiplier) { mutableStateOf(Format.decimal(ace.flushMultiplier, 1)) }
    val wanted = Format.parseDecimal(text)
    val valid = wanted != null && wanted in 0.1..3.0
    val changed = valid && ace.flushMultiplier != null && abs(wanted!! - ace.flushMultiplier) > 0.001
    val locked = ace.printing && !unlocked
    LaunchedEffect(wanted) { delay(250); onPreview(if (valid) wanted else null) }

    SectionLabel("Spülen und Einstellungen der ACE", Modifier.padding(top = 12.dp))
    if (!ace.present) {
        Hint("Die Bridge konnte die Einstellungen noch nicht vom Drucker lesen.")
        return
    }
    Row(verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f)) {
            Text("Spülen (Multiplikator)", style = MaterialTheme.typography.bodySmall, color = K.Muted)
            Text("× ${Format.decimal(ace.flushMultiplier, 1)}", fontFamily = PlexMono, style = MaterialTheme.typography.headlineSmall)
        }
        if (locked) SecondaryButton("Freischalten", { unlocked = true })
    }
    if (ace.printing && unlocked) Hint("Druck läuft: Der neue Wert gilt ab dem nächsten Farbwechsel. Weniger Spülen spart " +
        "Filament, kann aber Farben vermischen.")
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        ace.presets.forEach { (key, value) ->
            val on = ace.flushMultiplier?.let { abs(it - value) < 0.001 } == true
            Text("${PRESET_LABEL[key] ?: key} ${Format.decimal(value, 1)}",
                style = MaterialTheme.typography.labelMedium, color = if (on) K.Accent else K.Muted,
                modifier = Modifier.clip(RoundedCornerShape(50)).border(1.dp, if (on) K.Accent else K.LineStrong, RoundedCornerShape(50))
                    .background(if (on) K.AccentSoft else K.Surface)
                    .clickable(enabled = !locked, role = Role.Button) { onSetFlush(value, unlocked) }
                    .padding(horizontal = 12.dp, vertical = 8.dp))
        }
    }
    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        OutlinedTextField(text, { v -> text = v.filter { it.isDigit() || it == ',' || it == '.' } }, label = { Text("Multiplikator") },
            singleLine = true, enabled = !locked, modifier = Modifier.width(150.dp), shape = RoundedCornerShape(12.dp),
            isError = text.isNotBlank() && !valid, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal))
        PrimaryButton("Übernehmen", { wanted?.let { onSetFlush(it, unlocked) } }, Modifier.weight(1f), enabled = changed && !locked)
    }
    preview?.takeIf { it.pairs.isNotEmpty() }?.let { p ->
        val sorted = p.pairs.sortedBy { it.mm }
        Text(if (changed) "Mit × ${Format.decimal(wanted, 1)} pro Farbwechsel:" else "Pro Farbwechsel mit den eingelegten Spulen:",
            style = MaterialTheme.typography.bodySmall, color = K.Muted)
        listOf("teuerster" to sorted.last(), "günstigster" to sorted.first()).distinctBy { it.second }.forEach { (label, pair) ->
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(label, style = MaterialTheme.typography.bodySmall, color = K.Muted, modifier = Modifier.width(86.dp))
                Dot(pair.fromColor); Text("→", color = K.Muted); Dot(pair.toColor)
                Text("Slot ${pair.fromSlot} → ${pair.toSlot}", style = MaterialTheme.typography.bodySmall, modifier = Modifier.weight(1f))
                Text("${pair.mm.toInt()} mm · ${Format.decimal(pair.g, 1)} g", fontFamily = PlexMono,
                    style = MaterialTheme.typography.bodySmall)
            }
        }
        Text("Erster Ladevorgang eines Drucks ≈ ${p.firstLoadMm.toInt()} mm. Gerechnet wie die Firmware.",
            style = MaterialTheme.typography.bodySmall, color = K.Faint)
    }
    OptionRow("Automatisch nachladen", "Ist eine Spule leer, lädt die ACE eine passende Ersatzspule",
        ace.autoRefill, !locked) { onOption("auto_refill", it, unlocked) }
    OptionRow("Leer-Erkennung", "Die ACE erkennt, wenn eine Spule zu Ende ist",
        ace.runoutDetect, !locked) { onOption("runout_detect", it, unlocked) }
}

@Composable
private fun Dot(hex: String?) {
    Box(Modifier.size(12.dp).clip(CircleShape).background(spoolColor(hex)))
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

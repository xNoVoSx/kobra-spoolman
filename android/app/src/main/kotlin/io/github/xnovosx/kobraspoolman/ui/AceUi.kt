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
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Slider
import androidx.compose.material3.SliderDefaults
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.text.style.TextOverflow
import io.github.xnovosx.kobraspoolman.data.AcePurge
import io.github.xnovosx.kobraspoolman.ui.theme.spoolColor
import kotlinx.coroutines.delay
import kotlin.math.abs
import kotlin.math.roundToInt
import io.github.xnovosx.kobraspoolman.data.Dryer
import io.github.xnovosx.kobraspoolman.ui.theme.K
import kotlinx.serialization.json.JsonPrimitive
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.LocalTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import io.github.xnovosx.kobraspoolman.data.tr
import io.github.xnovosx.kobraspoolman.data.I18n

private val MODE_LABEL get() = mapOf("exact" to tr("Same colour"), "material" to tr("Same material"), "next" to tr("Next spool"))
private val PRESET_LABEL get() = mapOf("minimal" to tr("Minimal"), "normal" to tr("Normal"), "maximum" to tr("Maximum"))

/**
 * Settings of the ACE the printer display does not show, per driver.
 * Klipper + ACEPRO: endless spool and its mode (apply at the next empty slot, also during a print); purge volumes from Orca.
 * Rinkhals: endless spool, runout detection and the firmware's purge multiplier with a preview per colour pair - the
 * firmware purges by itself. Changes during a print need a confirmation (they apply from the next colour change).
 * onOption(key, value, confirmPrinting); purgePreview(multiplier) loads the pairs.
 */
@Composable
fun AceSection(ace: AceSettings, onOption: (String, JsonPrimitive, Boolean) -> Unit,
               purgePreview: suspend (Double?) -> AcePurge? = { null }) {
    SectionLabel(tr("ACE settings"), Modifier.padding(top = 12.dp))
    if (!ace.present) {
        Hint(tr("The ACE driver reports no connected ACE."))
        return
    }
    val rinkhals = ace.variant == "rinkhals"
    var ask by remember { mutableStateOf<Pair<String, JsonPrimitive>?>(null) }
    val set: (String, JsonPrimitive) -> Unit = { k, v -> if (rinkhals && ace.printing) ask = k to v else onOption(k, v, false) }
    ask?.let { (k, v) ->
        AlertDialog(onDismissRequest = { ask = null }, containerColor = K.Surface,
            title = { Text(tr("Change during the print?")) }, text = { Text(tr("The printer applies it from the next colour change on.")) },
            confirmButton = { TextButton(onClick = { ask = null; onOption(k, v, true) }) { Text(tr("Change"), color = K.Accent) } },
            dismissButton = { TextButton(onClick = { ask = null }) { Text(tr("Back")) } })
    }

    OptionRow(tr("Endless spool"), tr("If a spool runs empty, the ACE loads a matching other one and keeps printing"),
        ace.endlessSpool, true) { set("endless_spool", JsonPrimitive(it)) }
    if (ace.endlessSpool == true && ace.endlessModes.isNotEmpty()) {
        Text(tr("Which spool matches?"), style = MaterialTheme.typography.bodySmall, color = K.Muted)
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            ace.endlessModes.keys.forEach { key ->
                Chip(MODE_LABEL[key] ?: key, ace.endlessMode == key) { set("endless_mode", JsonPrimitive(key)) }
            }
        }
    }
    if (!rinkhals) {
        Text(tr("Purge volumes per colour change are set in Orca (flushing volumes dialog next to “Filament”).") +
            (ace.firmware?.let { " " + tr("ACE firmware {version}.", "version" to it) } ?: ""), style = MaterialTheme.typography.bodySmall, color = K.Faint)
        return
    }
    OptionRow(tr("Runout detection"), tr("The printer pauses when the filament runs out"), ace.runoutDetect, true) {
        set("runout_detect", JsonPrimitive(it))
    }
    PurgeMultiplier(ace, { set("flush_multiplier", JsonPrimitive(it)) }, purgePreview)
}

@Composable
private fun Chip(label: String, on: Boolean, enabled: Boolean = true, onClick: () -> Unit) {
    Text(label, style = MaterialTheme.typography.labelMedium, color = if (on) K.Accent else K.Muted,
        modifier = Modifier.clip(RoundedCornerShape(50)).border(1.dp, if (on) K.Accent else K.LineStrong, RoundedCornerShape(50))
            .background(if (on) K.AccentSoft else K.Surface)
            .clickable(enabled = enabled && !on, role = Role.Button, onClick = onClick)
            .padding(horizontal = 12.dp, vertical = 8.dp))
}

/** Rinkhals: the firmware's purge multiplier with a "what if" preview per colour pair. */
@Composable
private fun PurgeMultiplier(ace: AceSettings, onApply: (Double) -> Unit, purgePreview: suspend (Double?) -> AcePurge?) {
    val current = ace.flushMultiplier
    val (lo, hi) = ace.limits["flush_multiplier"]?.takeIf { it.size == 2 }?.let { it[0] to it[1] } ?: (0.1 to 3.0)
    var want by remember(current) { mutableStateOf(current) }
    var preview by remember { mutableStateOf<AcePurge?>(null) }
    LaunchedEffect(want) {
        delay(250)
        preview = purgePreview(want)
    }
    val editable = ace.flushMultiplierEditable && current != null
    val x = { v: Double -> Format.decimal(v, 1) + "×" }

    SectionLabel(tr("Purge per colour change"), Modifier.padding(top = 8.dp))
    Text(tr("Under Rinkhals the printer purges by itself at every colour change – Orca's flushing volumes do not apply. The amount follows the colour difference times this multiplier."),
        style = MaterialTheme.typography.bodySmall, color = K.Muted)
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        ace.presets.forEach { (k, v) -> Chip("${PRESET_LABEL[k] ?: k} ${x(v)}", want != null && abs(want!! - v) < 0.001, editable) { want = v } }
    }
    Row(verticalAlignment = Alignment.CenterVertically) {
        Slider((want ?: 1.0).toFloat(), { want = (it * 10).roundToInt() / 10.0 }, Modifier.weight(1f), enabled = editable,
            valueRange = lo.toFloat()..hi.toFloat(),
            colors = SliderDefaults.colors(thumbColor = K.Accent, activeTrackColor = K.Accent))
        Text(want?.let(x) ?: "–", style = MaterialTheme.typography.titleMedium, modifier = Modifier.padding(start = 10.dp))
    }
    if (!editable && current != null) Hint(tr("The firmware does not allow changing the multiplier right now"))
    val w = want
    if (w != null && current != null && abs(w - current) > 0.001) {
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            PrimaryButton(tr("Apply {m}×", "m" to Format.decimal(w, 1)), { onApply(w) }, Modifier.weight(1f))
            TextButton(onClick = { want = current }) { Text(tr("Reset")) }
        }
    }
    preview?.let { p ->
        if (p.pairs.isEmpty()) {
            Hint(tr("Load at least two colours to see the purge per change."))
        } else {
            Text(tr("First load of a print: about {mm} mm.", "mm" to Format.decimal(p.firstLoadMm, 0)),
                style = MaterialTheme.typography.bodySmall, color = K.Muted)
            p.pairs.forEach { pair ->
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    Dot(pair.fromColor)
                    Text("${pair.fromSlot}", style = MaterialTheme.typography.bodySmall)
                    Text("→", style = MaterialTheme.typography.bodySmall, color = K.Muted)
                    Dot(pair.toColor)
                    Text("${pair.toSlot} · ${pair.toName}", style = MaterialTheme.typography.bodySmall, maxLines = 1,
                        overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f))
                    Text("${Format.decimal(pair.mm, 0)} mm · ${Format.decimal(pair.g, 1)} g", style = MaterialTheme.typography.bodySmall)
                }
            }
        }
    }
}

@Composable
private fun Dot(hex: String?) {
    Box(Modifier.size(12.dp).clip(CircleShape).background(spoolColor(hex)).border(1.dp, K.LineStrong, CircleShape))
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

/** Schedule a one-off drying (today/tomorrow, time, optional temperature and duration). */
@Composable
fun DryPlanSection(d: Dryer, onPlan: (Double, Int?, Double?) -> Unit, onClear: () -> Unit) {
    val zone = ZoneId.systemDefault()
    var tomorrow by remember { mutableStateOf(LocalTime.now().isAfter(LocalTime.of(21, 30))) }
    var time by remember { mutableStateOf("22:00") }
    var temp by remember { mutableStateOf("") }
    var hours by remember { mutableStateOf(Format.decimal(d.config.maxHours, 0)) }

    SectionLabel(tr("Schedule drying"), Modifier.padding(top = 12.dp))
    d.schedule?.let { s ->
        val at = LocalDateTime.ofInstant(java.time.Instant.ofEpochMilli((s.at * 1000).toLong()), zone)
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(tr("Scheduled: {at}", "at" to at.format(DateTimeFormatter.ofPattern(if (I18n.lang == "de") "dd.MM. HH:mm" else "d MMM HH:mm", I18n.locale))) +
                (s.temp?.let { " · ${it.toInt()} °C" } ?: "") + (s.hours?.let { " · ${Format.decimal(it, 1)} h" } ?: ""),
                style = MaterialTheme.typography.bodyMedium, color = K.Accent, modifier = Modifier.weight(1f))
            TextButton(onClick = onClear) { Text(tr("Delete"), color = K.DangerText) }
        }
    }
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        listOf(false to tr("Today"), true to tr("Tomorrow")).forEach { (v, label) ->
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
        OutlinedTextField(time, { time = it.filter { c -> c.isDigit() || c == ':' }.take(5) }, label = { Text(tr("Time")) },
            singleLine = true, modifier = Modifier.weight(1f), shape = RoundedCornerShape(12.dp), isError = t == null)
        OutlinedTextField(temp, { temp = it.filter(Char::isDigit) }, label = { Text("°C") }, singleLine = true,
            placeholder = { Text(tr("auto"), color = K.Faint) }, modifier = Modifier.weight(1f), shape = RoundedCornerShape(12.dp),
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number))
        OutlinedTextField(hours, { hours = it.filter { c -> c.isDigit() || c == ',' || c == '.' } }, label = { Text(tr("Hours")) },
            singleLine = true, modifier = Modifier.weight(1f), shape = RoundedCornerShape(12.dp),
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal))
    }
    PrimaryButton(if (d.schedule != null) tr("Replace schedule") else tr("Schedule"),
        { atEpoch?.let { onPlan(it, temp.toIntOrNull(), h) } }, Modifier.fillMaxWidth(), enabled = ok)
}

package io.github.xnovosx.kobraspoolman.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import io.github.xnovosx.kobraspoolman.data.AceSettings
import io.github.xnovosx.kobraspoolman.data.Dryer
import io.github.xnovosx.kobraspoolman.data.DryerConfig
import io.github.xnovosx.kobraspoolman.ui.theme.K
import io.github.xnovosx.kobraspoolman.ui.theme.PlexMono
import kotlinx.serialization.json.JsonPrimitive
import io.github.xnovosx.kobraspoolman.data.tr

private val DryingBg = Color(0xFF231A10)
private val DryingLine = Color(0xFF6B4A18)

private val RUN_SOURCE get() = mapOf("hand" to tr("by hand"), "plan" to tr("scheduled"), "spule" to tr("after inserting"))   // keys: stable API codes

private fun num(v: Double?): String = v?.let { if (it % 1.0 == 0.0) it.toInt().toString() else it.toString() } ?: "?"

/** Card on the home screen: humidity, temperature, dryer state. Tapping opens the controls. */
@Composable
fun DryerCard(d: Dryer, onOpen: () -> Unit) {
    val shape = RoundedCornerShape(18.dp)
    Row(
        Modifier.fillMaxWidth().clip(shape).background(if (d.drying) DryingBg else K.Surface)
            .border(1.dp, if (d.drying) DryingLine else K.Line, shape).clickable(role = Role.Button, onClick = onOpen)
            .padding(horizontal = 14.dp, vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        Column {
            Text(tr("HUMIDITY"), style = MaterialTheme.typography.labelSmall, color = K.Muted)
            Text("${num(d.humidity)} %", fontFamily = PlexMono, style = MaterialTheme.typography.titleLarge)
        }
        Column {
            Text("ACE", style = MaterialTheme.typography.labelSmall, color = K.Muted)
            Text("${num(d.temp)} °C", fontFamily = PlexMono, style = MaterialTheme.typography.titleLarge)
        }
        Column(Modifier.weight(1f)) {
            Text(if (d.drying) tr("Drying at {temp} °C", "temp" to num(d.targetTemp)) else tr("Dryer off"),
                style = MaterialTheme.typography.bodyMedium, color = if (d.drying) K.Accent else K.Text)
            val sub = buildList {
                if (d.drying && d.remainingMin != null) add(tr("{time} left", "time" to Format.duration(d.remainingMin * 60)))
                if (d.drying) d.run?.source?.let { RUN_SOURCE[it] }?.let { add(it) }
                add(if (d.config.enabled) tr("Automatic from {pct} %", "pct" to num(d.config.startAbove)) else tr("Automatic off"))
            }.joinToString(" · ")
            Text(sub, style = MaterialTheme.typography.bodySmall, color = K.Muted)
        }
    }
}

/** Content of the dryer sheet: dry now + automatic. */
@Composable
fun DryerSheet(
    d: Dryer, ace: AceSettings?,
    onStart: (Int?, Double?) -> Unit, onStop: () -> Unit, onSaveConfig: (DryerConfig) -> Unit,
    onPlan: (Double, Int?, Double?) -> Unit, onClearPlan: () -> Unit,
    onOption: (String, JsonPrimitive) -> Unit,
    humidity: @Composable () -> Unit = {},
    pa: @Composable () -> Unit = {},
) {
    var temp by remember { mutableStateOf("") }
    var hours by remember { mutableStateOf(num(d.config.maxHours)) }
    var c by remember { mutableStateOf(d.config) }
    var startAbove by remember { mutableStateOf(num(d.config.startAbove)) }
    var stopBelow by remember { mutableStateOf(num(d.config.stopBelow)) }
    var maxHours by remember { mutableStateOf(num(d.config.maxHours)) }
    var pause by remember { mutableStateOf(num(d.config.pauseMinutes)) }
    var delay by remember { mutableStateOf(num(d.config.startDelayMinutes)) }
    val req = d.required

    Column(Modifier.fillMaxWidth().verticalScroll(rememberScrollState()).padding(horizontal = 20.dp).padding(bottom = 28.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Text("ACE", style = MaterialTheme.typography.headlineSmall)
        Text(tr("Humidity {h} % · ACE {t} °C", "h" to num(d.humidity), "t" to num(d.temp)) + (d.model?.let { " · $it" } ?: ""),
            style = MaterialTheme.typography.bodySmall, color = K.Muted)

        SectionLabel(tr("Dry now"), Modifier.padding(top = 8.dp))
        val why = req.slots.filter { it.slot in req.limitedBy }.joinToString { tr("Slot {slot}", "slot" to it.slot) + " " + it.name }
        Hint(if (req.temp != null) tr("At most {temp} °C", "temp" to req.temp) + (if (why.isNotBlank()) " – " + tr("because of {why}", "why" to why) else "") +
            ". " + tr("The bridge never goes above it, even if you enter more.") else tr("No spool loaded – enter a temperature."))
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            NumField(tr("Temperature (°C)"), temp, { temp = it }, Modifier.weight(1f), placeholder = req.temp?.toString())
            NumField(tr("Duration (h)"), hours, { hours = it }, Modifier.weight(1f))
        }
        d.run?.takeIf { d.drying && it.source != "auto" }?.let { r ->
            Hint(tr("Runs {source} until the time is up – even if the ACE already reports dry. If the ACE stops earlier, the bridge restarts it with the time left.", "source" to (RUN_SOURCE[r.source] ?: r.source)))
        }
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            PrimaryButton(if (d.drying) tr("Restart") else tr("Start drying"),
                { onStart(temp.toDoubleOrNull()?.toInt(), hours.replace(',', '.').toDoubleOrNull()) }, Modifier.weight(1f))
            if (d.drying) SecondaryButton(tr("Stop"), onStop, Modifier.weight(1f))
        }

        SectionLabel(tr("Automatic"), Modifier.padding(top = 12.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(tr("Dry automatically"), style = MaterialTheme.typography.bodyLarge, modifier = Modifier.weight(1f))
            Switch(c.enabled, { c = c.copy(enabled = it) },
                colors = SwitchDefaults.colors(checkedTrackColor = K.Accent, checkedThumbColor = K.OnAccent))
        }
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            NumField(tr("Start above (%)"), startAbove, { startAbove = it }, Modifier.weight(1f))
            NumField(tr("Stop below (%)"), stopBelow, { stopBelow = it }, Modifier.weight(1f))
        }
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            NumField(tr("Max. duration (h)"), maxHours, { maxHours = it }, Modifier.weight(1f))
            NumField(tr("Pause afterwards (min)"), pause, { pause = it }, Modifier.weight(1f))
        }
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp), verticalAlignment = Alignment.CenterVertically) {
            NumField(tr("Wait (min)"), delay, { delay = it }, Modifier.weight(1f))
            Text(tr("Humidity must stay above the threshold this long in one go – a lid briefly open starts nothing."),
                style = MaterialTheme.typography.bodySmall, color = K.Muted, modifier = Modifier.weight(1f))
        }
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(tr("Also during a print"), style = MaterialTheme.typography.bodyLarge, modifier = Modifier.weight(1f))
            Switch(c.whilePrinting, { c = c.copy(whilePrinting = it) },
                colors = SwitchDefaults.colors(checkedTrackColor = K.Accent, checkedThumbColor = K.OnAccent))
        }
        PrimaryButton(tr("Save automatic"), {
            onSaveConfig(c.copy(
                startAbove = startAbove.replace(',', '.').toDoubleOrNull() ?: c.startAbove,
                stopBelow = stopBelow.replace(',', '.').toDoubleOrNull() ?: c.stopBelow,
                maxHours = maxHours.replace(',', '.').toDoubleOrNull() ?: c.maxHours,
                pauseMinutes = pause.replace(',', '.').toDoubleOrNull() ?: c.pauseMinutes,
                startDelayMinutes = delay.replace(',', '.').toDoubleOrNull() ?: c.startDelayMinutes,
            ))
        }, Modifier.fillMaxWidth())
        d.lastEvent?.let { Text(tr("Last: {text}", "text" to it.text), style = MaterialTheme.typography.bodySmall, color = K.Muted) }
        DryPlanSection(d, onPlan, onClearPlan)
        humidity()
        ace?.let { AceSection(it, onOption) }
        pa()
        Text(tr("The temperature always follows the most sensitive loaded filament (field “Dry max.” in Spoolman, else a default per material) and never goes above what the ACE can do (ACE 2 Pro: {max} °C).", "max" to req.aceMax),
            style = MaterialTheme.typography.bodySmall, color = K.Faint)
    }
}

@Composable
internal fun NumField(label: String, value: String, onChange: (String) -> Unit, modifier: Modifier, placeholder: String? = null) {
    OutlinedTextField(
        value = value, onValueChange = { v -> onChange(v.filter { it.isDigit() || it == '.' || it == ',' }) },
        label = { Text(label) }, singleLine = true, modifier = modifier.width(120.dp), shape = RoundedCornerShape(12.dp),
        placeholder = placeholder?.let { { Text(it, color = K.Faint) } },
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
    )
}

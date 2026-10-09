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

private val DryingBg = Color(0xFF231A10)
private val DryingLine = Color(0xFF6B4A18)

private val RUN_SOURCE = mapOf("hand" to "von Hand", "plan" to "geplant", "spule" to "nach dem Einlegen")

private fun num(v: Double?): String = v?.let { if (it % 1.0 == 0.0) it.toInt().toString() else it.toString() } ?: "?"

/** Karte auf der Startseite: Feuchte, Temperatur, Trockner-Zustand. Tippen oeffnet die Steuerung. */
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
            Text("FEUCHTE", style = MaterialTheme.typography.labelSmall, color = K.Muted)
            Text("${num(d.humidity)} %", fontFamily = PlexMono, style = MaterialTheme.typography.titleLarge)
        }
        Column {
            Text("ACE", style = MaterialTheme.typography.labelSmall, color = K.Muted)
            Text("${num(d.temp)} °C", fontFamily = PlexMono, style = MaterialTheme.typography.titleLarge)
        }
        Column(Modifier.weight(1f)) {
            Text(if (d.drying) "Trocknet auf ${num(d.targetTemp)} °C" else "Trockner aus",
                style = MaterialTheme.typography.bodyMedium, color = if (d.drying) K.Accent else K.Text)
            val sub = buildList {
                if (d.drying && d.remainingMin != null) add("noch ${Format.duration(d.remainingMin * 60)}")
                if (d.drying) d.run?.source?.let { RUN_SOURCE[it] }?.let { add(it) }
                add(if (d.config.enabled) "Automatik ab ${num(d.config.startAbove)} %" else "Automatik aus")
            }.joinToString(" · ")
            Text(sub, style = MaterialTheme.typography.bodySmall, color = K.Muted)
        }
    }
}

/** Inhalt des Trockner-Fensters: jetzt trocknen + Automatik. */
@Composable
fun DryerSheet(
    d: Dryer, ace: AceSettings?,
    onStart: (Int?, Double?) -> Unit, onStop: () -> Unit, onSaveConfig: (DryerConfig) -> Unit,
    onPlan: (Double, Int?, Double?) -> Unit, onClearPlan: () -> Unit,
    onOption: (String, JsonPrimitive) -> Unit,
    humidity: @Composable () -> Unit = {},
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
        Text("Feuchte ${num(d.humidity)} % · ACE ${num(d.temp)} °C" + (d.model?.let { " · $it" } ?: ""),
            style = MaterialTheme.typography.bodySmall, color = K.Muted)

        SectionLabel("Jetzt trocknen", Modifier.padding(top = 8.dp))
        val why = req.slots.filter { it.slot in req.limitedBy }.joinToString { "Slot ${it.slot} ${it.name}" }
        Hint(if (req.temp != null) "Höchstens ${req.temp} °C" + (if (why.isNotBlank()) " – wegen $why" else "") +
            ". Die Bridge geht nie darüber, auch wenn du mehr einträgst." else "Keine Spule eingelegt – Temperatur angeben.")
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            NumField("Temperatur (°C)", temp, { temp = it }, Modifier.weight(1f), placeholder = req.temp?.toString())
            NumField("Dauer (h)", hours, { hours = it }, Modifier.weight(1f))
        }
        d.run?.takeIf { d.drying && it.source != "auto" }?.let { r ->
            Hint("Läuft ${RUN_SOURCE[r.source] ?: r.source} bis zum Ende der Zeit – auch wenn die ACE schon trocken " +
                "meldet. Hört die ACE vorher auf, startet die Bridge sie mit der Restzeit neu.")
        }
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            PrimaryButton(if (d.drying) "Neu starten" else "Trocknen starten",
                { onStart(temp.toDoubleOrNull()?.toInt(), hours.replace(',', '.').toDoubleOrNull()) }, Modifier.weight(1f))
            if (d.drying) SecondaryButton("Stoppen", onStop, Modifier.weight(1f))
        }

        SectionLabel("Automatik", Modifier.padding(top = 12.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("Automatisch trocknen", style = MaterialTheme.typography.bodyLarge, modifier = Modifier.weight(1f))
            Switch(c.enabled, { c = c.copy(enabled = it) },
                colors = SwitchDefaults.colors(checkedTrackColor = K.Accent, checkedThumbColor = K.OnAccent))
        }
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            NumField("Start ab (%)", startAbove, { startAbove = it }, Modifier.weight(1f))
            NumField("Stopp unter (%)", stopBelow, { stopBelow = it }, Modifier.weight(1f))
        }
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            NumField("Höchstdauer (h)", maxHours, { maxHours = it }, Modifier.weight(1f))
            NumField("Pause danach (min)", pause, { pause = it }, Modifier.weight(1f))
        }
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp), verticalAlignment = Alignment.CenterVertically) {
            NumField("Warten (min)", delay, { delay = it }, Modifier.weight(1f))
            Text("So lange muss die Feuchte am Stück über der Schwelle liegen – Deckel kurz offen startet nichts.",
                style = MaterialTheme.typography.bodySmall, color = K.Muted, modifier = Modifier.weight(1f))
        }
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("Auch während eines Drucks", style = MaterialTheme.typography.bodyLarge, modifier = Modifier.weight(1f))
            Switch(c.whilePrinting, { c = c.copy(whilePrinting = it) },
                colors = SwitchDefaults.colors(checkedTrackColor = K.Accent, checkedThumbColor = K.OnAccent))
        }
        PrimaryButton("Automatik speichern", {
            onSaveConfig(c.copy(
                startAbove = startAbove.replace(',', '.').toDoubleOrNull() ?: c.startAbove,
                stopBelow = stopBelow.replace(',', '.').toDoubleOrNull() ?: c.stopBelow,
                maxHours = maxHours.replace(',', '.').toDoubleOrNull() ?: c.maxHours,
                pauseMinutes = pause.replace(',', '.').toDoubleOrNull() ?: c.pauseMinutes,
                startDelayMinutes = delay.replace(',', '.').toDoubleOrNull() ?: c.startDelayMinutes,
            ))
        }, Modifier.fillMaxWidth())
        d.lastEvent?.let { Text("Zuletzt: ${it.text}", style = MaterialTheme.typography.bodySmall, color = K.Muted) }
        DryPlanSection(d, onPlan, onClearPlan)
        humidity()
        ace?.let { AceSection(it, onOption) }
        Text("Die Temperatur richtet sich immer nach dem empfindlichsten eingelegten Filament (Feld „Trocknen max.“ in " +
            "Spoolman, sonst Startwert je Material) und geht nie über das, was die ACE kann (ACE 2 Pro: ${req.aceMax} °C).",
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

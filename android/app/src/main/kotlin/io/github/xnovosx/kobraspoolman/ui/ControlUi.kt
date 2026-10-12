package io.github.xnovosx.kobraspoolman.ui

import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Slider
import androidx.compose.material3.SliderDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.role
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import io.github.xnovosx.kobraspoolman.data.Printer
import io.github.xnovosx.kobraspoolman.ui.theme.K
import io.github.xnovosx.kobraspoolman.ui.theme.PlexMono
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlin.math.roundToInt
import io.github.xnovosx.kobraspoolman.data.tr

private const val HOLD_MS = 2000

/**
 * Print control below the print status: pause/resume, cancel (confirmation), tune, emergency stop (hold 2 s +
 * confirmation). If Klipper is not ready (emergency stop, error) but Moonraker is there: only "Reload Klipper".
 */
@Composable
fun ControlRow(p: Printer, onAction: (String, String) -> Unit, onTune: () -> Unit) {
    var ask by remember { mutableStateOf<String?>(null) }
    if (p.state == "offline") {
        if (!p.moonrakerConnected || p.klippyReady) return
        if (!p.canRestart) {
            // Rinkhals blocks reloading (GoKlipper would hang): only switching the printer off and on helps
            Text(tr("The printer is not ready – switch it off and on."), style = MaterialTheme.typography.bodySmall, color = K.Muted)
            return
        }
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(tr("Klipper is not ready."), style = MaterialTheme.typography.bodySmall, color = K.Muted, modifier = Modifier.weight(1f))
            PrimaryButton(tr("Reload Klipper"), { ask = "firmware_restart" })
        }
        if (ask == "firmware_restart") ConfirmDialog(tr("Reload Klipper?"),
            tr("Klipper is not ready (emergency stop or error). Reloading takes a few seconds; the axes must be homed again afterwards."), tr("Reload"),
            onOk = { ask = null; onAction("firmware_restart", tr("Klipper is reloading")) }, onDismiss = { ask = null })
        return
    }
    val printing = p.state == "printing"
    val paused = p.state == "paused"
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        if (printing || paused) Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            if (printing) SecondaryButton(tr("Pause"), { onAction("pause", tr("Paused")) }, Modifier.weight(1f))
            if (paused) PrimaryButton(tr("Resume"), { onAction("resume", tr("Running again")) }, Modifier.weight(1f))
            SecondaryButton(tr("Cancel"), { ask = "cancel" }, Modifier.weight(1f))
        }
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
            SecondaryButton(tr("Tune"), onTune, Modifier.weight(1f))
            HoldButton(tr("Emergency stop (hold)"), Modifier.weight(1f)) { ask = "emergency_stop" }
        }
    }
    when (ask) {
        "cancel" -> ConfirmDialog(tr("Cancel the print?"),
            "${p.file?.removeSuffix(".gcode") ?: tr("Running print")}${p.progress?.let { " · ${(it * 100).roundToInt()} %" } ?: ""}. " +
                tr("A cancelled print cannot be resumed."), tr("Cancel print"),
            onOk = { ask = null; onAction("cancel", tr("Print cancelled")) }, onDismiss = { ask = null })
        "emergency_stop" -> ConfirmDialog(tr("Trigger the emergency stop?"),
            if (p.canRestart) tr("Stops all motors and heaters at once. Reload Klipper afterwards (the button appears here).")
            else tr("Stops all motors and heaters at once. Afterwards switch the printer off and on."),
            tr("Emergency stop"), onOk = { ask = null; onAction("emergency_stop", tr("Emergency stop triggered")) }, onDismiss = { ask = null })
    }
}

@Composable
private fun ConfirmDialog(title: String, text: String, ok: String, onOk: () -> Unit, onDismiss: () -> Unit) {
    AlertDialog(onDismissRequest = onDismiss, containerColor = K.Surface,
        title = { Text(title) }, text = { Text(text) },
        confirmButton = { TextButton(onClick = onOk) { Text(ok, color = K.DangerText) } },
        dismissButton = { TextButton(onClick = onDismiss) { Text(tr("Back")) } })
}

/** Triggers only after being held for HOLD_MS; the bar shows the progress. */
@Composable
private fun HoldButton(label: String, modifier: Modifier, onHeld: () -> Unit) {
    val progress = remember { Animatable(0f) }
    val scope = rememberCoroutineScope()
    Box(
        modifier.height(48.dp).clip(RoundedCornerShape(14.dp)).background(K.DangerSoft)
            .border(1.dp, K.DangerLine, RoundedCornerShape(14.dp))
            .semantics { role = Role.Button; contentDescription = tr("{label} – hold for 2 seconds", "label" to label) }
            .pointerInput(Unit) {
                detectTapGestures(onPress = {
                    val job = scope.launch {
                        progress.snapTo(0f)
                        progress.animateTo(1f, tween(HOLD_MS, easing = LinearEasing))
                        progress.snapTo(0f)
                        onHeld()
                    }
                    tryAwaitRelease()
                    if (job.isActive) { job.cancel(); scope.launch { progress.snapTo(0f) } }
                })
            },
        contentAlignment = Alignment.Center,
    ) {
        Box(Modifier.align(Alignment.CenterStart).fillMaxHeight().fillMaxWidth(progress.value).background(K.Danger.copy(alpha = 0.35f)))
        Text(label, style = MaterialTheme.typography.labelLarge, color = K.DangerText)
    }
}

// ====================================================================== tune
@Composable
private fun TuneSlider(label: String, value: Float, range: ClosedFloatingPointRange<Float>, steps: Int,
                       presets: List<Int> = emptyList(), onChange: (Float) -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
        Row {
            Text(label, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1f))
            Text("${value.roundToInt()} %", fontFamily = PlexMono, style = MaterialTheme.typography.bodyMedium)
        }
        Slider(value, onChange, valueRange = range, steps = steps,
            colors = SliderDefaults.colors(thumbColor = K.Accent, activeTrackColor = K.Accent, inactiveTrackColor = K.Surface2,
                activeTickColor = Color.Transparent, inactiveTickColor = Color.Transparent))
        if (presets.isNotEmpty()) Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            presets.forEach { v -> TextButton(onClick = { onChange(v.toFloat()) }) { Text("$v %", color = if (value.roundToInt() == v) K.Accent else K.Muted) } }
        }
    }
}

/** Speed, flow, fans, target temperatures - only what was changed is sent. */
@Composable
fun TuneSheet(p: Printer, onApply: (JsonObject) -> Unit) {
    val fans = p.fans.associateBy { it.key }
    val initSpeed = ((p.speedFactor ?: 1.0) * 100).toFloat()
    val initFlow = ((p.flowFactor ?: 1.0) * 100).toFloat()
    var speed by remember { mutableFloatStateOf(initSpeed) }
    var flow by remember { mutableFloatStateOf(initFlow) }
    val fanInit = fans.mapValues { (it.value.speed * 100).toFloat() }
    val fanVals = remember { fanInit.toMutableMap().let { m -> mutableStateOf(m.toMap()) } }
    val nozzleInit = (p.nozzle?.target ?: 0.0).roundToInt().toString()
    val bedInit = (p.bed?.target ?: 0.0).roundToInt().toString()
    var nozzle by remember { mutableStateOf(nozzleInit) }
    var bed by remember { mutableStateOf(bedInit) }
    var confirmHot by remember { mutableStateOf(false) }
    val n = nozzle.toIntOrNull()
    val b = bed.toIntOrNull()
    val badTemp = n == null || n !in 0..300 || b == null || b !in 0..110

    fun body(confirm: Boolean): JsonObject {
        val m = mutableMapOf<String, kotlinx.serialization.json.JsonElement>()
        if (speed.roundToInt() != initSpeed.roundToInt()) m["speed"] = JsonPrimitive(speed.roundToInt())
        if (flow.roundToInt() != initFlow.roundToInt()) m["flow"] = JsonPrimitive(flow.roundToInt())
        val f = fanVals.value.filter { (k, v) -> v.roundToInt() != fanInit[k]?.roundToInt() }
            .mapValues { JsonPrimitive(it.value.roundToInt()) }
        if (f.isNotEmpty()) m["fans"] = JsonObject(f)
        if (nozzle != nozzleInit && n != null) m["nozzle"] = JsonPrimitive(n)
        if (bed != bedInit && b != null) m["bed"] = JsonPrimitive(b)
        if (confirm) m["confirm"] = JsonPrimitive(true)
        return JsonObject(m)
    }
    val changes = body(false)

    Column(Modifier.fillMaxWidth().verticalScroll(rememberScrollState()).padding(horizontal = 20.dp).padding(bottom = 28.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Text(tr("Tune"), style = MaterialTheme.typography.titleLarge)
        TuneSlider(tr("Speed"), speed, 50f..200f, 29, listOf(50, 100, 150)) { speed = it }
        TuneSlider(tr("Flow"), flow, 90f..110f, 19, listOf(95, 100, 105)) { flow = it }
        listOf("part" to tr("Part fan"), "box" to tr("Enclosure fan"), "filter" to tr("Air filter")).forEach { (k, label) ->
            if (fans.containsKey(k)) TuneSlider(label, fanVals.value[k] ?: 0f, 0f..100f, 19) { v -> fanVals.value = fanVals.value + (k to v) }
        }
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            OutlinedTextField(nozzle, { nozzle = it.filter(Char::isDigit).take(3); confirmHot = false },
                label = { Text(tr("Nozzle °C (now {t})", "t" to (p.nozzle?.temp?.roundToInt() ?: "–"))) }, singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number), modifier = Modifier.weight(1f))
            OutlinedTextField(bed, { bed = it.filter(Char::isDigit).take(3) },
                label = { Text(tr("Bed °C (now {t})", "t" to (p.bed?.temp?.roundToInt() ?: "–"))) }, singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number), modifier = Modifier.weight(1f))
        }
        if (badTemp) Text(tr("Nozzle 0–300 °C, bed 0–110 °C"), color = K.DangerText, style = MaterialTheme.typography.bodySmall)
        if (confirmHot) Text(tr("Nozzle above 260 °C – tap once more to send it anyway."), color = K.DangerText,
            style = MaterialTheme.typography.bodySmall)
        Text(tr("Only what you change is sent. The slicer may set fans and temperatures again later."),
            style = MaterialTheme.typography.bodySmall, color = K.Muted)
        PrimaryButton(if (confirmHot) tr("Send anyway") else tr("Apply"), {
            if ((n ?: 0) > 260 && !confirmHot && changes.containsKey("nozzle")) confirmHot = true
            else onApply(body(confirmHot))
        }, Modifier.fillMaxWidth(), enabled = changes.isNotEmpty() && !badTemp)
        Box(Modifier.width(1.dp).height(1.dp))
    }
}

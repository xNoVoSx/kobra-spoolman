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

private const val HOLD_MS = 2000

/**
 * Drucksteuerung unter dem Druckstatus: Pause/Weiter, Abbrechen (Rueckfrage), Nachjustieren, Not-Aus
 * (2 s halten + Rueckfrage; danach Drucker aus/an, Rinkhals sperrt den Firmware-Neustart).
 */
@Composable
fun ControlRow(p: Printer, onAction: (String, String) -> Unit, onTune: () -> Unit) {
    if (p.state == "offline") return
    val printing = p.state == "printing"
    val paused = p.state == "paused"
    var ask by remember { mutableStateOf<String?>(null) }
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        if (printing || paused) Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            if (printing) SecondaryButton("Pause", { onAction("pause", "Pausiert") }, Modifier.weight(1f))
            if (paused) PrimaryButton("Weiter", { onAction("resume", "Läuft weiter") }, Modifier.weight(1f))
            SecondaryButton("Abbrechen", { ask = "cancel" }, Modifier.weight(1f))
        }
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
            SecondaryButton("Nachjustieren", onTune, Modifier.weight(1f))
            HoldButton("Not-Aus (halten)", Modifier.weight(1f)) { ask = "emergency_stop" }
        }
    }
    when (ask) {
        "cancel" -> ConfirmDialog("Druck abbrechen?",
            "${p.file?.removeSuffix(".gcode") ?: "Laufender Druck"}${p.progress?.let { " · ${(it * 100).roundToInt()} %" } ?: ""}. " +
                "Ein abgebrochener Druck lässt sich nicht fortsetzen.", "Druck abbrechen",
            onOk = { ask = null; onAction("cancel", "Druck abgebrochen") }, onDismiss = { ask = null })
        "emergency_stop" -> ConfirmDialog("Not-Aus auslösen?",
            "Stoppt sofort alle Motoren und Heizungen. Danach muss der Drucker aus- und wieder eingeschaltet werden.",
            "Not-Aus", onOk = { ask = null; onAction("emergency_stop", "Not-Aus ausgelöst") }, onDismiss = { ask = null })
    }
}

@Composable
private fun ConfirmDialog(title: String, text: String, ok: String, onOk: () -> Unit, onDismiss: () -> Unit) {
    AlertDialog(onDismissRequest = onDismiss, containerColor = K.Surface,
        title = { Text(title) }, text = { Text(text) },
        confirmButton = { TextButton(onClick = onOk) { Text(ok, color = K.DangerText) } },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Zurück") } })
}

/** Loest erst aus, wenn HOLD_MS lang gedrueckt gehalten wurde; der Balken zeigt den Fortschritt. */
@Composable
private fun HoldButton(label: String, modifier: Modifier, onHeld: () -> Unit) {
    val progress = remember { Animatable(0f) }
    val scope = rememberCoroutineScope()
    Box(
        modifier.height(48.dp).clip(RoundedCornerShape(14.dp)).background(K.DangerSoft)
            .border(1.dp, K.DangerLine, RoundedCornerShape(14.dp))
            .semantics { role = Role.Button; contentDescription = "$label – 2 Sekunden gedrückt halten" }
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

// ====================================================================== Nachjustieren
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

/** Tempo, Fluss, Luefter, Solltemperaturen - gesendet wird nur, was geaendert wurde. */
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
        Text("Nachjustieren", style = MaterialTheme.typography.titleLarge)
        TuneSlider("Tempo", speed, 50f..200f, 29, listOf(50, 100, 150)) { speed = it }
        TuneSlider("Fluss", flow, 90f..110f, 19, listOf(95, 100, 105)) { flow = it }
        listOf("part" to "Bauteillüfter", "box" to "Gehäuselüfter", "filter" to "Luftfilter").forEach { (k, label) ->
            if (fans.containsKey(k)) TuneSlider(label, fanVals.value[k] ?: 0f, 0f..100f, 19) { v -> fanVals.value = fanVals.value + (k to v) }
        }
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            OutlinedTextField(nozzle, { nozzle = it.filter(Char::isDigit).take(3); confirmHot = false },
                label = { Text("Düse °C (ist ${p.nozzle?.temp?.roundToInt() ?: "–"})") }, singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number), modifier = Modifier.weight(1f))
            OutlinedTextField(bed, { bed = it.filter(Char::isDigit).take(3) },
                label = { Text("Bett °C (ist ${p.bed?.temp?.roundToInt() ?: "–"})") }, singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number), modifier = Modifier.weight(1f))
        }
        if (badTemp) Text("Düse 0–300 °C, Bett 0–110 °C", color = K.DangerText, style = MaterialTheme.typography.bodySmall)
        if (confirmHot) Text("Düse über 260 °C – noch einmal tippen, um es trotzdem zu senden.", color = K.DangerText,
            style = MaterialTheme.typography.bodySmall)
        Text("Gesendet wird nur, was du änderst. Der Slicer setzt Lüfter und Temperaturen evtl. später wieder.",
            style = MaterialTheme.typography.bodySmall, color = K.Muted)
        PrimaryButton(if (confirmHot) "Trotzdem senden" else "Übernehmen", {
            if ((n ?: 0) > 260 && !confirmHot && changes.containsKey("nozzle")) confirmHot = true
            else onApply(body(confirmHot))
        }, Modifier.fillMaxWidth(), enabled = changes.isNotEmpty() && !badTemp)
        Box(Modifier.width(1.dp).height(1.dp))
    }
}

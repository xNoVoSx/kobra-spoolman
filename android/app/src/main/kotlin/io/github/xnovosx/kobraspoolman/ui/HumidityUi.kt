package io.github.xnovosx.kobraspoolman.ui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.unit.dp
import io.github.xnovosx.kobraspoolman.data.HumidityData
import io.github.xnovosx.kobraspoolman.data.SpoolMoistureFull
import io.github.xnovosx.kobraspoolman.ui.theme.K
import io.github.xnovosx.kobraspoolman.ui.theme.PlexMono
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.jsonPrimitive
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

private val SOURCE = mapOf("auto" to "Automatik", "hand" to "von Hand", "plan" to "geplant", "spule" to "Spule eingelegt",
    "drucker" to "Display/Mainsail", "unbekannt" to "schon vorher")
private fun JsonArray.num(i: Int): Double? = getOrNull(i)?.jsonPrimitive?.doubleOrNull
private fun time(t: Double, long: Boolean = false): String =
    SimpleDateFormat(if (long) "dd.MM. HH:mm" else "HH:mm", Locale.GERMANY).format(Date((t * 1000).toLong()))
private fun dur(min: Double): String = if (min >= 90) String.format(Locale.GERMANY, "%.1f h", min / 60) else "${min.toInt()} min"

/** Feuchte-Verlauf der ACE mit Trocknungen (im Trockner-Fenster). */
@Composable
fun HumiditySection(load: suspend (Int) -> HumidityData?) {
    var hours by remember { mutableIntStateOf(24) }
    var d by remember { mutableStateOf<HumidityData?>(null) }
    LaunchedEffect(hours) {
        while (isActive) { d = load(hours) ?: d; delay(60_000) }
    }
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        SectionLabel("Feuchte-Verlauf", Modifier.padding(top = 12.dp))
        Segmented(listOf("6" to "6 h", "24" to "24 h", "168" to "7 Tage", "720" to "30 Tage"), hours.toString()) { hours = it.toInt() }
        val data = d
        if (data == null) {
            Text("lädt …", color = K.Muted)
        } else if (data.points.isEmpty()) {
            Text("Noch kein Verlauf – die Bridge zeichnet ab jetzt jede Minute auf.", style = MaterialTheme.typography.bodySmall, color = K.Muted)
        } else {
            HumidityChart(data, hours)
            Text("Gelb: Feuchte · Grau: ACE-Temperatur · Rot: Soll beim Trocknen · Flächen: Trocknung / Druck",
                style = MaterialTheme.typography.bodySmall, color = K.Muted)
        }
        data?.sessions?.take(6)?.forEach { s ->
            Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(14.dp)).background(K.Sunken).padding(12.dp),
                verticalArrangement = Arrangement.spacedBy(2.dp)) {
                val temps = s.temps.mapNotNull { it.num(1)?.toInt() }.joinToString(" → ")
                Text("${time(s.start, true)} · ${if (s.running) "läuft" else dur((s.minutes ?: 0).toDouble())} · $temps °C · " +
                    (SOURCE[s.source] ?: s.source), fontFamily = PlexMono, style = MaterialTheme.typography.bodySmall)
                Text(s.reason + (s.endReason?.let { " → $it" } ?: ""), style = MaterialTheme.typography.bodySmall, color = K.Muted)
                Text("Feuchte ${s.humidityStart?.toInt() ?: "?"} %" + if (s.running) "" else " → ${s.humidityEnd?.toInt() ?: "?"} %",
                    style = MaterialTheme.typography.bodySmall, color = K.Muted)
            }
        }
    }
}

@Composable
private fun HumidityChart(d: HumidityData, hours: Int) {
    val now = System.currentTimeMillis() / 1000.0
    val t0 = now - hours * 3600.0
    val pts = d.points
    val hMax = maxOf(40.0, (pts.mapNotNull { it.num(1) }.maxOrNull() ?: 0.0) + 5)
    val accent = K.Accent
    val muted = K.Muted
    val line = K.Line
    Box(Modifier.fillMaxWidth().height(180.dp).clip(RoundedCornerShape(12.dp)).background(Color(0xFF0B0C0E))) {
        Canvas(Modifier.fillMaxWidth().height(180.dp).padding(8.dp)) {
            val w = size.width
            val h = size.height
            fun x(t: Double) = ((t - t0) / (now - t0) * w).toFloat()
            fun yh(v: Double) = ((1 - v / hMax) * h).toFloat()
            fun yt(c: Double) = ((1 - (c - 15) / 60) * h).toFloat()
            d.prints.forEach { p ->
                val a = x(maxOf(p.start, t0))
                drawRect(line.copy(alpha = 0.5f), Offset(a, 0f), Size(maxOf(1f, x(minOf(p.end, now)) - a), h))
            }
            d.sessions.forEach { s ->
                val a = x(maxOf(s.start, t0))
                drawRect(accent.copy(alpha = 0.16f), Offset(a, 0f), Size(maxOf(2f, x(minOf(s.end ?: now, now)) - a), h))
            }
            listOf(0.0, 20.0, 40.0, 60.0).filter { it <= hMax }.forEach { v ->
                drawLine(line, Offset(0f, yh(v)), Offset(w, yh(v)), 1f)
            }
            val dash = PathEffect.dashPathEffect(floatArrayOf(10f, 8f))
            d.automation.startAbove?.let { drawLine(accent.copy(alpha = if (d.automation.enabled) 0.8f else 0.3f), Offset(0f, yh(it)), Offset(w, yh(it)), 2f, pathEffect = dash) }
            d.automation.stopBelow?.let { drawLine(K.Ok.copy(alpha = if (d.automation.enabled) 0.8f else 0.3f), Offset(0f, yh(it)), Offset(w, yh(it)), 2f, pathEffect = dash) }
            fun path(k: Int, y: (Double) -> Float, onlyDrying: Boolean = false): Path {
                val p = Path()
                var started = false
                pts.forEach { a ->
                    val t = a.num(0) ?: return@forEach
                    val v = a.num(k)
                    if (v == null || (onlyDrying && (a.num(4) ?: 0.0) < 0.5)) { started = false; return@forEach }
                    if (!started) p.moveTo(x(t), y(v)) else p.lineTo(x(t), y(v))
                    started = true
                }
                return p
            }
            drawPath(path(2, ::yt), muted, style = Stroke(2f))
            drawPath(path(3, ::yt, onlyDrying = true), K.Danger, style = Stroke(3f, pathEffect = PathEffect.dashPathEffect(floatArrayOf(8f, 6f))))
            drawPath(path(1, ::yh), accent, style = Stroke(4f))
        }
        Text("${hMax.toInt()} %", style = MaterialTheme.typography.labelSmall, color = K.Muted, modifier = Modifier.padding(6.dp))
    }
}

/** Feuchte einer Spule auf der Spulenkarte. */
@Composable
fun SpoolMoistureSection(spoolId: Int, canWrite: Boolean, load: suspend (Int) -> SpoolMoistureFull?,
                         onDried: (Int, Double, () -> Unit) -> Unit) {
    var m by remember { mutableStateOf<SpoolMoistureFull?>(null) }
    var tick by remember { mutableIntStateOf(0) }
    var form by remember { mutableStateOf(false) }
    LaunchedEffect(spoolId, tick) { m = load(spoolId) }
    val s = m ?: return
    val (word, color) = when (s.state) {
        "ok" -> "trocken" to K.Ok
        "soon" -> "bald trocknen" to K.Accent
        "wet" -> "trocknen empfohlen" to K.Danger
        else -> "unbekannt – noch kein Verlauf" to K.Muted
    }
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        SectionLabel("Feuchte", Modifier.padding(top = 12.dp))
        Row {
            Text(word, style = MaterialTheme.typography.bodyLarge, color = color, modifier = Modifier.weight(1f))
            Text(s.score?.let { "$it %" } ?: "–", fontFamily = PlexMono)
        }
        Box(Modifier.fillMaxWidth().height(6.dp).clip(RoundedCornerShape(3.dp)).background(K.Sunken)) {
            Box(Modifier.fillMaxWidth(minOf(1f, (s.score ?: 0) / 200f)).height(6.dp).background(color))
        }
        val p = s.params
        Text(listOfNotNull(
            s.where?.let { "Ort: $it" },
            s.lastDried?.let { "zuletzt getrocknet ${time(it.at, true)}" + (it.temp?.let { t -> " · ${t.toInt()} °C" } ?: "") },
            if (s.needsDrying) "jetzt nötig ~${String.format(Locale.GERMANY, "%.1f", s.hoursNeeded ?: p.dryHours)} h bei ${p.dryTemp} °C" else null,
            "${p.material}: offen bis trocknen ${String.format(Locale.GERMANY, "%.1f", p.openDays)} Tage (50 % rF)",
        ).joinToString("\n"), style = MaterialTheme.typography.bodySmall, color = K.Muted)
        if (canWrite) {
            if (form) {
                var temp by remember { mutableStateOf(p.dryTemp?.toString() ?: "") }
                var hrs by remember { mutableStateOf(String.format(Locale.GERMANY, "%.0f", p.dryHours)) }
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    NumField("Temperatur (°C)", temp, { temp = it }, Modifier.weight(1f))
                    NumField("Dauer (h)", hrs, { hrs = it }, Modifier.weight(1f))
                }
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    PrimaryButton("Speichern", {
                        onDried(temp.toIntOrNull() ?: 0, hrs.replace(',', '.').toDoubleOrNull() ?: 0.0) { form = false; tick++ }
                    }, Modifier.weight(1f))
                    SecondaryButton("Abbrechen", { form = false }, Modifier.weight(1f))
                }
            } else {
                SecondaryButton("Außerhalb getrocknet …", { form = true }, Modifier.fillMaxWidth())
            }
        }
    }
}

package io.github.xnovosx.kobraspoolman.ui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
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
import io.github.xnovosx.kobraspoolman.data.tr
import io.github.xnovosx.kobraspoolman.data.I18n

// keys: stable API codes of the bridge (dryer.py)
private val SOURCE get() = mapOf("auto" to tr("Automatic"), "hand" to tr("by hand"), "plan" to tr("scheduled"), "spule" to tr("Spool inserted"),
    "drucker" to tr("Display/Mainsail"), "unbekannt" to tr("already running"))
private fun JsonArray.num(i: Int): Double? = getOrNull(i)?.jsonPrimitive?.doubleOrNull
private fun time(t: Double, long: Boolean = false): String =
    SimpleDateFormat(if (!long) "HH:mm" else if (I18n.lang == "de") "dd.MM. HH:mm" else "d MMM HH:mm", I18n.locale).format(Date((t * 1000).toLong()))
private fun dur(min: Double): String = if (min >= 90) Format.decimal(min / 60, 1) + " h" else "${min.toInt()} min"

/** Humidity history of the ACE with drying runs (in the dryer sheet). */
@Composable
fun HumiditySection(load: suspend (Int) -> HumidityData?, discard: ((String, () -> Unit) -> Unit)? = null) {
    var hours by remember { mutableIntStateOf(24) }
    var rev by remember { mutableIntStateOf(0) }
    var d by remember { mutableStateOf<HumidityData?>(null) }
    var ask by remember { mutableStateOf<String?>(null) }
    LaunchedEffect(hours, rev) {
        while (isActive) { d = load(hours) ?: d; delay(60_000) }
    }
    ask?.let { id ->
        AlertDialog(onDismissRequest = { ask = null }, containerColor = K.Surface,
            title = { Text(tr("Discard this drying run?")) },
            text = { Text(tr("The spools of this run go back to the moisture estimate from before it (also in Spoolman). Use it when the run did not really dry, e.g. with the lid open.")) },
            confirmButton = { TextButton(onClick = { ask = null; discard?.invoke(id) { rev++ } }) { Text(tr("Discard"), color = K.Danger) } },
            dismissButton = { TextButton(onClick = { ask = null }) { Text(tr("Back")) } })
    }
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        SectionLabel(tr("Humidity history"), Modifier.padding(top = 12.dp))
        Segmented(listOf("6" to "6 h", "24" to "24 h", "168" to tr("7 days"), "720" to tr("30 days")), hours.toString()) { hours = it.toInt() }
        val data = d
        if (data == null) {
            Text(tr("loading …"), color = K.Muted)
        } else if (data.points.isEmpty()) {
            Text(tr("No history yet – the bridge records every minute from now on."), style = MaterialTheme.typography.bodySmall, color = K.Muted)
        } else {
            HumidityChart(data, hours)
            Text(tr("Yellow: humidity · grey: ACE temperature · red: target while drying · areas: drying / print"),
                style = MaterialTheme.typography.bodySmall, color = K.Muted)
        }
        data?.sessions?.take(6)?.forEach { s ->
            Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(14.dp)).background(K.Sunken).padding(12.dp),
                verticalArrangement = Arrangement.spacedBy(2.dp)) {
                val temps = s.temps.mapNotNull { it.num(1)?.toInt() }.joinToString(" → ")
                Text("${time(s.start, true)} · ${if (s.running) tr("running") else dur((s.minutes ?: 0).toDouble())} · $temps °C · " +
                    (SOURCE[s.source] ?: s.source), fontFamily = PlexMono, style = MaterialTheme.typography.bodySmall)
                Text(s.reason + (s.endReason?.let { " → $it" } ?: ""), style = MaterialTheme.typography.bodySmall, color = K.Muted)
                Text(tr("Humidity {h} %", "h" to (s.humidityStart?.toInt() ?: "?")) + if (s.running) "" else " → ${s.humidityEnd?.toInt() ?: "?"} %",
                    style = MaterialTheme.typography.bodySmall, color = K.Muted)
                val lid = when {
                    s.lidOpenNow -> tr("lid open?")
                    (s.lidMinutes ?: 0) > 0 -> tr("{min} min too cold", "min" to s.lidMinutes!!)
                    else -> null
                }
                if (lid != null || s.discarded != null || (discard != null && !s.running)) {
                    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        lid?.let { Text(it, style = MaterialTheme.typography.bodySmall, color = K.Accent) }
                        if (s.discarded != null) Text(tr("discarded"), style = MaterialTheme.typography.bodySmall, color = K.Muted)
                        Spacer(Modifier.weight(1f))
                        if (discard != null && !s.running && s.discarded == null)
                            TextButton(onClick = { ask = s.id }) { Text(tr("Discard"), color = K.Muted) }
                    }
                }
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

/** Moisture of a spool on the spool card. */
@Composable
fun SpoolMoistureSection(spoolId: Int, canWrite: Boolean, load: suspend (Int) -> SpoolMoistureFull?,
                         onDried: (Int, Double, () -> Unit) -> Unit) {
    var m by remember { mutableStateOf<SpoolMoistureFull?>(null) }
    var tick by remember { mutableIntStateOf(0) }
    var form by remember { mutableStateOf(false) }
    LaunchedEffect(spoolId, tick) { m = load(spoolId) }
    val s = m ?: return
    val (word, color) = when (s.state) {
        "ok" -> tr("dry") to K.Ok
        "soon" -> tr("dry soon") to K.Accent
        "wet" -> tr("drying recommended") to K.Danger
        else -> tr("unknown – no history yet") to K.Muted
    }
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        SectionLabel(tr("Humidity"), Modifier.padding(top = 12.dp))
        Row {
            Text(word, style = MaterialTheme.typography.bodyLarge, color = color, modifier = Modifier.weight(1f))
            Text(s.score?.let { "$it %" } ?: "–", fontFamily = PlexMono)
        }
        Box(Modifier.fillMaxWidth().height(6.dp).clip(RoundedCornerShape(3.dp)).background(K.Sunken)) {
            Box(Modifier.fillMaxWidth(minOf(1f, (s.score ?: 0) / 200f)).height(6.dp).background(color))
        }
        val p = s.params
        Text(listOfNotNull(
            s.where?.let { tr("Place: {where}", "where" to it) },
            s.lastDried?.let { tr("last dried {when}", "when" to time(it.at, true)) + (it.temp?.let { t -> " · ${t.toInt()} °C" } ?: "") },
            if (s.needsDrying) tr("needed now ~{hours} h at {temp} °C", "hours" to Format.decimal(s.hoursNeeded ?: p.dryHours, 1), "temp" to p.dryTemp) else null,
            p.material + ": " + tr("open until drying {days} days (50 % RH)", "days" to Format.decimal(p.openDays, 1)),
        ).joinToString("\n"), style = MaterialTheme.typography.bodySmall, color = K.Muted)
        if (canWrite) {
            if (form) {
                var temp by remember { mutableStateOf(p.dryTemp?.toString() ?: "") }
                var hrs by remember { mutableStateOf(Format.decimal(p.dryHours, 0)) }
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    NumField(tr("Temperature (°C)"), temp, { temp = it }, Modifier.weight(1f))
                    NumField(tr("Duration (h)"), hrs, { hrs = it }, Modifier.weight(1f))
                }
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    PrimaryButton(tr("Save"), {
                        onDried(temp.toIntOrNull() ?: 0, hrs.replace(',', '.').toDoubleOrNull() ?: 0.0) { form = false; tick++ }
                    }, Modifier.weight(1f))
                    SecondaryButton(tr("Cancel"), { form = false }, Modifier.weight(1f))
                }
            } else {
                SecondaryButton(tr("Dried elsewhere …"), { form = true }, Modifier.fillMaxWidth())
            }
        }
    }
}

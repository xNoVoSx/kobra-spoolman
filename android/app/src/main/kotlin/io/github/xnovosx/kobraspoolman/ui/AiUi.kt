package io.github.xnovosx.kobraspoolman.ui

import android.graphics.BitmapFactory
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
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
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.unit.dp
import io.github.xnovosx.kobraspoolman.data.VisionEvent
import io.github.xnovosx.kobraspoolman.data.VisionFull
import io.github.xnovosx.kobraspoolman.ui.theme.K
import io.github.xnovosx.kobraspoolman.ui.theme.PlexMono
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import java.util.Locale

private val LEVEL = mapOf("ok" to "unauffällig", "warn" to "verdächtig", "fail" to "Fehldruck?")
private fun n2(v: Double?) = v?.let { String.format(Locale.GERMANY, "%.2f", it) } ?: "–"

/**
 * KI-Seite (Mehr -> KI): Zustand, die wichtigsten Einstellungen, "diesen Druck nicht ueberwachen" und die
 * Ereignisse mit Bild und Bewertung. Bereiche zeichnen und die Bildersammlung gibt es im KI-Tab der Weboberflaeche.
 */
@Composable
fun AiScreen(padding: androidx.compose.foundation.layout.PaddingValues, vm: AppViewModel, onBack: () -> Unit) {
    var v by remember { mutableStateOf<VisionFull?>(null) }
    var tick by remember { mutableIntStateOf(0) }
    val reload = { tick++ }
    LaunchedEffect(tick) {
        while (isActive) {
            v = vm.vision() ?: v
            delay(5_000)
        }
    }
    fun set(build: kotlinx.serialization.json.JsonObjectBuilder.() -> Unit) = vm.visionSettings(buildJsonObject(build)) { reload() }

    LazyColumn(Modifier.fillMaxSize().background(K.Ground), contentPadding = listPadding(padding),
        verticalArrangement = Arrangement.spacedBy(12.dp)) {
        item { ScreenHeader("KI", onBack) }
        val s = v
        if (s == null) {
            item { Text("Lade …", color = K.Muted) }
            return@LazyColumn
        }
        if (!s.configured) {
            item { Hint("Der KI-Dienst ist nicht eingerichtet: im Stack kobra-vision aufnehmen und bei der Bridge VISION_URL setzen.") }
        }
        // ---- Zustand
        item {
            Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(18.dp)).background(K.Surface).padding(16.dp),
                verticalArrangement = Arrangement.spacedBy(6.dp)) {
                val learning = s.printing && s.prediction.frames < s.safeFrames
                val word = when {
                    !s.enabled -> "aus"
                    !s.printing -> "bereit"
                    s.muted -> "für diesen Druck stumm" + if (s.mutedReason == "false_alarm") " (Fehlalarm)" else ""
                    learning -> "lernt den Druck (${s.prediction.frames}/${s.safeFrames})"
                    else -> LEVEL[s.level] ?: s.level
                }
                Text(word, style = MaterialTheme.typography.titleLarge,
                    color = when { s.level == "fail" && !s.muted -> K.Danger; s.level == "warn" && !s.muted -> K.Accent; else -> K.Text })
                Text("Wert ${n2(s.score)} (ab 0,33 verdächtig, ab 0,67 Fehldruck)", fontFamily = PlexMono,
                    style = MaterialTheme.typography.bodyMedium)
                val prov = s.health.model?.provider?.removeSuffix("ExecutionProvider")
                Text(s.error ?: listOfNotNull(if (prov == "CUDA") "Grafikkarte" else prov,
                    s.ms?.let { "${it.toInt()} ms pro Bild" },
                    if (s.actionNow == "pause") "pausiert bei Fehldruck" else "meldet nur",
                    if (s.quietNow) "Ruhezeit" else null).joinToString(" · "),
                    style = MaterialTheme.typography.bodySmall, color = if (s.error != null) K.Danger else K.Muted)
                if (s.printing && s.enabled) {
                    SecondaryButton(if (s.muted) "Wieder überwachen" else "Diesen Druck nicht überwachen",
                        { vm.visionMute(!s.muted) { reload() } }, Modifier.fillMaxWidth())
                }
            }
        }
        // ---- Einstellungen
        item { SectionLabel("Einstellungen", Modifier.padding(top = 8.dp)) }
        item {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("KI-Überwachung", style = MaterialTheme.typography.bodyLarge, modifier = Modifier.weight(1f))
                Switch(s.settings.enabled, { on -> set { put("enabled", on) } }, enabled = s.configured)
            }
        }
        item {
            Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text("Empfindlichkeit (× ${String.format(Locale.GERMANY, "%.1f", s.settings.sensitivity)})",
                    style = MaterialTheme.typography.bodyMedium, color = K.Muted)
                val cur = when (s.settings.sensitivity) { 0.7 -> "low"; 1.0 -> "normal"; 1.5 -> "high"; else -> "" }
                Segmented(listOf("low" to "Niedrig", "normal" to "Normal", "high" to "Hoch"), cur) { k ->
                    set { put("sensitivity", mapOf("low" to 0.7, "normal" to 1.0, "high" to 1.5).getValue(k)) }
                }
            }
        }
        item {
            Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text("Bei Fehldruck", style = MaterialTheme.typography.bodyMedium, color = K.Muted)
                Segmented(listOf("warn" to "Nur melden", "pause" to "Pausieren"), s.settings.action) { k -> set { put("action", k) } }
            }
        }
        item {
            Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text("Alarm aufs Handy", style = MaterialTheme.typography.bodyMedium, color = K.Muted)
                Segmented(listOf("warn" to "Schon bei verdächtig", "fail" to "Erst bei Fehldruck"), s.settings.notify) { k ->
                    set { put("notify", k) }
                }
            }
        }
        item {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text("Nach KI-Pause Düse aus", style = MaterialTheme.typography.bodyLarge)
                    Text("Noch ungetestet am Kobra", style = MaterialTheme.typography.bodySmall, color = K.Muted)
                }
                Switch(s.settings.heaterOff, { on -> set { put("heater_off", on) } })
            }
        }
        item {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text("Ruhezeiten ${s.settings.quiet.start}–${s.settings.quiet.end}", style = MaterialTheme.typography.bodyLarge)
                    Text(if (s.settings.quiet.mode == "pause") "dann bei Fehldruck pausieren" else "dann nur Fehldruck melden",
                        style = MaterialTheme.typography.bodySmall, color = K.Muted)
                }
                Switch(s.settings.quiet.enabled, { on -> set { put("quiet", buildJsonObject { put("enabled", on) }) } })
            }
        }
        item {
            Hint("Uhrzeiten, Bildabstand, Lernzeit, ignorierte Bereiche und die Bildersammlung stellst du im KI-Tab der " +
                "Weboberfläche ein.")
        }
        // ---- Gedaechtnis
        item { SectionLabel("Gedächtnis", Modifier.padding(top = 8.dp)) }
        item {
            Text("Grundlinie ${n2(s.prediction.long)} aus ${s.prediction.lifetime} Bildern · Sammlung ${s.dataset.frames} Bilder " +
                "aus ${s.dataset.jobs} Drucken (${String.format(Locale.GERMANY, "%.1f", s.dataset.mb / 1024)} von " +
                "${String.format(Locale.GERMANY, "%.0f", s.dataset.limitGb)} GB) · ${s.dataset.labelled} gekennzeichnet",
                style = MaterialTheme.typography.bodySmall, color = K.Muted)
        }
        item { SectionLabel("Ereignisse", Modifier.padding(top = 8.dp)) }
        if (s.events.isEmpty()) item { Text("Noch keine Meldung der KI.", color = K.Muted) }
        items(s.events.take(20), key = { it.id }) { e -> AiEventCard(e, vm, onVerdict = { verdict -> vm.visionFeedback(e.id, verdict) { reload() } }) }
    }
}

@Composable
private fun AiEventCard(e: VisionEvent, vm: AppViewModel, onVerdict: (String) -> Unit) {
    var img by remember(e.id) { mutableStateOf<ImageBitmap?>(null) }
    LaunchedEffect(e.id) {
        img = vm.image("/api/vision/event/${e.id}.jpg")?.let { b ->
            runCatching { BitmapFactory.decodeByteArray(b, 0, b.size)?.asImageBitmap() }.getOrNull()
        }
    }
    Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(18.dp)).background(K.Surface).padding(12.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp)) {
        img?.let {
            Image(it, contentDescription = "Bild des Ereignisses", contentScale = ContentScale.Fit,
                modifier = Modifier.fillMaxWidth().aspectRatio(16f / 9f).clip(RoundedCornerShape(12.dp)))
        }
        Text((if (e.level == "fail") "Fehldruck" else "verdächtig") + " · Wert ${n2(e.score)}" + (if (e.paused) " · pausiert" else "") +
            " · " + Format.ago(e.at.toLong()), style = MaterialTheme.typography.bodyMedium,
            color = if (e.level == "fail") K.Danger else K.Accent)
        e.file?.let { Text(it.substringAfterLast('/'), style = MaterialTheme.typography.bodySmall, color = K.Muted) }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            val chosen = { k: String -> if (e.verdict == k) "✓ " else "" }
            SecondaryButton(chosen("false_alarm") + "Fehlalarm", { onVerdict("false_alarm") }, Modifier.weight(1f))
            SecondaryButton(chosen("confirmed") + "Stimmt", { onVerdict("confirmed") }, Modifier.weight(1f))
        }
    }
}

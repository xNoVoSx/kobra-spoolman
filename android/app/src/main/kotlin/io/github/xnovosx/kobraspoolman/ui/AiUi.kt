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
import io.github.xnovosx.kobraspoolman.data.tr

private val LEVEL get() = mapOf("ok" to tr("normal"), "warn" to tr("suspicious"), "fail" to tr("Failure?"))
private fun n2(v: Double?) = Format.decimal(v, 2)

/**
 * AI page (More -> AI): state, the main settings, "don't watch this print" and the events with image and rating.
 * Drawing areas and the image collection are in the AI tab of the web UI.
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
        item { ScreenHeader(tr("AI"), onBack) }
        val s = v
        if (s == null) {
            item { Text(tr("Loading …"), color = K.Muted) }
            return@LazyColumn
        }
        if (!s.configured) {
            item { Hint(tr("The AI service is not set up: add kobra-vision to the stack and set VISION_URL on the bridge.")) }
        }
        // ---- state
        item {
            Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(18.dp)).background(K.Surface).padding(16.dp),
                verticalArrangement = Arrangement.spacedBy(6.dp)) {
                val learning = s.printing && s.prediction.frames < s.safeFrames
                val word = when {
                    !s.enabled -> tr("off")
                    !s.printing -> tr("ready")
                    s.muted -> tr("muted for this print") + if (s.mutedReason == "false_alarm") " " + tr("(false alarm)") else ""
                    learning -> tr("learning the print ({n}/{total})", "n" to s.prediction.frames, "total" to s.safeFrames)
                    else -> LEVEL[s.level] ?: s.level
                }
                Text(word, style = MaterialTheme.typography.titleLarge,
                    color = when { s.level == "fail" && !s.muted -> K.Danger; s.level == "warn" && !s.muted -> K.Accent; else -> K.Text })
                Text(tr("Score {score} (suspicious from {low}, failure from {high})", "score" to n2(s.score), "low" to n2(0.33), "high" to n2(0.67)), fontFamily = PlexMono,
                    style = MaterialTheme.typography.bodyMedium)
                val prov = s.health.model?.provider?.removeSuffix("ExecutionProvider")
                Text(s.error ?: listOfNotNull(if (prov == "CUDA") tr("graphics card") else prov,
                    s.ms?.let { tr("{ms} ms per image", "ms" to it.toInt()) },
                    if (s.actionNow == "pause") tr("pauses on failure") else tr("notify only"),
                    if (s.quietNow) tr("quiet hours") else null).joinToString(" · "),
                    style = MaterialTheme.typography.bodySmall, color = if (s.error != null) K.Danger else K.Muted)
                if (s.printing && s.enabled) {
                    SecondaryButton(if (s.muted) tr("Watch again") else tr("Don't watch this print"),
                        { vm.visionMute(!s.muted) { reload() } }, Modifier.fillMaxWidth())
                }
            }
        }
        // ---- settings
        item { SectionLabel(tr("Settings"), Modifier.padding(top = 8.dp)) }
        item {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(tr("AI monitoring"), style = MaterialTheme.typography.bodyLarge, modifier = Modifier.weight(1f))
                Switch(s.settings.enabled, { on -> set { put("enabled", on) } }, enabled = s.configured)
            }
        }
        item {
            Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text(tr("Sensitivity (× {value})", "value" to Format.decimal(s.settings.sensitivity, 1)),
                    style = MaterialTheme.typography.bodyMedium, color = K.Muted)
                val cur = when (s.settings.sensitivity) { 0.7 -> "low"; 1.0 -> "normal"; 1.5 -> "high"; else -> "" }
                Segmented(listOf("low" to tr("Low"), "normal" to tr("Normal"), "high" to tr("High")), cur) { k ->
                    set { put("sensitivity", mapOf("low" to 0.7, "normal" to 1.0, "high" to 1.5).getValue(k)) }
                }
            }
        }
        item {
            Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text(tr("On failure"), style = MaterialTheme.typography.bodyMedium, color = K.Muted)
                Segmented(listOf("warn" to tr("Notify only"), "pause" to tr("Pause")), s.settings.action) { k -> set { put("action", k) } }
            }
        }
        item {
            Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text(tr("Alarm to the phone"), style = MaterialTheme.typography.bodyMedium, color = K.Muted)
                Segmented(listOf("warn" to tr("Already at suspicious"), "fail" to tr("Only at failure")), s.settings.notify) { k ->
                    set { put("notify", k) }
                }
            }
        }
        item {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text(tr("Nozzle off after an AI pause"), style = MaterialTheme.typography.bodyLarge)
                    Text(tr("Not yet tested on the Kobra"), style = MaterialTheme.typography.bodySmall, color = K.Muted)
                }
                Switch(s.settings.heaterOff, { on -> set { put("heater_off", on) } })
            }
        }
        item {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text(tr("Quiet hours {start}–{end}", "start" to s.settings.quiet.start, "end" to s.settings.quiet.end), style = MaterialTheme.typography.bodyLarge)
                    Text(if (s.settings.quiet.mode == "pause") tr("then pause on failure") else tr("then only report failures"),
                        style = MaterialTheme.typography.bodySmall, color = K.Muted)
                }
                Switch(s.settings.quiet.enabled, { on -> set { put("quiet", buildJsonObject { put("enabled", on) }) } })
            }
        }
        item {
            Hint(tr("Times, image interval, learning time, ignored areas and the image collection are set in the AI tab of the web UI."))
        }
        // ---- memory
        item { SectionLabel(tr("Memory"), Modifier.padding(top = 8.dp)) }
        item {
            Text(tr("Baseline {baseline} from {images} images · collection {frames} images from {jobs} prints ({used} of {limit} GB) · {labelled} labelled",
                "baseline" to n2(s.prediction.long), "images" to s.prediction.lifetime, "frames" to s.dataset.frames, "jobs" to s.dataset.jobs,
                "used" to Format.decimal(s.dataset.mb / 1024, 1), "limit" to Format.decimal(s.dataset.limitGb, 0), "labelled" to s.dataset.labelled),
                style = MaterialTheme.typography.bodySmall, color = K.Muted)
        }
        item { SectionLabel(tr("Events"), Modifier.padding(top = 8.dp)) }
        if (s.events.isEmpty()) item { Text(tr("No report from the AI yet."), color = K.Muted) }
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
            Image(it, contentDescription = tr("Image of the event"), contentScale = ContentScale.Fit,
                modifier = Modifier.fillMaxWidth().aspectRatio(16f / 9f).clip(RoundedCornerShape(12.dp)))
        }
        Text((if (e.level == "fail") tr("Failure") else tr("suspicious")) + " · " + tr("score {s}", "s" to n2(e.score)) + (if (e.paused) " · " + tr("paused") else "") +
            " · " + Format.ago(e.at.toLong()), style = MaterialTheme.typography.bodyMedium,
            color = if (e.level == "fail") K.Danger else K.Accent)
        e.file?.let { Text(it.substringAfterLast('/'), style = MaterialTheme.typography.bodySmall, color = K.Muted) }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            val chosen = { k: String -> if (e.verdict == k) "✓ " else "" }
            SecondaryButton(chosen("false_alarm") + tr("False alarm"), { onVerdict("false_alarm") }, Modifier.weight(1f))
            SecondaryButton(chosen("confirmed") + tr("Correct"), { onVerdict("confirmed") }, Modifier.weight(1f))
        }
    }
}

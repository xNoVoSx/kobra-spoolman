package io.github.xnovosx.kobraspoolman.ui

import android.graphics.BitmapFactory
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxScope
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LocalLifecycleOwner
import io.github.xnovosx.kobraspoolman.data.Heater
import io.github.xnovosx.kobraspoolman.data.PrintInfo
import io.github.xnovosx.kobraspoolman.data.Printer
import io.github.xnovosx.kobraspoolman.ui.theme.K
import io.github.xnovosx.kobraspoolman.ui.theme.PlexMono
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.withContext
import java.util.Locale
import kotlin.math.roundToInt

private fun decode(bytes: ByteArray?): ImageBitmap? =
    bytes?.let { runCatching { BitmapFactory.decodeByteArray(it, 0, it.size)?.asImageBitmap() }.getOrNull() }

/** Bild, das sich in einem festen Takt erneuert, solange es angezeigt wird. */
@Composable
private fun rememberLiveImage(path: String?, everyMs: Long, fetch: suspend (String) -> ByteArray?): ImageBitmap? {
    var img by remember(path) { mutableStateOf<ImageBitmap?>(null) }
    LaunchedEffect(path) {
        if (path == null) return@LaunchedEffect
        while (isActive) {
            decode(fetch(path))?.let { img = it }
            delay(everyMs)
        }
    }
    return img
}

/** Kamera live (Restream der Bridge) mit selbst gemessener Bildrate; bei Abbruch nach 5 s neu verbinden. */
@Composable
private fun rememberCamera(active: Boolean, stream: () -> Flow<ByteArray>): Triple<ImageBitmap?, Float?, String?> {
    var img by remember { mutableStateOf<ImageBitmap?>(null) }
    var fps by remember { mutableStateOf<Float?>(null) }
    var err by remember { mutableStateOf<String?>(null) }
    // App im Hintergrund: Stream trennen, damit die Bridge (und damit der Drucker) ihn schliessen kann
    val lifecycle by LocalLifecycleOwner.current.lifecycle.currentStateFlow.collectAsState()
    val on = active && lifecycle.isAtLeast(Lifecycle.State.STARTED)
    LaunchedEffect(on) {
        if (!on) { fps = null; return@LaunchedEffect }
        val times = ArrayDeque<Long>()
        while (isActive) {
            try {
                stream().collect { bytes ->
                    val bmp = withContext(Dispatchers.Default) { decode(bytes) } ?: return@collect
                    img = bmp
                    err = null
                    val now = System.nanoTime()
                    times.addLast(now)
                    while (times.size > 2 && now - times.first() > 3_000_000_000L) times.removeFirst()
                    if (times.size >= 2) fps = (times.size - 1) / ((times.last() - times.first()) / 1e9f)
                }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                err = e.message
            }
            fps = null
            delay(5_000)
        }
    }
    return Triple(img, fps, err)
}

/** Ein Wert der Druckerleiste: kleine Beschriftung, darunter der Wert. */
@Composable
private fun Stat(label: String, value: String, hot: Boolean = false) {
    Column {
        Text(label.uppercase(), style = MaterialTheme.typography.labelSmall, color = K.Muted)
        Text(value, fontFamily = PlexMono, style = MaterialTheme.typography.bodyMedium,
            color = if (hot) K.Accent else K.Text)
    }
}

private fun temp(h: Heater): String =
    if (h.target > 0) "${h.temp.roundToInt()}/${h.target.roundToInt()}°" else "${h.temp.roundToInt()}°"

private fun share(v: Double): String = if (v <= 0.0) "aus" else "${(v * 100).roundToInt()} %"

/** Druckerdaten unter dem Bild: Temperaturen, Luefter, Tempo, Fluss, Schicht (nur was der Drucker meldet). */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun MachineBar(p: Printer) {
    if (p.nozzle == null && p.bed == null && p.fans.isEmpty()) return
    FlowRow(Modifier.fillMaxWidth().padding(horizontal = 14.dp, vertical = 10.dp),
        horizontalArrangement = Arrangement.spacedBy(18.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        p.nozzle?.let { Stat("Düse", temp(it), hot = it.target > 0) }
        p.bed?.let { Stat("Bett", temp(it), hot = it.target > 0) }
        p.fans.forEach { Stat(it.name, share(it.speed)) }
        p.speedFactor?.let { Stat("Tempo", "${(it * 100).roundToInt()} %", hot = it != 1.0) }
        p.flowFactor?.let { Stat("Fluss", "${(it * 100).roundToInt()} %", hot = it != 1.0) }
        if (p.layer != null && p.layers != null) Stat("Schicht", "${p.layer} / ${p.layers}")
    }
}

/** Kleine Bildrate oben rechts im Kamerabild. */
@Composable
private fun BoxScope.FpsBadge(fps: Float?) {
    fps ?: return
    Text(if (fps < 10) "%.1f fps".format(Locale.GERMANY, fps) else "${fps.roundToInt()} fps",
        fontFamily = PlexMono, style = MaterialTheme.typography.labelSmall, color = Color.White,
        modifier = Modifier.align(Alignment.TopEnd).padding(8.dp).clip(RoundedCornerShape(6.dp))
            .background(Color(0x8C000000)).padding(horizontal = 7.dp, vertical = 2.dp))
}

/**
 * Druckansicht auf der Startseite: Modell (von der Bridge gerechnetes Bild der Druckdatei, alle 10 s neu)
 * oder Kamera (Restream der Bridge, nur gekoppelt). Tippen oeffnet das Vollbild; beide teilen sich eine
 * Verbindung zur Bridge.
 */
@Composable
fun PrintMedia(
    printer: Printer,
    canWrite: Boolean,
    fetch: suspend (String) -> ByteArray?,
    info: suspend () -> PrintInfo?,
    camera: () -> Flow<ByteArray>,
) {
    // Kamera ist die Hauptansicht; das Modell gibt es nur, solange gedruckt wird
    var chosen by rememberSaveable { mutableStateOf("camera") }
    val running = printer.state == "printing" || printer.state == "paused"
    val tab = if (running) chosen else "camera"
    var full by remember { mutableStateOf(false) }
    var meta by remember { mutableStateOf<PrintInfo?>(null) }
    LaunchedEffect(tab) {
        while (isActive && tab == "model") { meta = info(); delay(10_000) }
    }
    val modelPath = when {
        meta?.status == "ready" -> "/api/print/preview.png"
        meta?.thumbnail == true -> "/api/print/thumbnail.png"
        else -> null
    }
    val (camImg, fps, camErr) = rememberCamera(tab == "camera" && canWrite, camera)
    val modelImg = rememberLiveImage(if (tab == "model") modelPath else null, 10_000, fetch)
    val img = if (tab == "camera") camImg else modelImg
    Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(16.dp)).background(Color(0xFF0B0C0E))) {
        Row(Modifier.fillMaxWidth().background(Color(0x59000000)).padding(4.dp),
            verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(4.dp)) {
            (listOf("camera" to "Kamera") + if (running) listOf("model" to "Modell") else emptyList()).forEach { (k, label) ->
                Text(label, style = MaterialTheme.typography.labelMedium, color = if (tab == k) K.Text else K.Muted,
                    modifier = Modifier.clip(RoundedCornerShape(8.dp)).background(if (tab == k) K.Surface2 else Color.Transparent)
                        .clickable(role = Role.Tab) { chosen = k }.padding(horizontal = 12.dp, vertical = 8.dp))
            }
            Box(Modifier.weight(1f))
            val m = meta
            if (tab == "model" && printer.layer == null && m?.layer != null && m.layers > 0) {
                Text("Schicht ${m.layer} / ${m.layers}", fontFamily = PlexMono, style = MaterialTheme.typography.labelSmall,
                    color = K.Muted, modifier = Modifier.padding(end = 8.dp))
            }
        }
        Box(Modifier.fillMaxWidth().aspectRatio(16f / 10f).clickable(enabled = img != null) { full = true },
            contentAlignment = Alignment.Center) {
            if (img != null) {
                Image(img, if (tab == "camera") "Kamera" else "Vorschau der Druckdatei", Modifier.fillMaxSize(),
                    contentScale = ContentScale.Fit)
                if (tab == "camera") FpsBadge(fps)
            } else {
                Text(when {
                    tab == "camera" && !canWrite -> "Die Kamera sehen nur gekoppelte Geräte."
                    tab == "camera" -> camErr ?: "Kamera lädt …"
                    meta?.status == "loading" -> "Druckdatei wird geladen …"
                    else -> "Kein Druck – keine Vorschau"
                }, style = MaterialTheme.typography.bodySmall, color = K.Muted, modifier = Modifier.padding(16.dp))
            }
        }
        MachineBar(printer)
    }
    if (full) {
        Dialog(onDismissRequest = { full = false }, properties = DialogProperties(usePlatformDefaultWidth = false)) {
            Box(Modifier.fillMaxSize().background(Color.Black).clickable { full = false }, contentAlignment = Alignment.Center) {
                img?.let { Image(it, "Vollbild", Modifier.fillMaxSize(), contentScale = ContentScale.Fit) }
                if (tab == "camera") FpsBadge(fps)
                Box(Modifier.align(Alignment.BottomCenter).fillMaxWidth().background(Color(0xB3000000))) { MachineBar(printer) }
            }
        }
    }
}

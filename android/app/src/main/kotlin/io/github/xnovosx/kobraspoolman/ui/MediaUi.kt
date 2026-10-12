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
import kotlin.math.roundToInt
import io.github.xnovosx.kobraspoolman.data.tr

private fun decode(bytes: ByteArray?): ImageBitmap? =
    bytes?.let { runCatching { BitmapFactory.decodeByteArray(it, 0, it.size)?.asImageBitmap() }.getOrNull() }

/** Image that refreshes at a fixed interval while it is shown. */
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

/** Live camera (bridge restream) with a self-measured frame rate; reconnect after 5 s on a drop. */
@Composable
private fun rememberCamera(active: Boolean, stream: () -> Flow<ByteArray>): Triple<ImageBitmap?, Float?, String?> {
    var img by remember { mutableStateOf<ImageBitmap?>(null) }
    var fps by remember { mutableStateOf<Float?>(null) }
    var err by remember { mutableStateOf<String?>(null) }
    // app in the background: drop the stream so the bridge (and so the printer) can close it
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

/** A value of the printer bar: small label, the value below. */
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

private fun share(v: Double): String = if (v <= 0.0) tr("off") else "${(v * 100).roundToInt()} %"

/** Printer data below the image: temperatures, fans, speed, flow, layer (only what the printer reports). */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun MachineBar(p: Printer, inset: Boolean = true) {
    if (p.nozzle == null && p.bed == null && p.fans.isEmpty()) return
    FlowRow(Modifier.fillMaxWidth().then(if (inset) Modifier.padding(horizontal = 14.dp, vertical = 10.dp) else Modifier),
        horizontalArrangement = Arrangement.spacedBy(18.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        p.nozzle?.let { Stat(tr("Nozzle"), temp(it), hot = it.target > 0) }
        p.bed?.let { Stat(tr("Bed"), temp(it), hot = it.target > 0) }
        p.fans.forEach { Stat(it.name, share(it.speed)) }
        p.speedFactor?.let { Stat(tr("Speed"), "${(it * 100).roundToInt()} %", hot = it != 1.0) }
        p.flowFactor?.let { Stat(tr("Flow"), "${(it * 100).roundToInt()} %", hot = it != 1.0) }
        if (p.layer != null && p.layers != null) Stat(tr("Layer"), "${p.layer} / ${p.layers}")
    }
}

/** Small frame rate at the top right of the camera image. */
@Composable
private fun BoxScope.FpsBadge(fps: Float?) {
    fps ?: return
    Text(if (fps < 10) Format.decimal(fps.toDouble(), 1) + " fps" else "${fps.roundToInt()} fps",
        fontFamily = PlexMono, style = MaterialTheme.typography.labelSmall, color = Color.White,
        modifier = Modifier.align(Alignment.TopEnd).padding(8.dp).clip(RoundedCornerShape(6.dp))
            .background(Color(0x8C000000)).padding(horizontal = 7.dp, vertical = 2.dp))
}

/**
 * Print view on the home screen: model (image of the print file rendered by the bridge, every 10 s) or camera
 * (bridge restream, paired only). Tapping opens full screen; both share one connection to the bridge.
 */
@Composable
fun PrintMedia(
    printer: Printer,
    canWrite: Boolean,
    fetch: suspend (String) -> ByteArray?,
    info: suspend () -> PrintInfo?,
    camera: () -> Flow<ByteArray>,
    viewerUrl: String? = null,
) {
    // the camera is the main view; the model exists only while printing
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
            (listOf("camera" to tr("Camera")) + if (running) listOf("model" to tr("Model")) else emptyList()).forEach { (k, label) ->
                Text(label, style = MaterialTheme.typography.labelMedium, color = if (tab == k) K.Text else K.Muted,
                    modifier = Modifier.clip(RoundedCornerShape(8.dp)).background(if (tab == k) K.Surface2 else Color.Transparent)
                        .clickable(role = Role.Tab) { chosen = k }.padding(horizontal = 12.dp, vertical = 8.dp))
            }
            Box(Modifier.weight(1f))
            val m = meta
            if (tab == "model" && printer.layer == null && m?.layer != null && m.layers > 0) {
                Text(tr("Layer {layer} / {layers}", "layer" to m.layer, "layers" to m.layers), fontFamily = PlexMono, style = MaterialTheme.typography.labelSmall,
                    color = K.Muted, modifier = Modifier.padding(end = 8.dp))
            }
        }
        if (tab == "model" && viewerUrl != null) {
            // the bridge's 3D view (WebGL) - rotate, zoom, layer slider; full screen via the button below
            ModelWebView(viewerUrl, Modifier.fillMaxWidth().aspectRatio(4f / 3.4f))
            Text(tr("Full screen"), style = MaterialTheme.typography.labelMedium, color = K.Accent,
                modifier = Modifier.clickable(role = Role.Button) { full = true }.padding(12.dp))
        } else Box(Modifier.fillMaxWidth().aspectRatio(16f / 10f).clickable(enabled = img != null) { full = true },
            contentAlignment = Alignment.Center) {
            if (img != null) {
                Image(img, if (tab == "camera") tr("Camera") else tr("Preview of the print file"), Modifier.fillMaxSize(),
                    contentScale = ContentScale.Fit)
                if (tab == "camera") FpsBadge(fps)
            } else {
                Text(when {
                    tab == "camera" && !canWrite -> tr("Only paired devices see the camera.")
                    tab == "camera" -> camErr ?: tr("Camera loading …")
                    meta?.status == "loading" -> tr("Loading the print file …")
                    else -> tr("No print – no preview")
                }, style = MaterialTheme.typography.bodySmall, color = K.Muted, modifier = Modifier.padding(16.dp))
            }
        }
    }
    if (full) {
        Dialog(onDismissRequest = { full = false }, properties = DialogProperties(usePlatformDefaultWidth = false)) {
            if (tab == "model" && viewerUrl != null) {
                Box(Modifier.fillMaxSize().background(Color.Black)) {
                    ModelWebView(viewerUrl, Modifier.fillMaxSize())
                    Text(tr("Close"), style = MaterialTheme.typography.labelLarge, color = K.Accent,
                        modifier = Modifier.align(Alignment.TopEnd).clip(RoundedCornerShape(10.dp)).background(Color(0xCC000000))
                            .clickable(role = Role.Button) { full = false }.padding(14.dp))
                }
                return@Dialog
            }
            Box(Modifier.fillMaxSize().background(Color.Black).clickable { full = false }, contentAlignment = Alignment.Center) {
                img?.let { Image(it, tr("Full screen"), Modifier.fillMaxSize(), contentScale = ContentScale.Fit) }
                if (tab == "camera") FpsBadge(fps)
                Box(Modifier.align(Alignment.BottomCenter).fillMaxWidth().background(Color(0xB3000000))) { MachineBar(printer) }
            }
        }
    }
}

/**
 * 3D view of the print file: the bridge page /viewer (WebGL in the phone's browser). Touches go to the view
 * (rotate/zoom), not to the list behind it.
 */
@android.annotation.SuppressLint("SetJavaScriptEnabled", "ClickableViewAccessibility")
@Composable
fun ModelWebView(url: String, modifier: Modifier = Modifier) {
    androidx.compose.ui.viewinterop.AndroidView(
        factory = { ctx ->
            android.webkit.WebView(ctx).apply {
                // fixed size: without it the WebView measures its content, and a page with height 100 % collapses to 0
                layoutParams = android.view.ViewGroup.LayoutParams(android.view.ViewGroup.LayoutParams.MATCH_PARENT,
                    android.view.ViewGroup.LayoutParams.MATCH_PARENT)
                settings.javaScriptEnabled = true
                settings.domStorageEnabled = true
                setBackgroundColor(0xFF0B0C0E.toInt())
                setOnTouchListener { v, _ -> v.parent?.requestDisallowInterceptTouchEvent(true); false }
                loadUrl(url)
            }
        },
        update = { if (it.url != url) it.loadUrl(url) },
        onRelease = { it.destroy() },
        modifier = modifier,
    )
}


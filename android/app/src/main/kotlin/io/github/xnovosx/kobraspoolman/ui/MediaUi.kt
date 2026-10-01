package io.github.xnovosx.kobraspoolman.ui

import android.graphics.BitmapFactory
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
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
import io.github.xnovosx.kobraspoolman.data.PrintInfo
import io.github.xnovosx.kobraspoolman.ui.theme.K
import io.github.xnovosx.kobraspoolman.ui.theme.PlexMono
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive

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

/**
 * Druckansicht auf der Startseite: Modell (von der Bridge gerechnetes Bild der Druckdatei, alle 10 s neu)
 * oder Kamera (Einzelbilder ueber die Bridge, 1/s; nur gekoppelt). Tippen oeffnet das Vollbild.
 */
@Composable
fun PrintMedia(canWrite: Boolean, fetch: suspend (String) -> ByteArray?, info: suspend () -> PrintInfo?) {
    var tab by rememberSaveable { mutableStateOf("model") }
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
    val img = when (tab) {
        "camera" -> rememberLiveImage(if (canWrite) "/api/camera/snapshot.jpg" else null, 1_000, fetch)
        else -> rememberLiveImage(modelPath, 10_000, fetch)
    }
    Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(16.dp)).background(Color(0xFF0B0C0E))) {
        Row(Modifier.fillMaxWidth().background(Color(0x59000000)).padding(4.dp),
            verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(4.dp)) {
            listOf("model" to "Modell", "camera" to "Kamera").forEach { (k, label) ->
                Text(label, style = MaterialTheme.typography.labelMedium, color = if (tab == k) K.Text else K.Muted,
                    modifier = Modifier.clip(RoundedCornerShape(8.dp)).background(if (tab == k) K.Surface2 else Color.Transparent)
                        .clickable(role = Role.Tab) { tab = k }.padding(horizontal = 12.dp, vertical = 8.dp))
            }
            Box(Modifier.weight(1f))
            val m = meta
            if (tab == "model" && m?.layer != null && m.layers > 0) {
                Text("Schicht ${m.layer} / ${m.layers}", fontFamily = PlexMono, style = MaterialTheme.typography.labelSmall,
                    color = K.Muted, modifier = Modifier.padding(end = 8.dp))
            }
        }
        Box(Modifier.fillMaxWidth().aspectRatio(16f / 10f).clickable(enabled = img != null) { full = true },
            contentAlignment = Alignment.Center) {
            if (img != null) {
                Image(img, if (tab == "camera") "Kamera" else "Vorschau der Druckdatei", Modifier.fillMaxSize(),
                    contentScale = ContentScale.Fit)
            } else {
                Text(when {
                    tab == "camera" && !canWrite -> "Die Kamera sehen nur gekoppelte Geräte."
                    tab == "camera" -> "Kamera lädt …"
                    meta?.status == "loading" -> "Druckdatei wird geladen …"
                    else -> "Kein Druck – keine Vorschau"
                }, style = MaterialTheme.typography.bodySmall, color = K.Muted, modifier = Modifier.padding(16.dp))
            }
        }
    }
    if (full) {
        Dialog(onDismissRequest = { full = false }, properties = DialogProperties(usePlatformDefaultWidth = false)) {
            val big = when (tab) {
                "camera" -> rememberLiveImage("/api/camera/snapshot.jpg", 1_000, fetch)
                else -> img
            }
            Box(Modifier.fillMaxSize().background(Color.Black).clickable { full = false }, contentAlignment = Alignment.Center) {
                big?.let { Image(it, "Vollbild", Modifier.fillMaxSize(), contentScale = ContentScale.Fit) }
            }
        }
    }
}

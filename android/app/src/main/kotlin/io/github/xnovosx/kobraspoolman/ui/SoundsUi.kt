package io.github.xnovosx.kobraspoolman.ui

import android.content.Context
import android.content.Intent
import android.media.AudioAttributes
import android.media.MediaPlayer
import android.provider.Settings as AndroidSettings
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import io.github.xnovosx.kobraspoolman.monitor.EventKind
import io.github.xnovosx.kobraspoolman.monitor.Notifier
import io.github.xnovosx.kobraspoolman.ui.theme.K

/** Ein Ton zum Probehoeren: Name, wann er kommt, Kanal. */
private data class SoundRow(val kind: EventKind, val name: String, val whenText: String)

private val rows = listOf(
    SoundRow(EventKind.ALARM, "Alarm", "Fehler, Abbruch, Pause (nicht von dir), Farbwechsel hängt, Düse kühlt ab, " +
        "Drucker/Bridge weg, Spule reicht nicht"),
    SoundRow(EventKind.DONE, "Druck fertig", "Druck erfolgreich beendet"),
    SoundRow(EventKind.START, "Druck gestartet", "Ein Druck beginnt"),
    SoundRow(EventKind.LAYER, "Erste Schicht fertig", "Zeit für einen Blick aufs Bett"),
    SoundRow(EventKind.HINT, "Hinweis", "Unbekannter Tag, Slot ohne Material, Spoolman länger weg"),
)

/** Spielt einen Ton aus res/raw; der vorige wird gestoppt. */
private class SoundPlayer(private val context: Context) {
    private var player: MediaPlayer? = null

    fun play(kind: EventKind) {
        val res = Notifier.sounds[Notifier.channelOf(kind)] ?: return
        stop()
        // gleiche Lautstaerke wie die echte Benachrichtigung
        player = MediaPlayer.create(context, res, AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_NOTIFICATION_EVENT)
            .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION).build(), 0)
            ?.apply {
                setOnCompletionListener { it.release(); if (player === it) player = null }
                start()
            }
    }

    fun stop() {
        player?.release()
        player = null
    }
}

/** Einstellungen -> Toene: jeden Ton anhoeren und eine echte Probe-Benachrichtigung senden. */
@Composable
fun SoundsSection() {
    val context = LocalContext.current
    val player = remember { SoundPlayer(context.applicationContext) }
    DisposableEffect(Unit) { onDispose { player.stop() } }

    SectionLabel("Töne", Modifier.fillMaxWidth())
    Text("„Anhören“ spielt den Ton direkt. „Probe“ schickt eine echte Benachrichtigung – so prüfst du Lautstärke, " +
        "„Nicht stören“ und die Android-Einstellungen des Kanals.",
        style = MaterialTheme.typography.bodySmall, color = K.Muted)
    rows.forEach { r ->
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Column(Modifier.weight(1f)) {
                Text(r.name, style = MaterialTheme.typography.bodyLarge)
                Text(r.whenText, style = MaterialTheme.typography.bodySmall, color = K.Muted)
            }
            SecondaryButton("Anhören", { player.play(r.kind) })
            SecondaryButton("Probe", {
                Notifier.channels(context)
                Notifier.test(context, r.kind)
            })
        }
    }
    SecondaryButton("Benachrichtigungen in Android einstellen", {
        context.startActivity(Intent(AndroidSettings.ACTION_APP_NOTIFICATION_SETTINGS)
            .putExtra(AndroidSettings.EXTRA_APP_PACKAGE, context.packageName)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
    }, Modifier.fillMaxWidth())
}

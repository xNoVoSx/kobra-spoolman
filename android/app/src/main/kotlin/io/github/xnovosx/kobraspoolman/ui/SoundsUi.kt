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
import io.github.xnovosx.kobraspoolman.data.tr

/** A sound to listen to: name, when it comes, channel. */
private data class SoundRow(val kind: EventKind, val name: String, val whenText: String)

private val rows get() = listOf(
    SoundRow(EventKind.ALARM, tr("Alarm"), tr("Error, cancel, pause (not by you), colour change stuck, nozzle cooling, printer/bridge gone, spool not enough")),
    SoundRow(EventKind.DONE, tr("Print finished"), tr("Print ended successfully")),
    SoundRow(EventKind.START, tr("Print started"), tr("A print begins")),
    SoundRow(EventKind.LAYER, tr("First layer done"), tr("Time for a look at the bed")),
    SoundRow(EventKind.HINT, tr("Hint"), tr("Unknown tag, slot without material, Spoolman gone for longer")),
)

/** Plays a sound from res/raw; the previous one is stopped. */
private class SoundPlayer(private val context: Context) {
    private var player: MediaPlayer? = null

    fun play(kind: EventKind) {
        val res = Notifier.sounds[Notifier.channelOf(kind)] ?: return
        stop()
        // same volume as the real notification
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

/** Settings -> sounds: listen to every sound and send a real test notification. */
@Composable
fun SoundsSection() {
    val context = LocalContext.current
    val player = remember { SoundPlayer(context.applicationContext) }
    DisposableEffect(Unit) { onDispose { player.stop() } }

    SectionLabel(tr("Sounds"), Modifier.fillMaxWidth())
    Text(tr("“Listen” plays the sound directly. “Test” sends a real notification – that is how you check the volume, “Do not disturb” and the channel's Android settings."),
        style = MaterialTheme.typography.bodySmall, color = K.Muted)
    rows.forEach { r ->
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Column(Modifier.weight(1f)) {
                Text(r.name, style = MaterialTheme.typography.bodyLarge)
                Text(r.whenText, style = MaterialTheme.typography.bodySmall, color = K.Muted)
            }
            SecondaryButton(tr("Listen"), { player.play(r.kind) })
            SecondaryButton(tr("Test"), {
                Notifier.channels(context)
                Notifier.test(context, r.kind)
            })
        }
    }
    SecondaryButton(tr("Set up notifications in Android"), {
        context.startActivity(Intent(AndroidSettings.ACTION_APP_NOTIFICATION_SETTINGS)
            .putExtra(AndroidSettings.EXTRA_APP_PACKAGE, context.packageName)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
    }, Modifier.fillMaxWidth())
}

package io.github.xnovosx.kobraspoolman.monitor

import android.app.NotificationManager
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.widget.Toast
import io.github.xnovosx.kobraspoolman.data.BridgeClient
import io.github.xnovosx.kobraspoolman.data.Settings
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * Knoepfe am KI-Alarm: "Pausieren" pausiert den Druck ueber die Bridge und merkt das Bild als Fehldruck,
 * "Fehlalarm" merkt es als Fehlalarm (die KI ist dann fuer den Rest des Drucks still).
 */
class VisionActionReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val eventId = intent.getStringExtra(EXTRA_EVENT) ?: return
        val notificationId = intent.getIntExtra(EXTRA_NOTIFICATION, 0)
        val pending = goAsync()
        CoroutineScope(Dispatchers.IO).launch {
            val msg = runCatching {
                val c = Settings(context).connection.first()
                val client = BridgeClient(c.url, c.token)
                when (intent.action) {
                    ACTION_PAUSE -> {
                        client.printAction("pause")
                        client.visionFeedback(eventId, "confirmed")
                        "Druck pausiert"
                    }
                    else -> {
                        client.visionFeedback(eventId, "false_alarm")
                        "Als Fehlalarm gemerkt – KI für diesen Druck still"
                    }
                }
            }.getOrElse { "Nicht geklappt: ${it.message ?: it.javaClass.simpleName}" }
            withContext(Dispatchers.Main) {
                context.getSystemService(NotificationManager::class.java).cancel(notificationId)
                Toast.makeText(context, msg, Toast.LENGTH_LONG).show()
            }
            pending.finish()
        }
    }

    companion object {
        const val ACTION_PAUSE = "io.github.xnovosx.kobraspoolman.VISION_PAUSE"
        const val ACTION_FALSE_ALARM = "io.github.xnovosx.kobraspoolman.VISION_FALSE_ALARM"
        const val EXTRA_EVENT = "event"
        const val EXTRA_NOTIFICATION = "notification"
    }
}

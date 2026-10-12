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
import io.github.xnovosx.kobraspoolman.data.tr

/**
 * Buttons on the AI alarm: "Pause" pauses the print via the bridge and marks the image as a failure, "Correct"
 * only marks it as a failure, "False alarm" as a false alarm (the AI is then quiet for the rest of the print).
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
                        tr("Print paused")
                    }
                    ACTION_CONFIRM -> {
                        client.visionFeedback(eventId, "confirmed")
                        tr("Marked as a failure")
                    }
                    else -> {
                        client.visionFeedback(eventId, "false_alarm")
                        tr("Marked as a false alarm – AI quiet for this print")
                    }
                }
            }.getOrElse { tr("Did not work: {error}", "error" to (it.message ?: it.javaClass.simpleName)) }
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
        const val ACTION_CONFIRM = "io.github.xnovosx.kobraspoolman.VISION_CONFIRM"
        const val EXTRA_EVENT = "event"
        const val EXTRA_NOTIFICATION = "notification"
    }
}

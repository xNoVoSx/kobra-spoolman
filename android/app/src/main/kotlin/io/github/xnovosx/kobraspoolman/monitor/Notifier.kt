package io.github.xnovosx.kobraspoolman.monitor

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationChannelGroup
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.ContentResolver
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.media.AudioAttributes
import android.net.Uri
import android.os.Build
import android.os.Bundle
import io.github.xnovosx.kobraspoolman.MainActivity
import io.github.xnovosx.kobraspoolman.R
import io.github.xnovosx.kobraspoolman.data.Printer
import io.github.xnovosx.kobraspoolman.data.tr
import io.github.xnovosx.kobraspoolman.ui.Format

/**
 * Notifications of the print monitoring. Every channel can be set separately in the Android settings
 *  - Monitoring: silent service without a print (at the very bottom, no icon in the status bar)
 *  - Print running: progress; from Android 16 as a live update (always on top, lock screen, status bar "48 %")
 *  - Print started / First layer / Print finished: one sound each
 *  - Alarm: own alarm sound, with a camera image
 *  - Hints: quieter own sound, only things you can act on
 * Android fixes a channel's sound when it is created - new sounds need new channel IDs (suffix _2). Names and
 * descriptions follow the app language (channels() runs again at every service start).
 */
object Notifier {
    const val CH_MONITOR = "monitor_2"
    const val CH_LIVE = "live_2"
    const val CH_START = "start_2"
    const val CH_LAYER = "layer_2"
    const val CH_DONE = "done_2"
    const val CH_ALARM = "alarm_2"
    const val CH_HINT = "hint_2"
    const val ID_PROGRESS = 1
    private const val GROUP_PRINT = "print"
    private val OLD_CHANNELS = listOf("progress", "print", "alarm", "hint")

    /** Sound per channel (res/raw, made by tools/make_sounds.py). */
    val sounds = linkedMapOf(
        CH_START to R.raw.snd_start, CH_LAYER to R.raw.snd_first_layer, CH_DONE to R.raw.snd_done,
        CH_ALARM to R.raw.snd_alarm, CH_HINT to R.raw.snd_hint,
    )

    fun soundUri(context: Context, res: Int): Uri =
        Uri.parse("${ContentResolver.SCHEME_ANDROID_RESOURCE}://${context.packageName}/$res")

    fun channels(context: Context) {
        val nm = context.getSystemService(NotificationManager::class.java)
        OLD_CHANNELS.forEach { runCatching { nm.deleteNotificationChannel(it) } }   // channels of app 1.3
        nm.createNotificationChannelGroup(NotificationChannelGroup(GROUP_PRINT, tr("Print")))
        val notif = AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_NOTIFICATION_EVENT)
            .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION).build()

        fun ch(id: String, name: String, importance: Int, desc: String, block: NotificationChannel.() -> Unit = {}) =
            nm.createNotificationChannel(NotificationChannel(id, name, importance).apply {
                description = desc
                sounds[id]?.let { setSound(soundUri(context, it), notif) }
                block()
            })

        ch(CH_MONITOR, tr("Monitoring"), NotificationManager.IMPORTANCE_MIN,
            tr("Silent note that the app watches the printer in the background (without a print)")) { setShowBadge(false) }
        ch(CH_LIVE, tr("Print running"), NotificationManager.IMPORTANCE_DEFAULT,
            tr("Progress, time left, finish time – always on top while printing (no sound)")) {
            setSound(null, null)
            enableVibration(false)
            setShowBadge(false)
            group = GROUP_PRINT
        }
        ch(CH_START, tr("Print started"), NotificationManager.IMPORTANCE_DEFAULT, tr("A print begins")) { group = GROUP_PRINT }
        ch(CH_LAYER, tr("First layer done"), NotificationManager.IMPORTANCE_DEFAULT,
            tr("The first layer is through – time for a look at the bed")) { group = GROUP_PRINT }
        ch(CH_DONE, tr("Print finished"), NotificationManager.IMPORTANCE_DEFAULT, tr("Print ended successfully")) { group = GROUP_PRINT }
        ch(CH_ALARM, tr("Alarm"), NotificationManager.IMPORTANCE_HIGH,
            tr("Printer error, cancel or pause (not by you), colour change stuck, nozzle cooling, printer or bridge gone, spool not enough")) {
            // Android resets USAGE_ALARM to USAGE_NOTIFICATION for channels (checked in the emulator) - so normal
            // notification volume; the alarm should stand out by sound, vibration and popping up
            enableVibration(true)
            vibrationPattern = longArrayOf(0, 400, 200, 400, 200, 400)
            lockscreenVisibility = Notification.VISIBILITY_PUBLIC
        }
        ch(CH_HINT, tr("Hints"), NotificationManager.IMPORTANCE_DEFAULT,
            tr("Unknown tag in the slot, slot without material, Spoolman gone for longer …"))
    }

    private fun openApp(context: Context): PendingIntent = PendingIntent.getActivity(context, 0,
        Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),
        PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)

    /** Can this app show live updates? (Android 16+, not switched off by the user) */
    fun liveUpdates(context: Context): Boolean = Build.VERSION.SDK_INT >= 36 &&
        context.getSystemService(NotificationManager::class.java).canPostPromotedNotifications()

    /**
     * Ongoing notification of the service. While printing: live update (without an image, Android does not allow one
     * there); if that is switched off or the phone is older, a normal notification with the camera image.
     * Without a print: silent in the channel "Monitoring".
     */
    fun progress(context: Context, p: Printer?, camera: Bitmap?, reachable: Boolean): Notification {
        val running = reachable && p != null && (p.state == "printing" || p.state == "paused")
        val b = Notification.Builder(context, if (running) CH_LIVE else CH_MONITOR)
            .setSmallIcon(R.drawable.ic_stat_printer)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setContentIntent(openApp(context))
            .setCategory(if (running) Notification.CATEGORY_PROGRESS else Notification.CATEGORY_SERVICE)
        if (!running || p == null) {
            val what = if (!reachable) tr("Bridge not reachable") else p?.let { Format.stateLabel(it) } ?: "–"
            return b.setContentTitle("Kobra S1 · $what").setContentText(tr("Monitoring active")).build()
        }
        val pct = ((p.progress ?: 0.0) * 100).toInt()
        val file = p.file?.substringAfterLast('/')?.removeSuffix(".gcode") ?: tr("Print")
        val title = if (p.state == "paused") tr("Paused · {pct} %", "pct" to pct) else "$pct % · $file"
        val text = Format.progressLine(p)
        // progress is not secret: show it completely on the lock screen too
        b.setContentTitle(title).setContentText(text).setVisibility(Notification.VISIBILITY_PUBLIC)
        if (Build.VERSION.SDK_INT >= 36 && liveUpdates(context)) {
            b.setStyle(Notification.ProgressStyle().setProgress(pct).setStyledByProgress(true)
                .setProgressSegments(listOf(Notification.ProgressStyle.Segment(100).setColor(ACCENT))))
                // as an extra instead of setRequestPromotedOngoing(): the method exists from 36.1, the extra from 36
                .addExtras(Bundle().apply { putBoolean(Notification.EXTRA_REQUEST_PROMOTED_ONGOING, true) })
                .setShortCriticalText(if (p.state == "paused") tr("Pause") else "$pct %")
        } else {
            b.setProgress(100, pct, false)
            if (camera != null) b.setLargeIcon(camera).setStyle(Notification.BigPictureStyle().bigPicture(camera)
                .setSummaryText(text))
        }
        return b.build()
    }

    fun channelOf(kind: EventKind): String = when (kind) {
        EventKind.START -> CH_START
        EventKind.LAYER -> CH_LAYER
        EventKind.DONE -> CH_DONE
        EventKind.ALARM -> CH_ALARM
        EventKind.HINT -> CH_HINT
    }

    /** Report an event; alarms with the latest camera image (you see what is going on without opening the app). */
    fun event(context: Context, e: PrintEvent, camera: Bitmap? = null) {
        val b = Notification.Builder(context, channelOf(e.kind))
            .setSmallIcon(R.drawable.ic_stat_printer)
            .setContentTitle(e.title)
            .setContentText(e.text)
            .setAutoCancel(true)
            .setContentIntent(openApp(context))
            .setCategory(if (e.kind == EventKind.ALARM) Notification.CATEGORY_ALARM else Notification.CATEGORY_STATUS)
        if (e.kind == EventKind.ALARM && camera != null) {
            b.setLargeIcon(camera).setStyle(Notification.BigPictureStyle().bigPicture(camera).setSummaryText(e.text))
        } else {
            b.setStyle(Notification.BigTextStyle().bigText(e.text))
        }
        // the same message (key) replaces the previous one instead of stacking
        val id = 1000 + (e.key.hashCode() and 0xffff)
        e.aiEvent?.let { ev ->
            // AI alarm: pause right from the notification or report a false alarm
            fun action(what: String, label: String, req: Int) = Notification.Action.Builder(null, label,
                PendingIntent.getBroadcast(context, req, Intent(context, VisionActionReceiver::class.java).setAction(what)
                    .putExtra(VisionActionReceiver.EXTRA_EVENT, ev).putExtra(VisionActionReceiver.EXTRA_NOTIFICATION, id),
                    PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)).build()
            b.addAction(action(VisionActionReceiver.ACTION_PAUSE, tr("Pause"), id * 3))
            b.addAction(action(VisionActionReceiver.ACTION_CONFIRM, tr("Correct"), id * 3 + 2))
            b.addAction(action(VisionActionReceiver.ACTION_FALSE_ALARM, tr("False alarm"), id * 3 + 1))
        }
        context.getSystemService(NotificationManager::class.java).notify(id, b.build())
    }

    /** Test notification from the settings: checks sound, volume and "Do not disturb" of the channel. */
    fun test(context: Context, kind: EventKind) {
        val (title, text) = when (kind) {
            EventKind.START -> tr("Print started") to tr("Test – this is how a print start sounds")
            EventKind.LAYER -> tr("First layer done") to tr("Test – this is how the first layer sounds")
            EventKind.DONE -> tr("Print finished") to tr("Test – this is how a finished print sounds")
            EventKind.ALARM -> tr("Alarm (test)") to tr("This is how an alarm sounds – e.g. printer error or colour change stuck")
            EventKind.HINT -> tr("Hint (test)") to tr("This is how a hint sounds – e.g. unknown tag in the slot")
        }
        event(context, PrintEvent(kind, title, text, "test-${kind.name}"))
    }

    private const val ACCENT = 0xFFF2B53A.toInt()
}

package io.github.xnovosx.kobraspoolman.monitor

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.media.AudioAttributes
import android.media.RingtoneManager
import io.github.xnovosx.kobraspoolman.MainActivity
import io.github.xnovosx.kobraspoolman.R
import io.github.xnovosx.kobraspoolman.data.Printer
import io.github.xnovosx.kobraspoolman.ui.Format

/**
 * Benachrichtigungen der Druck-Ueberwachung. Vier Kanaele - jeder ist in den Android-Einstellungen einzeln
 * laut/leise/aus stellbar:
 *  - Fortschritt: dauerhaft in der Leiste (Balken, %, Restzeit, Fertig-Uhrzeit, Kamerabild)
 *  - Druck: Start, erste Schicht, fertig (mit Ton)
 *  - Alarm: Pause, Abbruch, Fehler, haengender Farbwechsel, Temperatur, Drucker/Bridge weg (laut)
 *  - Hinweise: gelbe Meldungen der Bridge (leise)
 */
object Notifier {
    const val CH_PROGRESS = "progress"
    const val CH_PRINT = "print"
    const val CH_ALARM = "alarm"
    const val CH_HINT = "hint"
    const val ID_PROGRESS = 1

    fun channels(context: Context) {
        val nm = context.getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(NotificationChannel(CH_PROGRESS, "Druckfortschritt", NotificationManager.IMPORTANCE_LOW).apply {
            description = "Laufender Druck in der Leiste; ohne Druck: stille Überwachung"
            setShowBadge(false)
        })
        nm.createNotificationChannel(NotificationChannel(CH_PRINT, "Druck", NotificationManager.IMPORTANCE_DEFAULT).apply {
            description = "Druck gestartet, erste Schicht fertig, Druck fertig"
        })
        nm.createNotificationChannel(NotificationChannel(CH_ALARM, "Alarm", NotificationManager.IMPORTANCE_HIGH).apply {
            description = "Pause, Abbruch, Fehler, Farbwechsel hängt, Temperatur, Drucker oder Bridge weg, Spule reicht nicht"
            enableVibration(true)
            setSound(RingtoneManager.getDefaultUri(RingtoneManager.TYPE_ALARM), AudioAttributes.Builder()
                .setUsage(AudioAttributes.USAGE_ALARM).setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION).build())
        })
        nm.createNotificationChannel(NotificationChannel(CH_HINT, "Hinweise", NotificationManager.IMPORTANCE_LOW).apply {
            description = "Spule fast leer, offene Buchung, unbekannter Tag …"
        })
    }

    private fun openApp(context: Context): PendingIntent = PendingIntent.getActivity(context, 0,
        Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),
        PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)

    /** Dauerhafte Benachrichtigung des Dienstes: Fortschritt im Druck, sonst ein stiller Zustand. */
    fun progress(context: Context, p: Printer?, camera: Bitmap?, reachable: Boolean): Notification {
        val b = Notification.Builder(context, CH_PROGRESS)
            .setSmallIcon(R.drawable.ic_stat_printer)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setContentIntent(openApp(context))
            .setCategory(Notification.CATEGORY_PROGRESS)
        val running = p != null && (p.state == "printing" || p.state == "paused")
        if (!reachable) {
            b.setContentTitle("Kobra S1").setContentText("Bridge nicht erreichbar")
        } else if (!running || p == null) {
            b.setContentTitle("Kobra S1 · ${p?.let { Format.stateLabel(it) } ?: "–"}").setContentText("Überwachung läuft")
        } else {
            val pct = ((p.progress ?: 0.0) * 100).toInt()
            val file = p.file?.substringAfterLast('/')?.removeSuffix(".gcode") ?: "Druck"
            val title = if (p.state == "paused") "Pausiert · $pct %" else "$pct % · $file"
            val text = listOfNotNull(
                p.etaS?.let { "noch ${Format.duration(it)}" },
                p.etaS?.let { "fertig ${Format.finishAt(it)}" },
                if (p.layer != null && p.layers != null) "Schicht ${p.layer}/${p.layers}" else null,
            ).joinToString(" · ")
            b.setContentTitle(title).setContentText(text).setProgress(100, pct, false)
            if (camera != null) b.setLargeIcon(camera).setStyle(Notification.BigPictureStyle().bigPicture(camera)
                .setSummaryText(text))
        }
        return b.build()
    }

    fun event(context: Context, e: PrintEvent) {
        val channel = when (e.kind) { EventKind.ALARM -> CH_ALARM; EventKind.PRINT -> CH_PRINT; EventKind.HINT -> CH_HINT }
        val n = Notification.Builder(context, channel)
            .setSmallIcon(R.drawable.ic_stat_printer)
            .setContentTitle(e.title)
            .setContentText(e.text)
            .setStyle(Notification.BigTextStyle().bigText(e.text))
            .setAutoCancel(true)
            .setContentIntent(openApp(context))
            .setCategory(if (e.kind == EventKind.ALARM) Notification.CATEGORY_ALARM else Notification.CATEGORY_STATUS)
            .build()
        // gleiche Meldung (key) ersetzt die vorige statt sich zu stapeln
        context.getSystemService(NotificationManager::class.java).notify(1000 + (e.key.hashCode() and 0xffff), n)
    }
}

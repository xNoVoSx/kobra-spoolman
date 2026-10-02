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
import io.github.xnovosx.kobraspoolman.ui.Format

/**
 * Benachrichtigungen der Druck-Ueberwachung. Jeder Kanal ist in den Android-Einstellungen einzeln stellbar:
 *  - Ueberwachung: stiller Dienst ohne Druck (ganz unten, ohne Symbol in der Statusleiste)
 *  - Druck laeuft: Fortschritt; ab Android 16 als Live-Update (immer oben, Sperrbildschirm, Statusleiste "48 %")
 *  - Druck gestartet / Erste Schicht / Druck fertig: je ein eigener Ton
 *  - Alarm: eigener Alarmton, mit Kamerabild
 *  - Hinweise: leiser eigener Ton, nur was man tun kann
 * Android legt den Ton eines Kanals beim Anlegen fest - neue Toene brauchen neue Kanal-IDs (Suffix _2).
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

    /** Ton je Kanal (res/raw, erzeugt von tools/make_sounds.py). */
    val sounds = linkedMapOf(
        CH_START to R.raw.snd_start, CH_LAYER to R.raw.snd_first_layer, CH_DONE to R.raw.snd_done,
        CH_ALARM to R.raw.snd_alarm, CH_HINT to R.raw.snd_hint,
    )

    fun soundUri(context: Context, res: Int): Uri =
        Uri.parse("${ContentResolver.SCHEME_ANDROID_RESOURCE}://${context.packageName}/$res")

    fun channels(context: Context) {
        val nm = context.getSystemService(NotificationManager::class.java)
        OLD_CHANNELS.forEach { runCatching { nm.deleteNotificationChannel(it) } }   // Kanaele von App 1.3
        nm.createNotificationChannelGroup(NotificationChannelGroup(GROUP_PRINT, "Druck"))
        val notif = AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_NOTIFICATION_EVENT)
            .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION).build()

        fun ch(id: String, name: String, importance: Int, desc: String, block: NotificationChannel.() -> Unit = {}) =
            nm.createNotificationChannel(NotificationChannel(id, name, importance).apply {
                description = desc
                sounds[id]?.let { setSound(soundUri(context, it), notif) }
                block()
            })

        ch(CH_MONITOR, "Überwachung", NotificationManager.IMPORTANCE_MIN,
            "Stiller Hinweis, dass die App im Hintergrund auf den Drucker achtet (ohne Druck)") { setShowBadge(false) }
        ch(CH_LIVE, "Druck läuft", NotificationManager.IMPORTANCE_DEFAULT,
            "Fortschritt, Restzeit, Fertig-Uhrzeit – immer oben, solange gedruckt wird (ohne Ton)") {
            setSound(null, null)
            enableVibration(false)
            setShowBadge(false)
            group = GROUP_PRINT
        }
        ch(CH_START, "Druck gestartet", NotificationManager.IMPORTANCE_DEFAULT, "Ein Druck beginnt") { group = GROUP_PRINT }
        ch(CH_LAYER, "Erste Schicht fertig", NotificationManager.IMPORTANCE_DEFAULT,
            "Die erste Schicht ist durch – Zeit für einen Blick aufs Bett") { group = GROUP_PRINT }
        ch(CH_DONE, "Druck fertig", NotificationManager.IMPORTANCE_DEFAULT, "Druck erfolgreich beendet") { group = GROUP_PRINT }
        ch(CH_ALARM, "Alarm", NotificationManager.IMPORTANCE_HIGH,
            "Druckerfehler, Abbruch oder Pause (nicht von dir), Farbwechsel hängt, Düse kühlt ab, " +
                "Drucker oder Bridge weg, Spule reicht nicht") {
            // USAGE_ALARM setzt Android bei Kanaelen auf USAGE_NOTIFICATION zurueck (im Emulator geprueft) - also
            // normale Benachrichtigungs-Lautstaerke; auffallen soll der Alarm ueber Ton, Vibration und Aufpoppen
            enableVibration(true)
            vibrationPattern = longArrayOf(0, 400, 200, 400, 200, 400)
            lockscreenVisibility = Notification.VISIBILITY_PUBLIC
        }
        ch(CH_HINT, "Hinweise", NotificationManager.IMPORTANCE_DEFAULT,
            "Unbekannter Tag im Slot, Slot ohne Material, Spoolman länger weg …")
    }

    private fun openApp(context: Context): PendingIntent = PendingIntent.getActivity(context, 0,
        Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),
        PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)

    /** Kann diese App Live-Updates zeigen? (Android 16+, vom Nutzer nicht abgeschaltet) */
    fun liveUpdates(context: Context): Boolean = Build.VERSION.SDK_INT >= 36 &&
        context.getSystemService(NotificationManager::class.java).canPostPromotedNotifications()

    /**
     * Dauerhafte Benachrichtigung des Dienstes. Im Druck: Live-Update (ohne Bild, das erlaubt Android dort nicht);
     * ist das abgeschaltet oder das Handy aelter, eine normale Benachrichtigung mit Kamerabild.
     * Ohne Druck: still im Kanal "Ueberwachung".
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
            val what = if (!reachable) "Bridge nicht erreichbar" else p?.let { Format.stateLabel(it) } ?: "–"
            return b.setContentTitle("Kobra S1 · $what").setContentText("Überwachung läuft").build()
        }
        val pct = ((p.progress ?: 0.0) * 100).toInt()
        val file = p.file?.substringAfterLast('/')?.removeSuffix(".gcode") ?: "Druck"
        val title = if (p.state == "paused") "Pausiert · $pct %" else "$pct % · $file"
        val text = listOfNotNull(
            p.etaS?.let { "noch ${Format.duration(it)}" },
            p.etaS?.let { "fertig ${Format.finishAt(it)}" },
            if (p.layer != null && p.layers != null) "Schicht ${p.layer}/${p.layers}" else null,
        ).joinToString(" · ")
        // Fortschritt ist nicht geheim: auch auf dem Sperrbildschirm vollstaendig zeigen
        b.setContentTitle(title).setContentText(text).setVisibility(Notification.VISIBILITY_PUBLIC)
        if (Build.VERSION.SDK_INT >= 36 && liveUpdates(context)) {
            b.setStyle(Notification.ProgressStyle().setProgress(pct).setStyledByProgress(true)
                .setProgressSegments(listOf(Notification.ProgressStyle.Segment(100).setColor(ACCENT))))
                // als Extra statt setRequestPromotedOngoing(): die Methode gibt es erst ab 36.1, das Extra ab 36
                .addExtras(Bundle().apply { putBoolean(Notification.EXTRA_REQUEST_PROMOTED_ONGOING, true) })
                .setShortCriticalText(if (p.state == "paused") "Pause" else "$pct %")
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

    /** Ereignis melden; Alarme mit dem letzten Kamerabild (sieht man, was los ist, ohne die App zu oeffnen). */
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
        // gleiche Meldung (key) ersetzt die vorige statt sich zu stapeln
        context.getSystemService(NotificationManager::class.java).notify(1000 + (e.key.hashCode() and 0xffff), b.build())
    }

    /** Probe-Benachrichtigung aus den Einstellungen: prueft Ton, Lautstaerke und "Nicht stoeren" des Kanals. */
    fun test(context: Context, kind: EventKind) {
        val (title, text) = when (kind) {
            EventKind.START -> "Druck gestartet" to "Probe – so klingt ein Druckstart"
            EventKind.LAYER -> "Erste Schicht fertig" to "Probe – so klingt die erste Schicht"
            EventKind.DONE -> "Druck fertig" to "Probe – so klingt ein fertiger Druck"
            EventKind.ALARM -> "Alarm (Probe)" to "So klingt ein Alarm – z. B. Druckerfehler oder Farbwechsel hängt"
            EventKind.HINT -> "Hinweis (Probe)" to "So klingt ein Hinweis – z. B. unbekannter Tag im Slot"
        }
        event(context, PrintEvent(kind, title, text, "test-${kind.name}"))
    }

    private const val ACCENT = 0xFFF2B53A.toInt()
}

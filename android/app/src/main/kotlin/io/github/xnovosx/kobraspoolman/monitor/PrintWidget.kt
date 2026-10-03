package io.github.xnovosx.kobraspoolman.monitor

import android.app.PendingIntent
import android.appwidget.AppWidgetManager
import android.appwidget.AppWidgetProvider
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.view.View
import android.widget.RemoteViews
import io.github.xnovosx.kobraspoolman.MainActivity
import io.github.xnovosx.kobraspoolman.R
import io.github.xnovosx.kobraspoolman.data.Printer
import io.github.xnovosx.kobraspoolman.ui.Format

/**
 * Startbildschirm-Widget "Kobra Druck". Die Daten kommen vom Ueberwachungsdienst (MonitorService), der die Bridge
 * ohnehin abfragt - das Widget selbst fragt nichts ab. Ohne Dienst zeigt es den letzten Stand bzw. einen Hinweis.
 */
class PrintWidget : AppWidgetProvider() {
    override fun onUpdate(context: Context, manager: AppWidgetManager, ids: IntArray) {
        render(context, last, lastCamera, lastReachable, monitorOff = lastPrinter == null)
    }

    companion object {
        private var last: Printer? = null
        private var lastPrinter: Printer? = null
        private var lastCamera: Bitmap? = null
        private var lastReachable = true

        private fun ids(context: Context): IntArray =
            AppWidgetManager.getInstance(context).getAppWidgetIds(ComponentName(context, PrintWidget::class.java))

        /** Vom Dienst nach jedem Abruf. Kamerabild klein halten (RemoteViews-Grenze ~1 MB). */
        fun update(context: Context, p: Printer?, camera: Bitmap?, reachable: Boolean) {
            if (ids(context).isEmpty()) return
            last = p
            lastPrinter = p
            lastReachable = reachable
            lastCamera = camera?.let { scale(it) }
            render(context, p, lastCamera, reachable, monitorOff = false)
        }

        private fun scale(b: Bitmap): Bitmap {
            val w = 480
            return if (b.width <= w) b else Bitmap.createScaledBitmap(b, w, (b.height * w / b.width.toFloat()).toInt(), true)
        }

        private fun render(context: Context, p: Printer?, camera: Bitmap?, reachable: Boolean, monitorOff: Boolean) {
            val ids = ids(context)
            if (ids.isEmpty()) return
            val v = RemoteViews(context.packageName, R.layout.widget_print)
            val running = p != null && (p.state == "printing" || p.state == "paused")
            val pct = ((p?.progress ?: 0.0) * 100).toInt()
            val file = p?.file?.substringAfterLast('/')?.removeSuffix(".gcode")
            val title = when {
                monitorOff -> "Kobra S1"
                !reachable -> "Kobra S1 · Bridge nicht erreichbar"
                p == null -> "Kobra S1"
                running && p.state == "paused" -> "Pausiert · $pct %"
                running -> "$pct % · ${file ?: "Druck"}"
                else -> "Kobra S1 · ${Format.stateLabel(p)}"
            }
            val sub = when {
                monitorOff -> "Überwachung aus – in der App unter Einstellungen einschalten"
                running && p != null -> listOfNotNull(
                    p.etaS?.let { "noch ${Format.duration(it)}" },
                    p.etaS?.let { "fertig ${Format.finishAt(it)}" },
                    if (p.layer != null && p.layers != null) "Schicht ${p.layer}/${p.layers}" else null,
                ).joinToString(" · ")
                else -> "Kein Druck"
            }
            v.setTextViewText(R.id.widget_title, title)
            v.setTextViewText(R.id.widget_sub, sub)
            v.setViewVisibility(R.id.widget_progress, if (running) View.VISIBLE else View.GONE)
            v.setProgressBar(R.id.widget_progress, 100, pct, false)
            if (running && camera != null) {
                v.setImageViewBitmap(R.id.widget_camera, camera)
                v.setViewVisibility(R.id.widget_camera, View.VISIBLE)
            } else {
                v.setViewVisibility(R.id.widget_camera, View.GONE)
            }
            val open = PendingIntent.getActivity(context, 7, Intent(context, MainActivity::class.java)
                .addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP), PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
            v.setOnClickPendingIntent(R.id.widget_root, open)
            AppWidgetManager.getInstance(context).updateAppWidget(ids, v)
        }
    }
}

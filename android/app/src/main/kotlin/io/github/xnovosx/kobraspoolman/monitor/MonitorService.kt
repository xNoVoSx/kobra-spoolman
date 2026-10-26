package io.github.xnovosx.kobraspoolman.monitor

import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.graphics.BitmapFactory
import android.os.IBinder
import io.github.xnovosx.kobraspoolman.data.BridgeAccess
import io.github.xnovosx.kobraspoolman.data.PrinterLabel
import io.github.xnovosx.kobraspoolman.data.Settings
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

/**
 * Print monitoring in the background (replaces the OctoApp companion, which ate 64 % CPU on the printer): only
 * queries the bridge - every 5 s during a print, else every 30 s - and reports events. It costs nothing on the
 * printer. Switch on/off: Settings -> "Monitor the printer in the background". Away from home it takes the second
 * address (VPN) or Home Assistant like the app (BridgeAccess).
 */
class MonitorService : Service() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private val detector = EventDetector()

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        Notifier.channels(this)
        startForeground(Notifier.ID_PROGRESS, Notifier.progress(this, null, null, reachable = true),
            ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE)
        scope.launch { loop() }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int = START_STICKY

    override fun onDestroy() {
        scope.cancel()
        super.onDestroy()
    }

    private suspend fun loop() {
        val settings = Settings(this)
        var lastCamera = 0L
        var camera: android.graphics.Bitmap? = null
        while (scope.isActive) {
            val c = settings.connection.first()
            if (!settings.monitor.first() || !c.configured) { stopSelf(); return }
            val client = BridgeAccess.Default.client(c)
            val state = runCatching { client.state() }.getOrNull()
            if (state == null) BridgeAccess.Default.failed(c)
            val now = System.currentTimeMillis()
            val p = state?.printer
            if (state != null) PrinterLabel.name = state.printerName
            val running = p != null && (p.state == "printing" || p.state == "paused")
            val away = state == null && settings.awayHint.first() && HomeNetwork.away(this, c.url)
            val events = detector.update(state, now, away)
            // alarm with a fresh camera image: you see at once what is going on
            if (events.any { it.kind == EventKind.ALARM } && state?.canWrite == true) {
                camera = runCatching { client.image("/api/camera/snapshot.jpg") }.getOrNull()
                    ?.let { BitmapFactory.decodeByteArray(it, 0, it.size) } ?: camera
                lastCamera = now
            }
            val vpnApp = if (events.any { it.vpn }) VpnApps.pick(this, settings.vpnApp.first())?.pkg else null
            events.forEach { Notifier.event(this, it, if (it.kind == EventKind.ALARM) camera else null, vpnApp) }
            // camera image for the status bar: at most once a minute (the bridge fetches it only once anyway)
            if (running && state.canWrite && now - lastCamera > 60_000) {
                lastCamera = now
                camera = runCatching { client.image("/api/camera/snapshot.jpg") }.getOrNull()
                    ?.let { BitmapFactory.decodeByteArray(it, 0, it.size) } ?: camera
            }
            if (!running) camera = null
            getSystemService(android.app.NotificationManager::class.java)
                .notify(Notifier.ID_PROGRESS, Notifier.progress(this, p, camera, reachable = state != null))
            PrintWidget.update(this, p, camera, reachable = state != null)
            delay(if (running) 5_000 else 30_000)
        }
    }

    companion object {
        fun start(context: Context) {
            context.startForegroundService(Intent(context, MonitorService::class.java))
        }

        fun stop(context: Context) {
            context.stopService(Intent(context, MonitorService::class.java))
        }
    }
}

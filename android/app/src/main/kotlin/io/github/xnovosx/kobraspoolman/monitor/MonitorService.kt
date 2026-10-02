package io.github.xnovosx.kobraspoolman.monitor

import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.graphics.BitmapFactory
import android.os.IBinder
import io.github.xnovosx.kobraspoolman.data.BridgeClient
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
 * Druck-Ueberwachung im Hintergrund (ersetzt den OctoApp-Companion, der auf dem Drucker 64 % CPU frass):
 * fragt nur die Bridge ab - alle 5 s waehrend eines Drucks, sonst alle 30 s - und meldet Ereignisse.
 * Am Drucker kostet das nichts. Ein-/ausschalten: Einstellungen -> "Drucker im Hintergrund überwachen".
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
            val client = BridgeClient(c.url, c.token)
            val state = runCatching { client.state() }.getOrNull()
            val now = System.currentTimeMillis()
            detector.update(state, now).forEach { Notifier.event(this, it) }
            val p = state?.printer
            val running = p != null && (p.state == "printing" || p.state == "paused")
            // Kamerabild fuer die Leiste: hoechstens einmal pro Minute (die Bridge holt es ohnehin nur einmal)
            if (running && state.canWrite && now - lastCamera > 60_000) {
                lastCamera = now
                camera = runCatching { client.image("/api/camera/snapshot.jpg") }.getOrNull()
                    ?.let { BitmapFactory.decodeByteArray(it, 0, it.size) } ?: camera
            }
            if (!running) camera = null
            getSystemService(android.app.NotificationManager::class.java)
                .notify(Notifier.ID_PROGRESS, Notifier.progress(this, p, camera, reachable = state != null))
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

package io.github.xnovosx.kobraspoolman.monitor

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import io.github.xnovosx.kobraspoolman.data.Settings
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.flow.first

/** Nach einem Neustart des Handys die Ueberwachung wieder starten (wenn eingeschaltet). */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Intent.ACTION_BOOT_COMPLETED) return
        val s = Settings(context)
        val on = runBlocking { s.monitor.first() && s.connection.first().configured }
        if (on) MonitorService.start(context)
    }
}

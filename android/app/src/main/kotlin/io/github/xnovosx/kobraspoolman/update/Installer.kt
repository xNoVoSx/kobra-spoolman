package io.github.xnovosx.kobraspoolman.update

import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.Build
import android.content.pm.PackageInstaller
import android.net.Uri
import android.provider.Settings
import android.widget.Toast
import java.io.File

/**
 * Installiert eine von der Bridge geladene APK ueber den PackageInstaller. Android fragt dabei immer selbst
 * nach ("Aktualisieren?") - still im Hintergrund geht das ausserhalb des Play Store nicht.
 * Voraussetzung: einmalig "Unbekannte Apps installieren" fuer diese App erlauben.
 */
object Installer {
    /** Darf die App Pakete installieren? Sonst zuerst die Einstellung oeffnen. */
    fun allowed(context: Context): Boolean = context.packageManager.canRequestPackageInstalls()

    fun openPermission(context: Context) {
        context.startActivity(Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:${context.packageName}"))
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
    }

    fun install(context: Context, apk: File) {
        val installer = context.packageManager.packageInstaller
        val params = PackageInstaller.SessionParams(PackageInstaller.SessionParams.MODE_FULL_INSTALL)
        params.setAppPackageName(context.packageName)
        val id = installer.createSession(params)
        installer.openSession(id).use { session ->
            session.openWrite("kobra-spoolman.apk", 0, apk.length()).use { out ->
                apk.inputStream().use { it.copyTo(out) }
                session.fsync(out)
            }
            val intent = Intent(context, InstallReceiver::class.java)
            // MUTABLE: das System traegt Status und Bestaetigungs-Intent ein
            val pending = PendingIntent.getBroadcast(context, id, intent,
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_MUTABLE)
            session.commit(pending.intentSender)
        }
    }
}

/** Ergebnis der Installation: Bestaetigung anzeigen oder Fehler melden. */
class InstallReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        when (val status = intent.getIntExtra(PackageInstaller.EXTRA_STATUS, PackageInstaller.STATUS_FAILURE)) {
            PackageInstaller.STATUS_PENDING_USER_ACTION -> {
                // die typisierte Variante gibt es erst ab Android 13 (API 33)
                val confirm = (if (Build.VERSION.SDK_INT >= 33) intent.getParcelableExtra(Intent.EXTRA_INTENT, Intent::class.java)
                    else @Suppress("DEPRECATION") intent.getParcelableExtra(Intent.EXTRA_INTENT)) ?: return
                context.startActivity(confirm.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            }
            PackageInstaller.STATUS_SUCCESS -> Unit      // die App wird neu gestartet
            else -> {
                val msg = intent.getStringExtra(PackageInstaller.EXTRA_STATUS_MESSAGE) ?: "Fehler $status"
                Toast.makeText(context, "Update nicht installiert: $msg", Toast.LENGTH_LONG).show()
            }
        }
    }
}

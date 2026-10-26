package io.github.xnovosx.kobraspoolman.monitor

import android.Manifest
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager

/**
 * VPN apps on the phone (NetBird, Tailscale, WireGuard ...): apps with a VPN service. No app may switch another one's
 * VPN on (NetBird's service is not exported, Android allows only one VPN) - the away hint can only open the VPN app.
 * Visible through the launcher query in the manifest (no QUERY_ALL_PACKAGES).
 */
object VpnApps {
    data class App(val pkg: String, val label: String)

    fun installed(context: Context): List<App> {
        val pm = context.packageManager
        val launchers = pm.queryIntentActivities(Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER), 0)
        return launchers.map { it.activityInfo.packageName }.distinct().filter { pkg ->
            pkg != context.packageName && runCatching {
                pm.getPackageInfo(pkg, PackageManager.GET_SERVICES).services.orEmpty()
                    .any { it.permission == Manifest.permission.BIND_VPN_SERVICE }
            }.getOrDefault(false)
        }.map { App(it, pm.getApplicationLabel(pm.getApplicationInfo(it, 0)).toString()) }.sortedBy { it.label.lowercase() }
    }

    /** The VPN app to open: the chosen one, else the only one installed; null = none. */
    fun pick(context: Context, chosen: String): App? {
        val all = installed(context)
        return all.firstOrNull { it.pkg == chosen } ?: all.singleOrNull()
    }

    fun launch(context: Context, pkg: String): Intent? = context.packageManager.getLaunchIntentForPackage(pkg)
}

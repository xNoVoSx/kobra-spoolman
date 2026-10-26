package io.github.xnovosx.kobraspoolman.monitor

import android.content.Context
import android.net.ConnectivityManager
import java.net.InetAddress

/**
 * Is the phone away from home? Yes when the network it uses has no route into the bridge's network - on mobile data or
 * a foreign Wi-Fi only the default route leads there. At home (Wi-Fi) and with a VPN that routes the home network
 * (NetBird, Tailscale, WireGuard) there is such a route. Only for a bridge address given as an IP; a host name cannot
 * be checked without asking a DNS server, then it counts as home (the alarm stays).
 */
object HomeNetwork {
    private val IP = Regex("""^[0-9.]+$|^\[?[0-9a-fA-F:]+]?$""")

    fun away(context: Context, bridgeUrl: String): Boolean {
        val host = runCatching { java.net.URI(bridgeUrl).host }.getOrNull()?.trim('[', ']') ?: return false
        if (!IP.matches(host)) return false
        val addr = runCatching { InetAddress.getByName(host) }.getOrNull() ?: return false
        val cm = context.getSystemService(ConnectivityManager::class.java) ?: return false
        val net = cm.activeNetwork ?: return true                 // no network at all: certainly not at home
        val routes = cm.getLinkProperties(net)?.routes ?: return false
        return routes.none { it.destination.prefixLength > 0 && it.matches(addr) }
    }
}

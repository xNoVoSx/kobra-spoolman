package io.github.xnovosx.kobraspoolman.data

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import java.util.concurrent.TimeUnit

/** Way to the bridge: home network, second address (VPN) or Home Assistant. */
enum class RouteKind { LOCAL, VPN, HA }

/** A way: base address of the bridge and the HTTP client for it (through HA with the ingress session). */
class Route(val kind: RouteKind, val base: String, val http: OkHttpClient, val ingress: IngressSession? = null)

/**
 * Picks the way to the bridge (Settings -> Remote access): the home address first, then the second address (VPN, e.g.
 * NetBird), then Home Assistant. A way that worked is kept until a request on it fails; on a way from outside the app
 * looks for home again every minute, so it is back on the direct way as soon as the phone is home. Nothing reachable:
 * it tries again at most every 10 s and meanwhile uses the home address (its error is the usual "not reachable").
 * One instance per app process (Default) - the screen and the background monitoring share the way and the HA session.
 */
class BridgeAccess(
    private val http: OkHttpClient = BridgeClient.defaultHttp,
    private val clock: () -> Long = System::currentTimeMillis,
) {
    companion object {
        const val RECHECK_MS = 60_000L
        const val RETRY_MS = 10_000L
        val Default = BridgeAccess()
    }

    private val mutex = Mutex()
    private var conn: Connection? = null
    private var active: Route? = null
    private var probedAt: Long? = null
    private var ingress: IngressSession? = null

    private val _kind = MutableStateFlow<RouteKind?>(null)
    /** The way in use, null = none reachable (or not looked yet). */
    val kind: StateFlow<RouteKind?> = _kind

    /** Client on the current way (looks for one if needed). */
    suspend fun client(c: Connection): BridgeClient = route(c).let { BridgeClient(it.base, c.token, it.http, frames = it.kind == RouteKind.HA) }

    suspend fun route(c: Connection): Route = mutex.withLock {
        if (c != conn) {
            conn = c
            active = null
            probedAt = null
            ingress = if (c.ha.ready) IngressSession(HaIngress(c.ha.url, c.ha.token, http), clock) else null
        }
        val cur = active
        val now = clock()
        val since = probedAt?.let { now - it }
        if (cur != null && (cur.kind == RouteKind.LOCAL || since != null && since < RECHECK_MS)) return cur
        if (cur == null && since != null && since < RETRY_MS) return local(c)
        probedAt = now
        val found = probe(c)
        active = found
        _kind.value = found?.kind
        found ?: local(c)
    }

    /** A request on the way failed (bridge not reachable): look again with the next request. */
    suspend fun failed(c: Connection) = mutex.withLock {
        if (c == conn) {
            active = null
            _kind.value = null
        }
    }

    /** The way in use for a WebView (3D view): base address and the cookie it needs (through HA), null = none yet. */
    fun web(): Pair<String, String?>? = active?.let { it.base to it.ingress?.cookie }

    /** Settings -> Test: every configured way on its own; null = reachable, else why not. */
    suspend fun test(c: Connection): Map<RouteKind, String?> = coroutineScope {
        val session = if (c.ha.ready) IngressSession(HaIngress(c.ha.url, c.ha.token, http), clock) else null
        listOfNotNull(local(c), vpn(c), session?.let { ha(c, it) })
            .map { r -> async { r.kind to reason(r, c.token) } }.awaitAll().toMap()
    }

    private fun local(c: Connection) = Route(RouteKind.LOCAL, BridgeClient.normalizeUrl(c.url), http)

    private fun vpn(c: Connection) = c.vpnUrl.takeIf { it.isNotBlank() }
        ?.let { Route(RouteKind.VPN, BridgeClient.normalizeUrl(it), http) }

    private fun ha(c: Connection, session: IngressSession) = Route(RouteKind.HA, HaIngress.normalizeUrl(c.ha.url) + c.ha.ingress,
        http.newBuilder().addInterceptor(IngressCookie(session)).build(), session)

    /** Home and VPN at the same time (both short), Home Assistant only when neither answers. */
    private suspend fun probe(c: Connection): Route? = coroutineScope {
        val direct = listOfNotNull(local(c), vpn(c)).map { r -> async { r.takeIf { reason(it, c.token) == null } } }.awaitAll()
        direct.firstOrNull { it != null } ?: ingress?.let { ha(c, it) }?.takeIf { reason(it, c.token) == null }
    }

    /** null = this way reaches the bridge. */
    private suspend fun reason(r: Route, token: String): String? = withContext(Dispatchers.IO) {
        val quick = r.http.newBuilder().connectTimeout(3, TimeUnit.SECONDS).readTimeout(6, TimeUnit.SECONDS).build()
        try {
            val h = BridgeClient(r.base, token, quick).health()
            if (h.app == "ace-lane-bridge") null else tr("Answers, but is not the bridge")
        } catch (e: BridgeException) {
            e.message ?: "?"
        }
    }
}

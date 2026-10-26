package io.github.xnovosx.kobraspoolman

import io.github.xnovosx.kobraspoolman.data.BridgeAccess
import io.github.xnovosx.kobraspoolman.data.Connection
import io.github.xnovosx.kobraspoolman.data.HaIngress
import io.github.xnovosx.kobraspoolman.data.HaRemote
import io.github.xnovosx.kobraspoolman.data.RouteKind
import kotlinx.coroutines.test.runTest
import mockwebserver3.Dispatcher
import mockwebserver3.MockResponse
import mockwebserver3.MockWebServer
import mockwebserver3.RecordedRequest
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.util.concurrent.atomic.AtomicInteger

/** The way to the bridge (BridgeAccess): home first, then the VPN address, then Home Assistant with its ingress session. */
class BridgeAccessTest {
    private val home = MockWebServer()
    private val vpn = MockWebServer()
    private val ha = MockWebServer()
    private var now = 0L
    private val dead = "http://127.0.0.1:1"          // nothing listens there: connection refused at once

    private val health = """{"app":"ace-lane-bridge","version":"4.6.0"}"""
    private val state = """{"version":"4.6.0","printer":{"state":"standby"},"slots":[],"shelf":[]}"""

    /** A bridge answering health and state; up = false: it is gone (503, like a proxy in front of a dead bridge). */
    private fun bridge(server: MockWebServer, hits: AtomicInteger = AtomicInteger(), up: () -> Boolean = { true }) {
        server.dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse {
                hits.incrementAndGet()
                if (!up()) return MockResponse.Builder().code(503).build()
                val body = if (request.url.encodedPath == "/api/health") health else state
                return MockResponse.Builder().code(200).body(body).build()
            }
        }
    }

    // Home Assistant: WebSocket login, ingress sessions, the bridge behind /api/hassio_ingress/tok
    private val sessions = mutableListOf<String>()
    private var validSession: String? = null
    private var haToken = "ha-token"
    private var adminOnly = false                    // add-on with panel_admin (default) and a non-admin HA user

    private fun homeAssistant() {
        ha.dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse {
                val path = request.url.encodedPath
                if (path == "/api/websocket") return MockResponse.Builder().webSocketUpgrade(object : WebSocketListener() {
                    override fun onOpen(webSocket: WebSocket, response: Response) {
                        webSocket.send("""{"type":"auth_required"}""")
                    }

                    override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
                        webSocket.close(1000, null)
                    }

                    override fun onMessage(webSocket: WebSocket, text: String) {
                        when {
                            "\"auth\"" in text && haToken in text -> webSocket.send("""{"type":"auth_ok"}""")
                            "\"auth\"" in text -> webSocket.send("""{"type":"auth_invalid","message":"Invalid access token"}""")
                            "/ingress/session" in text -> {
                                val s = "s${sessions.size + 1}"
                                sessions += s
                                validSession = s
                                webSocket.send("""{"id":1,"type":"result","success":true,"result":{"session":"$s"}}""")
                            }
                        }
                    }
                }).build()
                if (!path.startsWith("/api/hassio_ingress/tok/")) return MockResponse.Builder().code(404).build()
                if (request.headers["Cookie"] != "ingress_session=$validSession")
                    return MockResponse.Builder().code(401).addHeader("Content-Type", "text/plain").body("401: Unauthorized").build()
                if (adminOnly)
                    return MockResponse.Builder().code(403).addHeader("Content-Type", "text/plain").body("403: Forbidden").build()
                // the bridge key passes HA unchanged
                if (request.headers["Authorization"] != "Bearer key") return MockResponse.Builder().code(403).build()
                return MockResponse.Builder().code(200).body(if (path.endsWith("/api/health")) health else state).build()
            }
        }
    }

    @Before fun start() { home.start(); vpn.start(); ha.start() }
    @After fun stop() { home.close(); vpn.close(); ha.close() }

    private fun access() = BridgeAccess(clock = { now })
    private fun conn(url: String, vpnUrl: String = "", haOn: Boolean = false) = Connection(url, "key", vpnUrl,
        HaRemote(haOn, ha.url("/").toString().trimEnd('/'), haToken, "/api/hassio_ingress/tok"))

    @Test fun home_comes_first() = runTest {
        bridge(home); bridge(vpn)
        val a = access()
        val c = conn(home.url("/").toString(), vpn.url("/").toString())
        assertEquals(RouteKind.LOCAL, a.route(c).kind)
        assertEquals(RouteKind.LOCAL, a.kind.value)
        assertEquals("standby", a.client(c).state().printer.state)
    }

    @Test fun vpn_when_home_is_gone_and_back_home_after_a_minute() = runTest {
        var atHome = false
        bridge(home, up = { atHome })
        bridge(vpn)
        val a = access()
        val c = conn(home.url("/").toString(), vpn.url("/").toString())
        assertEquals(RouteKind.VPN, a.route(c).kind)
        atHome = true
        now += 30_000
        assertEquals(RouteKind.VPN, a.route(c).kind)          // the way that works is kept ...
        now += BridgeAccess.RECHECK_MS
        assertEquals(RouteKind.LOCAL, a.route(c).kind)        // ... until it looks for home again
        assertEquals(RouteKind.LOCAL, a.kind.value)
    }

    @Test fun nothing_reachable_is_not_probed_on_every_request() = runTest {
        val hits = AtomicInteger()
        val a = access()
        val c = conn(dead, dead)
        assertEquals(RouteKind.LOCAL, a.route(c).kind)       // nothing: the home address, its error is the usual one
        assertNull(a.kind.value)
        bridge(vpn, hits)
        val c2 = c.copy(vpnUrl = vpn.url("/").toString())
        assertEquals(RouteKind.VPN, a.route(c2).kind)
        now += 5_000
        a.failed(c2)
        assertEquals(RouteKind.LOCAL, a.route(c2).kind)      // within RETRY_MS: no new probing
        val before = hits.get()
        now += BridgeAccess.RETRY_MS
        assertEquals(RouteKind.VPN, a.route(c2).kind)
        assertEquals(before + 1, hits.get())
    }

    @Test fun home_assistant_with_ingress_session_renewed_when_refused() = runTest {
        homeAssistant()
        val a = access()
        val c = conn(dead, haOn = true)
        assertEquals(RouteKind.HA, a.route(c).kind)
        assertEquals(listOf("s1"), sessions)
        val client = a.client(c)
        assertEquals("standby", client.state().printer.state)
        validSession = "expired"                                   // HA forgot the session (Supervisor restart)
        assertEquals("standby", client.state().printer.state)     // refused -> new session -> repeated
        assertEquals(listOf("s1", "s2"), sessions)
        val (base, cookie) = a.web()!!
        assertTrue(base.endsWith("/api/hassio_ingress/tok"))
        assertEquals("ingress_session=s2", cookie)
    }

    @Test fun idle_session_is_renewed_before_use() = runTest {
        homeAssistant()
        val a = access()
        val c = conn(dead, haOn = true)
        a.client(c).state()
        now += 15 * 60_000L                                        // 15 min nothing: HA dropped it anyway
        a.client(c).state()
        assertEquals(listOf("s1", "s2"), sessions)
    }

    @Test fun test_reports_every_way() = runTest {
        homeAssistant()
        bridge(vpn)
        haToken = "ha-token"
        val result = access().test(conn(dead, vpn.url("/").toString(), haOn = true).let { it.copy(ha = it.ha.copy(token = "wrong")) })
        assertTrue(result[RouteKind.LOCAL]!!.isNotBlank())
        assertNull(result[RouteKind.VPN])
        assertTrue(result[RouteKind.HA]!!, "refused the token" in result[RouteKind.HA]!!)
    }

    @Test fun admin_only_add_on_is_explained() = runTest {
        homeAssistant()
        adminOnly = true
        val why = access().test(conn(dead, haOn = true))[RouteKind.HA]!!
        assertTrue(why, "only open to administrators" in why)
        assertEquals(listOf("s1"), sessions)                       // no endless renewing
    }

    @Test fun ingress_path_from_what_is_pasted() {
        assertEquals("/api/hassio_ingress/abc_DEF-123456789012", HaIngress.ingressPath("https://ha.example.org/api/hassio_ingress/abc_DEF-123456789012/"))
        assertEquals("/api/hassio_ingress/s65bor48v40w3r0m8v", HaIngress.ingressPath("s65bor48v40w3r0m8v"))
        assertNull(HaIngress.ingressPath("a0d7b954_kobra"))       // the add-on slug is not the ingress token
        assertEquals("https://ha.example.org", HaIngress.normalizeUrl("ha.example.org/"))
        assertEquals("http://192.168.1.10:8123", HaIngress.normalizeUrl("http://192.168.1.10:8123"))
    }
}

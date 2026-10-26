package io.github.xnovosx.kobraspoolman.data

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import okhttp3.Interceptor
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import java.io.IOException
import java.util.concurrent.CompletableFuture
import java.util.concurrent.ExecutionException
import java.util.concurrent.TimeUnit
import java.util.concurrent.TimeoutException

/** Home Assistant refused or is not reachable - an IOException, so a bridge call through HA ends as "not reachable". */
class HaException(message: String) : IOException(message)

/**
 * Home Assistant as the way to the bridge from outside, when the bridge runs as a HA add-on: the app logs in to HA's
 * WebSocket API with a long-lived token and asks the Supervisor for an ingress session (`supervisor/api`
 * POST `/ingress/session`); with the cookie `ingress_session` HA passes `/api/hassio_ingress/<token>/...` on to the
 * add-on. The bridge key goes along in `Authorization` - both proxies keep it, HA itself ignores a key it does not know.
 * A session lives 15 minutes after its last use (Supervisor ingress.py). Non-admin users get a session too (HA hassio
 * websocket_api, WS_NO_ADMIN_ENDPOINTS), but the Supervisor lets them through only to add-ons with
 * `panel_admin: false` - else 403 (addonRefused).
 */
class HaIngress(haUrl: String, private val token: String, private val http: OkHttpClient) {
    companion object {
        private val PATH = Regex("""/api/hassio_ingress/([A-Za-z0-9_-]+)""")
        private val TOKEN = Regex("""[A-Za-z0-9_-]{16,}""")

        /** "ha.example.org" -> "https://ha.example.org": from outside HA is nearly always reached over TLS. */
        fun normalizeUrl(input: String): String {
            val s = input.trim().trimEnd('/')
            if (s.isEmpty()) return s
            return if (s.startsWith("http://") || s.startsWith("https://")) s else "https://$s"
        }

        /** The ingress path from what the user pasted: the path, a whole URL with it, or only the token; null = none. */
        fun ingressPath(input: String): String? {
            val s = input.trim()
            PATH.find(s)?.let { return "/api/hassio_ingress/" + it.groupValues[1] }
            return if (TOKEN.matches(s)) "/api/hassio_ingress/$s" else null
        }

        /** HA's answer to a request through ingress without a valid session (plain text, not a bridge JSON error). */
        fun sessionRefused(resp: Response): Boolean = resp.code == 401 && !fromBridge(resp)

        /** The Supervisor refuses the add-on to this HA user (admin-only add-on, non-admin user). */
        fun addonRefused(resp: Response): Boolean = resp.code == 403 && !fromBridge(resp)

        private fun fromBridge(resp: Response) = resp.header("Content-Type")?.contains("application/json") == true
    }

    val base = normalizeUrl(haUrl)

    /** A new ingress session (blocking, at most 15 s - runs on OkHttp's or an IO thread). */
    fun newSession(): String {
        val result = CompletableFuture<String>()
        val ws = http.newWebSocket(Request.Builder().url("$base/api/websocket").build(), object : WebSocketListener() {
            override fun onMessage(webSocket: WebSocket, text: String) {
                val msg = runCatching { BridgeClient.json.parseToJsonElement(text).jsonObject }.getOrNull() ?: return
                when (msg.str("type")) {
                    "auth_required" -> webSocket.send(buildJsonObject { put("type", "auth"); put("access_token", token) }.toString())
                    "auth_ok" -> webSocket.send(buildJsonObject {
                        put("id", 1); put("type", "supervisor/api"); put("endpoint", "/ingress/session"); put("method", "post")
                    }.toString())
                    "auth_invalid" -> result.completeExceptionally(
                        HaException(tr("Home Assistant refused the token – check the long-lived token")))
                    "result" -> if (msg["id"]?.jsonPrimitive?.intOrNull == 1) {
                        val session = (msg["result"] as? JsonObject)?.str("session")
                        if (msg["success"]?.jsonPrimitive?.booleanOrNull == true && !session.isNullOrBlank()) result.complete(session)
                        else result.completeExceptionally(HaException(tr("Home Assistant gave no ingress session ({detail}) – is the bridge a Home Assistant add-on?",
                            "detail" to ((msg["error"] as? JsonObject)?.str("message") ?: "?"))))
                    }
                }
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                result.completeExceptionally(HaException(tr("Home Assistant not reachable ({detail})",
                    "detail" to (response?.let { "HTTP ${it.code}" } ?: t.message ?: t.javaClass.simpleName))))
            }
        })
        try {
            return result.get(15, TimeUnit.SECONDS)
        } catch (e: ExecutionException) {
            throw e.cause as? HaException ?: HaException(e.cause?.message ?: "?")
        } catch (e: TimeoutException) {
            throw HaException(tr("Home Assistant not reachable ({detail})", "detail" to "timeout"))
        } finally {
            ws.close(1000, null)
        }
    }

    private fun JsonObject.str(key: String): String? = this[key]?.jsonPrimitive?.contentOrNull
}

/**
 * The current ingress session: fetched on first use, renewed when HA refuses it or when it has been idle for so long
 * that it ran out (15 min sliding window - renewing a little earlier saves a refused round trip).
 */
class IngressSession(private val ha: HaIngress, private val clock: () -> Long = System::currentTimeMillis) {
    private var session: String? = null
    private var usedAt = 0L

    @Synchronized
    fun current(): String {
        val s = session
        if (s != null && clock() - usedAt < IDLE_MS) return s.also { usedAt = clock() }
        return renew(s)
    }

    /** A new session unless another request renewed it in the meantime (then that one). */
    @Synchronized
    fun renew(old: String?): String {
        session?.takeIf { it != old }?.let { return it }
        return ha.newSession().also { session = it; usedAt = clock() }
    }

    /** For the WebView (3D view): cookie for the HA address. */
    val cookie: String? @Synchronized get() = session?.let { "ingress_session=$it" }

    private companion object { const val IDLE_MS = 14 * 60_000L }
}

/** Adds the ingress session to every request through HA; a refused session is renewed once and the request repeated. */
class IngressCookie(private val session: IngressSession) : Interceptor {
    override fun intercept(chain: Interceptor.Chain): Response {
        val s = session.current()
        var resp = chain.proceed(chain.request().withSession(s))
        if (HaIngress.sessionRefused(resp)) {
            resp.close()
            resp = chain.proceed(chain.request().withSession(session.renew(s)))
        }
        if (HaIngress.addonRefused(resp)) {
            resp.close()
            throw HaException(tr("Home Assistant refuses this user the add-on – it is only open to administrators"))
        }
        return resp
    }

    private fun Request.withSession(s: String) = newBuilder().header("Cookie", "ingress_session=$s").build()
}

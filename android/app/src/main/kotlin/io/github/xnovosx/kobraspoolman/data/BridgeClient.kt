package io.github.xnovosx.kobraspoolman.data

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.KSerializer
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.IOException
import java.util.concurrent.TimeUnit

/** Fehler der Bridge mit ihrer Meldung ({"error": "..."}) und dem HTTP-Status (0 = nicht erreichbar). */
class BridgeException(val status: Int, message: String) : Exception(message)

/** HTTP-Zugriff auf die ace-lane-bridge. Schreibende Aufrufe senden den App-Schluessel. */
class BridgeClient(
    private val baseUrl: String,
    private val token: String,
    private val http: OkHttpClient = defaultHttp,
) {
    companion object {
        val json = Json { ignoreUnknownKeys = true; explicitNulls = false }
        private val JSON_TYPE = "application/json".toMediaType()
        val defaultHttp: OkHttpClient = OkHttpClient.Builder()
            .connectTimeout(4, TimeUnit.SECONDS)
            .readTimeout(15, TimeUnit.SECONDS)
            .build()

        /** "10.0.0.19:7913" -> "http://10.0.0.19:7913", ohne Schraegstrich am Ende. */
        fun normalizeUrl(input: String): String {
            val s = input.trim().trimEnd('/')
            if (s.isEmpty()) return s
            return if (s.startsWith("http://") || s.startsWith("https://")) s else "http://$s"
        }
    }

    private val base = normalizeUrl(baseUrl)

    private suspend fun <T> call(method: String, path: String, bodyJson: String?, out: KSerializer<T>): T =
        withContext(Dispatchers.IO) {
            val builder = Request.Builder().url(base + path)
            if (method != "GET" && token.isNotBlank()) builder.header("Authorization", "Bearer $token")
            builder.method(method, bodyJson?.toRequestBody(JSON_TYPE) ?: if (method == "GET") null else "{}".toRequestBody(JSON_TYPE))
            try {
                http.newCall(builder.build()).execute().use { resp ->
                    val text = resp.body.string()
                    if (!resp.isSuccessful) {
                        val msg = runCatching { json.decodeFromString(ApiError.serializer(), text).error }.getOrNull()
                        throw BridgeException(resp.code, msg?.takeIf { it.isNotBlank() } ?: "HTTP ${resp.code}")
                    }
                    json.decodeFromString(out, text)
                }
            } catch (e: IOException) {
                throw BridgeException(0, "Bridge nicht erreichbar (${e.message ?: e.javaClass.simpleName})")
            }
        }

    suspend fun health(): Health = call("GET", "/api/health", null, Health.serializer())
    suspend fun state(): AppState = call("GET", "/api/app/state", null, AppState.serializer())
    suspend fun catalog(): Catalog = call("GET", "/api/app/catalog", null, Catalog.serializer())
    suspend fun spool(id: Int): SpoolDetail = call("GET", "/api/app/spool/$id", null, SpoolDetail.serializer())
    suspend fun spoolByTag(uid: String): SpoolInfo =
        call("GET", "/api/app/tag/$uid", null, SpoolResponse.serializer()).spool

    suspend fun createSpool(req: NewSpool): SpoolInfo =
        call("POST", "/api/app/spool", json.encodeToString(NewSpool.serializer(), req), SpoolResponse.serializer()).spool

    suspend fun moveSpool(id: Int, slot: Int?): SpoolInfo =
        call("POST", "/api/app/spool/$id/location", json.encodeToString(LocationChange.serializer(), LocationChange(slot)),
            SpoolResponse.serializer()).spool

    suspend fun archiveSpool(id: Int) {
        call("POST", "/api/app/spool/$id/archive", null, ApiError.serializer())
    }

    suspend fun createVendor(name: String): Vendor =
        call("POST", "/api/app/vendor", json.encodeToString(JsonObject.serializer(),
            JsonObject(mapOf("name" to JsonPrimitive(name)))), VendorResponse.serializer()).vendor

    /** Filament anlegen; body = nur die gesetzten Felder (siehe FilamentDraft.toJson). */
    suspend fun createFilament(body: JsonObject): FilamentInfo =
        call("POST", "/api/app/filament", json.encodeToString(JsonObject.serializer(), body), FilamentResponse.serializer()).filament

    suspend fun dryerStart(temp: Int?, hours: Double?) {
        call("POST", "/api/dryer/start", json.encodeToString(DryerStart.serializer(), DryerStart(temp, hours)), ApiError.serializer())
    }

    suspend fun dryerStop() {
        call("POST", "/api/dryer/stop", "{}", ApiError.serializer())
    }

    suspend fun dryerConfig(c: DryerConfig) {
        call("POST", "/api/dryer/config", json.encodeToString(DryerConfig.serializer(), c), ApiError.serializer())
    }

    suspend fun issueTag(spoolId: Int): TagIssue =
        call("POST", "/api/app/tag/issue", json.encodeToString(SpoolIdBody.serializer(), SpoolIdBody(spoolId)),
            TagIssue.serializer())

    suspend fun linkTag(spoolId: Int, uid: String, force: Boolean = false): SpoolInfo =
        call("POST", "/api/app/tag/link", json.encodeToString(TagLink.serializer(), TagLink(spoolId, uid, force)),
            SpoolResponse.serializer()).spool
}

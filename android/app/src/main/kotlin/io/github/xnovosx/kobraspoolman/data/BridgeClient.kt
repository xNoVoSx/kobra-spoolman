package io.github.xnovosx.kobraspoolman.data

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.flowOn
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

        /** "192.168.1.10:7913" -> "http://192.168.1.10:7913", ohne Schraegstrich am Ende. */
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
            // Immer mitschicken: die Bridge erkennt daran das gekoppelte Geraet (auch beim Lesen, fuer can_write)
            if (token.isNotBlank()) builder.header("Authorization", "Bearer $token")
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

    /** Bild der Bridge (Kamera, Druckvorschau); null, wenn es gerade keins gibt (404/503). */
    suspend fun image(path: String): ByteArray? = withContext(Dispatchers.IO) {
        val builder = Request.Builder().url(base + path)
        if (token.isNotBlank()) builder.header("Authorization", "Bearer $token")
        try {
            http.newCall(builder.build()).execute().use { resp ->
                when {
                    resp.isSuccessful -> resp.body.bytes()
                    resp.code == 404 || resp.code == 503 -> null
                    else -> throw BridgeException(resp.code, "HTTP ${resp.code}")
                }
            }
        } catch (e: IOException) {
            throw BridgeException(0, "Bridge nicht erreichbar (${e.message ?: e.javaClass.simpleName})")
        }
    }

    /**
     * Kamera live: Restream der Bridge (eine Verbindung zum Drucker fuer alle Zuschauer). Laeuft, solange
     * gesammelt wird; Fehler beenden den Flow mit BridgeException.
     */
    fun cameraStream(): Flow<ByteArray> = flow {
        val builder = Request.Builder().url("$base/api/camera/stream.mjpg")
        if (token.isNotBlank()) builder.header("Authorization", "Bearer $token")
        val call = http.newCall(builder.build())
        try {
            call.execute().use { resp ->
                if (!resp.isSuccessful) {
                    val msg = runCatching { json.decodeFromString(ApiError.serializer(), resp.body.string()).error }.getOrNull()
                    throw BridgeException(resp.code, msg?.takeIf { it.isNotBlank() } ?: "HTTP ${resp.code}")
                }
                val reader = MjpegReader(resp.body.byteStream())
                while (true) emit(reader.next() ?: break)
            }
        } catch (e: IOException) {
            throw BridgeException(0, "Kamera unterbrochen (${e.message ?: e.javaClass.simpleName})")
        } finally {
            call.cancel()
        }
    }.flowOn(Dispatchers.IO)

    suspend fun jobs(): List<PrintJob> = call("GET", "/api/jobs", null, PrintJobList.serializer()).jobs
    suspend fun console(after: Long): ConsoleLines = call("GET", "/api/console?after=$after", null, ConsoleLines.serializer())
    suspend fun logs(after: Long, level: String): LogLines =
        call("GET", "/api/logs?after=$after&level=$level", null, LogLines.serializer())

    suspend fun printInfo(): PrintInfo = call("GET", "/api/print/info", null, PrintInfo.serializer())

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

    suspend fun authStatus(): AuthStatus = call("GET", "/api/auth/status", null, AuthStatus.serializer())

    suspend fun pair(code: String, name: String): PairResult =
        call("POST", "/api/auth/pair", json.encodeToString(PairRequest.serializer(), PairRequest(code, name, "app")),
            PairResult.serializer())

    suspend fun newPairingCode(): PairingCode = call("POST", "/api/auth/code", "{}", PairingCode.serializer())
    suspend fun devices(): List<Device> = call("GET", "/api/auth/devices", null, DeviceList.serializer()).devices
    suspend fun removeDevice(id: String) {
        call("DELETE", "/api/auth/devices/$id", null, ApiError.serializer())
    }

    /** pause, resume, cancel, emergency_stop - die App hat vorher selbst nachgefragt (confirm). */
    suspend fun printAction(action: String) {
        call("POST", "/api/print/$action", "{\"confirm\":true}", ApiError.serializer())
    }

    /** Nachjustieren: {speed, flow, fans: {part, box, filter}, nozzle, bed}. */
    suspend fun tune(body: JsonObject) {
        call("POST", "/api/print/tune", body.toString(), ApiError.serializer())
    }

    suspend fun dryerStart(temp: Int?, hours: Double?) {
        call("POST", "/api/dryer/start", json.encodeToString(DryerStart.serializer(), DryerStart(temp, hours)), ApiError.serializer())
    }

    suspend fun dryerStop() {
        call("POST", "/api/dryer/stop", "{}", ApiError.serializer())
    }

    suspend fun dryerConfig(c: DryerConfig) {
        call("POST", "/api/dryer/config", json.encodeToString(DryerConfig.serializer(), c), ApiError.serializer())
    }

    suspend fun dryerSchedule(atEpochS: Double, temp: Int?, hours: Double?) {
        call("POST", "/api/dryer/schedule", json.encodeToString(DrySchedule.serializer(),
            DrySchedule(atEpochS, temp?.toDouble(), hours)), ApiError.serializer())
    }

    suspend fun clearDryerSchedule() {
        call("DELETE", "/api/dryer/schedule", null, ApiError.serializer())
    }

    /** ACE-Einstellungen und Spuel-Vorschau; mit multiplier fuer einen gewuenschten Wert. */
    suspend fun ace(multiplier: Double? = null): AceResponse =
        call("GET", "/api/ace" + (multiplier?.let { "?multiplier=$it" } ?: ""), null, AceResponse.serializer())

    suspend fun setFlushMultiplier(value: Double, confirmPrinting: Boolean) {
        call("POST", "/api/ace/flush", json.encodeToString(FlushChange.serializer(), FlushChange(value, confirmPrinting)),
            ApiError.serializer())
    }

    suspend fun setAceOption(key: String, value: Boolean, confirmPrinting: Boolean) {
        call("POST", "/api/ace/options", json.encodeToString(JsonObject.serializer(), JsonObject(mapOf(
            key to JsonPrimitive(value), "confirm_printing" to JsonPrimitive(confirmPrinting)))), ApiError.serializer())
    }

    suspend fun issueTag(spoolId: Int): TagIssue =
        call("POST", "/api/app/tag/issue", json.encodeToString(SpoolIdBody.serializer(), SpoolIdBody(spoolId)),
            TagIssue.serializer())

    suspend fun linkTag(spoolId: Int, uid: String, force: Boolean = false): SpoolInfo =
        call("POST", "/api/app/tag/link", json.encodeToString(TagLink.serializer(), TagLink(spoolId, uid, force)),
            SpoolResponse.serializer()).spool
}

package io.github.xnovosx.kobraspoolman.data

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.flowOn
import kotlinx.coroutines.withContext
import kotlinx.serialization.KSerializer
import kotlinx.serialization.SerializationException
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
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
                    try {
                        json.decodeFromString(out, text)
                    } catch (e: SerializationException) {
                        // andere Bridge-Version: nie abstuerzen, sondern melden
                        throw BridgeException(0, "Antwort der Bridge nicht lesbar – App und Bridge auf denselben Stand bringen " +
                            "(${e.message?.substringBefore('\n')?.take(120)})")
                    }
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

    suspend fun appUpdate(): AppUpdate = call("GET", "/api/app/update", null, AppUpdate.serializer())

    /** APK von der Bridge in eine Datei laden; progress bekommt 0..1. */
    suspend fun download(path: String, dest: java.io.File, progress: (Float) -> Unit) = withContext(Dispatchers.IO) {
        val req = Request.Builder().url(base + path).build()
        try {
            http.newBuilder().readTimeout(60, TimeUnit.SECONDS).build().newCall(req).execute().use { resp ->
                if (!resp.isSuccessful) throw BridgeException(resp.code, "Download fehlgeschlagen (HTTP ${resp.code})")
                val total = resp.body.contentLength().takeIf { it > 0 } ?: -1L
                dest.parentFile?.mkdirs()
                resp.body.byteStream().use { input ->
                    dest.outputStream().use { out ->
                        val buf = ByteArray(64 * 1024)
                        var done = 0L
                        while (true) {
                            val n = input.read(buf)
                            if (n < 0) break
                            out.write(buf, 0, n)
                            done += n
                            if (total > 0) progress(done.toFloat() / total)
                        }
                    }
                }
            }
        } catch (e: IOException) {
            throw BridgeException(0, "Download abgebrochen (${e.message ?: e.javaClass.simpleName})")
        }
    }

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

    /** pause, resume, cancel, emergency_stop, firmware_restart - die App hat vorher selbst nachgefragt (confirm). */
    suspend fun printAction(action: String) {
        call("POST", "/api/print/$action", "{\"confirm\":true}", ApiError.serializer())
    }

    suspend fun humidity(hours: Int): HumidityData = call("GET", "/api/humidity?hours=$hours", null, HumidityData.serializer())
    suspend fun spoolMoisture(id: Int): SpoolMoistureFull =
        call("GET", "/api/spool/$id/moisture", null, SpoolMoistureFull.serializer())

    /** Ausserhalb der ACE getrocknet (eigener Trockner). */
    suspend fun spoolDried(id: Int, temp: Int, minutes: Double) {
        call("POST", "/api/spool/$id/dried", buildJsonObject { put("temp", temp); put("minutes", minutes) }.toString(),
            ApiError.serializer())
    }

    suspend fun vision(): VisionFull = call("GET", "/api/vision", null, VisionFull.serializer())

    /** KI-Einstellungen aendern - nur die mitgeschickten Felder. */
    suspend fun visionSettings(changes: JsonObject) {
        call("POST", "/api/vision/settings", changes.toString(), ApiError.serializer())
    }

    /** Diesen Druck (nicht) ueberwachen. */
    suspend fun visionMute(on: Boolean) {
        call("POST", "/api/vision/mute", buildJsonObject { put("on", on) }.toString(), ApiError.serializer())
    }

    /** KI-Ereignis bewerten: false_alarm (KI fuer den Rest des Drucks still) oder confirmed. */
    suspend fun visionFeedback(eventId: String, verdict: String) {
        call("POST", "/api/vision/feedback", buildJsonObject { put("id", eventId); put("verdict", verdict) }.toString(),
            ApiError.serializer())
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

    /** Endlosspule (endless_spool: Boolean) oder ihr Modus (endless_mode: exact | material | next). */
    suspend fun setAceOption(key: String, value: JsonPrimitive): AceSettings =
        call("POST", "/api/ace/options", json.encodeToString(JsonObject.serializer(), JsonObject(mapOf(key to value))),
            AceResponse.serializer()).settings

    /** Auto-PA-Schalter in Klipper (null = unveraendert). */
    suspend fun paSwitch(enabled: Boolean?, auto: Boolean?) {
        val body = buildMap<String, JsonPrimitive> {
            enabled?.let { put("enabled", JsonPrimitive(it)) }
            auto?.let { put("auto", JsonPrimitive(it)) }
        }
        call("POST", "/api/pa/switch", json.encodeToString(JsonObject.serializer(), JsonObject(body)), ApiError.serializer())
    }

    /** PA jetzt messen (nur ohne Druck; Ergebnis kommt nach ~2 min ueber den Status). */
    suspend fun paCalibrate(slot: Int) {
        call("POST", "/api/pa/calibrate", "{\"slot\":$slot}", ApiError.serializer())
    }

    /** PA eines Filaments in Spoolman loeschen - beim naechsten Druck wird neu gemessen. */
    suspend fun paForget(filamentId: Int) {
        call("POST", "/api/pa/forget", "{\"filament_id\":$filamentId}", ApiError.serializer())
    }

    suspend fun issueTag(spoolId: Int): TagIssue =
        call("POST", "/api/app/tag/issue", json.encodeToString(SpoolIdBody.serializer(), SpoolIdBody(spoolId)),
            TagIssue.serializer())

    suspend fun linkTag(spoolId: Int, uid: String, force: Boolean = false, reset: Boolean = true): SpoolInfo =
        call("POST", "/api/app/tag/link", json.encodeToString(TagLink.serializer(), TagLink(spoolId, uid, force, reset)),
            SpoolResponse.serializer()).spool
}

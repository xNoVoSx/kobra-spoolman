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

/** Error of the bridge with its message ({"error": "..."}) and the HTTP status (0 = not reachable). */
class BridgeException(val status: Int, message: String) : Exception(message)

/**
 * HTTP access to the ace-lane-bridge. Writing calls send the app key; every request carries the app language (X-Lang),
 * so messages of the bridge come in the same language as the app.
 */
class BridgeClient(
    private val baseUrl: String,
    private val token: String,
    private val http: OkHttpClient = defaultHttp,
) {
    companion object {
        // coerceInputValues: null for a field with a default -> default (a bridge answer must never break the app)
        val json = Json { ignoreUnknownKeys = true; explicitNulls = false; coerceInputValues = true }
        private val JSON_TYPE = "application/json".toMediaType()
        val defaultHttp: OkHttpClient = OkHttpClient.Builder()
            .connectTimeout(4, TimeUnit.SECONDS)
            .readTimeout(15, TimeUnit.SECONDS)
            .build()

        /** "192.168.1.10:7913" -> "http://192.168.1.10:7913", without a trailing slash. */
        fun normalizeUrl(input: String): String {
            val s = input.trim().trimEnd('/')
            if (s.isEmpty()) return s
            return if (s.startsWith("http://") || s.startsWith("https://")) s else "http://$s"
        }
    }

    private val base = normalizeUrl(baseUrl)

    /** Request with language and - always: the bridge recognises the paired device by it (also when reading, for
     *  can_write) - the key. */
    private fun request(url: String): Request.Builder {
        val builder = Request.Builder().url(url).header("X-Lang", I18n.lang)
        if (token.isNotBlank()) builder.header("Authorization", "Bearer $token")
        return builder
    }

    private suspend fun <T> call(method: String, path: String, bodyJson: String?, out: KSerializer<T>): T =
        withContext(Dispatchers.IO) {
            val builder = request(base + path)
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
                        // other bridge version: never crash, report it
                        throw BridgeException(0, tr("Bridge answer not readable – bring app and bridge to the same version ({detail})",
                            "detail" to e.message?.substringBefore('\n')?.take(120)))
                    }
                }
            } catch (e: IOException) {
                throw BridgeException(0, tr("Bridge not reachable ({detail})", "detail" to (e.message ?: e.javaClass.simpleName)))
            }
        }

    /** Image of the bridge (camera, print preview); null when there is none right now (404/503). */
    suspend fun image(path: String): ByteArray? = withContext(Dispatchers.IO) {
        val builder = request(base + path)
        try {
            http.newCall(builder.build()).execute().use { resp ->
                when {
                    resp.isSuccessful -> resp.body.bytes()
                    resp.code == 404 || resp.code == 503 -> null
                    else -> throw BridgeException(resp.code, "HTTP ${resp.code}")
                }
            }
        } catch (e: IOException) {
            throw BridgeException(0, tr("Bridge not reachable ({detail})", "detail" to (e.message ?: e.javaClass.simpleName)))
        }
    }

    /**
     * Live camera: restream of the bridge (one connection to the printer for all viewers). Runs while collected;
     * errors end the flow with BridgeException.
     */
    fun cameraStream(): Flow<ByteArray> = flow {
        val builder = request("$base/api/camera/stream.mjpg")
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
            throw BridgeException(0, tr("Camera interrupted ({detail})", "detail" to (e.message ?: e.javaClass.simpleName)))
        } finally {
            call.cancel()
        }
    }.flowOn(Dispatchers.IO)

    suspend fun appUpdate(): AppUpdate = call("GET", "/api/app/update", null, AppUpdate.serializer())

    /** Download the APK from the bridge into a file; progress gets 0..1. */
    suspend fun download(path: String, dest: java.io.File, progress: (Float) -> Unit) = withContext(Dispatchers.IO) {
        val req = Request.Builder().url(base + path).build()
        try {
            http.newBuilder().readTimeout(60, TimeUnit.SECONDS).build().newCall(req).execute().use { resp ->
                if (!resp.isSuccessful) throw BridgeException(resp.code, tr("Download failed (HTTP {code})", "code" to resp.code))
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
            throw BridgeException(0, tr("Download aborted ({detail})", "detail" to (e.message ?: e.javaClass.simpleName)))
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

    /** Create a filament; body = only the fields set (see FilamentDraft.toJson). */
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

    /** pause, resume, cancel, emergency_stop, firmware_restart - the app asked for confirmation itself (confirm). */
    suspend fun printAction(action: String): ActionResult =
        call("POST", "/api/print/$action", "{\"confirm\":true}", ActionResult.serializer())

    suspend fun humidity(hours: Int): HumidityData = call("GET", "/api/humidity?hours=$hours", null, HumidityData.serializer())
    suspend fun spoolMoisture(id: Int): SpoolMoistureFull =
        call("GET", "/api/spool/$id/moisture", null, SpoolMoistureFull.serializer())

    /** A drying run that did not dry: its spools go back to the moisture before it. */
    suspend fun discardDrying(id: String) {
        call("POST", "/api/humidity/sessions/$id/discard", "{}", ApiError.serializer())
    }

    /** Dried outside the ACE (own dryer). */
    suspend fun spoolDried(id: Int, temp: Int, minutes: Double) {
        call("POST", "/api/spool/$id/dried", buildJsonObject { put("temp", temp); put("minutes", minutes) }.toString(),
            ApiError.serializer())
    }

    suspend fun vision(): VisionFull = call("GET", "/api/vision", null, VisionFull.serializer())

    /** Change AI settings - only the fields sent. */
    suspend fun visionSettings(changes: JsonObject) {
        call("POST", "/api/vision/settings", changes.toString(), ApiError.serializer())
    }

    /** (Don't) watch this print. */
    suspend fun visionMute(on: Boolean) {
        call("POST", "/api/vision/mute", buildJsonObject { put("on", on) }.toString(), ApiError.serializer())
    }

    /** Rate an AI event: false_alarm (AI quiet for the rest of the print) or confirmed. */
    suspend fun visionFeedback(eventId: String, verdict: String) {
        call("POST", "/api/vision/feedback", buildJsonObject { put("id", eventId); put("verdict", verdict) }.toString(),
            ApiError.serializer())
    }

    /** Tune: {speed, flow, fans: {part, box, filter}, nozzle, bed}. */
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

    /**
     * ACE setting: endless_spool, endless_mode (ACEPRO), runout_detect, flush_multiplier (Rinkhals). Rinkhals refuses a change
     * during a print with 409 unless confirmPrinting (it applies from the next colour change).
     */
    suspend fun setAceOption(key: String, value: JsonPrimitive, confirmPrinting: Boolean = false): AceSettings {
        val body = if (confirmPrinting) mapOf(key to value, "confirm_printing" to JsonPrimitive(true)) else mapOf(key to value)
        return call("POST", "/api/ace/options", json.encodeToString(JsonObject.serializer(), JsonObject(body)),
            AceResponse.serializer()).settings
    }

    /** ACE settings and (Rinkhals) the purge per colour pair - with a wanted multiplier for "what if". */
    suspend fun ace(multiplier: Double? = null): AceResponse =
        call("GET", "/api/ace" + (multiplier?.let { "?multiplier=$it" } ?: ""), null, AceResponse.serializer())

    /** Auto PA switches in Klipper (null = unchanged). */
    suspend fun paSwitch(enabled: Boolean?, auto: Boolean?) {
        val body = buildMap<String, JsonPrimitive> {
            enabled?.let { put("enabled", JsonPrimitive(it)) }
            auto?.let { put("auto", JsonPrimitive(it)) }
        }
        call("POST", "/api/pa/switch", json.encodeToString(JsonObject.serializer(), JsonObject(body)), ApiError.serializer())
    }

    /** Resume the interrupted print (only after checking the part) or discard it. */
    suspend fun resume(start: Boolean) {
        if (start) call("POST", "/api/resume", "{\"confirm\":true}", ApiError.serializer())
        else call("POST", "/api/resume/discard", "{}", ApiError.serializer())
    }

    /** Clog detection: enabled and/or action (warn, pause); null = unchanged. */
    suspend fun clogSwitch(enabled: Boolean?, action: String?) {
        val parts = listOfNotNull(enabled?.let { "\"enabled\":$it" }, action?.let { "\"action\":\"$it\"" })
        call("POST", "/api/clog/switch", parts.joinToString(",", "{", "}"), ApiError.serializer())
    }

    /** Direct feed on (with the spool inserted in the toolhead, optionally unloading the ACE first) or off. */
    suspend fun direct(enable: Boolean, spoolId: Int?, unload: Boolean) {
        val body = if (enable) "{\"enable\":true,\"spool_id\":$spoolId,\"unload\":$unload}" else "{\"enable\":false}"
        call("POST", "/api/direct", body, ApiError.serializer())
    }

    /** Swappable hotends: hotend in use and/or the print start check (bridge nozzle.py). */
    suspend fun nozzle(hotend: String? = null, check: Boolean? = null) {
        val parts = listOfNotNull(hotend?.let { "\"hotend\":\"$it\"" }, check?.let { "\"check\":$it" })
        call("POST", "/api/nozzle", parts.joinToString(",", "{", "}"), ApiError.serializer())
    }

    /** Measure the PID of the hotend in use (a few minutes, the result arrives via the state). */
    suspend fun nozzlePid() {
        call("POST", "/api/nozzle/pid", "{}", ApiError.serializer())
    }

    /** All features of the system (one page, one switch each - bridge features.py). */
    suspend fun features(): Features = call("GET", "/api/features", null, Features.serializer())

    suspend fun switchFeature(key: String, on: Boolean) {
        call("POST", "/api/features/$key", "{\"on\":$on}", ApiError.serializer())
    }

    /** First start: what the bridge found and the features (setup page). */
    suspend fun setup(): SetupInfo = call("GET", "/api/setup", null, SetupInfo.serializer())

    /** The setup was gone through - the bridge does not open it by itself any more (also not in the web UI). */
    suspend fun setupDone() {
        call("POST", "/api/setup/done", "{}", ApiError.serializer())
    }

    /** Set a switch from /api/switches (e.g. usb_watch). */
    suspend fun setSwitch(key: String, value: Boolean) {
        call("POST", "/api/switch", "{\"key\":\"$key\",\"value\":$value}", ApiError.serializer())
    }

    suspend fun resumeSwitch(enabled: Boolean) {
        call("POST", "/api/resume/switch", "{\"enabled\":$enabled}", ApiError.serializer())
    }

    /** Measure PA now (only without a print; the result arrives after ~5 min via the state). */
    suspend fun paCalibrate(slot: Int) {
        call("POST", "/api/pa/calibrate", "{\"slot\":$slot}", ApiError.serializer())
    }

    /** Delete a filament's PA in Spoolman - it is measured again at the next print. */
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

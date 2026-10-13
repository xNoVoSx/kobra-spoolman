package io.github.xnovosx.kobraspoolman.ui

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import io.github.xnovosx.kobraspoolman.BuildConfig
import io.github.xnovosx.kobraspoolman.data.SpoolMoistureFull
import io.github.xnovosx.kobraspoolman.data.AcePurge
import io.github.xnovosx.kobraspoolman.data.HumidityData
import io.github.xnovosx.kobraspoolman.data.VisionFull
import io.github.xnovosx.kobraspoolman.data.AppState
import io.github.xnovosx.kobraspoolman.data.Features
import io.github.xnovosx.kobraspoolman.data.SetupInfo
import io.github.xnovosx.kobraspoolman.data.AppUpdate
import io.github.xnovosx.kobraspoolman.monitor.MonitorService
import io.github.xnovosx.kobraspoolman.update.Installer
import io.github.xnovosx.kobraspoolman.data.ConsoleLines
import io.github.xnovosx.kobraspoolman.data.PrintJob
import io.github.xnovosx.kobraspoolman.data.LogLines
import io.github.xnovosx.kobraspoolman.data.BridgeClient
import io.github.xnovosx.kobraspoolman.data.BridgeException
import io.github.xnovosx.kobraspoolman.data.Catalog
import io.github.xnovosx.kobraspoolman.data.Connection
import io.github.xnovosx.kobraspoolman.data.Device
import io.github.xnovosx.kobraspoolman.data.PairingCode
import io.github.xnovosx.kobraspoolman.data.DryerConfig
import io.github.xnovosx.kobraspoolman.data.PrintInfo
import io.github.xnovosx.kobraspoolman.data.FieldSpec
import io.github.xnovosx.kobraspoolman.data.FilamentDraft
import io.github.xnovosx.kobraspoolman.data.NewSpool
import io.github.xnovosx.kobraspoolman.data.Settings
import io.github.xnovosx.kobraspoolman.data.SpoolDetail
import io.github.xnovosx.kobraspoolman.data.SpoolInfo
import io.github.xnovosx.kobraspoolman.data.TagContent
import io.github.xnovosx.kobraspoolman.data.I18n
import io.github.xnovosx.kobraspoolman.data.tr
import io.github.xnovosx.kobraspoolman.nfc.AceTag
import io.github.xnovosx.kobraspoolman.nfc.ScannedTag
import io.github.xnovosx.kobraspoolman.nfc.TagScanner
import io.github.xnovosx.kobraspoolman.nfc.WriteResult
import io.github.xnovosx.kobraspoolman.nfc.toAceTag
import kotlinx.coroutines.Job
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.emptyFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonPrimitive

/** What the UI should do after a scan. */
sealed interface ScanResult {
    data class Known(val spoolId: Int) : ScanResult
    /** blank: the tag has no ACE content (empty sticker) - then write it instead of linking. */
    data class Unknown(val uid: String, val blank: Boolean = false) : ScanResult
}

class AppViewModel(app: Application) : AndroidViewModel(app) {
    private val settings = Settings(app)

    val connection: StateFlow<Connection?> = settings.connection
        .stateIn(viewModelScope, SharingStarted.Eagerly, null)

    private val _state = MutableStateFlow<AppState?>(null)
    val state: StateFlow<AppState?> = _state
    private val _error = MutableStateFlow<String?>(null)
    val error: StateFlow<String?> = _error
    private val _catalog = MutableStateFlow<Catalog?>(null)
    val catalog: StateFlow<Catalog?> = _catalog
    private val _detail = MutableStateFlow<SpoolDetail?>(null)
    val detail: StateFlow<SpoolDetail?> = _detail
    private val _createdFilament = MutableStateFlow<Int?>(null)
    /** Filament created last in the app - "New spool" preselects it. */
    val createdFilament: StateFlow<Int?> = _createdFilament
    /** Tag that is about to be written (spool + content), null = no write job. */
    /** side 1/2: the ACE 2 Pro needs one tag per spool side, both with the same content. */
    data class TagJob(val spoolId: Int, val content: TagContent, val ace: AceTag, val side: Int = 1, val firstUid: String? = null)
    private val _tagJob = MutableStateFlow<TagJob?>(null)
    val tagJob: StateFlow<TagJob?> = _tagJob
    private val _me = MutableStateFlow<Device?>(null)
    /** This device according to the bridge (null = not paired or bridge not reachable). */
    val me: StateFlow<Device?> = _me
    private val _meChecked = MutableStateFlow(false)
    /** true once the bridge answered - then me == null means: key invalid. */
    val meChecked: StateFlow<Boolean> = _meChecked
    private val _devices = MutableStateFlow<List<Device>>(emptyList())
    val devices: StateFlow<List<Device>> = _devices
    private val _pairingCode = MutableStateFlow<PairingCode?>(null)
    val pairingCode: StateFlow<PairingCode?> = _pairingCode
    private val _busy = MutableStateFlow(false)
    val busy: StateFlow<Boolean> = _busy

    private val _messages = Channel<String>(Channel.BUFFERED)
    val messages = _messages.receiveAsFlow()
    private val _scans = Channel<ScanResult>(Channel.BUFFERED)
    val scans = _scans.receiveAsFlow()

    private var polling: Job? = null

    private fun client(): BridgeClient? =
        connection.value?.takeIf { it.configured }?.let { BridgeClient(it.url, it.token) }

    // ------------------------------------------------------------ loading
    fun startPolling() {
        if (polling?.isActive == true) return
        polling = viewModelScope.launch {
            while (isActive) {
                refresh()
                delay(3000)
            }
        }
    }

    fun stopPolling() {
        polling?.cancel()
        polling = null
    }

    fun refreshNow() = viewModelScope.launch { refresh() }

    suspend fun refresh() {
        val c = client() ?: return
        try {
            _state.value = c.state()
            _error.value = null
        } catch (e: BridgeException) {
            _error.value = e.message
        }
    }

    fun loadCatalog() = launchSafe(showBusy = false) { _catalog.value = it.catalog() }

    fun loadSpool(id: Int) {
        if (_detail.value?.spool?.spoolId != id) _detail.value = null
        launchSafe(showBusy = false) { _detail.value = it.spool(id) }
    }

    // ------------------------------------------------------------ actions
    fun moveSpool(id: Int, slot: Int?) = launchSafe {
        it.moveSpool(id, slot)
        _messages.send(if (slot == null) tr("Put on the shelf") else tr("Put into slot {slot}", "slot" to slot))
        _detail.value = it.spool(id)
        refresh()
    }

    fun archiveSpool(id: Int, done: () -> Unit) = launchSafe {
        it.archiveSpool(id)
        _messages.send(tr("Spool archived"))
        refresh()
        done()
    }

    fun createSpool(req: NewSpool, tagUid: String?, done: (SpoolInfo) -> Unit) = launchSafe {
        var spool = it.createSpool(req)
        if (tagUid != null) spool = it.linkTag(spool.spoolId, tagUid)
        _messages.send(if (tagUid != null) tr("Spool #{id} created and linked to the tag", "id" to spool.spoolId) else tr("Spool #{id} created", "id" to spool.spoolId))
        refresh()
        done(spool)
    }

    fun createFilament(draft: FilamentDraft, specs: List<FieldSpec>, done: () -> Unit) = launchSafe {
        val vendorId = draft.vendorId ?: it.createVendor(draft.newVendor.trim()).id
        val fil = it.createFilament(draft.toJson(specs, vendorId))
        _createdFilament.value = fil.filamentId
        _catalog.value = it.catalog()
        _messages.send(tr("Filament “{name}” created", "name" to fil.displayName))
        done()
    }

    /** Get a tag number and have the next tag put on written with it. */
    /** side 2 = only write the tag for the second spool side (the first is already linked). */
    fun prepareTag(spoolId: Int, scanner: TagScanner, side: Int = 1) = launchSafe {
        _tagJob.value = null
        val issue = it.issueTag(spoolId)
        val ace = try { issue.tag.toAceTag() } catch (e: IllegalStateException) {
            _messages.send(e.message ?: tr("Tag content incomplete")); return@launchSafe
        } catch (e: IllegalArgumentException) {
            _messages.send(e.message ?: tr("Tag content incomplete")); return@launchSafe
        }
        scanner.armWrite(ace.encode())
        val first = if (side == 2) state.value?.let { s -> (s.slots.mapNotNull { it.spool } + s.shelf)
            .firstOrNull { it.spoolId == spoolId }?.nfcUids?.firstOrNull() } else null
        _tagJob.value = TagJob(spoolId, issue.tag, ace, side, first)
    }

    fun cancelTag(scanner: TagScanner) {
        scanner.disarm()
        _tagJob.value = null
    }

    /**
 * The tag is written: link its ID with the spool. After the first tag it goes straight on to the
 * second (same content, other spool side); the same sticker does not count as the second one.
     */
    fun onTagWritten(r: WriteResult, scanner: TagScanner, done: (Int) -> Unit) = launchSafe {
        val job = _tagJob.value ?: return@launchSafe
        when (r) {
            is WriteResult.Failed -> _messages.send(r.message)
            is WriteResult.Written -> when {
                job.side == 1 -> {
                    it.linkTag(job.spoolId, r.uid, force = true, reset = true)
                    scanner.armWrite(job.ace.encode())
                    _tagJob.value = job.copy(side = 2, firstUid = r.uid)
                    _messages.send(tr("Tag 1 written – now the second sticker for the other spool side"))
                }
                r.uid == job.firstUid -> {
                    scanner.armWrite(job.ace.encode())
                    _messages.send(tr("That is the same sticker – please hold the second one to the phone"))
                }
                else -> {
                    it.linkTag(job.spoolId, r.uid, force = true, reset = false)
                    _tagJob.value = null
                    _messages.send(tr("Both tags {sku} written and linked to spool #{id}", "sku" to job.content.sku, "id" to job.spoolId))
                    refresh()
                    done(job.spoolId)
                }
            }
        }
    }

    fun dryerStart(temp: Int?, hours: Double?) = launchSafe {
        it.dryerStart(temp, hours)
        _messages.send(tr("Drying started"))
        refresh()
    }

    fun dryerStop() = launchSafe {
        it.dryerStop()
        _messages.send(tr("Drying stopped"))
        refresh()
    }

    fun dryerConfig(c: DryerConfig) = launchSafe {
        it.dryerConfig(c)
        _messages.send(if (c.enabled) tr("Automatic saved: from {start} %, until {stop} %", "start" to c.startAbove.toInt(), "stop" to c.stopBelow.toInt()) else tr("Automatic off"))
        refresh()
    }

    /** ACE setting (see BridgeClient.setAceOption); confirmPrinting = the user agreed to a change during a print. */
    fun setAceOption(key: String, value: JsonPrimitive, confirmPrinting: Boolean = false) = launchSafe {
        it.setAceOption(key, value, confirmPrinting)
        _messages.send(tr("ACE: saved"))
        refresh()
    }

    fun paSwitch(enabled: Boolean? = null, auto: Boolean? = null) = launchSafe {
        it.paSwitch(enabled, auto)
        refresh()
    }

    fun resume(start: Boolean) = launchSafe {
        it.resume(start)
        _messages.send(if (start) tr("Resume started – heating, probing, printing on") else tr("Interrupted print discarded"))
        refresh()
    }

    fun clogSwitch(enabled: Boolean? = null, action: String? = null) = launchSafe {
        it.clogSwitch(enabled, action)
        refresh()
    }

    fun setSwitch(key: String, value: Boolean) = launchSafe {
        it.setSwitch(key, value)
        refresh()
    }

    fun resumeSwitch(enabled: Boolean) = launchSafe {
        it.resumeSwitch(enabled)
        refresh()
    }

    fun paCalibrate(slot: Int) = launchSafe {
        it.paCalibrate(slot)
        _messages.send(tr("PA measurement running – result in ~2 minutes"))
        refresh()
    }

    fun paForget(filamentId: Int) = launchSafe {
        it.paForget(filamentId)
        _messages.send(tr("PA discarded – measured again at the next print"))
        refresh()
    }

    fun dryerSchedule(atEpochS: Double, temp: Int?, hours: Double?) = launchSafe {
        it.dryerSchedule(atEpochS, temp, hours)
        _messages.send(tr("Drying scheduled"))
        refresh()
    }

    fun clearDryerSchedule() = launchSafe {
        it.clearDryerSchedule()
        _messages.send(tr("Schedule deleted"))
        refresh()
    }

    /** Get an image from the bridge (camera only when paired); null on error or without an image. */
    suspend fun image(path: String): ByteArray? = runCatching { client()?.image(path) }.getOrNull()

    fun printAction(action: String, done: String) = launchSafe {
        it.printAction(action)
        _messages.send(done)
        refresh()
    }

    // ------------------------------------------------ 3D model
    val render3d: StateFlow<String> = settings.render3d.stateIn(viewModelScope, SharingStarted.Eagerly, "auto")

    fun setRender3d(v: String) = viewModelScope.launch { settings.setRender3d(v) }

    /** Address of the bridge's 3D view (/viewer, in the app language) - null: show the bridge image. */
    fun viewerUrl(c: Connection?, mode: String): String? =
        if (c == null || !c.configured || mode == "image") null
        else BridgeClient.normalizeUrl(c.url) + "/viewer?q=" + mode + "&lang=" + I18n.lang

    // ------------------------------------------------ humidity
    suspend fun humidity(hours: Int): HumidityData? = runCatching { client()?.humidity(hours) }.getOrNull()
    suspend fun spoolMoisture(id: Int): SpoolMoistureFull? = runCatching { client()?.spoolMoisture(id) }.getOrNull()

    fun spoolDried(id: Int, temp: Int, hours: Double, done: () -> Unit) = launchSafe {
        it.spoolDried(id, temp, hours * 60)
        _messages.send(tr("Marked as dried"))
        done()
    }

    // ------------------------------------------------ AI
    suspend fun vision(): VisionFull? = runCatching { client()?.vision() }.getOrNull()

    fun visionSettings(changes: kotlinx.serialization.json.JsonObject, done: () -> Unit) = launchSafe {
        it.visionSettings(changes)
        _messages.send(tr("AI setting saved"))
        done()
    }

    fun visionMute(on: Boolean, done: () -> Unit) = launchSafe {
        it.visionMute(on)
        _messages.send(if (on) tr("This print is not watched") else tr("The AI is watching again"))
        done()
    }

    fun visionFeedback(id: String, verdict: String, done: () -> Unit) = launchSafe {
        it.visionFeedback(id, verdict)
        _messages.send(if (verdict == "false_alarm") tr("Marked as a false alarm") else tr("Marked as a failure"))
        done()
    }

    fun tune(body: kotlinx.serialization.json.JsonObject) = launchSafe {
        it.tune(body)
        _messages.send(tr("Applied"))
        refresh()
    }

    // ------------------------------------------------ print monitoring in the background
    val monitor: StateFlow<Boolean> = settings.monitor.stateIn(viewModelScope, SharingStarted.Eagerly, true)

    fun setMonitor(on: Boolean) = viewModelScope.launch {
        settings.setMonitor(on)
        val ctx = getApplication<Application>()
        if (on) MonitorService.start(ctx) else MonitorService.stop(ctx)
    }

    /** At app start: start monitoring if switched on and set up. */
    fun ensureMonitor() = viewModelScope.launch {
        if (settings.monitor.first() && settings.connection.first().configured) MonitorService.start(getApplication())
    }

    // ------------------------------------------------ features and setup (bridge features.py / setup.py)
    /** "" undecided, "pending" freshly paired -> open the setup, "hint" paired before -> hint once, "seen". */
    val appSetup: StateFlow<String?> = settings.appSetup.stateIn(viewModelScope, SharingStarted.Eagerly, null)
    private val _features = MutableStateFlow<Features?>(null)
    val features: StateFlow<Features?> = _features
    private val _setup = MutableStateFlow<SetupInfo?>(null)
    val setup: StateFlow<SetupInfo?> = _setup

    /** At app start: an app that was paired before this version gets only the hint, never the setup. */
    fun decideAppSetup() = viewModelScope.launch {
        if (settings.appSetup.first().isEmpty() && settings.connection.first().token.isNotBlank()) settings.setAppSetup("hint")
    }

    fun setAppSetup(v: String) = viewModelScope.launch { settings.setAppSetup(v) }

    fun loadFeatures() = launchSafe(showBusy = false) { _features.value = it.features() }

    fun switchFeature(key: String, on: Boolean) = launchSafe {
        it.switchFeature(key, on)
        _features.value = it.features()
    }

    fun loadSetup() = launchSafe(showBusy = false) { _setup.value = it.setup() }

    /** Setup: switch what the user chose (only what changed), then show step 3. */
    fun applySetup(choice: Map<String, Boolean>, done: () -> Unit) = launchSafe {
        val current = it.features().items.associateBy { f -> f.key }
        for ((key, on) in choice) {
            val f = current[key] ?: continue
            if (!f.switchable || (f.on == true) == on) continue
            try { it.switchFeature(key, on) } catch (e: BridgeException) { _messages.send("${f.title}: ${e.message}") }
        }
        _features.value = it.features()
        done()
    }

    /** Setup finished in the app: never again by itself here, and the bridge (web UI) counts it as done too. */
    fun finishSetup(done: () -> Unit) = viewModelScope.launch {
        settings.setAppSetup("seen")
        client()?.let { c -> runCatching { c.setupDone() } }
        done()
    }

    // ------------------------------------------------ app update from the bridge
    private val _appUpdate = MutableStateFlow<AppUpdate?>(null)
    /** Newer app the bridge brings along (release build only; the debug app has its own package ID). */
    val appUpdate: StateFlow<AppUpdate?> = _appUpdate
    private val _updateProgress = MutableStateFlow<Float?>(null)
    val updateProgress: StateFlow<Float?> = _updateProgress

    fun checkUpdate(announce: Boolean = false) = viewModelScope.launch {
        val u = client()?.let { c -> runCatching { c.appUpdate() }.getOrNull() }
        _appUpdate.value = u?.takeIf { it.available && it.code > BuildConfig.VERSION_CODE && !BuildConfig.DEBUG }
        if (announce) _messages.send(when {
            BuildConfig.DEBUG -> tr("Debug build: updates only exist for the release app")
            u == null -> tr("Bridge not reachable")
            _appUpdate.value != null -> tr("Update to {version} available", "version" to u.version)
            u.available -> tr("The app is up to date ({version})", "version" to BuildConfig.VERSION_NAME)
            else -> tr("This bridge brings no app along")
        })
    }

    fun installUpdate() = launchSafe(showBusy = false) { c ->
        val u = _appUpdate.value ?: return@launchSafe
        val ctx = getApplication<Application>()
        if (!Installer.allowed(ctx)) {
            Installer.openPermission(ctx)
            _messages.send(tr("Allow “Install unknown apps”, then tap Install once more"))
            return@launchSafe
        }
        val file = java.io.File(ctx.cacheDir, "update/kobra-spoolman-${u.version}.apk")
        _updateProgress.value = 0f
        try {
            c.download(u.url, file) { _updateProgress.value = it }
        } finally {
            _updateProgress.value = null
        }
        Installer.install(ctx, file)
    }

    suspend fun jobs(): List<PrintJob>? = runCatching { client()?.jobs() }.getOrNull()
    suspend fun console(after: Long): ConsoleLines? = runCatching { client()?.console(after) }.getOrNull()
    suspend fun logs(after: Long, level: String): LogLines? = runCatching { client()?.logs(after, level) }.getOrNull()

    /** Live camera via the bridge restream; empty without a connection. */
    fun cameraStream(): Flow<ByteArray> = client()?.cameraStream() ?: emptyFlow()

    suspend fun printInfo(): PrintInfo? = runCatching { client()?.printInfo() }.getOrNull()

    fun linkTag(spoolId: Int, uid: String, done: () -> Unit) = launchSafe {
        it.linkTag(spoolId, uid)
        _messages.send(tr("Tag linked to spool #{id}", "id" to spoolId))
        refresh()
        done()
    }

    /** Pair with the bridge: code (6 digits, setup code or for a transition the APP_TOKEN) against a key. */
    fun pair(url: String, code: String, name: String, done: () -> Unit) = viewModelScope.launch {
        _busy.value = true
        try {
            val res = BridgeClient(url, "").pair(code.trim(), name.trim())
            settings.save(Connection(url, res.token))
            settings.setAppSetup("pending")              // freshly paired: the setup opens next
            _me.value = res.device
            _meChecked.value = true
            _messages.send(tr("Paired as “{name}”", "name" to res.device.name))
            done()
        } catch (e: BridgeException) {
            _messages.send(e.message ?: tr("Pairing failed"))
        } finally {
            _busy.value = false
        }
    }

    /** Forget only here; the bridge keeps the device listed until it is removed there. */
    fun forgetPairing() = viewModelScope.launch {
        settings.save(Connection(connection.value?.url.orEmpty(), ""))
        _me.value = null
        _meChecked.value = false
    }

    fun loadMe() = launchSafe(showBusy = false) {
        _me.value = it.authStatus().device
        _meChecked.value = true
    }
    fun loadDevices() = launchSafe(showBusy = false) { _devices.value = it.devices() }

    fun newPairingCode() = launchSafe { _pairingCode.value = it.newPairingCode() }
    fun clearPairingCode() { _pairingCode.value = null }

    fun removeDevice(id: String) = launchSafe {
        it.removeDevice(id)
        _messages.send(tr("Device removed"))
        _devices.value = it.devices()
    }

    /** Scanned tag -> look up the spool. */
    fun onTag(tag: ScannedTag) = launchSafe(showBusy = false) {
        try {
            _scans.send(ScanResult.Known(it.spoolByTag(tag.uid).spoolId))
        } catch (e: BridgeException) {
            if (e.status == 404) _scans.send(ScanResult.Unknown(tag.uid, blank = tag.ace == null)) else throw e
        }
    }

    /** Rinkhals purge preview for a multiplier; null without a bridge or on an error (the card just shows no table). */
    suspend fun acePurge(multiplier: Double?): AcePurge? =
        client()?.let { c -> try { c.ace(multiplier).purge } catch (e: BridgeException) { null } }

    private fun launchSafe(showBusy: Boolean = true, block: suspend (BridgeClient) -> Unit) = viewModelScope.launch {
        val c = client() ?: run { _messages.send(tr("Set up the bridge first (Settings)")); return@launch }
        if (showBusy) _busy.value = true
        try {
            block(c)
        } catch (e: BridgeException) {
            _messages.send(e.message ?: tr("Error"))
        } finally {
            if (showBusy) _busy.value = false
        }
    }
}

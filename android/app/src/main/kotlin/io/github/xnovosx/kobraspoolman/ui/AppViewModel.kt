package io.github.xnovosx.kobraspoolman.ui

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import io.github.xnovosx.kobraspoolman.data.AppState
import io.github.xnovosx.kobraspoolman.data.BridgeClient
import io.github.xnovosx.kobraspoolman.data.BridgeException
import io.github.xnovosx.kobraspoolman.data.Catalog
import io.github.xnovosx.kobraspoolman.data.Connection
import io.github.xnovosx.kobraspoolman.data.Device
import io.github.xnovosx.kobraspoolman.data.PairingCode
import io.github.xnovosx.kobraspoolman.data.DryerConfig
import io.github.xnovosx.kobraspoolman.data.PrintInfo
import io.github.xnovosx.kobraspoolman.data.PurgePreview
import io.github.xnovosx.kobraspoolman.data.FieldSpec
import io.github.xnovosx.kobraspoolman.data.FilamentDraft
import io.github.xnovosx.kobraspoolman.data.NewSpool
import io.github.xnovosx.kobraspoolman.data.Settings
import io.github.xnovosx.kobraspoolman.data.SpoolDetail
import io.github.xnovosx.kobraspoolman.data.SpoolInfo
import io.github.xnovosx.kobraspoolman.data.TagContent
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
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

/** Was die Oberflaeche nach einem Scan tun soll. */
sealed interface ScanResult {
    data class Known(val spoolId: Int) : ScanResult
    data class Unknown(val uid: String) : ScanResult
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
    /** Zuletzt in der App angelegtes Filament - "Neue Spule" waehlt es vor. */
    val createdFilament: StateFlow<Int?> = _createdFilament
    /** Tag, der gerade geschrieben werden soll (Spule + Inhalt), null = kein Schreibauftrag. */
    data class TagJob(val spoolId: Int, val content: TagContent, val ace: AceTag)
    private val _tagJob = MutableStateFlow<TagJob?>(null)
    val tagJob: StateFlow<TagJob?> = _tagJob
    private val _me = MutableStateFlow<Device?>(null)
    /** Dieses Geraet laut Bridge (null = nicht gekoppelt oder Bridge nicht erreichbar). */
    val me: StateFlow<Device?> = _me
    private val _meChecked = MutableStateFlow(false)
    /** true, sobald die Bridge geantwortet hat - dann heisst me == null: Schluessel ungueltig. */
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

    // ------------------------------------------------------------ Laden
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

    // ------------------------------------------------------------ Aktionen
    fun moveSpool(id: Int, slot: Int?) = launchSafe {
        it.moveSpool(id, slot)
        _messages.send(if (slot == null) "Ins Regal gelegt" else "In Slot $slot gelegt")
        _detail.value = it.spool(id)
        refresh()
    }

    fun archiveSpool(id: Int, done: () -> Unit) = launchSafe {
        it.archiveSpool(id)
        _messages.send("Spule archiviert")
        refresh()
        done()
    }

    fun createSpool(req: NewSpool, tagUid: String?, done: (SpoolInfo) -> Unit) = launchSafe {
        var spool = it.createSpool(req)
        if (tagUid != null) spool = it.linkTag(spool.spoolId, tagUid)
        _messages.send("Spule #${spool.spoolId} angelegt" + if (tagUid != null) " und mit dem Tag verknüpft" else "")
        refresh()
        done(spool)
    }

    fun createFilament(draft: FilamentDraft, specs: List<FieldSpec>, done: () -> Unit) = launchSafe {
        val vendorId = draft.vendorId ?: it.createVendor(draft.newVendor.trim()).id
        val fil = it.createFilament(draft.toJson(specs, vendorId))
        _createdFilament.value = fil.filamentId
        _catalog.value = it.catalog()
        _messages.send("Filament „${fil.displayName}“ angelegt")
        done()
    }

    /** Tag-Nummer holen und den naechsten aufgelegten Tag damit beschreiben lassen. */
    fun prepareTag(spoolId: Int, scanner: TagScanner) = launchSafe {
        _tagJob.value = null
        val issue = it.issueTag(spoolId)
        val ace = try { issue.tag.toAceTag() } catch (e: IllegalStateException) {
            _messages.send(e.message ?: "Tag-Inhalt unvollständig"); return@launchSafe
        } catch (e: IllegalArgumentException) {
            _messages.send(e.message ?: "Tag-Inhalt unvollständig"); return@launchSafe
        }
        scanner.armWrite(ace.encode())
        _tagJob.value = TagJob(spoolId, issue.tag, ace)
    }

    fun cancelTag(scanner: TagScanner) {
        scanner.disarm()
        _tagJob.value = null
    }

    /** Tag ist beschrieben: Seriennummer mit der Spule verknuepfen. */
    fun onTagWritten(r: WriteResult, done: (Int) -> Unit) = launchSafe {
        val job = _tagJob.value ?: return@launchSafe
        when (r) {
            is WriteResult.Failed -> _messages.send(r.message)
            is WriteResult.Written -> {
                it.linkTag(job.spoolId, r.uid, force = true)
                _tagJob.value = null
                _messages.send("Tag ${job.content.sku} geschrieben und mit Spule #${job.spoolId} verknüpft")
                refresh()
                done(job.spoolId)
            }
        }
    }

    fun dryerStart(temp: Int?, hours: Double?) = launchSafe {
        it.dryerStart(temp, hours)
        _messages.send("Trocknen gestartet")
        refresh()
    }

    fun dryerStop() = launchSafe {
        it.dryerStop()
        _messages.send("Trocknen gestoppt")
        refresh()
    }

    fun dryerConfig(c: DryerConfig) = launchSafe {
        it.dryerConfig(c)
        _messages.send(if (c.enabled) "Automatik gespeichert: ab ${c.startAbove.toInt()} %, bis ${c.stopBelow.toInt()} %" else "Automatik aus")
        refresh()
    }

    private val _purgePreview = MutableStateFlow<PurgePreview?>(null)
    val purgePreview: StateFlow<PurgePreview?> = _purgePreview

    /** Spuel-Vorschau fuer die eingelegten Farben laden (multiplier = gewuenschter Wert, null = aktueller). */
    fun loadPurgePreview(multiplier: Double?) = launchSafe(showBusy = false) {
        _purgePreview.value = it.ace(multiplier).purge
    }

    fun setFlushMultiplier(value: Double, confirmPrinting: Boolean) = launchSafe {
        it.setFlushMultiplier(value, confirmPrinting)
        _messages.send("Spülen am Drucker auf × ${Format.decimal(value, 1)} gesetzt")
        refresh()
    }

    fun setAceOption(key: String, value: Boolean, confirmPrinting: Boolean) = launchSafe {
        it.setAceOption(key, value, confirmPrinting)
        _messages.send("Am Drucker gespeichert")
        refresh()
    }

    fun dryerSchedule(atEpochS: Double, temp: Int?, hours: Double?) = launchSafe {
        it.dryerSchedule(atEpochS, temp, hours)
        _messages.send("Trocknen geplant")
        refresh()
    }

    fun clearDryerSchedule() = launchSafe {
        it.clearDryerSchedule()
        _messages.send("Plan gelöscht")
        refresh()
    }

    /** Bild von der Bridge holen (Kamera nur gekoppelt); null bei Fehler oder ohne Bild. */
    suspend fun image(path: String): ByteArray? = runCatching { client()?.image(path) }.getOrNull()

    /** Kamera live ueber den Restream der Bridge; leer ohne Verbindung. */
    fun cameraStream(): Flow<ByteArray> = client()?.cameraStream() ?: emptyFlow()

    suspend fun printInfo(): PrintInfo? = runCatching { client()?.printInfo() }.getOrNull()

    fun linkTag(spoolId: Int, uid: String, done: () -> Unit) = launchSafe {
        it.linkTag(spoolId, uid)
        _messages.send("Tag mit Spule #$spoolId verknüpft")
        refresh()
        done()
    }

    /** Mit der Bridge koppeln: Code (6 Ziffern, Einrichtungscode oder uebergangsweise APP_TOKEN) gegen Schluessel. */
    fun pair(url: String, code: String, name: String, done: () -> Unit) = viewModelScope.launch {
        _busy.value = true
        try {
            val res = BridgeClient(url, "").pair(code.trim(), name.trim())
            settings.save(Connection(url, res.token))
            _me.value = res.device
            _meChecked.value = true
            _messages.send("Gekoppelt als „${res.device.name}“")
            done()
        } catch (e: BridgeException) {
            _messages.send(e.message ?: "Koppeln fehlgeschlagen")
        } finally {
            _busy.value = false
        }
    }

    /** Nur hier vergessen; in der Bridge bleibt das Geraet gelistet, bis es dort entfernt wird. */
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
        _messages.send("Gerät entfernt")
        _devices.value = it.devices()
    }

    /** Gescannter Tag -> Spule nachschlagen. */
    fun onTag(tag: ScannedTag) = launchSafe(showBusy = false) {
        try {
            _scans.send(ScanResult.Known(it.spoolByTag(tag.uid).spoolId))
        } catch (e: BridgeException) {
            if (e.status == 404) _scans.send(ScanResult.Unknown(tag.uid)) else throw e
        }
    }

    private fun launchSafe(showBusy: Boolean = true, block: suspend (BridgeClient) -> Unit) = viewModelScope.launch {
        val c = client() ?: run { _messages.send("Erst die Bridge einrichten (Einstellungen)"); return@launch }
        if (showBusy) _busy.value = true
        try {
            block(c)
        } catch (e: BridgeException) {
            _messages.send(e.message ?: "Fehler")
        } finally {
            if (showBusy) _busy.value = false
        }
    }
}

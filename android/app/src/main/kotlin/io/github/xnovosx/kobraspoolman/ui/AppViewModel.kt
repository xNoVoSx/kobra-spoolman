package io.github.xnovosx.kobraspoolman.ui

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import io.github.xnovosx.kobraspoolman.data.AppState
import io.github.xnovosx.kobraspoolman.data.BridgeClient
import io.github.xnovosx.kobraspoolman.data.BridgeException
import io.github.xnovosx.kobraspoolman.data.Catalog
import io.github.xnovosx.kobraspoolman.data.Connection
import io.github.xnovosx.kobraspoolman.data.FieldSpec
import io.github.xnovosx.kobraspoolman.data.FilamentDraft
import io.github.xnovosx.kobraspoolman.data.NewSpool
import io.github.xnovosx.kobraspoolman.data.Settings
import io.github.xnovosx.kobraspoolman.data.SpoolDetail
import io.github.xnovosx.kobraspoolman.data.SpoolInfo
import io.github.xnovosx.kobraspoolman.nfc.ScannedTag
import kotlinx.coroutines.Job
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
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

    fun linkTag(spoolId: Int, uid: String, done: () -> Unit) = launchSafe {
        it.linkTag(spoolId, uid)
        _messages.send("Tag mit Spule #$spoolId verknüpft")
        refresh()
        done()
    }

    fun saveConnection(c: Connection, done: () -> Unit) = viewModelScope.launch {
        _busy.value = true
        try {
            val health = BridgeClient(c.url, c.token).health()
            settings.save(c)
            _messages.send("Verbunden mit ${health.app} ${health.version}")
            done()
        } catch (e: BridgeException) {
            _messages.send(e.message ?: "Bridge nicht erreichbar")
        } finally {
            _busy.value = false
        }
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

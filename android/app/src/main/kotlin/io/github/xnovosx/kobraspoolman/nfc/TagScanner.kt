package io.github.xnovosx.kobraspoolman.nfc

import android.app.Activity
import android.nfc.NfcAdapter
import android.nfc.Tag
import kotlinx.coroutines.channels.BufferOverflow
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlin.random.Random

/** Ein gescannter Tag. uid = Seriennummer als Hex (grossgeschrieben, ohne Trenner). */
data class ScannedTag(val uid: String, val virtual: Boolean = false)

/**
 * Liefert gescannte Tags. Echte Tags kommen ueber NFC (Reader-Modus, nur solange die App im
 * Vordergrund ist). Im Debug-Build gibt es zusaetzlich virtuelle Tags, weil der Emulator kein NFC
 * hat - der Rest der App behandelt beide gleich.
 */
class TagScanner {
    private val _tags = MutableSharedFlow<ScannedTag>(extraBufferCapacity = 4, onBufferOverflow = BufferOverflow.DROP_OLDEST)
    val tags: SharedFlow<ScannedTag> = _tags

    var nfcAvailable: Boolean = false
        private set
    var nfcEnabled: Boolean = false
        private set

    fun resume(activity: Activity) {
        val adapter = NfcAdapter.getDefaultAdapter(activity)
        nfcAvailable = adapter != null
        nfcEnabled = adapter?.isEnabled == true
        if (adapter == null || !adapter.isEnabled) return
        adapter.enableReaderMode(
            activity,
            { tag: Tag -> _tags.tryEmit(ScannedTag(uidHex(tag.id))) },
            NfcAdapter.FLAG_READER_NFC_A or NfcAdapter.FLAG_READER_SKIP_NDEF_CHECK,
            null,
        )
    }

    fun pause(activity: Activity) {
        NfcAdapter.getDefaultAdapter(activity)?.disableReaderMode(activity)
    }

    /** Virtueller Tag (Debug-Build/Emulator). */
    fun simulate(uid: String) {
        _tags.tryEmit(ScannedTag(uid, virtual = true))
    }

    companion object {
        fun uidHex(bytes: ByteArray): String = bytes.joinToString("") { "%02X".format(it) }

        /** Neue zufaellige 7-Byte-UID wie bei NTAG215 (erstes Byte 04 = NXP). */
        fun randomUid(random: Random = Random.Default): String =
            uidHex(byteArrayOf(0x04) + random.nextBytes(6))
    }
}

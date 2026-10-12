package io.github.xnovosx.kobraspoolman.nfc

import android.app.Activity
import android.nfc.NfcAdapter
import android.nfc.Tag
import android.nfc.tech.NfcA
import java.io.IOException
import kotlinx.coroutines.channels.BufferOverflow
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlin.random.Random
import io.github.xnovosx.kobraspoolman.data.tr

/** A scanned tag. uid = serial number as hex (upper case, no separators). */
data class ScannedTag(val uid: String, val virtual: Boolean = false, val ace: AceTag? = null)

/** Result of a write. */
sealed interface WriteResult {
    data class Written(val uid: String, val virtual: Boolean) : WriteResult
    data class Failed(val message: String) : WriteResult
}

/**
 * NFC in the foreground (reader mode): every tag put on is read - or written if [armWrite] was called before. The
 * debug build has virtual tags because the emulator has no NFC; the rest of the app treats them like real
 * ones.
 */
class TagScanner {
    private val _tags = MutableSharedFlow<ScannedTag>(extraBufferCapacity = 4, onBufferOverflow = BufferOverflow.DROP_OLDEST)
    val tags: SharedFlow<ScannedTag> = _tags
    private val _writes = MutableSharedFlow<WriteResult>(extraBufferCapacity = 4, onBufferOverflow = BufferOverflow.DROP_OLDEST)
    val writes: SharedFlow<WriteResult> = _writes

    @Volatile private var pendingWrite: Map<Int, ByteArray>? = null
    /** Virtual tags: UID -> memory (pages 0..44). */
    private val virtualTags = mutableMapOf<String, ByteArray>()

    var nfcAvailable: Boolean = false
        private set
    var nfcEnabled: Boolean = false
        private set

    fun resume(activity: Activity) {
        val adapter = NfcAdapter.getDefaultAdapter(activity)
        nfcAvailable = adapter != null
        nfcEnabled = adapter?.isEnabled == true
        if (adapter == null || !adapter.isEnabled) return
        adapter.enableReaderMode(activity, ::onTag,
            NfcAdapter.FLAG_READER_NFC_A or NfcAdapter.FLAG_READER_SKIP_NDEF_CHECK, null)
    }

    fun pause(activity: Activity) {
        NfcAdapter.getDefaultAdapter(activity)?.disableReaderMode(activity)
    }

    /** The next tag put on is written with these pages (instead of only read). */
    fun armWrite(pages: Map<Int, ByteArray>) { pendingWrite = pages }
    fun disarm() { pendingWrite = null }
    val armed: Boolean get() = pendingWrite != null

    private fun onTag(tag: Tag) {
        val uid = uidHex(tag.id)
        val nfc = NfcA.get(tag) ?: return
        val write = pendingWrite
        try {
            nfc.connect()
            nfc.timeout = 1500
            if (write != null) {
                writePages(nfc, write)
                pendingWrite = null
                _writes.tryEmit(WriteResult.Written(uid, virtual = false))
            } else {
                _tags.tryEmit(ScannedTag(uid, ace = runCatching { AceTag.decode(readPages(nfc, 0, 44)) }.getOrNull()))
            }
        } catch (e: IOException) {
            if (write != null) _writes.tryEmit(WriteResult.Failed(
                (tr("Write failed – tag taken away too early or write-protected (original Anycubic tags are locked).") + " " + (e.message ?: "")).trim()))
        } catch (e: VerifyException) {
            _writes.tryEmit(WriteResult.Failed(e.message ?: tr("Verification failed")))
        } finally {
            runCatching { nfc.close() }
        }
    }

    private class VerifyException(msg: String) : Exception(msg)

    /** WRITE (0xA2) per page, then read back and compare. */
    private fun writePages(nfc: NfcA, pages: Map<Int, ByteArray>) {
        for ((p, data) in pages.toSortedMap()) nfc.transceive(byteArrayOf(0xA2.toByte(), p.toByte()) + data)
        val first = pages.keys.min()
        val back = readPages(nfc, first, pages.keys.max())
        for ((p, data) in pages) {
            val got = back.copyOfRange((p - first) * 4, (p - first) * 4 + 4)
            if (!got.contentEquals(data)) throw VerifyException(tr("Tag differs from what was written (page {page}) – please put it on again", "page" to p))
        }
    }

    /** READ (0x30) returns 4 pages at once. */
    private fun readPages(nfc: NfcA, from: Int, to: Int): ByteArray {
        val out = java.io.ByteArrayOutputStream()
        var p = from
        while (p <= to) {
            val chunk = nfc.transceive(byteArrayOf(0x30, p.toByte()))
            out.write(chunk, 0, minOf(16, (to - p + 1) * 4))
            p += 4
        }
        return out.toByteArray()
    }

    // ------------------------------------------------------------ virtual tags (debug/emulator)
    /** Put a virtual tag on: writes it if a write job is waiting, else it is read. */
    fun simulate(uid: String) {
        val write = pendingWrite
        val mem = virtualTags.getOrPut(uid) { ByteArray(45 * 4) }
        if (write != null) {
            write.forEach { (p, b) -> b.copyInto(mem, p * 4) }
            pendingWrite = null
            _writes.tryEmit(WriteResult.Written(uid, virtual = true))
        } else {
            _tags.tryEmit(ScannedTag(uid, virtual = true, ace = AceTag.decode(mem)))
        }
    }

    val virtualUids: List<String> get() = virtualTags.keys.toList()

    companion object {
        fun uidHex(bytes: ByteArray): String = bytes.joinToString("") { "%02X".format(it) }

        /** New random 7-byte UID like NTAG215 (first byte 04 = NXP). */
        fun randomUid(random: Random = Random.Default): String =
            uidHex(byteArrayOf(0x04) + random.nextBytes(6))
    }
}

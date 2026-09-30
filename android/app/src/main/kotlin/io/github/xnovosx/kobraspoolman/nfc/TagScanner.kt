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

/** Ein gescannter Tag. uid = Seriennummer als Hex (grossgeschrieben, ohne Trenner). */
data class ScannedTag(val uid: String, val virtual: Boolean = false, val ace: AceTag? = null)

/** Ergebnis eines Schreibvorgangs. */
sealed interface WriteResult {
    data class Written(val uid: String, val virtual: Boolean) : WriteResult
    data class Failed(val message: String) : WriteResult
}

/**
 * NFC im Vordergrund (Reader-Modus): Jeder aufgelegte Tag wird gelesen - oder beschrieben, wenn
 * vorher [armWrite] aufgerufen wurde. Im Debug-Build gibt es virtuelle Tags, weil der Emulator kein
 * NFC hat; der Rest der App behandelt sie wie echte.
 */
class TagScanner {
    private val _tags = MutableSharedFlow<ScannedTag>(extraBufferCapacity = 4, onBufferOverflow = BufferOverflow.DROP_OLDEST)
    val tags: SharedFlow<ScannedTag> = _tags
    private val _writes = MutableSharedFlow<WriteResult>(extraBufferCapacity = 4, onBufferOverflow = BufferOverflow.DROP_OLDEST)
    val writes: SharedFlow<WriteResult> = _writes

    @Volatile private var pendingWrite: Map<Int, ByteArray>? = null
    /** Virtuelle Tags: UID -> Speicher (Seiten 0..44). */
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

    /** Der naechste aufgelegte Tag wird mit diesen Seiten beschrieben (statt nur gelesen). */
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
                "Schreiben fehlgeschlagen – Tag zu früh weggenommen oder schreibgeschützt (Original-Anycubic-Tags sind gesperrt). ${e.message ?: ""}".trim()))
        } catch (e: VerifyException) {
            _writes.tryEmit(WriteResult.Failed(e.message ?: "Prüfung fehlgeschlagen"))
        } finally {
            runCatching { nfc.close() }
        }
    }

    private class VerifyException(msg: String) : Exception(msg)

    /** WRITE (0xA2) je Seite, dann zuruecklesen und vergleichen. */
    private fun writePages(nfc: NfcA, pages: Map<Int, ByteArray>) {
        for ((p, data) in pages.toSortedMap()) nfc.transceive(byteArrayOf(0xA2.toByte(), p.toByte()) + data)
        val first = pages.keys.min()
        val back = readPages(nfc, first, pages.keys.max())
        for ((p, data) in pages) {
            val got = back.copyOfRange((p - first) * 4, (p - first) * 4 + 4)
            if (!got.contentEquals(data)) throw VerifyException("Tag nach dem Schreiben anders als erwartet (Seite $p) – bitte nochmal auflegen")
        }
    }

    /** READ (0x30) liefert 4 Seiten auf einmal. */
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

    // ------------------------------------------------------------ virtuelle Tags (Debug/Emulator)
    /** Virtuellen Tag auflegen: beschreibt ihn, wenn ein Schreibauftrag wartet, sonst wird er gelesen. */
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

        /** Neue zufaellige 7-Byte-UID wie bei NTAG215 (erstes Byte 04 = NXP). */
        fun randomUid(random: Random = Random.Default): String =
            uidHex(byteArrayOf(0x04) + random.nextBytes(6))
    }
}

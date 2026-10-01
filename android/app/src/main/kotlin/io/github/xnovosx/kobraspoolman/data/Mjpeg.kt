package io.github.xnovosx.kobraspoolman.data

import java.io.IOException
import java.io.InputStream

/**
 * Liest JPEG-Bilder aus einem multipart/x-mixed-replace-Strom (Restream der Bridge, mjpg-streamer).
 * Nutzt Content-Length, sonst die JPEG-Endmarke FF D9.
 */
class MjpegReader(private val input: InputStream) {
    private var buf = ByteArray(0)
    private val chunk = ByteArray(16 * 1024)

    private fun fill(): Boolean {
        val n = input.read(chunk)
        if (n <= 0) return false
        buf += chunk.copyOf(n)
        return true
    }

    private fun indexOf(pattern: ByteArray, from: Int = 0): Int {
        outer@ for (i in from..buf.size - pattern.size) {
            for (j in pattern.indices) if (buf[i + j] != pattern[j]) continue@outer
            return i
        }
        return -1
    }

    /** Naechstes Bild oder null am Ende des Stroms. */
    fun next(): ByteArray? {
        var end = indexOf(HEAD_END)
        while (end < 0) {
            if (buf.size > MAX_HEAD) throw IOException("Stream ohne erkennbare Bildgrenzen")
            if (!fill()) return null
            end = indexOf(HEAD_END)
        }
        val head = String(buf, 0, end, Charsets.ISO_8859_1)
        buf = buf.copyOfRange(end + HEAD_END.size, buf.size)
        val length = head.lineSequence()
            .firstOrNull { it.trim().lowercase().startsWith("content-length:") }
            ?.substringAfter(':')?.trim()?.toIntOrNull()
        val frame: ByteArray
        if (length != null) {
            // direkt in ein passendes Feld lesen statt den Puffer staendig zu vergroessern
            frame = ByteArray(length)
            val have = minOf(buf.size, length)
            buf.copyInto(frame, 0, 0, have)
            buf = buf.copyOfRange(have, buf.size)
            var pos = have
            while (pos < length) {
                val n = input.read(frame, pos, length - pos)
                if (n <= 0) return null
                pos += n
            }
        } else {
            var stop = indexOf(JPEG_END)
            while (stop < 0) {
                if (!fill()) return null
                stop = indexOf(JPEG_END)
            }
            frame = buf.copyOfRange(0, stop + 2)
            buf = buf.copyOfRange(stop + 2, buf.size)
        }
        val start = (0 until frame.size - 1).firstOrNull { frame[it] == 0xFF.toByte() && frame[it + 1] == 0xD8.toByte() }
            ?: return next()
        return if (start == 0) frame else frame.copyOfRange(start, frame.size)
    }

    private companion object {
        val HEAD_END = "\r\n\r\n".toByteArray()
        val JPEG_END = byteArrayOf(0xFF.toByte(), 0xD9.toByte())
        const val MAX_HEAD = 1_000_000
    }
}

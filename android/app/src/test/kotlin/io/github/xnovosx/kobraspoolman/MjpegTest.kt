package io.github.xnovosx.kobraspoolman

import io.github.xnovosx.kobraspoolman.data.MjpegReader
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertNull
import org.junit.Test
import java.io.ByteArrayOutputStream
import java.io.InputStream

class MjpegTest {
    private fun jpeg(i: Int) = byteArrayOf(0xFF.toByte(), 0xD8.toByte()) + "bild $i".toByteArray() +
        byteArrayOf(0xFF.toByte(), 0xD9.toByte())

    /** Liefert hoechstens 5 Bytes pro read() wie ein langsames Netz. */
    private class Trickle(private val data: ByteArray) : InputStream() {
        private var pos = 0
        override fun read(): Int = if (pos < data.size) data[pos++].toInt() and 0xFF else -1
        override fun read(b: ByteArray, off: Int, len: Int): Int {
            if (pos >= data.size) return -1
            val n = minOf(len, 5, data.size - pos)
            data.copyInto(b, off, pos, pos + n)
            pos += n
            return n
        }
    }

    @Test
    fun readsFramesWithContentLength() {
        val out = ByteArrayOutputStream()
        out.write("\r\n--boundarydonotcross\r\n".toByteArray())
        for (i in 1..3) {
            out.write("Content-Type: image/jpeg\r\nContent-Length: ${jpeg(i).size}\r\nX-Timestamp: 1\r\n\r\n".toByteArray())
            out.write(jpeg(i))
            out.write("\r\n--boundarydonotcross\r\n".toByteArray())
        }
        val r = MjpegReader(Trickle(out.toByteArray()))
        for (i in 1..3) assertArrayEquals(jpeg(i), r.next())
        assertNull(r.next())
    }

    @Test
    fun readsFramesWithoutContentLength() {
        val data = "--b\r\nContent-Type: image/jpeg\r\n\r\n".toByteArray() + jpeg(1) + "\r\n--b\r\n\r\n".toByteArray() + jpeg(2)
        val r = MjpegReader(Trickle(data))
        assertArrayEquals(jpeg(1), r.next())
        assertArrayEquals(jpeg(2), r.next())
        assertNull(r.next())
    }
}

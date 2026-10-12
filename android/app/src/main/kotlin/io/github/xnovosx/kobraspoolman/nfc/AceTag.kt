package io.github.xnovosx.kobraspoolman.nfc

import io.github.xnovosx.kobraspoolman.data.tr

/**
 * Content of an ACE tag (Anycubic ACE Pro / ACE 2 Pro) - own implementation.
 *
 * Page layout (4 bytes each, MIFARE Ultralight/NTAG), checked on an original tag
 * (Anycubic PETG black, NTAG213) and based on ACE-RFID (github.com/DnG-Crafts/ACE-RFID):
 *
 *   4      7B 00 65 00               header
 *   5-9    SKU, ASCII, 20 bytes      "AHPEBK-102" -> the ACE reports 102 as gate_spool_id
 *   10-14  brand, ASCII, 20 bytes    "AC" = Anycubic
 *   15-19  material, ASCII, 20 bytes "PETG"
 *   20     colour A B G R            FF 21 27 21
 *   23     speed min/max             50 / 200 (mm/s, 2 bytes each, low byte first)
 *   24     nozzle min/max            230 / 250 (degC)
 *   29     bed min/max               60 / 70 (degC)
 *   30     diameter x100, length     175 / 320 (m)
 *   31     weight                    1000 (g)
 * All other pages from 4 to 31 are 0.
 */
data class AceTag(
    val sku: String,
    val brand: String,
    val material: String,
    /** RRGGBB */
    val color: String,
    val nozzleMin: Int, val nozzleMax: Int,
    val bedMin: Int, val bedMax: Int,
    val diameterMm: Double = 1.75,
    val lengthM: Int,
    val weightG: Int,
    val speedMin: Int = 50, val speedMax: Int = 200,
) {
    /** Number after the dash of the SKU - that is how the ACE reports it (gate_spool_id). */
    val skuNumber: Long? get() = sku.substringAfterLast('-', "").toLongOrNull()

    /** Pages 4..31 for writing (empty ones too, so old content disappears). */
    fun encode(): Map<Int, ByteArray> {
        val data = ByteArray((LAST - FIRST + 1) * 4)
        fun put(page: Int, bytes: ByteArray) = bytes.copyInto(data, (page - FIRST) * 4)
        put(4, byteArrayOf(0x7B, 0x00, 0x65, 0x00))
        put(5, ascii(sku, 20))
        put(10, ascii(brand, 20))
        put(15, ascii(material, 20))
        put(20, colorBytes(color))
        put(23, pair(speedMin, speedMax))
        put(24, pair(nozzleMin, nozzleMax))
        put(29, pair(bedMin, bedMax))
        put(30, pair(Math.round(diameterMm * 100).toInt(), lengthM))
        put(31, pair(weightG, 0))
        return (FIRST..LAST).associateWith { data.copyOfRange((it - FIRST) * 4, (it - FIRST) * 4 + 4) }
    }

    companion object {
        const val FIRST = 4
        const val LAST = 31
        private val HEADER = byteArrayOf(0x7B, 0x00, 0x65, 0x00)

        private fun ascii(s: String, len: Int): ByteArray {
            val b = s.filter { it.code in 32..126 }.toByteArray(Charsets.US_ASCII)
            require(b.size <= len) { tr("“{text}” is too long (max. {max} characters)", "text" to s, "max" to len) }
            return b.copyOf(len)
        }

        private fun pair(a: Int, b: Int): ByteArray {
            require(a in 0..0xFFFF && b in 0..0xFFFF) { tr("Value outside 0..65535") }
            return byteArrayOf(a.toByte(), (a shr 8).toByte(), b.toByte(), (b shr 8).toByte())
        }

        /** RRGGBB -> A B G R. Pure black is written as 010101 (like ACE-RFID), 000000 counts as "no colour". */
        fun colorBytes(rgb: String): ByteArray {
            var h = rgb.removePrefix("#").uppercase()
            require(Regex("[0-9A-F]{6}").matches(h)) { tr("Colour as RRGGBB") }
            if (h == "000000") h = "010101"
            val r = h.substring(0, 2).toInt(16)
            val g = h.substring(2, 4).toInt(16)
            val b = h.substring(4, 6).toInt(16)
            return byteArrayOf(0xFF.toByte(), b.toByte(), g.toByte(), r.toByte())
        }

        /** Read a tag from pages 0..n (e.g. a memory dump); null = not an ACE tag. */
        fun decode(pages: ByteArray): AceTag? {
            if (pages.size < (LAST + 1) * 4) return null
            fun page(p: Int) = pages.copyOfRange(p * 4, p * 4 + 4)
            if (!page(4).contentEquals(HEADER)) return null
            fun text(p: Int) = pages.copyOfRange(p * 4, p * 4 + 20).takeWhile { it != 0.toByte() }.toByteArray()
                .toString(Charsets.US_ASCII)
            fun u16(p: Int, i: Int) = (pages[p * 4 + i].toInt() and 0xFF) or ((pages[p * 4 + i + 1].toInt() and 0xFF) shl 8)
            val c = page(20)
            val color = "%02X%02X%02X".format(c[3].toInt() and 0xFF, c[2].toInt() and 0xFF, c[1].toInt() and 0xFF)
            return AceTag(
                sku = text(5), brand = text(10), material = text(15), color = color,
                nozzleMin = u16(24, 0), nozzleMax = u16(24, 2), bedMin = u16(29, 0), bedMax = u16(29, 2),
                diameterMm = u16(30, 0) / 100.0, lengthM = u16(30, 2), weightG = u16(31, 0),
                speedMin = u16(23, 0), speedMax = u16(23, 2),
            )
        }
    }
}

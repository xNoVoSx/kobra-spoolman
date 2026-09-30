package io.github.xnovosx.kobraspoolman

import io.github.xnovosx.kobraspoolman.nfc.AceTag
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/** Kodierung gegen das Speicherabbild eines Original-Tags (Anycubic PETG Schwarz, NTAG213, NFC Tools). */
class AceTagTest {
    private val original: ByteArray = javaClass.getResourceAsStream("/anycubic_petg_black_ntag213.bin")!!.readBytes()

    @Test fun decodes_the_original_anycubic_tag() {
        val t = AceTag.decode(original)!!
        assertEquals("AHPEBK-102", t.sku)
        assertEquals(102L, t.skuNumber)
        assertEquals("AC", t.brand)
        assertEquals("PETG", t.material)
        assertEquals("212721", t.color)
        assertEquals(230 to 250, t.nozzleMin to t.nozzleMax)
        assertEquals(60 to 70, t.bedMin to t.bedMax)
        assertEquals(1.75, t.diameterMm, 0.0)
        assertEquals(320, t.lengthM)
        assertEquals(1000, t.weightG)
        assertEquals(50 to 200, t.speedMin to t.speedMax)
    }

    @Test fun encoding_reproduces_the_original_pages_4_to_31() {
        val pages = AceTag.decode(original)!!.encode()
        for (p in AceTag.FIRST..AceTag.LAST) {
            assertArrayEquals("Seite $p", original.copyOfRange(p * 4, p * 4 + 4), pages.getValue(p))
        }
    }

    @Test fun colour_order_and_black() {
        assertArrayEquals(byteArrayOf(0xFF.toByte(), 0xBC.toByte(), 0xD2.toByte(), 0x52), AceTag.colorBytes("52D2BC"))
        assertArrayEquals(byteArrayOf(0xFF.toByte(), 1, 1, 1), AceTag.colorBytes("000000"))
    }

    @Test fun own_tag_roundtrip() {
        val t = AceTag("AHPEBK-48213", "Sunlu", "PETG", "685BC7", 250, 255, 75, 80, 1.75, 328, 1000)
        val bytes = ByteArray(45 * 4)
        t.encode().forEach { (p, b) -> b.copyInto(bytes, p * 4) }
        assertEquals(t, AceTag.decode(bytes))
        assertNull(AceTag.decode(ByteArray(45 * 4)))   // leerer Tag ist kein ACE-Tag
    }
}

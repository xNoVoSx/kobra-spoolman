package io.github.xnovosx.kobraspoolman

import io.github.xnovosx.kobraspoolman.data.BridgeClient
import io.github.xnovosx.kobraspoolman.data.Printer
import io.github.xnovosx.kobraspoolman.nfc.TagScanner
import io.github.xnovosx.kobraspoolman.ui.Format
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.random.Random

class FormatTest {
    @Test fun grams_and_durations() {
        assertEquals("973 g", Format.grams(972.58))
        assertEquals("? g", Format.grams(null))
        assertEquals("29 min", Format.duration(1740))
        assertEquals("1 h 23 min", Format.duration(4980))
        assertEquals("42 %", Format.percent(0.42))
        assertEquals(0.5f, Format.fill(500.0, 1000.0))
        assertEquals(0f, Format.fill(null, 1000.0))
    }

    @Test fun printer_state_labels() {
        assertEquals("Druckt", Format.stateLabel(Printer(state = "printing")))
        assertEquals("Wechselt Filament", Format.stateLabel(Printer(state = "printing", changingFilament = true)))
        assertEquals("Bereit", Format.stateLabel(Printer(state = "standby")))
        assertEquals("Offline", Format.stateLabel(Printer()))
    }

    @Test fun bridge_url_is_normalized() {
        assertEquals("http://10.0.0.19:7913", BridgeClient.normalizeUrl(" 10.0.0.19:7913/ "))
        assertEquals("https://bridge.example", BridgeClient.normalizeUrl("https://bridge.example"))
    }

    @Test fun virtual_uid_looks_like_ntag() {
        val uid = TagScanner.randomUid(Random(1))
        assertEquals(14, uid.length)
        assertTrue(uid.startsWith("04"))
    }
}

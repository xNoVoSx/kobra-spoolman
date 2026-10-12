package io.github.xnovosx.kobraspoolman

import io.github.xnovosx.kobraspoolman.data.BridgeClient
import io.github.xnovosx.kobraspoolman.data.I18n
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
        assertEquals("Printing", Format.stateLabel(Printer(state = "printing")))
        assertEquals("Changing filament", Format.stateLabel(Printer(state = "printing", changingFilament = true)))
        assertEquals("Ready", Format.stateLabel(Printer(state = "standby")))
        assertEquals("Offline", Format.stateLabel(Printer()))
        // the bridge's print phase (3.9.0+) replaces the headline; "Printing · layer" not twice in the notification
        val soak = Printer(state = "printing", phase = "Preheating 5/15 min", phaseKey = "soak")
        assertEquals("Preheating 5/15 min", Format.headline(soak))
        assertEquals("Preheating 5/15 min", Format.extraPhase(soak))
        val layer = Printer(state = "printing", phase = "Printing · layer 3/80", phaseKey = "printing")
        assertEquals("Printing · layer 3/80", Format.headline(layer))
        assertEquals(null, Format.extraPhase(layer))
        assertEquals("Paused", Format.headline(Printer(state = "paused")))
    }

    @Test fun bridge_url_is_normalized() {
        assertEquals("http://192.168.1.10:7913", BridgeClient.normalizeUrl(" 192.168.1.10:7913/ "))
        assertEquals("https://bridge.example", BridgeClient.normalizeUrl("https://bridge.example"))
    }

    @Test fun decimals_follow_the_language() {
        assertEquals("1.0", Format.decimal(1.0, 1))
        assertEquals("0.65", Format.decimal(0.65, 2))
        assertEquals("–", Format.decimal(null))
        assertEquals(0.8, Format.parseDecimal(" 0,8 ")!!, 1e-9)
        assertEquals(0.8, Format.parseDecimal("0.8")!!, 1e-9)
        assertEquals(null, Format.parseDecimal("lots"))
    }

    @Test fun virtual_uid_looks_like_ntag() {
        val uid = TagScanner.randomUid(Random(1))
        assertEquals(14, uid.length)
        assertTrue(uid.startsWith("04"))
    }

    @Test
    fun finishAt() {
        val now = java.time.ZonedDateTime.of(2026, 10, 1, 22, 50, 0, 0, java.time.ZoneId.of("Europe/Berlin"))
        assertEquals("~23:35", Format.finishAt(45 * 60L, now))
        assertEquals("tomorrow ~02:10", Format.finishAt(200 * 60L, now))
        assertEquals("Sun ~10:50", Format.finishAt(60 * 3600L, now))   // Thu 22:50 + 60 h
        assertEquals("–", Format.finishAt(null, now))
    }

    @Test
    fun ago() {
        assertEquals("just now", Format.ago(1000, 1030))
        assertEquals("5 min ago", Format.ago(1000, 1000 + 5 * 60))
        assertEquals("15 h ago", Format.ago(0, 15 * 3600 + 5))
        assertEquals("3 days ago", Format.ago(0, 3 * 86400))
    }

    /** German from the app's catalog (src/main/assets/i18n/de.json) - numbers, dates and placeholders. */
    @Test
    fun german() {
        I18n.use("de", java.io.File("src/main/assets/i18n/de.json").readText())
        try {
            assertEquals("de", I18n.lang)   // i18n: keep
            assertEquals("Druckt", Format.stateLabel(Printer(state = "printing")))
            assertEquals("1,0", Format.decimal(1.0, 1))   // i18n: keep
            assertEquals("vor 3 Tagen", Format.ago(0, 3 * 86400))
            val now = java.time.ZonedDateTime.of(2026, 10, 1, 22, 50, 0, 0, java.time.ZoneId.of("Europe/Berlin"))   // i18n: keep
            assertEquals("morgen ~02:10", Format.finishAt(200 * 60L, now))   // i18n: keep
            assertEquals("So. ~10:50", Format.finishAt(60 * 3600L, now))   // i18n: keep
            assertEquals("Spule #7 angelegt", io.github.xnovosx.kobraspoolman.data.tr("Spool #{id} created", "id" to 7))
        } finally {
            I18n.use("en", null)
        }
    }
}

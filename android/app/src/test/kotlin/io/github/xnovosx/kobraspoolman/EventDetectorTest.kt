package io.github.xnovosx.kobraspoolman

import io.github.xnovosx.kobraspoolman.data.AppState
import io.github.xnovosx.kobraspoolman.data.Heater
import io.github.xnovosx.kobraspoolman.data.Notice
import io.github.xnovosx.kobraspoolman.data.Notices
import io.github.xnovosx.kobraspoolman.data.Printer
import io.github.xnovosx.kobraspoolman.monitor.EventDetector
import io.github.xnovosx.kobraspoolman.monitor.EventKind
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class EventDetectorTest {
    private fun st(state: String, layer: Int? = null, changing: Boolean = false, nozzle: Heater? = null,
                   notices: List<Notice> = emptyList(), message: String? = null) =
        AppState(printer = Printer(state = state, file = "drybox.gcode", layer = layer, layers = 100,
            changingFilament = changing, nozzle = nozzle, message = message), notices = Notices(notices))

    private fun titles(d: EventDetector, s: AppState?, t: Long) = d.update(s, t).map { it.title }

    @Test
    fun printLifecycle() {
        val d = EventDetector()
        assertEquals(emptyList<String>(), titles(d, st("standby"), 0))
        assertEquals(listOf("Druck gestartet"), titles(d, st("printing", layer = 1), 1_000))
        assertEquals(emptyList<String>(), titles(d, st("printing", layer = 1), 2_000))
        assertEquals(listOf("Erste Schicht fertig"), titles(d, st("printing", layer = 2), 3_000))
        assertEquals(emptyList<String>(), titles(d, st("printing", layer = 3), 4_000))   // nur einmal
        val paused = d.update(st("paused", layer = 3, message = "Filament leer"), 5_000)
        assertEquals(EventKind.ALARM, paused.single().kind)
        assertTrue(paused.single().text.contains("Filament leer"))
        assertEquals(listOf("Druck läuft weiter"), titles(d, st("printing", layer = 3), 6_000))
        assertEquals(listOf("Druck fertig"), titles(d, st("complete"), 7_000))
    }

    @Test
    fun startingMidPrintDoesNotRepeatOldEvents() {
        val d = EventDetector()
        val old = listOf(Notice("warn", "Slot 1: unbekannter Tag 4711", "tag1"))
        assertEquals(emptyList<String>(), titles(d, st("printing", layer = 40, notices = old), 0))
        assertEquals(emptyList<String>(), titles(d, st("printing", layer = 41, notices = old), 5_000))
    }

    @Test
    fun stuckChangeAndColdNozzle() {
        val d = EventDetector()
        d.update(st("printing", layer = 5), 0)
        assertEquals(emptyList<String>(), titles(d, st("printing", layer = 5, changing = true), 1_000))
        assertEquals(listOf("Farbwechsel hängt"), titles(d, st("printing", layer = 5, changing = true), 1_000 + 180_000))
        assertEquals(emptyList<String>(), titles(d, st("printing", layer = 5, changing = true), 1_000 + 200_000))
        val cold = Heater(temp = 180.0, target = 240.0)
        assertEquals(emptyList<String>(), titles(d, st("printing", layer = 6, nozzle = cold), 300_000))
        assertEquals(listOf("Düsentemperatur fällt"), titles(d, st("printing", layer = 6, nozzle = cold), 331_000))
    }

    @Test
    fun bridgeAndPrinterGoneOnlyMatterWhilePrinting() {
        val idle = EventDetector()
        idle.update(st("standby"), 0)
        assertEquals(emptyList<String>(), titles(idle, null, 1_000))
        assertEquals(emptyList<String>(), titles(idle, null, 120_000))                  // ohne Druck kein Alarm

        val d = EventDetector()
        d.update(st("printing", layer = 3), 0)
        assertEquals(emptyList<String>(), titles(d, null, 10_000))
        assertEquals(listOf("Bridge nicht erreichbar"), titles(d, null, 71_000))
        assertEquals(listOf("Bridge wieder erreichbar"), titles(d, st("printing", layer = 3), 80_000))
        assertEquals(emptyList<String>(), titles(d, st("offline"), 90_000))
        assertEquals(listOf("Drucker nicht erreichbar"), titles(d, st("offline"), 151_000))
    }

    @Test
    fun bridgeNoticesBecomeAlarmsOrHints() {
        val d = EventDetector()
        d.update(st("printing", layer = 3), 0)
        val reach = Notice("warn", "Slot 2 reicht wohl nicht", "reach2")
        val low = Notice("warn", "Slot 1 fast leer", "low1")
        val info = Notice("info", "Trockner fertig", "dryer")
        val ev = d.update(st("printing", layer = 3, notices = listOf(reach, low, info)), 5_000)
        assertEquals(listOf(EventKind.ALARM, EventKind.HINT), ev.map { it.kind })
        assertEquals(emptyList<String>(), titles(d, st("printing", layer = 3, notices = listOf(reach, low)), 10_000))
    }
}

package io.github.xnovosx.kobraspoolman

import io.github.xnovosx.kobraspoolman.data.AppState
import io.github.xnovosx.kobraspoolman.data.Heater
import io.github.xnovosx.kobraspoolman.data.LastControl
import io.github.xnovosx.kobraspoolman.data.Notice
import io.github.xnovosx.kobraspoolman.data.Notices
import io.github.xnovosx.kobraspoolman.data.Printer
import io.github.xnovosx.kobraspoolman.data.VisionEvent
import io.github.xnovosx.kobraspoolman.data.VisionInfo
import io.github.xnovosx.kobraspoolman.monitor.EventDetector
import io.github.xnovosx.kobraspoolman.monitor.EventKind
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class EventDetectorTest {
    private fun st(state: String, layer: Int? = null, changing: Boolean = false, nozzle: Heater? = null,
                   notices: List<Notice> = emptyList(), message: String? = null, control: LastControl? = null) =
        AppState(printer = Printer(state = state, file = "drybox.gcode", layer = layer, layers = 100,
            changingFilament = changing, nozzle = nozzle, message = message), notices = Notices(notices),
            lastControl = control)

    private fun titles(d: EventDetector, s: AppState?, t: Long) = d.update(s, t).map { it.title }

    @Test
    fun printLifecycle() {
        val d = EventDetector()
        assertEquals(emptyList<String>(), titles(d, st("standby"), 0))
        val start = d.update(st("printing", layer = 1), 1_000)
        assertEquals(listOf("Druck gestartet"), start.map { it.title })
        assertEquals(EventKind.START, start.single().kind)
        assertEquals(emptyList<String>(), titles(d, st("printing", layer = 1), 2_000))
        assertEquals(listOf(EventKind.LAYER), d.update(st("printing", layer = 2), 3_000).map { it.kind })
        assertEquals(emptyList<String>(), titles(d, st("printing", layer = 3), 4_000))   // nur einmal
        val paused = d.update(st("paused", layer = 3, message = "Filament leer"), 5_000)
        assertEquals(EventKind.ALARM, paused.single().kind)
        assertTrue(paused.single().text.contains("Filament leer"))
        assertEquals(emptyList<String>(), titles(d, st("printing", layer = 3), 6_000))   // weiter: steht in der Leiste
        assertEquals(listOf(EventKind.DONE), d.update(st("complete"), 7_000).map { it.kind })
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
        d.update(st("printing", layer = 6, nozzle = Heater(temp = 240.0, target = 240.0)), 290_000)   // Soll erreicht
        val cold = Heater(temp = 180.0, target = 240.0)
        assertEquals(emptyList<String>(), titles(d, st("printing", layer = 6, nozzle = cold), 300_000))
        assertEquals(emptyList<String>(), titles(d, st("printing", layer = 6, nozzle = cold), 331_000))   // < 60 s
        assertEquals(listOf("Düsentemperatur fällt"), titles(d, st("printing", layer = 6, nozzle = cold), 361_000))
    }

    /** Ablauf wie beim echten Druck am 03.10.: Aufheizen, Abtasten bei 140 degC, "error" fuer < 1 s. */
    @Test
    fun preparationOfARealPrintGivesNoAlarm() {
        val d = EventDetector()
        fun at(t: Long, state: String, temp: Double, target: Double, layer: Int = 0) =
            d.update(st(state, layer = layer, nozzle = Heater(temp = temp, target = target)), t * 1000).map { it.title }
        val all = mutableListOf<String>()
        all += at(0, "printing", 30.0, 0.0)
        for (t in 68L..144L step 5) all += at(t, "printing", 30.0 + (t - 68) * 2.3, 205.0)    // 76 s aufheizen
        all += at(150, "printing", 205.0, 205.0)
        for (t in 214L..700L step 20) all += at(t, "printing", 140.0, 140.0)                // abtasten
        all += at(709, "error", 140.0, 140.0)                                                 // kurzes Flackern
        all += at(710, "printing", 140.0, 140.0)
        for (t in 713L..746L step 5) all += at(t, "printing", 140.0 + (t - 713) * 2.0, 205.0)
        for (t in 3813L..3875L step 5) all += at(t, "printing", 140.0 + (t - 3813) * 1.7, 250.0)
        all += at(3880, "printing", 250.0, 250.0, layer = 1)
        assertEquals(emptyList<String>(), all.filter { it == "Düsentemperatur fällt" || it == "Druckerfehler" })
    }

    @Test
    fun printerErrorThatStaysIsAnAlarm() {
        val d = EventDetector()
        d.update(st("printing", layer = 3), 0)
        assertEquals(emptyList<String>(), titles(d, st("error", message = "Heizung"), 1_000))
        assertEquals(listOf("Druckerfehler"), titles(d, st("error", message = "Heizung"), 12_000))
        assertEquals(emptyList<String>(), titles(d, st("error", message = "Heizung"), 20_000))     // nur einmal
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
    fun ownPauseAndCancelAreNoAlarm() {
        val d = EventDetector()
        d.update(st("printing", layer = 3), 0)
        val mine = LastControl("pause", "Handy", at = 99.0)                        // vor 1 s ueber die Bridge
        assertEquals(emptyList<String>(), titles(d, st("paused", layer = 3, control = mine), 100_000))
        d.update(st("printing", layer = 3), 105_000)
        // spaeter pausiert der Drucker selbst (z. B. Filament leer) - die alte eigene Pause zaehlt nicht mehr
        assertEquals(listOf(EventKind.ALARM), d.update(st("paused", layer = 4, control = mine), 400_000).map { it.kind })
        d.update(st("printing", layer = 4), 405_000)
        val cancel = LastControl("cancel", "Firefox", at = 409.0)
        assertEquals(emptyList<String>(), titles(d, st("cancelled", control = cancel), 410_000))
    }

    @Test
    fun onlyActionableBridgeNoticesReachThePhone() {
        val d = EventDetector()
        d.update(st("printing", layer = 3), 0)
        val reach = Notice("warn", "Slot 2 reicht wohl nicht: braucht noch ~12 g", "reach2")
        val tag = Notice("warn", "Slot 3: unbekannter Tag 4711", "tag3")
        val low = Notice("warn", "Slot 1 fast leer", "low1")
        val open = Notice("warn", "1 Buchung noch nicht in Spoolman", "open")
        val cpu = Notice("warn", "Drucker-CPU bei 94 %", "cpu")
        val info = Notice("info", "Trockner fertig", "dryer")
        val ev = d.update(st("printing", layer = 3, notices = listOf(reach, tag, low, open, cpu, info)), 5_000)
        assertEquals(listOf(EventKind.ALARM, EventKind.HINT), ev.map { it.kind })
        // gleiche Meldung mit neuem Text (weniger Gramm) kommt nicht noch einmal
        val reach2 = reach.copy(text = "Slot 2 reicht wohl nicht: braucht noch ~11 g")
        assertEquals(emptyList<String>(), titles(d, st("printing", layer = 3, notices = listOf(reach2, tag)), 10_000))
    }

    @Test
    fun spoolmanGoneOnlyAfterFiveMinutes() {
        val d = EventDetector()
        d.update(st("standby"), 0)
        val sm = listOf(Notice("warn", "Spoolman nicht erreichbar", "spoolman"))
        assertEquals(emptyList<String>(), titles(d, st("standby", notices = sm), 1_000))
        assertEquals(emptyList<String>(), titles(d, st("standby", notices = sm), 200_000))
        assertEquals(listOf(EventKind.HINT), d.update(st("standby", notices = sm), 302_000).map { it.kind })
    }

    @Test
    fun aiAlarmCarriesTheEventForTheButtons() {
        val d = EventDetector()
        d.update(st("printing", layer = 3), 0)
        val ai = Notice("error", "KI: wahrscheinlich Fehldruck (Spaghetti) – Kamera prüfen", "ai-fail")
        val down = Notice("warn", "KI-Dienst nicht erreichbar", "ai-down")
        val state = st("printing", layer = 3, notices = listOf(ai, down))
            .copy(vision = VisionInfo(enabled = true, level = "fail", event = VisionEvent("abc123", "fail")))
        val ev = d.update(state, 5_000)
        assertEquals(1, ev.size)                                                   // "nicht erreichbar" bleibt in der App
        assertEquals(EventKind.ALARM, ev[0].kind)
        assertEquals("abc123", ev[0].aiEvent)
        assertEquals("KI: möglicher Fehldruck", ev[0].title)
        assertEquals("notice-ai", ev[0].key)                                       // ersetzt eine fruehere KI-Warnung
    }
}

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
        assertEquals(listOf("Print started"), start.map { it.title })
        assertEquals(EventKind.START, start.single().kind)
        assertEquals(emptyList<String>(), titles(d, st("printing", layer = 1), 2_000))
        assertEquals(listOf(EventKind.LAYER), d.update(st("printing", layer = 2), 3_000).map { it.kind })
        assertEquals(emptyList<String>(), titles(d, st("printing", layer = 3), 4_000))   // only once
        val paused = d.update(st("paused", layer = 3, message = "Filament runout"), 5_000)
        assertEquals(EventKind.ALARM, paused.single().kind)
        assertTrue(paused.single().text.contains("Filament runout"))
        assertEquals(emptyList<String>(), titles(d, st("printing", layer = 3), 6_000))   // resumed: shown in the status bar
        assertEquals(listOf(EventKind.DONE), d.update(st("complete"), 7_000).map { it.kind })
    }

    @Test
    fun startingMidPrintDoesNotRepeatOldEvents() {
        val d = EventDetector()
        val old = listOf(Notice("warn", "Slot 1: unknown tag 4711", "tag1"))
        assertEquals(emptyList<String>(), titles(d, st("printing", layer = 40, notices = old), 0))
        assertEquals(emptyList<String>(), titles(d, st("printing", layer = 41, notices = old), 5_000))
    }

    @Test
    fun stuckChangeAndColdNozzle() {
        val d = EventDetector()
        d.update(st("printing", layer = 5), 0)
        assertEquals(emptyList<String>(), titles(d, st("printing", layer = 5, changing = true), 1_000))
        assertEquals(listOf("Colour change stuck"), titles(d, st("printing", layer = 5, changing = true), 1_000 + 180_000))
        assertEquals(emptyList<String>(), titles(d, st("printing", layer = 5, changing = true), 1_000 + 200_000))
        d.update(st("printing", layer = 6, nozzle = Heater(temp = 240.0, target = 240.0)), 290_000)   // target reached
        val cold = Heater(temp = 180.0, target = 240.0)
        assertEquals(emptyList<String>(), titles(d, st("printing", layer = 6, nozzle = cold), 300_000))
        assertEquals(emptyList<String>(), titles(d, st("printing", layer = 6, nozzle = cold), 331_000))   // < 60 s
        assertEquals(listOf("Nozzle temperature dropping"), titles(d, st("printing", layer = 6, nozzle = cold), 361_000))
    }

    /** Sequence like the real print on 03.10.: heating, probing at 140 degC, "error" for < 1 s. */
    @Test
    fun preparationOfARealPrintGivesNoAlarm() {
        val d = EventDetector()
        fun at(t: Long, state: String, temp: Double, target: Double, layer: Int = 0) =
            d.update(st(state, layer = layer, nozzle = Heater(temp = temp, target = target)), t * 1000).map { it.title }
        val all = mutableListOf<String>()
        all += at(0, "printing", 30.0, 0.0)
        for (t in 68L..144L step 5) all += at(t, "printing", 30.0 + (t - 68) * 2.3, 205.0)    // 76 s heating
        all += at(150, "printing", 205.0, 205.0)
        for (t in 214L..700L step 20) all += at(t, "printing", 140.0, 140.0)                // probing
        all += at(709, "error", 140.0, 140.0)                                                 // brief flicker
        all += at(710, "printing", 140.0, 140.0)
        for (t in 713L..746L step 5) all += at(t, "printing", 140.0 + (t - 713) * 2.0, 205.0)
        for (t in 3813L..3875L step 5) all += at(t, "printing", 140.0 + (t - 3813) * 1.7, 250.0)
        all += at(3880, "printing", 250.0, 250.0, layer = 1)
        assertEquals(emptyList<String>(), all.filter { it == "Nozzle temperature dropping" || it == "Printer error" })
    }

    @Test
    fun printerErrorThatStaysIsAnAlarm() {
        val d = EventDetector()
        d.update(st("printing", layer = 3), 0)
        assertEquals(emptyList<String>(), titles(d, st("error", message = "Heater"), 1_000))
        assertEquals(listOf("Printer error"), titles(d, st("error", message = "Heater"), 12_000))
        assertEquals(emptyList<String>(), titles(d, st("error", message = "Heater"), 20_000))     // only once
    }

    @Test
    fun bridgeAndPrinterGoneOnlyMatterWhilePrinting() {
        val idle = EventDetector()
        idle.update(st("standby"), 0)
        assertEquals(emptyList<String>(), titles(idle, null, 1_000))
        assertEquals(emptyList<String>(), titles(idle, null, 120_000))                  // no alarm without a print

        val d = EventDetector()
        d.update(st("printing", layer = 3), 0)
        assertEquals(emptyList<String>(), titles(d, null, 10_000))
        assertEquals(listOf("Bridge not reachable"), titles(d, null, 71_000))
        assertEquals(listOf("Bridge reachable again"), titles(d, st("printing", layer = 3), 80_000))
        assertEquals(emptyList<String>(), titles(d, st("offline"), 90_000))
        assertEquals(listOf("Printer not reachable"), titles(d, st("offline"), 151_000))
    }

    @Test
    fun ownPauseAndCancelAreNoAlarm() {
        val d = EventDetector()
        d.update(st("printing", layer = 3), 0)
        val mine = LastControl("pause", "Phone", at = 99.0)                        // via the bridge 1 s ago
        assertEquals(emptyList<String>(), titles(d, st("paused", layer = 3, control = mine), 100_000))
        d.update(st("printing", layer = 3), 105_000)
        // later the printer pauses by itself (e.g. filament runout) - the old own pause no longer counts
        assertEquals(listOf(EventKind.ALARM), d.update(st("paused", layer = 4, control = mine), 400_000).map { it.kind })
        d.update(st("printing", layer = 4), 405_000)
        val cancel = LastControl("cancel", "Firefox", at = 409.0)
        assertEquals(emptyList<String>(), titles(d, st("cancelled", control = cancel), 410_000))
    }

    @Test
    fun onlyActionableBridgeNoticesReachThePhone() {
        val d = EventDetector()
        d.update(st("printing", layer = 3), 0)
        val reach = Notice("warn", "Slot 2 is probably not enough: needs ~12 g more", "reach2")
        val tag = Notice("warn", "Slot 3: unknown tag 4711", "tag3")
        val low = Notice("warn", "Slot 1 almost empty", "low1")
        val open = Notice("warn", "1 booking not yet in Spoolman", "open")
        val cpu = Notice("warn", "Printer CPU at 94 %", "cpu")
        val info = Notice("info", "Dryer done", "dryer")
        val ev = d.update(st("printing", layer = 3, notices = listOf(reach, tag, low, open, cpu, info)), 5_000)
        assertEquals(listOf(EventKind.ALARM, EventKind.HINT), ev.map { it.kind })
        // the same message with a new text (fewer grams) does not come again
        val reach2 = reach.copy(text = "Slot 2 is probably not enough: needs ~11 g more")
        assertEquals(emptyList<String>(), titles(d, st("printing", layer = 3, notices = listOf(reach2, tag)), 10_000))
    }

    @Test
    fun spoolmanGoneOnlyAfterFiveMinutes() {
        val d = EventDetector()
        d.update(st("standby"), 0)
        val sm = listOf(Notice("warn", "Spoolman not reachable", "spoolman"))
        assertEquals(emptyList<String>(), titles(d, st("standby", notices = sm), 1_000))
        assertEquals(emptyList<String>(), titles(d, st("standby", notices = sm), 200_000))
        assertEquals(listOf(EventKind.HINT), d.update(st("standby", notices = sm), 302_000).map { it.kind })
    }

    @Test
    fun aiAlarmCarriesTheEventForTheButtons() {
        val d = EventDetector()
        d.update(st("printing", layer = 3), 0)
        val ai = Notice("error", "AI: probably a failure (spaghetti) – check the camera", "ai-fail")
        val down = Notice("warn", "AI service not reachable", "ai-down")
        val state = st("printing", layer = 3, notices = listOf(ai, down))
            .copy(vision = VisionInfo(enabled = true, level = "fail", event = VisionEvent("abc123", "fail")))
        val ev = d.update(state, 5_000)
        assertEquals(1, ev.size)                                                   // "not reachable" stays in the app
        assertEquals(EventKind.ALARM, ev[0].kind)
        assertEquals("abc123", ev[0].aiEvent)
        assertEquals("AI: possible failure", ev[0].title)
        assertEquals("notice-ai", ev[0].key)                                       // replaces an earlier AI warning
    }
}

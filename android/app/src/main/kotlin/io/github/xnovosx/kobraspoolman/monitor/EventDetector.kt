package io.github.xnovosx.kobraspoolman.monitor

import io.github.xnovosx.kobraspoolman.data.AppState
import io.github.xnovosx.kobraspoolman.data.tr
import kotlin.math.abs

/** Kind of notification - one Android channel per kind with its own sound (adjustable separately). */
enum class EventKind { START, LAYER, DONE, ALARM, HINT }

/** An event for a notification. key: the same message replaces itself instead of stacking. vpn: offer to open the
 *  VPN app (away from home). */
data class PrintEvent(val kind: EventKind, val title: String, val text: String, val key: String,
                      val aiEvent: String? = null, val vpn: Boolean = false)

/**
 * Detects from consecutive bridge queries what should be reported (without Android - testable).
 * state = null means: bridge not reachable; away = the phone is outside the home network (HomeNetwork) - then the
 * bridge being gone is no alarm but a quiet hint: nothing is known about the print from here.
 */
class EventDetector(
    private val changeStuckMs: Long = 3 * 60_000L,
    private val tempDropMs: Long = 60_000L,
    private val errorMs: Long = 10_000L,
    private val tempDropK: Double = 15.0,
    private val goneMs: Long = 60_000L,
    private val spoolmanMs: Long = 5 * 60_000L,
    private val ownActionMs: Long = 120_000L,
) {
    private var prevState: String? = null
    private var firstLayerFile: String? = null
    private var changingSince: Long? = null
    private var changeAlarmed = false
    private var coldSince: Long? = null
    private var coldAlarmed = false
    // nozzle: only once the target was reached is "below" a cool-down (otherwise heating up)
    private var nozzleTarget = 0.0
    private var nozzleReached = false
    private var errorSince: Long? = null
    private var errorAlarmed = false
    private var bridgeGoneSince: Long? = null
    private var bridgeAlarmed = false
    private var printerGoneSince: Long? = null
    private var printerAlarmed = false
    private var wasPrinting = false
    private var spoolmanSince: Long? = null
    private val noticeKeys = mutableSetOf<String>()

    /** These bridge messages are already covered by the print state (else duplicate). */
    private val ownKeys = setOf("printer", "klippy", "paused", "error", "done", "camera", "rfid")

    fun update(state: AppState?, now: Long, away: Boolean = false): List<PrintEvent> {
        val out = mutableListOf<PrintEvent>()
        if (state == null) {
            val since = bridgeGoneSince ?: now.also { bridgeGoneSince = it }
            if (wasPrinting && !bridgeAlarmed && now - since >= goneMs) {
                bridgeAlarmed = true
                out += if (away) PrintEvent(EventKind.HINT, tr("Away from home"),
                    tr("The bridge cannot be reached from here – the print was still running. With the VPN on, the app keeps watching."),
                    "bridge", vpn = true)
                else PrintEvent(EventKind.ALARM, tr("Bridge not reachable"),
                    tr("No connection for over a minute – the print was still running."), "bridge")
            }
            return out
        }
        if (bridgeAlarmed) out += PrintEvent(EventKind.HINT, tr("Bridge reachable again"), tr("Connection is back."), "bridge")
        bridgeGoneSince = null
        bridgeAlarmed = false

        val p = state.printer
        val st = p.state
        val printing = st == "printing" || st == "paused"
        val file = p.file?.substringAfterLast('/')?.removeSuffix(".gcode") ?: tr("Print")
        val prev = prevState
        if (prev == null) {
            // first state after the service started: only remember, report nothing that was already so
            prevState = st
            wasPrinting = printing
            if (printing && (p.layer ?: 0) >= 2) firstLayerFile = file
            noticeKeys += state.notices?.messages.orEmpty().map { it.key }
            return out
        }

        // ---- print state
        if (prev != st) {
            val was = prev == "printing" || prev == "paused"
            // pause/cancel via web or app came from you - no alarm (the live bar shows "Paused")
            val lc = state.lastControl
            fun own(action: String) = lc != null && lc.action == action && abs(now - (lc.at * 1000).toLong()) < ownActionMs
            when {
                st == "printing" && !was -> {
                    firstLayerFile = null
                    out += PrintEvent(EventKind.START, tr("Print started"), file, "state")
                }
                st == "paused" && !own("pause") -> out += PrintEvent(EventKind.ALARM, tr("Print paused"),
                    listOfNotNull(file, p.message).joinToString(" – "), "state")
                st == "complete" && was -> out += PrintEvent(EventKind.DONE, tr("Print finished"),
                    file + (p.printDurationS?.let { " · ${formatDuration(it)}" } ?: ""), "state")
                st == "cancelled" && was && !own("cancel") ->
                    out += PrintEvent(EventKind.ALARM, tr("Print cancelled"), file, "state")
                // GoKlipper also reports "error" for < 1 s during preparation - only report below after errorMs
            }
        }
        prevState = st

        // ---- printer error that stays (ignore brief flicker during preparation)
        if (st == "error") {
            val since = errorSince ?: now.also { errorSince = it }
            if (!errorAlarmed && now - since >= errorMs) {
                errorAlarmed = true
                out += PrintEvent(EventKind.ALARM, tr("Printer error"), p.message ?: tr("The printer reports an error."), "state")
            }
        } else {
            errorSince = null
            errorAlarmed = false
        }

        // ---- printer gone (only while a print was running)
        if (st == "offline") {
            val since = printerGoneSince ?: now.also { printerGoneSince = it }
            if (wasPrinting && !printerAlarmed && now - since >= goneMs) {
                printerAlarmed = true
                out += PrintEvent(EventKind.ALARM, tr("Printer not reachable"),
                    tr("Moonraker has not answered for over a minute – the print was still running."), "printer")
            }
        } else {
            printerGoneSince = null
            printerAlarmed = false
            wasPrinting = printing
        }

        // ---- first layer
        val layer = p.layer
        if (st == "printing" && layer != null && layer >= 2 && firstLayerFile != file) {
            firstLayerFile = file
            out += PrintEvent(EventKind.LAYER, tr("First layer done"), tr("{file} – have a quick look at the bed now", "file" to file), "layer")
        }

        // ---- colour change stuck
        if (st == "printing" && p.changingFilament) {
            val since = changingSince ?: now.also { changingSince = it }
            if (!changeAlarmed && now - since >= changeStuckMs) {
                changeAlarmed = true
                out += PrintEvent(EventKind.ALARM, tr("Colour change stuck"),
                    tr("For {n} minutes", "n" to (now - since) / 60_000) + (p.mmuAction?.let { " – ACE: $it" } ?: ""), "change")
            }
        } else {
            changingSince = null
            changeAlarmed = false
        }

        // ---- nozzle cools down during the print: only if the target was reached (new/higher target = heating up),
        // only from layer 1 (preparation: probing at 140 degC, heating) and only after tempDropMs
        val n = p.nozzle
        if (n == null || n.target <= 0 || n.target != nozzleTarget) {
            nozzleTarget = n?.target ?: 0.0
            nozzleReached = false
        }
        if (n != null && n.target > 0 && n.temp >= n.target - 5) nozzleReached = true
        if (st == "printing" && n != null && nozzleReached && (p.layer ?: 0) >= 1 && n.temp < n.target - tempDropK) {
            val since = coldSince ?: now.also { coldSince = it }
            if (!coldAlarmed && now - since >= tempDropMs) {
                coldAlarmed = true
                out += PrintEvent(EventKind.ALARM, tr("Nozzle temperature dropping"),
                    tr("{temp} °C instead of {target} °C", "temp" to n.temp.toInt(), "target" to n.target.toInt()), "temp")
            }
        } else {
            coldSince = null
            coldAlarmed = false
        }

        // ---- bridge messages: only what you can act on. Red and "not enough" -> alarm; unknown tag, dryer too cold
        // and Spoolman gone for longer -> hint; everything else (almost empty, open booking, moisture ...) stays in the app.
        // Same message = same key (the text changes, e.g. "needs 12 g more" -> "11 g").
        val messages = state.notices?.messages.orEmpty()
        spoolmanSince = if (messages.any { it.key == "spoolman" }) spoolmanSince ?: now else null
        val current = messages.filter { m ->
            // dryer_lid: the ACE does not get warm while drying (lid open?) - worth a hint, it wastes hours
            m.key !in ownKeys && (m.level == "error" || m.key.startsWith("reach") || m.key.startsWith("tag") ||
                m.key == "dryer_lid" ||
                (m.key == "spoolman" && now - (spoolmanSince ?: now) >= spoolmanMs))
        }
        noticeKeys.retainAll(current.map { it.key }.toSet())
        for (m in current) {
            if (m.key in noticeKeys) continue
            noticeKeys += m.key
            val alarm = m.level == "error" || m.key.startsWith("reach")
            val ai = m.key.startsWith("ai-") && m.key != "ai-down"
            out += PrintEvent(if (alarm) EventKind.ALARM else EventKind.HINT,
                // AI: warn and fail share one notification - "failure" replaces "suspicious"
                if (ai) tr("AI: possible failure") else if (alarm) tr("Attention") else tr("Note"), m.text,
                if (ai) "notice-ai" else "notice-" + m.key,
                aiEvent = if (ai) state.vision?.event?.id else null)
        }
        return out
    }

    companion object {
        fun formatDuration(seconds: Long): String {
            val m = (seconds + 30) / 60
            return if (m >= 60) "${m / 60} h ${m % 60} min" else "$m min"
        }
    }
}

package io.github.xnovosx.kobraspoolman.monitor

import io.github.xnovosx.kobraspoolman.data.AppState

/** Art einer Benachrichtigung - je Art ein eigener Android-Kanal (laut/leise einzeln einstellbar). */
enum class EventKind { PRINT, ALARM, HINT }

/** Ein Ereignis fuer eine Benachrichtigung. key: dieselbe Meldung ersetzt sich selbst statt zu stapeln. */
data class PrintEvent(val kind: EventKind, val title: String, val text: String, val key: String)

/**
 * Erkennt aus aufeinanderfolgenden Abfragen der Bridge, was gemeldet werden soll (ohne Android - testbar).
 * state = null heisst: Bridge nicht erreichbar.
 */
class EventDetector(
    private val changeStuckMs: Long = 3 * 60_000L,
    private val tempDropMs: Long = 30_000L,
    private val tempDropK: Double = 15.0,
    private val goneMs: Long = 60_000L,
) {
    private var prevState: String? = null
    private var firstLayerFile: String? = null
    private var changingSince: Long? = null
    private var changeAlarmed = false
    private var coldSince: Long? = null
    private var coldAlarmed = false
    private var bridgeGoneSince: Long? = null
    private var bridgeAlarmed = false
    private var printerGoneSince: Long? = null
    private var printerAlarmed = false
    private var wasPrinting = false
    private val noticeKeys = mutableSetOf<String>()

    /** Diese Meldungen der Bridge deckt der Druckzustand schon ab (sonst doppelt). */
    private val ownKeys = setOf("printer", "klippy", "paused", "error", "done", "camera", "rfid")

    fun update(state: AppState?, now: Long): List<PrintEvent> {
        val out = mutableListOf<PrintEvent>()
        if (state == null) {
            val since = bridgeGoneSince ?: now.also { bridgeGoneSince = it }
            if (wasPrinting && !bridgeAlarmed && now - since >= goneMs) {
                bridgeAlarmed = true
                out += PrintEvent(EventKind.ALARM, "Bridge nicht erreichbar",
                    "Seit über einer Minute keine Verbindung – der Druck lief zuletzt noch.", "bridge")
            }
            return out
        }
        if (bridgeAlarmed) out += PrintEvent(EventKind.HINT, "Bridge wieder erreichbar", "Verbindung steht wieder.", "bridge")
        bridgeGoneSince = null
        bridgeAlarmed = false

        val p = state.printer
        val st = p.state
        val printing = st == "printing" || st == "paused"
        val file = p.file?.substringAfterLast('/')?.removeSuffix(".gcode") ?: "Druck"
        val prev = prevState
        if (prev == null) {
            // erster Stand nach dem Start des Dienstes: nur merken, nichts melden, was schon vorher so war
            prevState = st
            wasPrinting = printing
            if (printing && (p.layer ?: 0) >= 2) firstLayerFile = file
            noticeKeys += state.notices?.messages.orEmpty().map { it.key + "|" + it.text }
            return out
        }

        // ---- Druckzustand
        if (prev != st) {
            val was = prev == "printing" || prev == "paused"
            when {
                st == "printing" && prev == "paused" ->
                    out += PrintEvent(EventKind.PRINT, "Druck läuft weiter", file, "state")
                st == "printing" && !was -> {
                    firstLayerFile = null
                    out += PrintEvent(EventKind.PRINT, "Druck gestartet", file, "state")
                }
                st == "paused" -> out += PrintEvent(EventKind.ALARM, "Druck pausiert",
                    listOfNotNull(file, p.message).joinToString(" – "), "state")
                st == "complete" && was -> out += PrintEvent(EventKind.PRINT, "Druck fertig",
                    file + (p.printDurationS?.let { " · ${formatDuration(it)}" } ?: ""), "state")
                st == "cancelled" && was -> out += PrintEvent(EventKind.ALARM, "Druck abgebrochen", file, "state")
                st == "error" -> out += PrintEvent(EventKind.ALARM, "Druckerfehler",
                    p.message ?: "Der Drucker meldet einen Fehler.", "state")
            }
        }
        prevState = st

        // ---- Drucker weg (nur, wenn gerade gedruckt wurde)
        if (st == "offline") {
            val since = printerGoneSince ?: now.also { printerGoneSince = it }
            if (wasPrinting && !printerAlarmed && now - since >= goneMs) {
                printerAlarmed = true
                out += PrintEvent(EventKind.ALARM, "Drucker nicht erreichbar",
                    "Moonraker antwortet seit über einer Minute nicht – der Druck lief zuletzt noch.", "printer")
            }
        } else {
            printerGoneSince = null
            printerAlarmed = false
            wasPrinting = printing
        }

        // ---- erste Schicht
        val layer = p.layer
        if (st == "printing" && layer != null && layer >= 2 && firstLayerFile != file) {
            firstLayerFile = file
            out += PrintEvent(EventKind.PRINT, "Erste Schicht fertig", "$file – jetzt kurz aufs Bett schauen", "layer")
        }

        // ---- Farbwechsel haengt
        if (st == "printing" && p.changingFilament) {
            val since = changingSince ?: now.also { changingSince = it }
            if (!changeAlarmed && now - since >= changeStuckMs) {
                changeAlarmed = true
                out += PrintEvent(EventKind.ALARM, "Farbwechsel hängt",
                    "Seit ${(now - since) / 60_000} Minuten" + (p.mmuAction?.let { " – ACE: $it" } ?: ""), "change")
            }
        } else {
            changingSince = null
            changeAlarmed = false
        }

        // ---- Duese kuehlt im Druck ab
        val n = p.nozzle
        if (st == "printing" && n != null && n.target > 0 && n.temp < n.target - tempDropK) {
            val since = coldSince ?: now.also { coldSince = it }
            if (!coldAlarmed && now - since >= tempDropMs) {
                coldAlarmed = true
                out += PrintEvent(EventKind.ALARM, "Düsentemperatur fällt",
                    "${n.temp.toInt()} °C statt ${n.target.toInt()} °C", "temp")
            }
        } else {
            coldSince = null
            coldAlarmed = false
        }

        // ---- Meldungen der Bridge: neue rote -> Alarm, gelbe -> Hinweis ("reicht nicht" ist ein Alarm)
        val current = state.notices?.messages.orEmpty().filter { it.key !in ownKeys && it.level != "info" }
        val keys = current.map { it.key + "|" + it.text }.toSet()
        noticeKeys.retainAll(keys)
        for (m in current) {
            val id = m.key + "|" + m.text
            if (id in noticeKeys) continue
            noticeKeys += id
            val alarm = m.level == "error" || m.key.startsWith("reach")
            out += PrintEvent(if (alarm) EventKind.ALARM else EventKind.HINT,
                if (alarm) "Achtung" else "Hinweis", m.text, "notice-" + m.key)
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

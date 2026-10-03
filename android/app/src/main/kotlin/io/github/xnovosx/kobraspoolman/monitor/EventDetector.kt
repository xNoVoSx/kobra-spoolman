package io.github.xnovosx.kobraspoolman.monitor

import io.github.xnovosx.kobraspoolman.data.AppState
import kotlin.math.abs

/** Art einer Benachrichtigung - je Art ein eigener Android-Kanal mit eigenem Ton (einzeln einstellbar). */
enum class EventKind { START, LAYER, DONE, ALARM, HINT }

/** Ein Ereignis fuer eine Benachrichtigung. key: dieselbe Meldung ersetzt sich selbst statt zu stapeln. */
data class PrintEvent(val kind: EventKind, val title: String, val text: String, val key: String,
                      val aiEvent: String? = null)

/**
 * Erkennt aus aufeinanderfolgenden Abfragen der Bridge, was gemeldet werden soll (ohne Android - testbar).
 * state = null heisst: Bridge nicht erreichbar.
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
    // Duese: erst wenn das Soll einmal erreicht war, ist "darunter" ein Abkuehlen (sonst Aufheizen)
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
            noticeKeys += state.notices?.messages.orEmpty().map { it.key }
            return out
        }

        // ---- Druckzustand
        if (prev != st) {
            val was = prev == "printing" || prev == "paused"
            // Pause/Abbruch ueber Web oder App kam von dir - kein Alarm (die Live-Leiste zeigt "Pausiert")
            val lc = state.lastControl
            fun own(action: String) = lc != null && lc.action == action && abs(now - (lc.at * 1000).toLong()) < ownActionMs
            when {
                st == "printing" && !was -> {
                    firstLayerFile = null
                    out += PrintEvent(EventKind.START, "Druck gestartet", file, "state")
                }
                st == "paused" && !own("pause") -> out += PrintEvent(EventKind.ALARM, "Druck pausiert",
                    listOfNotNull(file, p.message).joinToString(" – "), "state")
                st == "complete" && was -> out += PrintEvent(EventKind.DONE, "Druck fertig",
                    file + (p.printDurationS?.let { " · ${formatDuration(it)}" } ?: ""), "state")
                st == "cancelled" && was && !own("cancel") ->
                    out += PrintEvent(EventKind.ALARM, "Druck abgebrochen", file, "state")
                // "error" meldet GoKlipper in der Vorbereitung auch fuer < 1 s - erst unten nach errorMs melden
            }
        }
        prevState = st

        // ---- Druckerfehler, der bleibt (kurzes Flackern in der Vorbereitung ignorieren)
        if (st == "error") {
            val since = errorSince ?: now.also { errorSince = it }
            if (!errorAlarmed && now - since >= errorMs) {
                errorAlarmed = true
                out += PrintEvent(EventKind.ALARM, "Druckerfehler", p.message ?: "Der Drucker meldet einen Fehler.", "state")
            }
        } else {
            errorSince = null
            errorAlarmed = false
        }

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
            out += PrintEvent(EventKind.LAYER, "Erste Schicht fertig", "$file – jetzt kurz aufs Bett schauen", "layer")
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

        // ---- Duese kuehlt im Druck ab: nur wenn das Soll schon erreicht war (neues/hoeheres Soll = Aufheizen),
        // erst ab Schicht 1 (Vorbereitung: Abtasten bei 140 degC, Aufheizen) und erst nach tempDropMs
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
                out += PrintEvent(EventKind.ALARM, "Düsentemperatur fällt",
                    "${n.temp.toInt()} °C statt ${n.target.toInt()} °C", "temp")
            }
        } else {
            coldSince = null
            coldAlarmed = false
        }

        // ---- Meldungen der Bridge: nur, was man tun kann. Rot und "reicht nicht" -> Alarm; unbekannter Tag und
        // Spoolman laenger weg -> Hinweis; alles andere (fast leer, offene Buchung, Feuchte ...) bleibt in der App.
        // Gleiche Meldung = gleicher key (der Text aendert sich, z. B. "braucht noch 12 g" -> "11 g").
        val messages = state.notices?.messages.orEmpty()
        spoolmanSince = if (messages.any { it.key == "spoolman" }) spoolmanSince ?: now else null
        val current = messages.filter { m ->
            m.key !in ownKeys && (m.level == "error" || m.key.startsWith("reach") || m.key.startsWith("tag") ||
                (m.key == "spoolman" && now - (spoolmanSince ?: now) >= spoolmanMs))
        }
        noticeKeys.retainAll(current.map { it.key }.toSet())
        for (m in current) {
            if (m.key in noticeKeys) continue
            noticeKeys += m.key
            val alarm = m.level == "error" || m.key.startsWith("reach")
            val ai = m.key.startsWith("ai-") && m.key != "ai-down"
            out += PrintEvent(if (alarm) EventKind.ALARM else EventKind.HINT,
                // KI: warn und fail teilen sich eine Benachrichtigung - "Fehldruck" ersetzt "verdaechtig"
                if (ai) "KI: möglicher Fehldruck" else if (alarm) "Achtung" else "Hinweis", m.text,
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

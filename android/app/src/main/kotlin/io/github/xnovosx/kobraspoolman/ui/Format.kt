package io.github.xnovosx.kobraspoolman.ui

import io.github.xnovosx.kobraspoolman.data.Printer
import kotlin.math.roundToInt

/** Anzeige-Texte (deutsch), ohne Android-Abhaengigkeiten - per JVM-Test pruefbar. */
object Format {
    fun grams(g: Double?): String = if (g == null) "? g" else "${g.roundToInt()} g"

    fun duration(seconds: Long?): String {
        if (seconds == null || seconds < 0) return "–"
        val m = (seconds + 30) / 60
        return if (m >= 60) "${m / 60} h ${m % 60} min" else "$m min"
    }

    /**
     * Ungefaehre Uhrzeit, wann der Druck fertig ist: "~14:35", "morgen ~02:10", sonst mit Wochentag "Fr. ~09:00".
     */
    fun finishAt(etaS: Long?, now: java.time.ZonedDateTime = java.time.ZonedDateTime.now()): String {
        if (etaS == null || etaS < 0) return "–"
        val end = now.plusSeconds(etaS)
        val time = "~%02d:%02d".format(end.hour, end.minute)
        val days = java.time.temporal.ChronoUnit.DAYS.between(now.toLocalDate(), end.toLocalDate())
        return when (days) {
            0L -> time
            1L -> "morgen $time"
            else -> end.format(java.time.format.DateTimeFormatter.ofPattern("EE", java.util.Locale.GERMANY)) + " $time"
        }
    }

    /** Feste Nachkommastellen mit Komma: decimal(1.0, 1) = "1,0". */
    fun decimal(v: Double?, digits: Int = 1): String =
        if (v == null) "–" else String.format(java.util.Locale.GERMANY, "%.${digits}f", v)

    /** Eingabe "0,8" / "0.8" -> 0.8; leer oder ungueltig -> null. */
    fun parseDecimal(t: String): Double? = t.trim().replace(',', '.').toDoubleOrNull()

    fun percent(p: Double?): String = if (p == null) "" else "${(p * 100).roundToInt()} %"

    /** Anteil Rest/Anfang fuer den Balken, 0..1. */
    fun fill(remaining: Double?, initial: Double?): Float {
        if (remaining == null || initial == null || initial <= 0) return 0f
        return (remaining / initial).toFloat().coerceIn(0f, 1f)
    }

    /** Zustand fuer Farben/Beschriftung; Filamentwechsel hat eine eigene Anzeige. */
    fun stateKey(p: Printer): String = if (p.state == "printing" && p.changingFilament) "changing" else p.state

    fun stateLabel(p: Printer): String = when (stateKey(p)) {
        "printing" -> "Druckt"
        "changing" -> "Wechselt Filament"
        "paused" -> "Pausiert"
        "complete" -> "Fertig"
        "cancelled" -> "Abgebrochen"
        "error" -> "Fehler"
        "offline" -> "Offline"
        else -> "Bereit"
    }
}

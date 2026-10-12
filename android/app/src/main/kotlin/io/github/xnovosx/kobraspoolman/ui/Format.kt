package io.github.xnovosx.kobraspoolman.ui

import io.github.xnovosx.kobraspoolman.data.I18n
import io.github.xnovosx.kobraspoolman.data.Printer
import io.github.xnovosx.kobraspoolman.data.tr
import kotlin.math.roundToInt

/** Display texts in the app language (I18n), without Android dependencies - testable on the JVM. */
object Format {
    fun grams(g: Double?): String = if (g == null) "? g" else "${g.roundToInt()} g"

    fun duration(seconds: Long?): String {
        if (seconds == null || seconds < 0) return "–"
        val m = (seconds + 30) / 60
        return if (m >= 60) "${m / 60} h ${m % 60} min" else "$m min"
    }

    /**
     * Approximate time the print is done: "~14:35", "tomorrow ~02:10", else with the weekday "Fri ~09:00".
     */
    fun finishAt(etaS: Long?, now: java.time.ZonedDateTime = java.time.ZonedDateTime.now()): String {
        if (etaS == null || etaS < 0) return "–"
        val end = now.plusSeconds(etaS)
        val time = "~%02d:%02d".format(end.hour, end.minute)
        val days = java.time.temporal.ChronoUnit.DAYS.between(now.toLocalDate(), end.toLocalDate())
        return when (days) {
            0L -> time
            1L -> tr("tomorrow {time}", "time" to time)
            else -> end.format(java.time.format.DateTimeFormatter.ofPattern("EE", I18n.locale)) + " $time"
        }
    }

    /** "just now", "5 min ago", "3 h ago", "2 days ago" (epochS = Unix seconds). */
    fun ago(epochS: Long, nowS: Long = System.currentTimeMillis() / 1000): String {
        val d = (nowS - epochS).coerceAtLeast(0)
        return when {
            d < 60 -> tr("just now")
            d < 3600 -> tr("{n} min ago", "n" to d / 60)
            d < 86400 -> tr("{n} h ago", "n" to d / 3600)
            d < 2 * 86400 -> tr("1 day ago")
            else -> tr("{n} days ago", "n" to d / 86400)
        }
    }

    /** Fixed decimals in the app language: decimal(1.0, 1) = "1.0" / "1,0". */
    fun decimal(v: Double?, digits: Int = 1): String =
        if (v == null) "–" else String.format(I18n.locale, "%.${digits}f", v)

    /** Input "0,8" / "0.8" -> 0.8; empty or invalid -> null. */
    fun parseDecimal(t: String): Double? = t.trim().replace(',', '.').toDoubleOrNull()

    fun percent(p: Double?): String = if (p == null) "" else "${(p * 100).roundToInt()} %"

    /** Share remaining/initial for the bar, 0..1. */
    fun fill(remaining: Double?, initial: Double?): Float {
        if (remaining == null || initial == null || initial <= 0) return 0f
        return (remaining / initial).toFloat().coerceIn(0f, 1f)
    }

    /** State for colours/labels; a filament change has its own display. */
    fun stateKey(p: Printer): String = if (p.state == "printing" && p.changingFilament) "changing" else p.state

    /** Headline: the print phase of the bridge, else the state. */
    fun headline(p: Printer): String = p.phase ?: stateLabel(p)

    /** Print phase only when it says more than "Printing · layer" (for notification/widget). */
    fun extraPhase(p: Printer): String? = p.phase?.takeIf { p.phaseKey != null && p.phaseKey != "printing" }

    /** Second line of notification and widget: phase · time left · finish · layer. */
    fun progressLine(p: Printer): String = listOfNotNull(
        extraPhase(p),
        p.etaS?.let { tr("{time} left", "time" to duration(it)) },
        p.etaS?.let { tr("done {time}", "time" to finishAt(it)) },
        if (p.layer != null && p.layers != null) tr("layer {layer}/{layers}", "layer" to p.layer, "layers" to p.layers) else null,
    ).joinToString(" · ")

    fun stateLabel(p: Printer): String = when (stateKey(p)) {
        "printing" -> tr("Printing")
        "changing" -> tr("Changing filament")
        "paused" -> tr("Paused")
        "complete" -> tr("Finished")
        "cancelled" -> tr("Cancelled")
        "error" -> tr("Error")
        "offline" -> tr("Offline")
        else -> tr("Ready")
    }
}

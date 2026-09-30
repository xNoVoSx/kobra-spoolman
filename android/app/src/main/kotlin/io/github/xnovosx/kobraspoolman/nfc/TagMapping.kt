package io.github.xnovosx.kobraspoolman.nfc

import io.github.xnovosx.kobraspoolman.data.TagContent
import kotlin.math.roundToInt

/** Bridge-Inhalt -> ACE-Tag. Fehlt etwas, das die ACE braucht, gibt es eine verstaendliche Meldung. */
fun TagContent.toAceTag(): AceTag {
    val nMin = nozzleMin ?: nozzleMax ?: error("Düsentemperatur fehlt am Filament und in der Vorlage")
    val bMin = bedMin ?: bedMax ?: error("Betttemperatur fehlt am Filament und in der Vorlage")
    require(color.length == 6) { "Farbe fehlt am Filament" }
    return AceTag(
        sku = sku, brand = brand.take(20), material = material.take(20), color = color,
        nozzleMin = nMin, nozzleMax = nozzleMax ?: nMin, bedMin = bMin, bedMax = bedMax ?: bMin,
        diameterMm = diameterMm, lengthM = (lengthM ?: 0.0).roundToInt(), weightG = (weightG ?: 0.0).roundToInt(),
    )
}

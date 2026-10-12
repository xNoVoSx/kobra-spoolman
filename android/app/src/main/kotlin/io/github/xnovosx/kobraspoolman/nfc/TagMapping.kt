package io.github.xnovosx.kobraspoolman.nfc

import io.github.xnovosx.kobraspoolman.data.TagContent
import kotlin.math.roundToInt
import io.github.xnovosx.kobraspoolman.data.tr

/** Bridge content -> ACE tag. If something the ACE needs is missing, there is an understandable message. */
fun TagContent.toAceTag(): AceTag {
    val nMin = nozzleMin ?: nozzleMax ?: error(tr("Nozzle temperature missing on the filament and in the template"))
    val bMin = bedMin ?: bedMax ?: error(tr("Bed temperature missing on the filament and in the template"))
    require(color.length == 6) { tr("Colour missing on the filament") }
    return AceTag(
        sku = sku, brand = brand.take(20), material = material.take(20), color = color,
        nozzleMin = nMin, nozzleMax = nozzleMax ?: nMin, bedMin = bMin, bedMax = bedMax ?: bMin,
        diameterMm = diameterMm, lengthM = (lengthM ?: 0.0).roundToInt(), weightG = (weightG ?: 0.0).roundToInt(),
    )
}

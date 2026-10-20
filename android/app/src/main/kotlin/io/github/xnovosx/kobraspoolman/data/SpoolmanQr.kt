package io.github.xnovosx.kobraspoolman.data

/**
 * QR codes from Spoolman's label printing. Spoolman writes one of two forms (setting "Use HTTP URL"):
 * `web+spoolman:s-<id>` (spool) / `web+spoolman:f-<id>` (filament), or its own address
 * `http(s)://<host>/spool/show/<id>` / `.../filament/show/<id>`. The host differs per install - only the ID counts.
 */
sealed interface SpoolmanQr {
    data class Spool(val id: Int) : SpoolmanQr
    data class Filament(val id: Int) : SpoolmanQr

    companion object {
        private val SCHEME = Regex("""^web\+spoolman:([sf])-(\d+)$""", RegexOption.IGNORE_CASE)
        private val HTTP = Regex("""^https?://[^/\s]+(?:/[^\s]*)?/(spool|filament)/show/(\d+)/?(?:[?#].*)?$""", RegexOption.IGNORE_CASE)

        /** null = not a Spoolman code (e.g. some other QR code on the box). */
        fun parse(text: String?): SpoolmanQr? {
            val t = text?.trim() ?: return null
            SCHEME.find(t)?.let { m ->
                val id = m.groupValues[2].toIntOrNull()?.takeIf { it > 0 } ?: return null
                return if (m.groupValues[1].equals("s", true)) Spool(id) else Filament(id)
            }
            HTTP.find(t)?.let { m ->
                val id = m.groupValues[2].toIntOrNull()?.takeIf { it > 0 } ?: return null
                return if (m.groupValues[1].equals("spool", true)) Spool(id) else Filament(id)
            }
            return null
        }
    }
}

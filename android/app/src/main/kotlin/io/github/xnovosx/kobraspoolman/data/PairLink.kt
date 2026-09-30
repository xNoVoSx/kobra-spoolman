package io.github.xnovosx.kobraspoolman.data

import java.net.URLDecoder
import java.net.URLEncoder

/**
 * Inhalt des Kopplungs-QR-Codes: kobraspoolman://pair?b=<bridge-adresse>&c=<code>.
 * Die Weboberflaeche und die App zeigen ihn bei "Geraet hinzufuegen" an.
 */
data class PairLink(val bridge: String, val code: String) {
    fun toUri(): String = "kobraspoolman://pair?b=${URLEncoder.encode(bridge, "UTF-8")}&c=$code"

    companion object {
        private val CODE = Regex("\\d{6}")

        fun parse(text: String): PairLink? {
            val t = text.trim()
            if (!t.startsWith("kobraspoolman://pair?")) return null
            val q = t.substringAfter('?').split('&').mapNotNull {
                val i = it.indexOf('=')
                if (i <= 0) null else it.substring(0, i) to URLDecoder.decode(it.substring(i + 1), "UTF-8")
            }.toMap()
            val b = q["b"]?.takeIf { it.startsWith("http://") || it.startsWith("https://") } ?: return null
            val c = q["c"]?.takeIf { CODE.matches(it) } ?: return null
            return PairLink(b, c)
        }
    }
}

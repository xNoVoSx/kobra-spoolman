package io.github.xnovosx.kobraspoolman.data

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.util.Locale

/**
 * Translations of the app: English source texts in the code, the German catalog in assets/i18n/de.json - the same
 * scheme as the bridge (locale/de.json) and the web UI (static/i18n/de.json).
 *
 *   tr("Spool #{id} created", "id" to 7)  ->  "Spool #7 created" / "Spule #7 angelegt"
 *
 * The language follows the app's locale (system language, or the per-app language of Android 13+ chosen in the
 * app's settings). KobraApp loads the catalog at start and on every configuration change; requests to the bridge
 * carry the language (X-Lang), so texts made by the bridge come in the same language.
 * Without Android dependencies: JVM tests run in English or load the catalog file themselves.
 * tests/test_i18n_app.py (bridge test suite) checks that every tr("...") has a German entry.
 */
object I18n {
    val LANGS = listOf("en", "de")

    @Volatile
    var lang: String = "en"
        private set

    @Volatile
    private var catalog: Map<String, String> = emptyMap()

    /** Locale for numbers and dates. */
    val locale: Locale get() = if (lang == "de") Locale.GERMANY else Locale.UK

    /** Supported language for a locale tag ("de-AT" -> "de", anything unknown -> "en"). */
    fun langOf(tag: String?): String = tag?.substringBefore('-')?.substringBefore('_')?.lowercase()
        ?.takeIf { it in LANGS } ?: "en"

    /** Switch the language; catalogJson is the content of i18n/<lang>.json (null for English). */
    fun use(language: String, catalogJson: String?) {
        catalog = if (language == "en" || catalogJson == null) emptyMap() else parse(catalogJson)
        lang = if (catalog.isEmpty()) "en" else language
    }

    fun parse(text: String): Map<String, String> =
        Json.parseToJsonElement(text).let { it as JsonObject }.mapValues { it.value.jsonPrimitive.content }

    /** Translate an English text; {name} placeholders are filled from args. */
    fun tr(text: String, vararg args: Pair<String, Any?>): String {
        val s = catalog[text] ?: text
        if (args.isEmpty()) return s
        val values = args.toMap()
        return PLACEHOLDER.replace(s) { m ->
            val k = m.groupValues[1]
            if (!values.containsKey(k) || values[k] == null) m.value else values[k].toString()
        }
    }

    private val PLACEHOLDER = Regex("\\{(\\w+)\\}")
}

/** Short form for UI code: tr("Spool #{id}", "id" to 7). */
fun tr(text: String, vararg args: Pair<String, Any?>): String = I18n.tr(text, *args)

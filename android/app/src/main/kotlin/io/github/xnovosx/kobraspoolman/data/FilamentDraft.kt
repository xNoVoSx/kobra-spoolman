package io.github.xnovosx.kobraspoolman.data

import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonPrimitive
import kotlin.math.roundToLong

/** Art eines Eingabefelds. */
enum class Kind { INT, FLOAT, BOOL, TEXT, MULTILINE }

/** Ein Feld im Filament-Assistenten. native = Spoolman-Standardfeld, sonst Zusatzfeld (extra). */
data class FieldSpec(val key: String, val label: String, val unit: String? = null, val kind: Kind, val native: Boolean = false,
                     val orcaKey: String? = null)

/**
 * Entwurf eines neuen Filaments, so wie der Nutzer ihn eingibt (Texte). Leere Felder bedeuten
 * "aus der Vorlage bzw. dem Orca-Profil" und werden nie an die Bridge geschickt.
 */
data class FilamentDraft(
    val vendorId: Int? = null,
    val newVendor: String = "",
    val name: String = "",
    val material: String = "",
    val colorHex: String = "",
    val values: Map<String, String> = emptyMap(),
) {
    fun value(key: String): String = values[key].orEmpty()
    fun with(key: String, v: String) = copy(values = values + (key to v))

    val template: String get() = value("vorlage")
    val orcaBasis: String get() = value("orca_basis")

    /** Fehler je Feld (fuer die Anzeige); leer = alles gueltig. */
    fun errors(specs: List<FieldSpec>): Map<String, String> {
        val out = mutableMapOf<String, String>()
        if (name.isBlank()) out["name"] = "Name fehlt"
        if (material.isBlank()) out["material"] = "Material fehlt"
        if (vendorId == null && newVendor.isBlank()) out["vendor"] = "Hersteller wählen oder neu eingeben"
        if (colorHex.isNotBlank() && !HEX.matches(colorHex.removePrefix("#"))) out["color"] = "Farbe als RRGGBB"
        for (s in specs) {
            val t = value(s.key).trim()
            if (t.isEmpty()) continue
            when (s.kind) {
                Kind.INT, Kind.FLOAT -> if (number(t) == null) out[s.key] = "Zahl erwartet"
                else -> {}
            }
        }
        return out
    }

    /** Body fuer POST /api/app/filament - nur gesetzte Felder. vendorId muss dann feststehen. */
    fun toJson(specs: List<FieldSpec>, vendor: Int): JsonObject {
        val body = linkedMapOf<String, JsonElement>(
            "name" to JsonPrimitive(name.trim()),
            "material" to JsonPrimitive(material.trim()),
            "vendor_id" to JsonPrimitive(vendor),
        )
        if (colorHex.isNotBlank()) body["color_hex"] = JsonPrimitive(colorHex.removePrefix("#").uppercase())
        val extra = linkedMapOf<String, JsonElement>()
        for (s in specs) {
            val t = value(s.key).trim()
            if (t.isEmpty()) continue
            val v: JsonElement = when (s.kind) {
                Kind.INT -> JsonPrimitive(number(t)!!.roundToLong())
                Kind.FLOAT -> JsonPrimitive(number(t)!!)
                Kind.BOOL -> JsonPrimitive(t == "true")
                Kind.TEXT, Kind.MULTILINE -> JsonPrimitive(t)
            }
            if (s.native) body[s.key] = v else extra[s.key] = v
        }
        if (extra.isNotEmpty()) body["extra"] = JsonObject(extra)
        return JsonObject(body)
    }

    /** Werte einer vorhandenen Produktreihe uebernehmen (nur deren eigene Werte, nie die der Vorlage). */
    fun copyFrom(f: FilamentInfo): FilamentDraft {
        val v = values.toMutableMap()
        for ((k, e) in f.native + f.extra) {
            if (k in COPY_SKIP) continue
            text(e)?.let { v[k] = it }
        }
        return copy(vendorId = f.vendorId ?: vendorId, material = material.ifBlank { f.material }, values = v)
    }

    companion object {
        private val HEX = Regex("[0-9A-Fa-f]{6}")
        private val COPY_SKIP = setOf("name", "material", "color_hex", "multi_color_hexes", "multi_color_direction",
            "article_number", "comment")

        fun number(t: String): Double? = t.replace(',', '.').toDoubleOrNull()

        /** JSON-Wert (Zahl, Text, Wahrheitswert) als Eingabetext. */
        fun text(e: JsonElement?): String? {
            if (e == null || e is JsonNull) return null
            val p = runCatching { e.jsonPrimitive }.getOrNull() ?: return null
            val c = p.contentOrNull ?: return null
            return if (!p.isString && c.endsWith(".0")) c.removeSuffix(".0") else c
        }
    }
}

/** Welche Vorlage gilt fuer den Entwurf - dieselbe Regel wie die Bridge (profiles.find_template). */
fun templateFor(d: FilamentDraft, templates: List<Template>): Template? {
    if (d.orcaBasis.isNotBlank()) return null                      // eigenes Orca-Profil ersetzt die Vorlage
    if (d.template.isNotBlank()) templates.firstOrNull { it.name == d.template }?.let { return it }
    val m = d.material.trim().uppercase()
    if (m.isEmpty()) return null
    val same = templates.filter { it.material.trim().uppercase() == m }
    return same.firstOrNull { it.name.uppercase() == "VORLAGE $m" } ?: same.minByOrNull { it.id }
}

/** Platzhalter fuer ein Feld aus der Vorlage (null = kein Wert). */
fun placeholder(t: Template?, spec: FieldSpec): String? =
    t?.let { FilamentDraft.text(if (spec.native) it.native[spec.key] else it.extra[spec.key]) }

/** Feldgruppen des Assistenten. Zusatzfelder kommen mit Name/Einheit aus Spoolman (catalog.fields). */
object FilamentForm {
    private val NATIVE = mapOf(
        "settings_extruder_temp" to FieldSpec("settings_extruder_temp", "Düse", "°C", Kind.INT, true, "nozzle_temperature"),
        "settings_bed_temp" to FieldSpec("settings_bed_temp", "Bett texturiert", "°C", Kind.INT, true, "textured_plate_temp"),
        "density" to FieldSpec("density", "Dichte", "g/cm³", Kind.FLOAT, true, "filament_density"),
        "diameter" to FieldSpec("diameter", "Durchmesser", "mm", Kind.FLOAT, true, "filament_diameter"),
        "weight" to FieldSpec("weight", "Netto je Spule", "g", Kind.FLOAT, true),
        "spool_weight" to FieldSpec("spool_weight", "Leerspule", "g", Kind.FLOAT, true),
        "price" to FieldSpec("price", "Preis je Spule", "€", Kind.FLOAT, true, "filament_cost"),
    )
    val PHYSICAL = listOf("diameter", "density", "weight", "spool_weight", "price")
    val TEMPS = listOf("settings_extruder_temp", "nozzle_temp_first_layer", "settings_bed_temp", "bed_temp_first_layer",
        "bed_temp_smooth", "bed_temp_smooth_first_layer", "chamber_temp", "dry_temp")
    val COOLING = listOf("fan_min", "fan_max", "fan_off_first_layers", "overhang_fan", "aux_fan", "air_filtration",
        "exhaust_fan_print", "exhaust_fan_done")
    val EXTRUSION = listOf("flow_ratio", "pressure_advance", "max_volumetric_speed", "retraction_length",
        "retraction_speed", "z_hop")
    val OVERRIDES = listOf("orca_overrides")
    private val HANDLED = PHYSICAL + TEMPS + COOLING + EXTRUSION + OVERRIDES + listOf("vorlage", "orca_basis")

    fun spec(key: String, fields: List<ExtraField>): FieldSpec? {
        NATIVE[key]?.let { return it }
        val f = fields.firstOrNull { it.key == key } ?: return null
        val kind = when (f.type) {
            "integer" -> Kind.INT
            "float" -> Kind.FLOAT
            "boolean" -> Kind.BOOL
            else -> if (key == "orca_overrides") Kind.MULTILINE else Kind.TEXT
        }
        return FieldSpec(key, f.name ?: key, f.unit, kind, false, f.orcaKey)
    }

    fun group(keys: List<String>, fields: List<ExtraField>): List<FieldSpec> = keys.mapNotNull { spec(it, fields) }

    /** Zusatzfelder, die (noch) keiner Gruppe zugeordnet sind - z.B. neue Felder einer neueren Bridge. */
    fun others(fields: List<ExtraField>): List<FieldSpec> =
        fields.filter { it.key !in HANDLED }.mapNotNull { spec(it.key, fields) }

    /** Alle Felder, die toJson/errors pruefen (vorlage/orca_basis sind Textfelder aus Schritt 1). */
    fun all(fields: List<ExtraField>): List<FieldSpec> =
        group(PHYSICAL + TEMPS + COOLING + EXTRUSION + OVERRIDES + listOf("vorlage", "orca_basis"), fields) + others(fields)
}

package io.github.xnovosx.kobraspoolman.data

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonElement

// Datenmodelle der Bridge-API (/api/app/..., docs/api.md). Unbekannte Felder werden ignoriert,
// damit eine neuere Bridge die App nicht bricht.

@Serializable
data class AppState(
    val version: String = "",
    val printer: Printer = Printer(),
    val spoolman: Boolean = false,
    @SerialName("can_write") val canWrite: Boolean = false,
    val slots: List<Slot> = emptyList(),
    val shelf: List<SpoolInfo> = emptyList(),
    val warnings: List<String> = emptyList(),
)

@Serializable
data class Printer(
    val state: String = "offline",
    val file: String? = null,
    val progress: Double? = null,
    @SerialName("print_duration_s") val printDurationS: Long? = null,
    @SerialName("eta_s") val etaS: Long? = null,
    val message: String? = null,
    @SerialName("active_slot") val activeSlot: Int? = null,
    @SerialName("mmu_action") val mmuAction: String? = null,
    @SerialName("changing_filament") val changingFilament: Boolean = false,
)

@Serializable
data class Slot(
    val slot: Int,
    val ace: Ace = Ace(),
    val hints: List<String> = emptyList(),
    val spool: SpoolInfo? = null,
)

@Serializable
data class Ace(
    val present: Boolean = false,
    val active: Boolean = false,
    val material: String = "",
    val color: String = "",
    val name: String = "",
    val vendor: String = "",
    @SerialName("tag_id") val tagId: Long? = null,
)

@Serializable
data class SpoolInfo(
    @SerialName("spool_id") val spoolId: Int,
    val location: String? = null,
    val slot: Int? = null,
    @SerialName("remaining_weight") val remainingWeight: Double? = null,
    @SerialName("initial_weight") val initialWeight: Double? = null,
    @SerialName("filament_id") val filamentId: Int? = null,
    @SerialName("orca_filament_id") val orcaFilamentId: String? = null,
    val name: String = "",
    val vendor: String = "",
    @SerialName("display_name") val displayName: String = "",
    val material: String = "",
    val color: String = "",
    @SerialName("nozzle_temp") val nozzleTemp: Double? = null,
    @SerialName("bed_temp") val bedTemp: Double? = null,
    val template: String? = null,
    @SerialName("tag_nr") val tagNr: Long? = null,
    @SerialName("nfc_uid") val nfcUid: String? = null,
)

@Serializable
data class SpoolDetail(
    val spool: SpoolInfo,
    val filament: FilamentInfo? = null,
    val jobs: List<Job> = emptyList(),
)

@Serializable
data class Job(
    val file: String? = null,
    val ended: String? = null,
    val state: String? = null,
    val g: Double? = null,
)

@Serializable
data class FilamentInfo(
    @SerialName("filament_id") val filamentId: Int,
    @SerialName("orca_id") val orcaId: String = "",
    @SerialName("display_name") val displayName: String = "",
    val vendor: String = "",
    val name: String = "",
    val material: String = "",
    val color: String = "",
    @SerialName("nozzle_temp") val nozzleTemp: Double? = null,
    @SerialName("bed_temp") val bedTemp: Double? = null,
    val template: String? = null,
    val weight: Double? = null,
    @SerialName("spool_weight") val spoolWeight: Double? = null,
    val spools: Int = 0,
    @SerialName("vendor_id") val vendorId: Int? = null,
    /** Nur am Filament selbst gesetzte Werte (fuer "Werte uebernehmen von ...") */
    val native: Map<String, JsonElement> = emptyMap(),
    val extra: Map<String, JsonElement> = emptyMap(),
)

@Serializable
data class Catalog(
    val vendors: List<Vendor> = emptyList(),
    val templates: List<Template> = emptyList(),
    val filaments: List<FilamentInfo> = emptyList(),
    val fields: List<ExtraField> = emptyList(),
    @SerialName("orca_bases") val orcaBases: List<String> = emptyList(),
    @SerialName("shelf_location") val shelfLocation: String = "Regal",
)

@Serializable
data class Vendor(val id: Int, val name: String, @SerialName("empty_spool_weight") val emptySpoolWeight: Double? = null)

/** Vorlage (Hersteller "Vorlage") mit ihren Werten - in der App nur Platzhalter, nie kopiert. */
@Serializable
data class Template(
    val id: Int,
    val name: String = "",
    val material: String = "",
    val native: Map<String, JsonElement> = emptyMap(),
    val extra: Map<String, JsonElement> = emptyMap(),
)

/** Spoolman-Zusatzfeld am Filament (aus spoolman_setup.py). */
@Serializable
data class ExtraField(
    val key: String,
    val name: String? = null,
    val type: String? = null,
    val unit: String? = null,
    val order: Int? = null,
    val choices: List<String>? = null,
    @SerialName("orca_key") val orcaKey: String? = null,
)

@Serializable
data class VendorResponse(val vendor: Vendor)

@Serializable
data class FilamentResponse(val filament: FilamentInfo)

@Serializable
data class SpoolResponse(val spool: SpoolInfo)

/** Antwort von POST /api/app/tag/issue: reservierte Tag-Nummer und Inhalt fuer den ACE-Tag. */
@Serializable
data class TagIssue(@SerialName("spool_id") val spoolId: Int, val tag: TagContent)

@Serializable
data class TagContent(
    @SerialName("tag_nr") val tagNr: Long,
    val sku: String,
    val brand: String = "",
    val material: String = "",
    val color: String = "",
    @SerialName("nozzle_min") val nozzleMin: Int? = null,
    @SerialName("nozzle_max") val nozzleMax: Int? = null,
    @SerialName("bed_min") val bedMin: Int? = null,
    @SerialName("bed_max") val bedMax: Int? = null,
    @SerialName("diameter_mm") val diameterMm: Double = 1.75,
    @SerialName("weight_g") val weightG: Double? = null,
    @SerialName("length_m") val lengthM: Double? = null,
)

@Serializable
data class SpoolIdBody(@SerialName("spool_id") val spoolId: Int)

@Serializable
data class Health(val app: String = "", val version: String = "")

@Serializable
data class ApiError(val error: String = "")

@Serializable
data class NewSpool(
    @SerialName("filament_id") val filamentId: Int,
    @SerialName("initial_weight") val initialWeight: Double? = null,
    @SerialName("spool_weight") val spoolWeight: Double? = null,
    val slot: Int? = null,
)

@Serializable
data class LocationChange(val slot: Int?)

@Serializable
data class TagLink(@SerialName("spool_id") val spoolId: Int, val uid: String, val force: Boolean = false)

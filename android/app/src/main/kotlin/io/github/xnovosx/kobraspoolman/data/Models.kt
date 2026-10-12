package io.github.xnovosx.kobraspoolman.data

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonElement

// Data models of the bridge API (/api/app/..., docs/api.md). Unknown fields are ignored,
// so a newer bridge does not break the app.

@Serializable
data class AppState(
    val version: String = "",
    val printer: Printer = Printer(),
    val spoolman: Boolean = false,
    @SerialName("can_write") val canWrite: Boolean = false,
    val slots: List<Slot> = emptyList(),
    val shelf: List<SpoolInfo> = emptyList(),
    val dryer: Dryer? = null,
    val ace: AceSettings? = null,
    /** Auto PA (Klipper module kobra_pa) - missing with older bridges */
    val pa: PaState? = null,
    /** Resume after power loss (Klipper module kobra_resume) - missing with older bridges */
    val resume: ResumeState? = null,
    /** Clog detection (Klipper module kobra_clog) - missing with older bridges */
    val clog: ClogState? = null,
    /** USB tunnel watchdog on the Klipper computer (bridge >= 3.11.0) - null without a watchdog */
    val usb: UsbState? = null,
    val warnings: List<String> = emptyList(),
    val notices: Notices? = null,
    @SerialName("last_control") val lastControl: LastControl? = null,
    val vision: VisionInfo? = null,
    val moisture: Map<String, MoistureBrief>? = null,
    val uses: List<SlotUse> = emptyList(),
)

/** Slot the running print file uses: total and still open (incl. purging). */
@Serializable
data class SlotUse(
    val slot: Int,
    val name: String? = null,
    val color: String? = null,
    @SerialName("total_g") val totalG: Double? = null,
    @SerialName("rest_g") val restG: Double? = null,
)

/** Moisture estimate of a spool in /api/app/state (short form). state: unknown | ok | soon | wet */
@Serializable
data class MoistureBrief(
    val score: Int? = null,
    val state: String = "unknown",
    @SerialName("needs_drying") val needsDrying: Boolean = false,
    @SerialName("hours_needed") val hoursNeeded: Double? = null,
)

/** GET /api/spool/{id}/moisture */
@Serializable
data class SpoolMoistureFull(
    val score: Int? = null,
    val state: String = "unknown",
    @SerialName("needs_drying") val needsDrying: Boolean = false,
    val where: String? = null,
    @SerialName("out_since") val outSince: Double? = null,
    @SerialName("last_dried") val lastDried: MoistHist? = null,
    val params: MoistParams = MoistParams(),
    @SerialName("hours_needed") val hoursNeeded: Double? = null,
    val history: List<MoistHist> = emptyList(),
)

@Serializable
data class MoistParams(
    @SerialName("open_days") val openDays: Double = 0.0,
    @SerialName("dry_hours") val dryHours: Double = 0.0,
    @SerialName("dry_temp") val dryTemp: Int? = null,
    val material: String = "",
)

@Serializable
data class MoistHist(
    val at: Double = 0.0, val kind: String = "", val slot: Int? = null, val temp: Double? = null,
    val minutes: Double? = null, val score: Int? = null, val manual: Boolean = false,
)

/** GET /api/humidity - points [time, humidity, ACE temp, target, drying] */
@Serializable
data class HumidityData(
    val hours: Double = 24.0,
    val points: List<JsonArray> = emptyList(),
    val sessions: List<DrySession> = emptyList(),
    val prints: List<PrintBand> = emptyList(),
    val automation: HumAutomation = HumAutomation(),
)

@Serializable
data class DrySession(
    val id: String = "", val start: Double = 0.0, val end: Double? = null, val minutes: Int? = null,
    val temps: List<JsonArray> = emptyList(), val source: String = "", val reason: String = "",
    @SerialName("end_reason") val endReason: String? = null,
    @SerialName("humidity_start") val humidityStart: Double? = null,
    @SerialName("humidity_end") val humidityEnd: Double? = null,
    val running: Boolean = false,
)

@Serializable
data class PrintBand(val start: Double = 0.0, val end: Double = 0.0, val file: String? = null)

@Serializable
data class HumAutomation(
    val enabled: Boolean = false,
    @SerialName("start_above") val startAbove: Double? = null,
    @SerialName("stop_below") val stopBelow: Double? = null,
)

/** AI failure detection (kobra-vision via the bridge). level: ok | warn | fail; event: open event. */
@Serializable
data class VisionInfo(
    val enabled: Boolean = false,
    val level: String = "ok",
    val muted: Boolean = false,
    val score: Double? = null,
    val event: VisionEvent? = null,
)

@Serializable
data class VisionEvent(
    val id: String, val level: String = "warn", val at: Double = 0.0, val score: Double? = null,
    val p: Double? = null, val verdict: String? = null, val file: String? = null, val paused: Boolean = false,
)

/** GET /api/vision - everything for the AI page. */
@Serializable
data class VisionFull(
    val enabled: Boolean = false,
    val configured: Boolean = false,
    val level: String = "ok",
    val muted: Boolean = false,
    @SerialName("muted_reason") val mutedReason: String? = null,
    val score: Double? = null,
    val printing: Boolean = false,
    val error: String? = null,
    val ms: Double? = null,
    @SerialName("quiet_now") val quietNow: Boolean = false,
    @SerialName("action_now") val actionNow: String = "warn",
    @SerialName("safe_frames") val safeFrames: Int = 30,
    val settings: VisionSettings = VisionSettings(),
    val prediction: VisionPrediction = VisionPrediction(),
    val events: List<VisionEvent> = emptyList(),
    val dataset: VisionDataset = VisionDataset(),
    val health: VisionHealth = VisionHealth(),
)

@Serializable
data class VisionSettings(
    val enabled: Boolean = true,
    val sensitivity: Double = 1.0,
    val action: String = "warn",
    @SerialName("heater_off") val heaterOff: Boolean = false,
    val notify: String = "warn",
    @SerialName("interval_s") val intervalS: Double = 10.0,
    @SerialName("safe_s") val safeS: Double = 300.0,
    val zones: List<JsonObject> = emptyList(),
    val quiet: VisionQuiet = VisionQuiet(),
    @SerialName("dataset_gb") val datasetGb: Double = 5.0,
)

@Serializable
data class VisionQuiet(val enabled: Boolean = false, val start: String = "22:00", val end: String = "07:00", val mode: String = "fail_only")

@Serializable
data class VisionPrediction(val p: Double = 0.0, val long: Double = 0.0, val frames: Int = 0, val lifetime: Int = 0)

@Serializable
data class VisionDataset(val jobs: Int = 0, val frames: Int = 0, val labelled: Int = 0, val mb: Double = 0.0,
                         @SerialName("limit_gb") val limitGb: Double = 5.0)

@Serializable
data class VisionHealth(val model: VisionModel? = null)

@Serializable
data class VisionModel(val loaded: Boolean = false, val provider: String? = null)

/** Print action last triggered via the bridge (pause, resume, cancel ...); at = Unix seconds. */
@Serializable
data class LastControl(val action: String, val source: String = "", val at: Double = 0.0)

/** Messages (by importance) and state of the connections - computed by the bridge. */
@Serializable
data class Notices(val messages: List<Notice> = emptyList(), val status: List<StatusLine> = emptyList())

/** level: error | warn | info */
@Serializable
data class Notice(val level: String, val text: String, val key: String = "")

/** state: ok | warn | bad | off; seen = last reported (Unix seconds, devices only) */
@Serializable
data class StatusLine(val key: String, val label: String, val state: String, val detail: String? = null, val seen: Double? = null)

/** Settings of the ACE driver (Klipper + ACEPRO, GET /api/ace, also in /api/app/state). */
@Serializable
data class AceSettings(
    val present: Boolean = false,
    @SerialName("endless_spool") val endlessSpool: Boolean? = null,
    @SerialName("endless_mode") val endlessMode: String? = null,
    /** mode -> description, e.g. "material" -> "same material" */
    @SerialName("endless_modes") val endlessModes: Map<String, String> = emptyMap(),
    val firmware: String? = null,
    val model: String? = null,
    @SerialName("read_at") val readAt: String? = null,
    val printing: Boolean = false,
)

@Serializable
data class AceResponse(val settings: AceSettings = AceSettings())

/** Auto PA (GET /api/pa, also in /api/app/state): switches in Klipper, PA per slot from Spoolman. */
@Serializable
data class PaState(
    val present: Boolean = false,
    val sync: Boolean = true,
    val enabled: Boolean? = null,
    val auto: Boolean? = null,
    val patched: Boolean? = null,
    val measuring: Boolean = false,
    val calibrating: Int? = null,
    val slots: List<PaSlot> = emptyList(),
    val last: PaLast? = null,
)

/** state: table | needed | failed | empty | measuring; source: table (measured) | manual | null */
@Serializable
data class PaSlot(
    val slot: Int,
    @SerialName("filament_id") val filamentId: Int? = null,
    val name: String? = null,
    val state: String = "",
    val source: String? = null,
    val speeds: List<Double> = emptyList(),
    val k: List<Double> = emptyList(),
    @SerialName("k_ref") val kRef: Double? = null,
    val date: String? = null,
    val active: Boolean = false,
)

/** USB tunnel printer <-> Klipper computer: state ok|warn|bad|off, detail as text, switches watch/auto_restart/full_speed. */
@Serializable
data class UsbState(
    val available: Boolean = false,
    val alive: Boolean = false,
    val state: String = "off",
    val detail: String = "",
    val switches: Map<String, Boolean> = emptyMap(),
    val events: List<UsbEvent> = emptyList(),
)

@Serializable
data class UsbEvent(val at: Long = 0, val text: String = "")

@Serializable
data class ClogState(
    val present: Boolean = false,
    val enabled: Boolean? = null,
    /** warn or pause */
    val action: String? = null,
    val available: Boolean? = null,
    val suspect: Boolean = false,
    val alarms: Int = 0,
    @SerialName("min_ratio") val minRatio: Double? = null,
    @SerialName("last_ratio") val lastRatio: Double? = null,
)

@Serializable
data class ResumeState(
    val present: Boolean = false,
    val enabled: Boolean? = null,
    val pending: ResumePending? = null,
    val running: Boolean = false,
    val error: String? = null,
)

@Serializable
data class ResumePending(
    val file: String = "",
    val layer: Int? = null,
    val layers: Int? = null,
    val progress: Double? = null,
)

@Serializable
data class PaLast(val t: Int = 0, val kind: String = "", val k: List<Double> = emptyList(), val message: String? = null)

/** State of the print preview (GET /api/print/info). */
@Serializable
data class PrintInfo(
    val file: String? = null,
    val status: String = "idle",
    val layer: Int? = null,
    val layers: Int = 0,
    val thumbnail: Boolean = false,
)

@Serializable
data class DrySchedule(val at: Double, val temp: Double? = null, val hours: Double? = null)

/** ACE dryer (GET /api/dryer, also in /api/app/state). */
@Serializable
data class Dryer(
    val present: Boolean = false,
    val model: String? = null,
    val humidity: Double? = null,
    val temp: Double? = null,
    val drying: Boolean = false,
    @SerialName("target_temp") val targetTemp: Double? = null,
    @SerialName("remaining_min") val remainingMin: Long? = null,
    val required: DryerRequired = DryerRequired(),
    val config: DryerConfig = DryerConfig(),
    @SerialName("last_event") val lastEvent: DryerEvent? = null,
    val schedule: DrySchedule? = null,
    /** running pass (only while drying) */
    val run: DryerRun? = null,
)

/** source: hand | plan | spule | auto (stable API codes). Non-automatic runs hold until `until`, however dry. */
@Serializable
data class DryerRun(
    val source: String = "",
    val until: Double? = null,
    val temp: Double? = null,
    val restarts: Int = 0,
)

@Serializable
data class DryerRequired(
    val temp: Int? = null,
    @SerialName("ace_max") val aceMax: Int = 65,
    val slots: List<DryerSlot> = emptyList(),
    @SerialName("limited_by") val limitedBy: List<Int> = emptyList(),
)

@Serializable
data class DryerSlot(val slot: Int, val name: String = "", val temp: Int = 0, val source: String = "")

@Serializable
data class DryerConfig(
    val enabled: Boolean = false,
    @SerialName("start_above") val startAbove: Double = 20.0,
    @SerialName("stop_below") val stopBelow: Double = 10.0,
    @SerialName("max_hours") val maxHours: Double = 6.0,
    @SerialName("pause_minutes") val pauseMinutes: Double = 60.0,
    @SerialName("while_printing") val whilePrinting: Boolean = true,
    /** humidity must stay above startAbove this long in one go (lid open briefly does not count) */
    @SerialName("start_delay_minutes") val startDelayMinutes: Double = 15.0,
)

@Serializable
data class DryerEvent(val at: String = "", val text: String = "")

@Serializable
data class Device(
    val id: String,
    val name: String = "",
    val kind: String = "",
    val created: Double? = null,
    @SerialName("last_seen") val lastSeen: Double? = null,
    val me: Boolean = false,
)

@Serializable
data class DeviceList(val devices: List<Device> = emptyList())

@Serializable
data class AuthStatus(@SerialName("setup_required") val setupRequired: Boolean = false, val devices: Int = 0,
                      val device: Device? = null)

@Serializable
data class PairRequest(val code: String, val name: String, val kind: String)

@Serializable
data class PairResult(val token: String, val device: Device)

@Serializable
data class PairingCode(val code: String, @SerialName("expires_in") val expiresIn: Int = 300)

@Serializable
data class DryerStart(val temp: Int? = null, val hours: Double? = null)

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
    val layer: Int? = null,
    val layers: Int? = null,
    val nozzle: Heater? = null,
    val bed: Heater? = null,
    val fans: List<Fan> = emptyList(),
    @SerialName("speed_factor") val speedFactor: Double? = null,
    @SerialName("flow_factor") val flowFactor: Double? = null,
    @SerialName("moonraker_connected") val moonrakerConnected: Boolean = false,
    @SerialName("klippy_ready") val klippyReady: Boolean = false,
    /** What is happening now ("Preheating 5/15 min", "Change to slot 2 · loading", "Printing · layer 3/80"); bridge 3.9.0+. */
    val phase: String? = null,
    @SerialName("phase_key") val phaseKey: String? = null,
)

/** Heater: actual, target (0 = off), power 0..1. */
@Serializable
data class Heater(val temp: Double, val target: Double = 0.0, val power: Double = 0.0)

/** Fan: part (part cooling), box (enclosure), filter (air filter); speed 0..1. */
@Serializable
data class Fan(val key: String, val name: String, val speed: Double, val rpm: Int? = null)

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
    /** ACE 2 Pro: one tag per spool side - up to two IDs. */
    @SerialName("nfc_uids") val nfcUids: List<String> = emptyList(),
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
    /** Values set on the filament itself only (for "Copy values from ...") */
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
    @SerialName("shelf_location") val shelfLocation: String = "Regal",   // Spoolman location name of the bridge (setting SHELF)
)

@Serializable
data class Vendor(val id: Int, val name: String, @SerialName("empty_spool_weight") val emptySpoolWeight: Double? = null)

/** Template (vendor "Vorlage" in Spoolman) with its values - in the app only placeholders, never copied. */
@Serializable
data class Template(
    val id: Int,
    val name: String = "",
    val material: String = "",
    val native: Map<String, JsonElement> = emptyMap(),
    val extra: Map<String, JsonElement> = emptyMap(),
)

/** Spoolman extra field on the filament (from spoolman_setup.py). */
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

/** Answer of POST /api/app/tag/issue: reserved tag number and content for the ACE tag. */
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
data class TagLink(
    @SerialName("spool_id") val spoolId: Int,
    val uid: String,
    val force: Boolean = false,
    /** true: this ID replaces all; false: a second tag (other spool side) is added */
    val reset: Boolean = true,
)

/** Print from the history (GET /api/jobs). */
@Serializable
data class PrintJob(
    val job: String,
    val file: String? = null,
    val started: String? = null,
    val ended: String? = null,
    val state: String = "",
    val changes: Int = 0,
    val slots: List<JobSlot> = emptyList(),
)

@Serializable
data class JobSlot(val slot: Int, val g: Double = 0.0, val mm: Double = 0.0)

@Serializable
data class PrintJobList(val jobs: List<PrintJob> = emptyList())

/** Line of the printer console: kind = command | response | error; source = who sent it. */
@Serializable
data class ConsoleLine(val id: Long, val time: Double, val kind: String, val text: String, val source: String? = null)

@Serializable
data class ConsoleLines(val lines: List<ConsoleLine> = emptyList(), val printing: Boolean = false)

/** Line of the bridge log. */
@Serializable
data class LogLine(val id: Long, val time: Double, val level: String, val name: String, val text: String)

@Serializable
data class LogLines(val lines: List<LogLine> = emptyList())

/** App update the bridge brings along (GET /api/app/update). */
@Serializable
data class AppUpdate(
    val available: Boolean = false,
    val version: String = "",
    val code: Int = 0,
    val size: Long = 0,
    val changes: List<String> = emptyList(),
    val url: String = "",
)

package io.github.xnovosx.kobraspoolman.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import io.github.xnovosx.kobraspoolman.BuildConfig
import io.github.xnovosx.kobraspoolman.data.AppState
import io.github.xnovosx.kobraspoolman.data.AppUpdate
import io.github.xnovosx.kobraspoolman.data.Catalog
import io.github.xnovosx.kobraspoolman.data.ConsoleLine
import io.github.xnovosx.kobraspoolman.data.ConsoleLines
import io.github.xnovosx.kobraspoolman.data.PrintJob
import io.github.xnovosx.kobraspoolman.data.LogLine
import io.github.xnovosx.kobraspoolman.data.LogLines
import io.github.xnovosx.kobraspoolman.data.SpoolInfo
import io.github.xnovosx.kobraspoolman.ui.theme.K
import io.github.xnovosx.kobraspoolman.ui.theme.PlexMono
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/** Kopfzeile der Unterseiten: Titel, optional Zurueck und ein Knopf rechts. */
@Composable
fun ScreenHeader(title: String, onBack: (() -> Unit)? = null, action: (@Composable () -> Unit)? = null) {
    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        onBack?.let { RoundIconButton(KIcons.Back, "Zurück", it) }
        Text(title, style = MaterialTheme.typography.headlineMedium, modifier = Modifier.weight(1f))
        action?.invoke()
    }
}

private fun listPadding(p: PaddingValues) =
    PaddingValues(start = 20.dp, end = 20.dp, top = p.calculateTopPadding() + 16.dp, bottom = p.calculateBottomPadding() + 16.dp)

/** Umschalter wie im Web (Spulen | Sorten, Befehle | Bridge). */
@Composable
fun Segmented(options: List<Pair<String, String>>, selected: String, onSelect: (String) -> Unit) {
    Row(Modifier.clip(RoundedCornerShape(12.dp)).background(K.Sunken).border(1.dp, K.Line, RoundedCornerShape(12.dp)).padding(3.dp),
        horizontalArrangement = Arrangement.spacedBy(2.dp)) {
        options.forEach { (k, label) ->
            Text(label, style = MaterialTheme.typography.labelLarge, color = if (k == selected) K.Text else K.Muted,
                modifier = Modifier.clip(RoundedCornerShape(9.dp)).background(if (k == selected) K.Surface2 else Color.Transparent)
                    .clickable(role = Role.Tab) { onSelect(k) }.padding(horizontal = 16.dp, vertical = 8.dp))
        }
    }
}

// ====================================================================== Meldungen
@Composable
fun NoticesScreen(state: AppState?, padding: PaddingValues, onRefresh: () -> Unit) {
    LazyColumn(Modifier.fillMaxSize().background(K.Ground), contentPadding = listPadding(padding),
        verticalArrangement = Arrangement.spacedBy(12.dp)) {
        item { ScreenHeader("Meldungen", action = { RoundIconButton(KIcons.Refresh, "Aktualisieren", onRefresh) }) }
        val n = state?.notices
        if (n == null) {
            item { Text(if (state == null) "Lade …" else "Diese Bridge kennt noch keine Meldungen (Update nötig).", color = K.Muted) }
        } else {
            item { NoticesCard(n, state.version, title = false) }
        }
    }
}

// ====================================================================== Filament: Spulen | Sorten
@Composable
fun FilamentHubScreen(
    state: AppState?,
    catalog: Catalog?,
    padding: PaddingValues,
    onLoadCatalog: () -> Unit,
    onSpool: (Int) -> Unit,
    onNewSpool: () -> Unit,
    onNewFilament: () -> Unit,
) {
    var view by rememberSaveable { mutableStateOf("spools") }
    var filter by rememberSaveable { mutableStateOf<Int?>(null) }
    LaunchedEffect(view) { if (view == "types") onLoadCatalog() }
    val spools = state?.let { (it.slots.mapNotNull { s -> s.spool } + it.shelf).distinctBy { sp -> sp.spoolId } }.orEmpty()
    LazyColumn(Modifier.fillMaxSize().background(K.Ground), contentPadding = listPadding(padding),
        verticalArrangement = Arrangement.spacedBy(10.dp)) {
        item {
            ScreenHeader("Filament", action = {
                RoundIconButton(KIcons.Plus, if (view == "spools") "Neue Spule" else "Neue Sorte",
                    if (view == "spools") onNewSpool else onNewFilament)
            })
        }
        item {
            Segmented(listOf("spools" to "Spulen ${spools.size}", "types" to "Sorten ${catalog?.filaments?.size ?: ""}".trim()), view) {
                view = it; if (it == "types") filter = null
            }
        }
        if (view == "spools") {
            val shown = filter?.let { f -> spools.filter { it.filamentId == f } } ?: spools
            if (filter != null) item {
                Text("Nur Spulen dieser Sorte – alle zeigen", color = K.Accent, style = MaterialTheme.typography.labelLarge,
                    modifier = Modifier.clickable { filter = null }.padding(vertical = 4.dp))
            }
            if (shown.isEmpty()) item { Text(if (state == null) "Lade …" else "Keine Spulen.", color = K.Muted) }
            items(shown.sortedWith(compareBy<SpoolInfo> { it.slot ?: 99 }.thenBy { it.displayName }), key = { it.spoolId }) { sp ->
                ShelfRow(sp) { onSpool(sp.spoolId) }
            }
        } else {
            val list = catalog?.filaments.orEmpty()
            if (catalog == null) item { Text("Lade …", color = K.Muted) }
            items(list, key = { it.filamentId }) { f ->
                Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(16.dp)).background(K.Surface)
                    .clickable { filter = f.filamentId; view = "spools" }.padding(14.dp),
                    verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    Box(Modifier.size(22.dp).clip(CircleShape).background(parseColor(f.color)).border(1.dp, K.LineStrong, CircleShape))
                    Column(Modifier.weight(1f)) {
                        Text(f.name.ifBlank { f.displayName }, style = MaterialTheme.typography.titleSmall, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        Text("${f.vendor} · ${f.material} · ${f.orcaId}", style = MaterialTheme.typography.bodySmall, color = K.Muted)
                    }
                    Text("${f.spools} ${if (f.spools == 1) "Spule" else "Spulen"}", style = MaterialTheme.typography.labelMedium, color = K.Muted)
                }
            }
        }
    }
}

private fun parseColor(hex: String): Color =
    runCatching { Color(android.graphics.Color.parseColor("#" + hex.removePrefix("#").take(6))) }.getOrDefault(K.Surface2)

// ====================================================================== Mehr
@Composable
fun MoreScreen(
    padding: PaddingValues,
    update: AppUpdate?,
    updateProgress: Float?,
    onInstall: () -> Unit,
    onCheckUpdate: () -> Unit,
    hasAce: Boolean,
    onAce: () -> Unit,
    onJobs: () -> Unit,
    onProtocol: () -> Unit,
    onDevices: () -> Unit,
    onSettings: () -> Unit,
) {
    LazyColumn(Modifier.fillMaxSize().background(K.Ground), contentPadding = listPadding(padding),
        verticalArrangement = Arrangement.spacedBy(10.dp)) {
        item { ScreenHeader("Mehr") }
        update?.let { u -> item { UpdateCard(u, updateProgress, onInstall) } }
        if (hasAce) item { MoreRow(KIcons.Dryer, "ACE & Trockner", "Trocknen, Spülen, Nachladen", onAce) }
        item { MoreRow(KIcons.Clock, "Drucke", "Verbrauch pro Druck und Spule", onJobs) }
        item { MoreRow(KIcons.Terminal, "Protokoll", "Gesendete Befehle, Antworten, was die Bridge macht", onProtocol) }
        item { MoreRow(KIcons.Phone, "Geräte", "Gekoppelte Geräte, Gerät hinzufügen", onDevices) }
        item { MoreRow(KIcons.Settings, "Einstellungen", "Kopplung, Benachrichtigungen, Töne", onSettings) }
        item {
            Text("App ${BuildConfig.VERSION_NAME} · nach Updates suchen", style = MaterialTheme.typography.bodySmall,
                color = K.Muted, modifier = Modifier.clickable(onClick = onCheckUpdate).padding(vertical = 8.dp))
        }
    }
}

/** Neue App-Version von der Bridge: Aenderungen, Download mit Fortschritt, dann Androids Installations-Rueckfrage. */
@Composable
private fun UpdateCard(u: AppUpdate, progress: Float?, onInstall: () -> Unit) {
    Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(18.dp)).background(K.AccentSoft)
        .border(1.dp, K.Accent, RoundedCornerShape(18.dp)).padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text("Update auf ${u.version}", style = MaterialTheme.typography.titleMedium, color = K.Accent)
        Text("Installiert: ${BuildConfig.VERSION_NAME} · ${"%.1f".format(Locale.GERMANY, u.size / 1e6)} MB von der Bridge",
            style = MaterialTheme.typography.bodySmall, color = K.Muted)
        u.changes.forEach { Text("• $it", style = MaterialTheme.typography.bodySmall) }
        if (progress != null) FillBar(progress, color = K.Accent, track = K.Surface2)
        else PrimaryButton("Herunterladen und installieren", onInstall, Modifier.fillMaxWidth())
    }
}

@Composable
private fun MoreRow(icon: ImageVector, title: String, sub: String, onClick: () -> Unit) {
    Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(18.dp)).background(K.Surface).clickable(onClick = onClick).padding(16.dp),
        verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(14.dp)) {
        Icon(icon, contentDescription = null, tint = K.Muted, modifier = Modifier.size(24.dp))
        Column(Modifier.weight(1f)) {
            Text(title, style = MaterialTheme.typography.titleMedium)
            Text(sub, style = MaterialTheme.typography.bodySmall, color = K.Muted)
        }
        Icon(KIcons.Chevron, contentDescription = null, tint = K.Faint, modifier = Modifier.size(20.dp))
    }
}

// ====================================================================== Drucke
private val JOB_STATE = mapOf("complete" to "fertig", "cancelled" to "abgebrochen", "error" to "Fehler", "printing" to "läuft")

@Composable
fun JobsScreen(padding: PaddingValues, load: suspend () -> List<PrintJob>?, onBack: () -> Unit) {
    var jobs by remember { mutableStateOf<List<PrintJob>?>(null) }
    LaunchedEffect(Unit) { jobs = load() ?: emptyList() }
    LazyColumn(Modifier.fillMaxSize().background(K.Ground), contentPadding = listPadding(padding),
        verticalArrangement = Arrangement.spacedBy(10.dp)) {
        item { ScreenHeader("Drucke", onBack) }
        val list = jobs
        if (list == null) item { Text("Lade …", color = K.Muted) }
        else if (list.isEmpty()) item { Text("Noch keine Drucke aufgezeichnet.", color = K.Muted) }
        else items(list, key = { it.job }) { j ->
            Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(16.dp)).background(K.Surface).padding(14.dp),
                verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(j.file?.removeSuffix(".gcode") ?: "–", fontFamily = PlexMono, style = MaterialTheme.typography.bodyMedium,
                        maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f))
                    val st = JOB_STATE[j.state] ?: j.state      // aeltere Eintraege: Klipper-Zustaende
                    Text(st, style = MaterialTheme.typography.labelMedium,
                        color = when (st) { "fertig" -> K.Ok; "läuft" -> K.Accent; "abgebrochen", "Fehler" -> K.DangerText; else -> K.Muted })
                }
                val total = j.slots.sumOf { it.g }
                Text("${(j.ended ?: j.started)?.replace('T', ' ')?.take(16) ?: ""} · ${Format.grams(total)} · ${j.changes} Wechsel",
                    style = MaterialTheme.typography.bodySmall, color = K.Muted)
                Text(j.slots.filter { it.slot > 0 }.joinToString("   ") { "Slot ${it.slot}: ${Format.grams(it.g)}" },
                    style = MaterialTheme.typography.bodySmall, color = K.Text)
            }
        }
    }
}

// ====================================================================== Protokoll (nur lesen)
private val clockFmt = SimpleDateFormat("HH:mm:ss", Locale.GERMANY)
private fun clock(t: Double) = clockFmt.format(Date((t * 1000).toLong()))

/**
 * Was ueber die Bridge an den Drucker ging (mit Absender), was er geantwortet hat und was die Bridge selbst
 * macht. In der App nur lesen - Befehle schickt man im Terminal der Weboberflaeche.
 */
@Composable
fun ProtocolScreen(
    padding: PaddingValues,
    console: suspend (Long) -> ConsoleLines?,
    logs: suspend (Long, String) -> LogLines?,
    onBack: () -> Unit,
) {
    var view by rememberSaveable { mutableStateOf("console") }
    var cLines by remember { mutableStateOf(emptyList<ConsoleLine>()) }
    var lLines by remember { mutableStateOf(emptyList<LogLine>()) }
    LaunchedEffect(view) {
        var after = 0L
        cLines = emptyList(); lLines = emptyList()
        while (isActive) {
            if (view == "console") console(after)?.lines?.takeIf { it.isNotEmpty() }?.let {
                after = it.last().id; cLines = (cLines + it).takeLast(500)
            } else logs(after, "INFO")?.lines?.takeIf { it.isNotEmpty() }?.let {
                after = it.last().id; lLines = (lLines + it).takeLast(1000)
            }
            delay(2_000)
        }
    }
    val listState = rememberLazyListState()
    val count = if (view == "console") cLines.size else lLines.size
    LaunchedEffect(count) { if (count > 0) listState.scrollToItem(count + 1) }
    LazyColumn(Modifier.fillMaxSize().background(K.Ground), state = listState, contentPadding = listPadding(padding),
        verticalArrangement = Arrangement.spacedBy(4.dp)) {
        item { ScreenHeader("Protokoll", onBack) }
        item {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.padding(bottom = 6.dp)) {
                Segmented(listOf("console" to "Befehle", "bridge" to "Bridge"), view) { view = it }
                Text(if (view == "console") "Befehle über die Bridge (mit Absender) und Antworten des Druckers. Senden geht im Terminal der Weboberfläche."
                     else "Was die Bridge macht: Buchungen, Slots, Trockner, Verbindungen.",
                    style = MaterialTheme.typography.bodySmall, color = K.Muted)
            }
        }
        if (count == 0) item { Text("Noch nichts.", color = K.Muted) }
        if (view == "console") items(cLines, key = { "c${it.id}" }) { l ->
            ProtocolLine(clock(l.time), if (l.kind == "command") l.source else null,
                if (l.kind == "command") "› ${l.text}" else l.text,
                when (l.kind) { "command" -> K.Accent; "error" -> K.DangerText; else -> K.Text })
        } else items(lLines, key = { "l${it.id}" }) { l ->
            ProtocolLine(clock(l.time), l.name, l.text,
                when (l.level) { "ERROR", "CRITICAL" -> K.DangerText; "WARNING" -> K.Accent; else -> K.Text })
        }
        item { Spacer(Modifier.size(1.dp)) }
    }
}

@Composable
private fun ProtocolLine(time: String, source: String?, text: String, color: Color) {
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        Text(time, fontFamily = PlexMono, style = MaterialTheme.typography.labelSmall, color = K.Faint, modifier = Modifier.width(56.dp))
        Column(Modifier.weight(1f)) {
            source?.let { Text(it, style = MaterialTheme.typography.labelSmall, color = K.Muted) }
            Text(text, fontFamily = PlexMono, style = MaterialTheme.typography.bodySmall, color = color)
        }
    }
}

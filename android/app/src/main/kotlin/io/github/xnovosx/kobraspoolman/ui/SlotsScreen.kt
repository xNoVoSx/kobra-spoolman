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
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import io.github.xnovosx.kobraspoolman.data.AppState
import io.github.xnovosx.kobraspoolman.data.PrintInfo
import io.github.xnovosx.kobraspoolman.data.Slot
import io.github.xnovosx.kobraspoolman.data.SpoolInfo
import io.github.xnovosx.kobraspoolman.ui.theme.K
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.emptyFlow

@Composable
fun SlotsScreen(
    state: AppState?,
    error: String?,
    contentPadding: PaddingValues,
    lanMissing: Boolean,
    onGrantLan: () -> Unit,
    onRefresh: () -> Unit,
    onSpool: (Int) -> Unit,
    onEmptySlot: (Int) -> Unit,
    onDryer: () -> Unit,
    fetchImage: suspend (String) -> ByteArray? = { null },
    printInfo: suspend () -> PrintInfo? = { null },
    camera: () -> Flow<ByteArray> = { emptyFlow() },
) {
    LazyColumn(
        Modifier.fillMaxSize().background(K.Ground),
        contentPadding = PaddingValues(start = 20.dp, end = 20.dp, top = contentPadding.calculateTopPadding() + 16.dp,
            bottom = contentPadding.calculateBottomPadding() + 16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        item {
            ScreenHeader("Kobra S1", action = { RoundIconButton(KIcons.Refresh, "Aktualisieren", onRefresh) })
        }
        if (lanMissing) item { LanMissing(onGrantLan) }
        if (error != null) item { Hint(error, danger = true) }
        if (state == null) {
            if (error == null) item { Text("Lade …", color = K.Muted) }
            return@LazyColumn
        }
        if (state.notices == null) state.warnings.forEach { w -> item { Hint(w, danger = true) } }   // aeltere Bridge
        // Startseite: Kamera oben, darunter der Druck, dann die Slots und die ACE - der Rest steckt in den Tabs
        if (state.printer.state != "offline") item { PrintMedia(state.printer, state.canWrite, fetchImage, printInfo, camera) }
        item {
            val active = state.slots.firstOrNull { it.slot == state.printer.activeSlot }?.spool
            StatusCard(state.printer, active?.name?.ifBlank { null } ?: active?.displayName)
        }
        state.slots.chunked(2).forEach { row ->
            item {
                Row(Modifier.height(IntrinsicSize.Min), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    row.forEach { slot ->
                        SlotCard(slot, active = slot.slot == state.printer.activeSlot, modifier = Modifier.weight(1f).fillMaxHeight(),
                            onClick = { slot.spool?.let { onSpool(it.spoolId) } ?: onEmptySlot(slot.slot) })
                    }
                    if (row.size == 1) Spacer(Modifier.weight(1f))
                }
            }
        }
        state.dryer?.takeIf { it.present }?.let { d -> item { DryerCard(d, onDryer, state.ace?.flushMultiplier) } }
        if (!state.canWrite) item {
            Hint("Nur lesen: Die App ist nicht gekoppelt. Koppeln unter Einstellungen.")
        }
    }
}

@Composable
private fun SlotCard(slot: Slot, active: Boolean, modifier: Modifier, onClick: () -> Unit) {
    val sp = slot.spool
    val shape = RoundedCornerShape(20.dp)
    Column(
        modifier.heightIn(min = 188.dp).clip(shape)
            .background(if (active) androidx.compose.ui.graphics.Color(0xFF16231C) else K.Surface)
            .border(if (active) 2.dp else 1.dp, if (active) K.Ok else K.Line, shape)
            .clickable(role = Role.Button, onClick = onClick).padding(14.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("SLOT ${slot.slot}", style = MaterialTheme.typography.titleSmall, color = K.Muted, modifier = Modifier.weight(1f))
            if (active) Badge("AKTIV", K.Ok, androidx.compose.ui.graphics.Color(0xFF0B2415))
            if ((slot.ace.tagId ?: 0) > 0) Badge("RFID", K.Surface2, K.Text)
        }
        SpoolDisc(sp?.color ?: slot.ace.color.ifBlank { null }, 64.dp)
        Text(sp?.displayName ?: if (slot.ace.present) "ACE: ${slot.ace.material.ifBlank { "ohne Material" }}" else "leer",
            style = MaterialTheme.typography.bodyMedium.copy(fontWeight = FontWeight.SemiBold), maxLines = 2,
            overflow = TextOverflow.Ellipsis)
        if (sp != null) {
            Row(Modifier.fillMaxWidth()) {
                Text(sp.material, style = MaterialTheme.typography.bodySmall, color = K.Muted, modifier = Modifier.weight(1f))
                Text(gramsText(sp.remainingWeight), style = MaterialTheme.typography.bodySmall)
            }
            val low = (sp.remainingWeight ?: 1000.0) < 100
            FillBar(Format.fill(sp.remainingWeight, sp.initialWeight), color = if (low) K.Danger else K.Accent)
        } else {
            Text("Tippen zum Zuordnen", style = MaterialTheme.typography.bodySmall, color = K.Accent)
        }
        slot.hints.forEach { Text(it, style = MaterialTheme.typography.bodySmall, color = K.DangerText) }
    }
}

@Composable
private fun Badge(text: String, bg: androidx.compose.ui.graphics.Color, fg: androidx.compose.ui.graphics.Color) {
    Text(text, style = MaterialTheme.typography.labelSmall, color = fg,
        modifier = Modifier.padding(start = 4.dp).clip(RoundedCornerShape(10.dp)).background(bg)
            .padding(horizontal = 8.dp, vertical = 3.dp))
}

@Composable
fun ShelfRow(sp: SpoolInfo, onClick: () -> Unit) {
    val shape = RoundedCornerShape(14.dp)
    Row(
        Modifier.fillMaxWidth().heightIn(min = 52.dp).clip(shape).background(K.Sunken).border(1.dp, K.Line, shape)
            .clickable(role = Role.Button, onClick = onClick).padding(horizontal = 12.dp, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        SpoolDisc(sp.color, 28.dp)
        Column(Modifier.weight(1f)) {
            Text(sp.displayName, style = MaterialTheme.typography.bodyMedium, maxLines = 1, overflow = TextOverflow.Ellipsis)
            Text(sp.material + (sp.location?.let { " · $it" } ?: ""), style = MaterialTheme.typography.bodySmall, color = K.Muted)
        }
        val low = (sp.remainingWeight ?: 1000.0) < 100
        Box { Text(gramsText(sp.remainingWeight), color = if (low) K.Danger else K.Text,
            style = MaterialTheme.typography.bodyMedium) }
    }
}

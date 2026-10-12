package io.github.xnovosx.kobraspoolman.ui

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import io.github.xnovosx.kobraspoolman.data.SpoolDetail
import io.github.xnovosx.kobraspoolman.data.SpoolInfo
import io.github.xnovosx.kobraspoolman.ui.theme.K
import io.github.xnovosx.kobraspoolman.ui.theme.PlexMono
import io.github.xnovosx.kobraspoolman.ui.theme.headerTint
import io.github.xnovosx.kobraspoolman.ui.theme.spoolColor
import io.github.xnovosx.kobraspoolman.data.tr

@Composable
fun SpoolScreen(
    detail: SpoolDetail?,
    slots: Int,
    canWrite: Boolean,
    busy: Boolean,
    contentPadding: PaddingValues,
    onBack: () -> Unit,
    onMove: (Int?) -> Unit,
    onArchive: () -> Unit,
    onWriteTag: (side: Int) -> Unit,
    moisture: @Composable () -> Unit = {},
) {
    var confirmArchive by remember { mutableStateOf(false) }
    Column(Modifier.fillMaxSize().background(K.Ground).verticalScroll(rememberScrollState())) {
        if (detail == null) {
            Row(Modifier.padding(start = 20.dp, top = contentPadding.calculateTopPadding() + 16.dp)) {
                RoundIconButton(KIcons.Back, tr("Back"), onBack)
            }
            Text(tr("Loading …"), color = K.Muted, modifier = Modifier.padding(20.dp))
            return@Column
        }
        val sp = detail.spool
        val tint = headerTint(spoolColor(sp.color))
        Column(
            Modifier.fillMaxWidth().background(tint)
                .padding(start = 20.dp, end = 20.dp, top = contentPadding.calculateTopPadding() + 16.dp, bottom = 24.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                RoundIconButton(KIcons.Back, tr("Back"), onBack, bg = K.Ground.copy(alpha = 0.4f))
                Text(tr("Spool #{id}", "id" to sp.spoolId) + tagsLabel(sp), style = MaterialTheme.typography.labelMedium,
                    color = K.Text, modifier = Modifier.padding(start = 12.dp))
            }
            Row(horizontalArrangement = Arrangement.spacedBy(16.dp), verticalAlignment = Alignment.CenterVertically) {
                SpoolDisc(sp.color, 96.dp, ring = spoolColor(sp.color).copy(alpha = 0.6f), hub = tint)
                Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Text(sp.vendor, style = MaterialTheme.typography.labelMedium, color = K.Muted)
                    Text(sp.name, style = MaterialTheme.typography.headlineSmall)
                    Text("#${sp.color} · ${sp.orcaFilamentId.orEmpty()}", fontFamily = PlexMono,
                        style = MaterialTheme.typography.bodySmall, color = K.Muted)
                }
            }
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.Bottom) {
                Text(gramsText(sp.remainingWeight), style = MaterialTheme.typography.headlineMedium,
                    modifier = Modifier.weight(1f))
                Text(tr("of {weight}", "weight" to Format.grams(sp.initialWeight)) + " · " + (sp.slot?.let { tr("in slot {slot}", "slot" to it) } ?: sp.location.orEmpty()),
                    style = MaterialTheme.typography.bodySmall, color = K.Muted)
            }
            FillBar(Format.fill(sp.remainingWeight, sp.initialWeight), track = K.Ground.copy(alpha = 0.5f), height = 8.dp)
        }

        Column(Modifier.padding(20.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Chip(sp.material)
                sp.nozzleTemp?.let { Chip(tr("Nozzle {t} °C", "t" to it.toInt())) }
                sp.bedTemp?.let { Chip(tr("Bed {t} °C", "t" to it.toInt())) }
                sp.template?.let { Chip(it, muted = true) }
            }
            SectionLabel(tr("Put into a slot"), Modifier.padding(top = 10.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                (1..slots).forEach { n ->
                    val here = sp.slot == n
                    OutlinedButton(
                        onClick = { if (!here) onMove(n) }, enabled = canWrite && !busy,
                        modifier = Modifier.weight(1f).height(56.dp), shape = RoundedCornerShape(14.dp),
                        border = BorderStroke(if (here) 2.dp else 1.dp, if (here) K.Accent else K.Line),
                        colors = ButtonDefaults.outlinedButtonColors(containerColor = if (here) K.AccentSoft else K.Surface,
                            contentColor = if (here) K.Accent else K.Text),
                    ) { Text("$n", style = MaterialTheme.typography.titleLarge) }
                }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                SecondaryButton(tr("To the shelf"), { onMove(null) }, Modifier.weight(1f), enabled = canWrite && !busy && sp.slot != null)
                val tags = tagCount(sp)
                // ACE 2 Pro: one tag per spool side. If the second is missing, write only that one.
                SecondaryButton(when (tags) { 0 -> tr("Write tags"); 1 -> tr("Write 2nd tag"); else -> tr("Rewrite tags") },
                    { onWriteTag(if (tags == 1) 2 else 1) }, Modifier.weight(1f), enabled = canWrite && !busy)
            }
            SecondaryButton(tr("Empty · archive"), { confirmArchive = true }, Modifier.fillMaxWidth(),
                enabled = canWrite && !busy, danger = true)
            if (!canWrite) Hint(tr("Changing only works once the app is paired (Settings)."))

            moisture()
            SectionLabel(tr("Recent prints"), Modifier.padding(top = 12.dp))
            if (detail.jobs.isEmpty()) Text(tr("No prints with this spool yet."), style = MaterialTheme.typography.bodySmall, color = K.Muted)
            detail.jobs.forEach { j ->
                Row(
                    Modifier.fillMaxWidth().clip(RoundedCornerShape(14.dp)).background(K.Sunken)
                        .border(1.dp, K.Surface2, RoundedCornerShape(14.dp)).padding(horizontal = 14.dp, vertical = 12.dp),
                ) {
                    Text(j.file ?: "–", style = MaterialTheme.typography.bodyMedium, maxLines = 1,
                        overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f))
                    Text(gramsText(j.g), color = K.Muted, style = MaterialTheme.typography.bodyMedium)
                }
            }
            Spacer(contentPadding.calculateBottomPadding())
        }
    }
    if (confirmArchive) {
        AlertDialog(
            onDismissRequest = { confirmArchive = false },
            title = { Text(tr("Archive the spool?")) },
            text = { Text(tr("The spool is empty: it leaves the slot and is archived in Spoolman.")) },
            confirmButton = { TextButton(onClick = { confirmArchive = false; onArchive() }) { Text(tr("Archive"), color = K.DangerText) } },
            dismissButton = { TextButton(onClick = { confirmArchive = false }) { Text(tr("Cancel")) } },
            containerColor = K.Surface,
        )
    }
}

@Composable
private fun Chip(text: String, muted: Boolean = false) {
    Text(text, style = MaterialTheme.typography.labelMedium, color = if (muted) K.Muted else K.Text,
        modifier = Modifier.clip(RoundedCornerShape(16.dp)).background(K.Surface).border(1.dp, K.Line, RoundedCornerShape(16.dp))
            .padding(horizontal = 12.dp, vertical = 7.dp))
}

@Composable
private fun Spacer(height: androidx.compose.ui.unit.Dp) = androidx.compose.foundation.layout.Spacer(Modifier.height(height))

private fun tagCount(sp: SpoolInfo): Int = sp.nfcUids.size.takeIf { it > 0 } ?: if (sp.nfcUid != null) 1 else 0

private fun tagsLabel(sp: SpoolInfo): String = when (tagCount(sp)) {
    0 -> ""
    1 -> " · " + tr("1 NFC tag (second side missing)")
    else -> " · " + tr("2 NFC tags")
}

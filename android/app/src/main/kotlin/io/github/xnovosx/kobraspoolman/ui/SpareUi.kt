package io.github.xnovosx.kobraspoolman.ui

import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import io.github.xnovosx.kobraspoolman.data.SpareSlot
import io.github.xnovosx.kobraspoolman.data.SpareState
import io.github.xnovosx.kobraspoolman.data.tr
import io.github.xnovosx.kobraspoolman.ui.theme.K
import kotlin.math.ceil
import kotlin.math.roundToInt

// Empty spool without a matching one (bridge spare.py, Klipper kobra_spare): the print waits over the waste chute;
// one tap = continue with that slot for the rest of the print. Home screen, like the power-loss question.

private fun SpareSlot.label(): String = spool?.name?.ifBlank { null } ?: material.ifBlank { "?" }
private fun SpareSlot.hex(): String? = spool?.color ?: color.ifBlank { null }

private fun SpareSlot.note(): String = when {
    !sameMaterial -> if (sticks) tr("other material") else tr("other material – may not stick")
    !sameColor -> tr("other colour")
    else -> ""
}

/** The slot the printer would take by itself (same order as kobra_spare). */
private fun SpareState.autoPick(): SpareSlot? = autoOrder.firstNotNullOfOrNull { kind ->
    candidates.firstOrNull { kind == "any" || (kind == "material" && it.sameMaterial) || (kind == "color" && it.sameColor) }
}

@Composable
fun SpareCard(sp: SpareState, canWrite: Boolean, onChoose: (Int) -> Unit) {
    var ask by remember { mutableStateOf<SpareSlot?>(null) }
    val w = sp.waiting
    Column(Modifier.fillMaxWidth().border(1.dp, K.DangerText, RoundedCornerShape(18.dp)).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text(if (sp.busy) tr("Changing the spool …") else tr("Spool empty – which one now?"),
            style = MaterialTheme.typography.titleMedium)
        w?.let {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                SpoolDisc(it.hex(), 28.dp)
                Text(tr("Slot {slot} · {name} is empty. No matching spool is loaded; the print waits over the waste chute.",
                    "slot" to it.slot, "name" to it.label()), style = MaterialTheme.typography.bodySmall)
            }
        }
        sp.error?.let { Text(tr("Change to another spool failed: {error}", "error" to it),
            style = MaterialTheme.typography.bodySmall, color = K.DangerText) }
        if (w != null && !sp.busy && canWrite) {
            sp.candidates.forEach { c ->
                Row(Modifier.fillMaxWidth()
                    .border(1.dp, if (c.sticks) K.LineStrong else K.DangerText, RoundedCornerShape(12.dp))
                    .clickable { if (c.sameMaterial) onChoose(c.tool) else ask = c }
                    .padding(10.dp),
                    verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    SpoolDisc(c.hex(), 32.dp)
                    Column(Modifier.weight(1f)) {
                        Text(tr("Slot {slot}", "slot" to c.slot) + " · " + c.label(), style = MaterialTheme.typography.bodyMedium)
                        Text(listOfNotNull(c.material.ifBlank { null }, c.note().ifBlank { null },
                            c.spool?.remainingWeight?.let { g -> tr("{g} left", "g" to "${g.roundToInt()} g") }).joinToString(" · "),
                            style = MaterialTheme.typography.bodySmall, color = if (c.sticks) K.Muted else K.DangerText)
                    }
                }
            }
            if (sp.candidates.isEmpty()) Text(tr("No other spool is ready – refill the slot."),
                style = MaterialTheme.typography.bodySmall, color = K.Muted)
            SecondaryButton(tr("Slot {slot} refilled – load and continue", "slot" to w.slot), { onChoose(w.tool) },
                Modifier.fillMaxWidth())
            sp.autoIn?.let { secs -> sp.autoPick()?.let { a ->
                Text(tr("Without an answer the printer takes slot {slot} in {min} min.", "slot" to a.slot,
                    "min" to maxOf(1, ceil(secs / 60.0).toInt())), style = MaterialTheme.typography.bodySmall, color = K.Muted)
            } }
        }
    }
    ask?.let { c ->
        AlertDialog(onDismissRequest = { ask = null }, containerColor = K.Surface,
            title = { Text(tr("Continue with {name}?", "name" to c.label())) },
            text = { Text(tr("Slot {slot} holds {material}, the print so far is {was}. The nozzle switches to the temperature of the new spool; the bed and the fans stay as the file sets them.",
                "slot" to c.slot, "material" to c.material, "was" to (w?.material ?: "?")) +
                (if (c.sticks) "" else " " + tr("These two materials usually do not stick to each other well."))) },
            confirmButton = { TextButton(onClick = { ask = null; onChoose(c.tool) }) {
                Text(tr("Continue"), color = if (c.sticks) K.Accent else K.DangerText) } },
            dismissButton = { TextButton(onClick = { ask = null }) { Text(tr("Back")) } })
    }
}

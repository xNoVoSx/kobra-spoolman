package io.github.xnovosx.kobraspoolman.ui

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.IconButtonDefaults
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import io.github.xnovosx.kobraspoolman.data.Printer
import io.github.xnovosx.kobraspoolman.ui.theme.K
import io.github.xnovosx.kobraspoolman.ui.theme.Plex
import io.github.xnovosx.kobraspoolman.ui.theme.PlexMono
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.withStyle
import kotlin.math.roundToInt
import io.github.xnovosx.kobraspoolman.ui.theme.spoolColor
import io.github.xnovosx.kobraspoolman.ui.theme.statusColors

/** Spule von der Seite: Scheibe in der Filamentfarbe mit Nabe. */
@Composable
fun SpoolDisc(hex: String?, size: Dp, ring: Color = K.LineStrong, hub: Color = K.Ground) {
    Box(
        Modifier.size(size).clip(CircleShape).background(spoolColor(hex)).border(2.dp, ring, CircleShape),
        contentAlignment = Alignment.Center,
    ) {
        Box(Modifier.size(size * 0.31f).clip(CircleShape).background(hub).border(2.dp, ring, CircleShape))
    }
}

@Composable
fun FillBar(fraction: Float, color: Color = K.Accent, track: Color = K.Surface2, height: Dp = 6.dp) {
    LinearProgressIndicator(
        progress = { fraction },
        modifier = Modifier.fillMaxWidth().height(height).clip(RoundedCornerShape(height / 2)),
        color = color, trackColor = track, strokeCap = StrokeCap.Butt, gapSize = 0.dp, drawStopIndicator = {},
    )
}

@Composable
fun RoundIconButton(icon: ImageVector, label: String, onClick: () -> Unit, bg: Color = K.Surface) {
    IconButton(
        onClick = onClick,
        modifier = Modifier.size(44.dp).border(1.dp, K.Line, CircleShape),
        colors = IconButtonDefaults.iconButtonColors(containerColor = bg, contentColor = K.Text),
    ) { Icon(icon, contentDescription = label, modifier = Modifier.size(20.dp)) }
}

@Composable
fun PrimaryButton(text: String, onClick: () -> Unit, modifier: Modifier = Modifier, enabled: Boolean = true) {
    Button(
        onClick = onClick, enabled = enabled, modifier = modifier.height(56.dp), shape = RoundedCornerShape(16.dp),
        colors = ButtonDefaults.buttonColors(containerColor = K.Accent, contentColor = K.OnAccent,
            disabledContainerColor = K.Surface2, disabledContentColor = K.Faint),
    ) { Text(text, style = MaterialTheme.typography.labelLarge) }
}

@Composable
fun SecondaryButton(text: String, onClick: () -> Unit, modifier: Modifier = Modifier, enabled: Boolean = true,
                    danger: Boolean = false) {
    OutlinedButton(
        onClick = onClick, enabled = enabled, modifier = modifier.height(52.dp), shape = RoundedCornerShape(14.dp),
        border = BorderStroke(1.dp, if (danger) K.DangerLine else K.Line),
        colors = ButtonDefaults.outlinedButtonColors(containerColor = if (danger) K.DangerSoft else K.Surface,
            contentColor = if (danger) K.DangerText else K.Text),
    ) { Text(text, style = MaterialTheme.typography.bodyLarge.copy(fontWeight = FontWeight.Medium)) }
}

@Composable
fun SectionLabel(text: String, modifier: Modifier = Modifier) {
    Text(text.uppercase(), style = MaterialTheme.typography.titleSmall, color = K.Muted, modifier = modifier)
}

/** Druckerstatus oben auf dem Startbildschirm. */
@Composable
fun StatusCard(p: Printer, activeName: String?) {
    val c = statusColors(Format.stateKey(p))
    Column(
        Modifier.fillMaxWidth().clip(RoundedCornerShape(18.dp)).background(c.bg).border(1.dp, c.line, RoundedCornerShape(18.dp))
            .padding(horizontal = 14.dp, vertical = 12.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Box(Modifier.size(10.dp).clip(CircleShape).background(c.dot))
            Text(Format.stateLabel(p), style = MaterialTheme.typography.titleMedium, color = c.fg)
            Text(p.file ?: p.message.orEmpty(), style = MaterialTheme.typography.labelMedium, color = K.Muted,
                maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f))
            if (p.progress != null) Text(Format.percent(p.progress), fontFamily = PlexMono, color = K.Text,
                style = MaterialTheme.typography.bodyMedium)
        }
        if (p.progress != null) FillBar(p.progress.toFloat(), color = c.dot, track = K.Ground)
        val left = when {
            p.activeSlot != null -> "Aktiv: Slot ${p.activeSlot}" + (activeName?.let { " · $it" } ?: "")
            p.state == "offline" -> "Drucker nicht erreichbar"
            else -> "Kein Slot aktiv"
        }
        Text(left, style = MaterialTheme.typography.bodySmall, color = K.Muted, maxLines = 1,
            overflow = TextOverflow.Ellipsis)
        if (p.printDurationS != null || p.etaS != null) {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                TimeStat("Läuft", Format.duration(p.printDurationS))
                TimeStat("Noch ca.", Format.duration(p.etaS))
                TimeStat("Fertig", Format.finishAt(p.etaS))
            }
        }
        MachineBar(p, inset = false)
    }
}

@Composable
private fun TimeStat(label: String, value: String) {
    Column {
        Text(label, style = MaterialTheme.typography.labelSmall, color = K.Muted)
        Text(value, fontFamily = PlexMono, style = MaterialTheme.typography.bodyMedium, color = K.Text)
    }
}

/** "973 g": Zahl in Festbreitenschrift, Einheit schmal in der Textschrift (sonst wirkt der Abstand zu gross). */
fun gramsText(g: Double?): AnnotatedString = buildAnnotatedString {
    withStyle(SpanStyle(fontFamily = PlexMono)) { append(if (g == null) "?" else g.roundToInt().toString()) }
    withStyle(SpanStyle(fontFamily = Plex)) { append("\u202Fg") }
}

/** Hinweis, wenn Android den Zugriff aufs Heimnetz (noch) nicht erlaubt. */
@Composable
fun LanMissing(onGrant: () -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Hint("Die App darf noch nicht ins Heimnetz – ohne das erreicht sie die Bridge nicht.", danger = true)
        SecondaryButton("Zugriff aufs Heimnetz erlauben", onGrant, Modifier.fillMaxWidth())
    }
}

@Composable
fun Hint(text: String, danger: Boolean = false) {
    Text(text, style = MaterialTheme.typography.bodySmall, color = if (danger) K.DangerText else K.Muted,
        modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp))
            .background(if (danger) K.DangerSoft else K.Sunken).padding(horizontal = 10.dp, vertical = 6.dp))
}

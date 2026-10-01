package io.github.xnovosx.kobraspoolman.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import io.github.xnovosx.kobraspoolman.data.Notices
import io.github.xnovosx.kobraspoolman.ui.theme.K

private fun levelColor(level: String): Color = when (level) {
    "error" -> K.Danger
    "warn" -> K.Accent
    else -> K.Muted
}

private fun stateColor(state: String): Color = when (state) {
    "ok" -> K.Ok
    "warn" -> K.Accent
    "bad" -> K.Danger
    else -> K.Faint
}

@Composable
private fun Dot(c: Color) = Box(Modifier.padding(top = 6.dp).size(8.dp).clip(CircleShape).background(c))

/** Meldungen & Status der Uebersicht, wie in der Weboberflaeche (GET /api/app/state -> notices). */
@Composable
fun NoticesCard(n: Notices, bridgeVersion: String, title: Boolean = true) {
    Column(
        Modifier.fillMaxWidth().clip(RoundedCornerShape(20.dp)).background(K.Surface)
            .border(1.dp, K.Line, RoundedCornerShape(20.dp)).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(if (title) "Meldungen" else "", style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f))
            if (n.messages.isEmpty()) Text("alles gut", style = MaterialTheme.typography.labelMedium, color = K.Ok)
        }
        n.messages.forEach { m ->
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                Dot(levelColor(m.level))
                Text(m.text, style = MaterialTheme.typography.bodyMedium,
                    color = if (m.level == "info") K.Muted else levelColor(m.level))
            }
        }
        Text("STATUS", style = MaterialTheme.typography.labelSmall, color = K.Muted, modifier = Modifier.padding(top = 4.dp))
        val lines = n.status.map { Triple(it.state, it.label, listOfNotNull(it.detail, it.seen?.let { s -> Format.ago(s.toLong()) }).joinToString(" · ")) } +
            Triple("ok", "Bridge", "$bridgeVersion · verbunden")
        lines.forEach { (state, label, detail) ->
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                Dot(stateColor(state))
                Text(label, style = MaterialTheme.typography.bodySmall, color = K.Text, modifier = Modifier.width(92.dp))
                Text(detail, style = MaterialTheme.typography.bodySmall, color = K.Muted, maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
        }
    }
}

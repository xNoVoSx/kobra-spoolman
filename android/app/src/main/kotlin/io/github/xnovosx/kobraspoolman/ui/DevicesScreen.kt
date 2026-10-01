package io.github.xnovosx.kobraspoolman.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import io.github.xnovosx.kobraspoolman.data.Device
import io.github.xnovosx.kobraspoolman.data.PairLink
import io.github.xnovosx.kobraspoolman.data.PairingCode
import io.github.xnovosx.kobraspoolman.ui.theme.K
import io.github.xnovosx.kobraspoolman.ui.theme.PlexMono
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

private val KIND = mapOf("app" to "App", "web" to "Browser", "plugin" to "Orca-Plugin", "other" to "Sonstiges")

@Composable
fun DevicesScreen(
    bridgeUrl: String,
    devices: List<Device>,
    code: PairingCode?,
    busy: Boolean,
    contentPadding: PaddingValues,
    onLoad: () -> Unit,
    onBack: () -> Unit,
    onNewCode: () -> Unit,
    onCloseCode: () -> Unit,
    onRemove: (Device) -> Unit,
) {
    LaunchedEffect(Unit) { onLoad() }
    var confirm by remember { mutableStateOf<Device?>(null) }
    Column(
        Modifier.fillMaxSize().background(K.Ground).verticalScroll(rememberScrollState())
            .padding(start = 20.dp, end = 20.dp, top = contentPadding.calculateTopPadding() + 16.dp,
                bottom = contentPadding.calculateBottomPadding() + 16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            RoundIconButton(KIcons.Back, "Zurück", onBack)
            Text("Geräte", style = MaterialTheme.typography.headlineSmall)
        }
        if (code == null) {
            PrimaryButton("Gerät hinzufügen", onNewCode, Modifier.fillMaxWidth(), enabled = !busy)
        } else {
            Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(18.dp)).background(K.Surface).border(1.dp, K.Line, RoundedCornerShape(18.dp))
                .padding(16.dp), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Text("Auf dem neuen Gerät scannen oder eintippen", style = MaterialTheme.typography.bodyMedium, color = K.Muted,
                    textAlign = TextAlign.Center)
                QrImage(PairLink(bridgeUrl, code.code).toUri(), Modifier.size(220.dp))
                Text(code.code.chunked(3).joinToString(" "), fontFamily = PlexMono, fontSize = 40.sp, color = K.Accent)
                Text("Gültig ${code.expiresIn / 60} Minuten, einmal verwendbar · $bridgeUrl", style = MaterialTheme.typography.bodySmall,
                    color = K.Muted, textAlign = TextAlign.Center)
                SecondaryButton("Fertig", onCloseCode, Modifier.fillMaxWidth())
            }
        }
        SectionLabel("Gekoppelt", Modifier.padding(top = 8.dp))
        devices.forEach { d ->
            Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(14.dp)).background(K.Sunken).border(1.dp, K.Line, RoundedCornerShape(14.dp))
                .padding(horizontal = 14.dp, vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text(d.name + if (d.me) "  (dieses Gerät)" else "", style = MaterialTheme.typography.bodyLarge)
                    Text(KIND[d.kind].orEmpty() + (d.lastSeen?.let { " · zuletzt " + SimpleDateFormat("dd.MM.yy HH:mm", Locale.GERMANY)
                        .format(Date((it * 1000).toLong())) } ?: ""), style = MaterialTheme.typography.bodySmall, color = K.Muted)
                }
                TextButton(onClick = { confirm = d }) { Text("Entfernen", color = K.DangerText) }
            }
        }
    }
    confirm?.let { d ->
        AlertDialog(
            onDismissRequest = { confirm = null },
            title = { Text("„${d.name}“ entfernen?") },
            text = { Text(if (d.me) "Das ist dieses Gerät – danach kann es nichts mehr ändern, bis es neu gekoppelt ist."
                else "Das Gerät kann danach nichts mehr ändern, bis es neu gekoppelt ist.") },
            confirmButton = { TextButton(onClick = { confirm = null; onRemove(d) }) { Text("Entfernen", color = K.DangerText) } },
            dismissButton = { TextButton(onClick = { confirm = null }) { Text("Abbrechen") } },
            containerColor = K.Surface,
        )
    }
}

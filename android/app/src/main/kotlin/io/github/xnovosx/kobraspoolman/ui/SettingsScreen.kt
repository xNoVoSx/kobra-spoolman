package io.github.xnovosx.kobraspoolman.ui

import android.os.Build
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import io.github.xnovosx.kobraspoolman.BuildConfig
import io.github.xnovosx.kobraspoolman.data.BridgeClient
import io.github.xnovosx.kobraspoolman.data.Connection
import io.github.xnovosx.kobraspoolman.data.Device
import io.github.xnovosx.kobraspoolman.data.PairLink
import io.github.xnovosx.kobraspoolman.ui.theme.K

@Composable
fun SettingsScreen(
    current: Connection,
    me: Device?,
    meChecked: Boolean,
    busy: Boolean,
    contentPadding: PaddingValues,
    lanMissing: Boolean,
    onGrantLan: () -> Unit,
    canGoBack: Boolean,
    onBack: () -> Unit,
    onLoadMe: () -> Unit,
    onPair: (url: String, code: String, name: String) -> Unit,
    onForget: () -> Unit,
    onDevices: () -> Unit,
) {
    val hasKey = current.token.isNotBlank()
    LaunchedEffect(hasKey) { if (hasKey) onLoadMe() }
    // Schluessel vorhanden, aber die Bridge kennt ihn nicht (mehr): wie nicht gekoppelt behandeln
    val invalid = hasKey && meChecked && me == null
    val paired = hasKey && !invalid
    var url by rememberSaveable(current.url) { mutableStateOf(current.url) }
    var code by rememberSaveable { mutableStateOf("") }
    var name by rememberSaveable { mutableStateOf("Handy (${Build.MODEL})") }
    var scanning by rememberSaveable { mutableStateOf(false) }

    Column(
        Modifier.fillMaxSize().background(K.Ground).imePadding().verticalScroll(rememberScrollState())
            .padding(start = 20.dp, end = 20.dp, top = contentPadding.calculateTopPadding() + 16.dp,
                bottom = contentPadding.calculateBottomPadding() + 16.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            if (canGoBack) RoundIconButton(KIcons.Back, "Zurück", onBack)
            Text("Einstellungen", style = MaterialTheme.typography.headlineSmall)
        }
        if (lanMissing) LanMissing(onGrantLan)

        if (paired) {
            SectionLabel("Verbunden")
            Hint("Bridge: ${current.url}\nGekoppelt als „${me?.name ?: "…"}“")
            PrimaryButton("Geräte verwalten", onDevices, Modifier.fillMaxWidth())
            SecondaryButton("Kopplung hier vergessen", onForget, Modifier.fillMaxWidth())
            Text("„Vergessen“ löscht den Schlüssel nur auf diesem Handy. Ganz entfernen: unter „Geräte verwalten“.",
                style = MaterialTheme.typography.bodySmall, color = K.Muted)
        } else {
            if (invalid) Hint("Die Bridge kennt dieses Gerät nicht mehr (entfernt oder neu eingerichtet) – bitte neu koppeln.",
                danger = true)
            SectionLabel("Mit der Bridge koppeln")
            Text("Am PC in der Weboberfläche oder in einer gekoppelten App „Gerät hinzufügen“ wählen und den QR-Code " +
                "scannen – oder Adresse und Code eintippen. Beim allerersten Gerät steht ein Einrichtungscode im Log der Bridge.",
                style = MaterialTheme.typography.bodyMedium, color = K.Muted)
            if (scanning) {
                QrScanner(onResult = { text ->
                    scanning = false
                    PairLink.parse(text)?.let { l ->
                        url = l.bridge
                        code = l.code
                        onPair(l.bridge, l.code, name)
                    }
                })
                SecondaryButton("Abbrechen", { scanning = false }, Modifier.fillMaxWidth())
            } else {
                PrimaryButton("QR-Code scannen", { scanning = true }, Modifier.fillMaxWidth(), enabled = !busy)
            }
            OutlinedTextField(url, { url = it }, label = { Text("Bridge-Adresse, z.B. 192.168.1.10:7913") }, singleLine = true,
                modifier = Modifier.fillMaxWidth(), shape = RoundedCornerShape(12.dp),
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri))
            OutlinedTextField(code, { code = it.trim() }, label = { Text("Code (6 Ziffern)") }, singleLine = true,
                modifier = Modifier.fillMaxWidth(), shape = RoundedCornerShape(12.dp),
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number))
            OutlinedTextField(name, { name = it }, label = { Text("Name dieses Geräts") }, singleLine = true,
                modifier = Modifier.fillMaxWidth(), shape = RoundedCornerShape(12.dp))
            SecondaryButton("Koppeln", { onPair(BridgeClient.normalizeUrl(url), code, name) }, Modifier.fillMaxWidth(),
                enabled = !busy && url.isNotBlank() && code.isNotBlank())
        }
        Text("App ${BuildConfig.VERSION_NAME}", style = MaterialTheme.typography.bodySmall, color = K.Faint)
    }
}

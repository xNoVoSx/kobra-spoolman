package io.github.xnovosx.kobraspoolman.ui

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
import androidx.compose.runtime.getValue
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import io.github.xnovosx.kobraspoolman.BuildConfig
import io.github.xnovosx.kobraspoolman.data.Connection
import io.github.xnovosx.kobraspoolman.ui.theme.K

@Composable
fun SettingsScreen(
    current: Connection,
    busy: Boolean,
    contentPadding: PaddingValues,
    lanMissing: Boolean,
    onGrantLan: () -> Unit,
    canGoBack: Boolean,
    onBack: () -> Unit,
    onSave: (Connection) -> Unit,
) {
    var url by rememberSaveable(current.url) { mutableStateOf(current.url) }
    var token by rememberSaveable(current.token) { mutableStateOf(current.token) }
    Column(
        Modifier.fillMaxSize().background(K.Ground).imePadding().verticalScroll(rememberScrollState())
            .padding(start = 20.dp, end = 20.dp, top = contentPadding.calculateTopPadding() + 16.dp,
                bottom = contentPadding.calculateBottomPadding() + 16.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            if (canGoBack) RoundIconButton(KIcons.Back, "Zurück", onBack)
            Text("Einstellungen", style = MaterialTheme.typography.headlineSmall)
        }
        if (lanMissing) LanMissing(onGrantLan)
        Text("Adresse der ace-lane-bridge – dieselbe wie im Orca-Plugin, z.B. 192.168.1.10:7913.",
            style = MaterialTheme.typography.bodyMedium, color = K.Muted)
        OutlinedTextField(url, { url = it }, label = { Text("Bridge-Adresse") }, singleLine = true,
            modifier = Modifier.fillMaxWidth(), shape = RoundedCornerShape(12.dp),
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri))
        OutlinedTextField(token, { token = it }, label = { Text("App-Schlüssel (APP_TOKEN)") }, singleLine = true,
            modifier = Modifier.fillMaxWidth(), shape = RoundedCornerShape(12.dp),
            visualTransformation = PasswordVisualTransformation(),
            supportingText = { Text("Leer = nur ansehen. Mit Schlüssel: Spulen anlegen, umlagern, Tags verknüpfen.") })
        PrimaryButton("Verbindung prüfen und speichern", { onSave(Connection(url, token)) }, Modifier.fillMaxWidth(),
            enabled = !busy && url.isNotBlank())
        Text("App ${BuildConfig.VERSION_NAME}", style = MaterialTheme.typography.bodySmall, color = K.Faint)
    }
}

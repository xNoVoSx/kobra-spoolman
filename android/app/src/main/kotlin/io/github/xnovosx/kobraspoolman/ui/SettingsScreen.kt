package io.github.xnovosx.kobraspoolman.ui

import android.app.LocaleManager
import android.os.Build
import android.os.LocaleList
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
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import io.github.xnovosx.kobraspoolman.BuildConfig
import io.github.xnovosx.kobraspoolman.data.BridgeClient
import io.github.xnovosx.kobraspoolman.data.Connection
import io.github.xnovosx.kobraspoolman.data.Device
import io.github.xnovosx.kobraspoolman.data.PairLink
import io.github.xnovosx.kobraspoolman.ui.theme.K
import io.github.xnovosx.kobraspoolman.data.tr

@Composable
fun SettingsScreen(
    current: Connection,
    me: Device?,
    meChecked: Boolean,
    busy: Boolean,
    contentPadding: PaddingValues,
    lanMissing: Boolean,
    onGrantLan: () -> Unit,
    monitor: Boolean,
    onMonitor: (Boolean) -> Unit,
    render3d: String = "auto",
    onRender3d: (String) -> Unit = {},
    canGoBack: Boolean,
    onBack: () -> Unit,
    onLoadMe: () -> Unit,
    onPair: (url: String, code: String, name: String) -> Unit,
    onForget: () -> Unit,
    onDevices: () -> Unit,
    remote: @Composable () -> Unit = {},
) {
    val hasKey = current.token.isNotBlank()
    LaunchedEffect(hasKey) { if (hasKey) onLoadMe() }
    // key present but the bridge does not know it (any more): treat it as not paired
    val invalid = hasKey && meChecked && me == null
    val paired = hasKey && !invalid
    var url by rememberSaveable(current.url) { mutableStateOf(current.url) }
    var code by rememberSaveable { mutableStateOf("") }
    var name by rememberSaveable { mutableStateOf(tr("Phone ({model})", "model" to Build.MODEL)) }
    var scanning by rememberSaveable { mutableStateOf(false) }

    Column(
        Modifier.fillMaxSize().background(K.Ground).imePadding().verticalScroll(rememberScrollState())
            .padding(start = 20.dp, end = 20.dp, top = contentPadding.calculateTopPadding() + 16.dp,
                bottom = contentPadding.calculateBottomPadding() + 16.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            if (canGoBack) RoundIconButton(KIcons.Back, tr("Back"), onBack)
            Text(tr("Settings"), style = MaterialTheme.typography.headlineSmall)
        }
        if (lanMissing) LanMissing(onGrantLan)

        if (paired) {
            SectionLabel(tr("Connected"))
            Hint(tr("Bridge: {url}", "url" to current.url) + "\n" + tr("Paired as “{name}”", "name" to (me?.name ?: "…")))
            PrimaryButton(tr("Manage devices"), onDevices, Modifier.fillMaxWidth())
            SecondaryButton(tr("Forget the pairing here"), onForget, Modifier.fillMaxWidth())
            Text(tr("“Forget” deletes the key only on this phone. To remove it completely: under “Manage devices”."),
                style = MaterialTheme.typography.bodySmall, color = K.Muted)
            remote()
            SectionLabel(tr("Notifications"), Modifier.padding(top = 8.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text(tr("Monitor the printer in the background"), style = MaterialTheme.typography.bodyLarge)
                    Text(tr("While printing always on top in the status bar (live update), own sounds for start, first layer, done, alarm and hint. Only queries the bridge – it costs nothing on the printer."),
                        style = MaterialTheme.typography.bodySmall, color = K.Muted)
                }
                Switch(monitor, onMonitor)
            }
            SoundsSection()
            val ctx = androidx.compose.ui.platform.LocalContext.current
            SecondaryButton(tr("Widget on the home screen"), {
                val m = android.appwidget.AppWidgetManager.getInstance(ctx)
                if (m.isRequestPinAppWidgetSupported) {
                    m.requestPinAppWidget(android.content.ComponentName(ctx, io.github.xnovosx.kobraspoolman.monitor.PrintWidget::class.java), null, null)
                }
            }, Modifier.fillMaxWidth())
            Text(tr("Shows progress, time left and the camera image – updated by the monitoring, so it costs nothing extra."),
                style = MaterialTheme.typography.bodySmall, color = K.Muted)
            SectionLabel(tr("Print preview"), Modifier.padding(top = 8.dp))
            Text(tr("3D model"), style = MaterialTheme.typography.bodyLarge)
            Segmented(listOf("auto" to tr("Automatic"), "volume" to tr("Volume"), "lines" to tr("Lines"), "image" to tr("Image")), render3d, onRender3d)
            Text(tr("Volume: shaded strands like in the slicer. Lines: saves battery and graphics. Image: the finished image of the bridge. Automatic lets the phone choose."),
                style = MaterialTheme.typography.bodySmall, color = K.Muted)
        } else {
            if (invalid) Hint(tr("The bridge no longer knows this device (removed or set up again) – please pair again."),
                danger = true)
            SectionLabel(tr("Pair with the bridge"))
            Text(tr("On the PC in the web UI or in a paired app choose “Add device” and scan the QR code – or type address and code. For the very first device a setup code is in the bridge log."),
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
                SecondaryButton(tr("Cancel"), { scanning = false }, Modifier.fillMaxWidth())
            } else {
                PrimaryButton(tr("Scan QR code"), { scanning = true }, Modifier.fillMaxWidth(), enabled = !busy)
            }
            OutlinedTextField(url, { url = it }, label = { Text(tr("Bridge address, e.g. 192.168.1.10:7913")) }, singleLine = true,
                modifier = Modifier.fillMaxWidth(), shape = RoundedCornerShape(12.dp),
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri))
            OutlinedTextField(code, { code = it.trim() }, label = { Text(tr("Code (6 digits)")) }, singleLine = true,
                modifier = Modifier.fillMaxWidth(), shape = RoundedCornerShape(12.dp),
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number))
            OutlinedTextField(name, { name = it }, label = { Text(tr("Name of this device")) }, singleLine = true,
                modifier = Modifier.fillMaxWidth(), shape = RoundedCornerShape(12.dp))
            SecondaryButton(tr("Pair"), { onPair(BridgeClient.normalizeUrl(url), code, name) }, Modifier.fillMaxWidth(),
                enabled = !busy && url.isNotBlank() && code.isNotBlank())
        }
        LanguageSection()
        Text("App ${BuildConfig.VERSION_NAME}", style = MaterialTheme.typography.bodySmall, color = K.Faint)
    }
}

/**
 * Language of the app: Android 13+ stores a per-app language (also under Settings -> Apps -> Kobra Spoolman ->
 * Language); Android recreates the screen and KobraApp switches the texts. Older Android: the system language.
 */
@Composable
private fun LanguageSection() {
    val ctx = LocalContext.current
    SectionLabel(tr("Language"), Modifier.padding(top = 8.dp))
    if (Build.VERSION.SDK_INT >= 33) {
        val lm = ctx.getSystemService(LocaleManager::class.java)
        val cur = lm.applicationLocales.takeIf { !it.isEmpty }?.get(0)?.language ?: "system"
        Segmented(listOf("system" to tr("System"), "en" to "English", "de" to "Deutsch"), cur) { v ->
            lm.applicationLocales = if (v == "system") LocaleList.getEmptyLocaleList() else LocaleList.forLanguageTags(v)
        }
    } else {
        Text(tr("The app follows the system language (English or German)."), style = MaterialTheme.typography.bodySmall, color = K.Muted)
    }
}

package io.github.xnovosx.kobraspoolman.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.unit.dp
import io.github.xnovosx.kobraspoolman.data.FeatureItem
import io.github.xnovosx.kobraspoolman.data.Features
import io.github.xnovosx.kobraspoolman.data.SetupInfo
import io.github.xnovosx.kobraspoolman.data.tr
import io.github.xnovosx.kobraspoolman.ui.theme.K

// Features and setup in the app - the same as the web UI (bridge features.py / setup.py): one switch per feature, no
// matter whether it lives in the bridge or in the printer; what the installation sets is shown, never changed here.

/** Right side of a feature row: a switch, or what it is (always on, set by the installation, paired, missing). */
@Composable
private fun FeatureState(it: FeatureItem, checked: Boolean, enabled: Boolean, onChange: (Boolean) -> Unit) {
    when {
        it.available && it.switchable -> Switch(checked, onChange, enabled = enabled,
            colors = SwitchDefaults.colors(checkedTrackColor = K.Accent, checkedThumbColor = K.OnAccent))
        !it.available -> Text(tr("not available"), style = MaterialTheme.typography.labelMedium, color = K.Muted)
        it.source == "core" -> Text(tr("always on"), style = MaterialTheme.typography.labelMedium, color = K.Ok)
        else -> Text(if (it.on == true) tr("on") else tr("off"), style = MaterialTheme.typography.labelMedium,
            color = if (it.on == true) K.Ok else K.Muted)
    }
}

@Composable
private fun FeatureRow(it: FeatureItem, checked: Boolean, enabled: Boolean, onChange: (Boolean) -> Unit) {
    val uri = LocalUriHandler.current
    Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth().padding(vertical = 8.dp)) {
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
            Text(it.title, style = MaterialTheme.typography.bodyLarge)
            Text(it.text, style = MaterialTheme.typography.bodySmall, color = K.Muted)
            (it.why ?: it.needs?.let { n -> tr("Needs: {needs}", "needs" to n) })?.let { w ->
                Text(w, style = MaterialTheme.typography.bodySmall, color = K.Faint)
            }
            it.doc?.let { d ->
                Text(tr("How it works"), style = MaterialTheme.typography.bodySmall, color = K.Accent,
                    modifier = Modifier.clickable { runCatching { uri.openUri(d) } })
            }
        }
        FeatureState(it, checked, enabled, onChange)
    }
}

@Composable
private fun GroupCard(title: String, content: @Composable () -> Unit) {
    Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(16.dp)).background(K.Surface).padding(14.dp)) {
        Text(title, style = MaterialTheme.typography.titleMedium)
        content()
    }
}

@Composable
fun FeaturesScreen(padding: PaddingValues, features: Features?, canWrite: Boolean, busy: Boolean,
                   onLoad: () -> Unit, onSwitch: (String, Boolean) -> Unit, onSetup: () -> Unit, onBack: () -> Unit) {
    LaunchedEffect(Unit) { onLoad() }
    LazyColumn(Modifier.fillMaxSize().background(K.Ground), contentPadding = listPadding(padding),
        verticalArrangement = Arrangement.spacedBy(10.dp)) {
        item { ScreenHeader(tr("Features"), onBack) }
        item {
            Text(tr("Everything the system can do, in one place. Switch what you want – what the installation sets (environment variables, Home Assistant add-on) stays as it is, and is changed there."),
                style = MaterialTheme.typography.bodySmall, color = K.Muted)
        }
        item { SecondaryButton(tr("Start setup"), onSetup, Modifier.fillMaxWidth()) }
        val f = features
        if (f == null) item { Text(tr("Loading …"), color = K.Muted) }
        else items(f.groups, key = { it.key }) { g ->
            GroupCard(g.title) {
                f.items.filter { it.group == g.key }.forEach { it ->
                    FeatureRow(it, it.on == true, canWrite && !busy) { on -> onSwitch(it.key, on) }
                }
            }
        }
    }
}

/** What only the phone can check for the setup: NFC for the tags, notifications for the printer's messages. */
data class PhoneChecks(val nfc: Boolean?, val notifications: Boolean, val monitor: Boolean)

@Composable
private fun Found(ok: Boolean?, label: String, detail: String) {
    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp),
        modifier = Modifier.fillMaxWidth().padding(vertical = 6.dp)) {
        Text(when (ok) { true -> "✓"; false -> "✗"; null -> "?" }, style = MaterialTheme.typography.titleMedium,
            color = when (ok) { true -> K.Ok; false -> K.DangerText; null -> K.Muted })
        Column(Modifier.weight(1f)) {
            Text(label, style = MaterialTheme.typography.bodyLarge)
            Text(detail, style = MaterialTheme.typography.bodySmall, color = K.Muted)
        }
    }
}

private val PLATFORM = mapOf("klipper" to "Klipper + ACEPRO", "rinkhals" to "Rinkhals")

/**
 * Setup after pairing (new) or from the Features page: 1 found (bridge + phone) · 2 choose · 3 what is left to do.
 * The app sets up what it can: the switches of the bridge and the printer, notifications on; the rest (display, Orca
 * plugin, Home Assistant, AI) is shown with a link.
 */
@Composable
fun SetupScreen(padding: PaddingValues, info: SetupInfo?, phone: PhoneChecks, busy: Boolean,
                onLoad: () -> Unit, onAllowNotifications: () -> Unit, onMonitor: (Boolean) -> Unit,
                onApply: (Map<String, Boolean>, () -> Unit) -> Unit, onFinish: () -> Unit) {
    LaunchedEffect(Unit) { onLoad() }
    var step by remember { mutableIntStateOf(1) }
    val want = remember { mutableStateMapOf<String, Boolean>() }
    LaunchedEffect(info) {
        info?.features?.items?.filter { it.switchable }?.forEach { if (it.key !in want) want[it.key] = it.on == true }
    }
    val uri = LocalUriHandler.current
    LazyColumn(Modifier.fillMaxSize().background(K.Ground), contentPadding = listPadding(padding),
        verticalArrangement = Arrangement.spacedBy(10.dp)) {
        item { ScreenHeader(tr("Setup")) }
        item {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                listOf(tr("Found"), tr("Choose"), tr("Done")).forEachIndexed { i, s ->
                    Text("${i + 1} · $s", style = MaterialTheme.typography.labelMedium,
                        color = if (step == i + 1) K.Accent else K.Muted)
                }
            }
        }
        if (info == null) { item { Text(tr("Loading …"), color = K.Muted) }; return@LazyColumn }
        val f = info.found
        val items = info.features.items
        when (step) {
            1 -> {
                item {
                    GroupCard(tr("What the bridge found")) {
                        Found(f.printer, tr("Printer"), if (f.printer) PLATFORM[f.platform] ?: f.platform else tr("Not reachable – check MOONRAKER_URL"))
                        Found(if (f.ace != null) true else if (f.printer) false else null, "ACE",
                            f.ace?.let { tr("Driver: {name}", "name" to it) } ?: tr("No ACE driver found"))
                        Found(f.spoolman, "Spoolman", if (f.spoolman) tr("Version {v}", "v" to (f.spoolmanVersion ?: "?")) else tr("Not reachable – check SPOOLMAN_URL"))
                        Found(f.camera, tr("Camera"), when (f.camera) { true -> tr("Image received"); false -> tr("No image – check the camera at the printer"); null -> tr("Checked when someone watches") })
                        if (f.platform == "klipper") Found(if (f.printerModules.isNotEmpty()) true else null, tr("Printer modules"),
                            if (f.printerModules.isNotEmpty()) f.printerModules.joinToString(", ") { k -> items.firstOrNull { it.key == k }?.title ?: k }
                            else tr("None installed (optional)"))
                    }
                }
                item {
                    GroupCard(tr("This phone")) {
                        Found(phone.nfc, tr("NFC for the tags"), when (phone.nfc) {
                            true -> tr("Ready – hold a spool to the phone to read or write its tag")
                            false -> tr("NFC is switched off – switch it on in the Android settings.")
                            null -> tr("This device has no NFC.")
                        })
                        Found(phone.notifications, tr("Notifications"), if (phone.notifications) tr("Allowed") else tr("Not allowed yet"))
                        if (!phone.notifications) SecondaryButton(tr("Allow notifications"), onAllowNotifications, Modifier.fillMaxWidth())
                        Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(top = 6.dp)) {
                            Column(Modifier.weight(1f)) {
                                Text(tr("Printer messages on the phone"), style = MaterialTheme.typography.bodyLarge)
                                Text(tr("Print finished, paused, errors, spool empty – every kind can be switched off later"),
                                    style = MaterialTheme.typography.bodySmall, color = K.Muted)
                            }
                            Switch(phone.monitor, onMonitor, colors = SwitchDefaults.colors(checkedTrackColor = K.Accent, checkedThumbColor = K.OnAccent))
                        }
                    }
                }
                item {
                    Text(tr("Spools, slots, bookings and RFID are always on, camera and print preview too (they can be switched off on the Features page). Next you choose what else the system should do."),
                        style = MaterialTheme.typography.bodySmall, color = K.Muted)
                }
                item { PrimaryButton(tr("Next"), { step = 2 }, Modifier.fillMaxWidth()) }
            }
            2 -> {
                items(info.features.groups.filter { it.key != "core" }, key = { it.key }) { g ->
                    GroupCard(g.title) {
                        items.filter { it.group == g.key }.forEach { it ->
                            FeatureRow(it, want[it.key] ?: (it.on == true), !busy) { on -> want[it.key] = on }
                        }
                    }
                }
                item {
                    Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                        SecondaryButton(tr("Back"), { step = 1 }, Modifier.weight(1f))
                        PrimaryButton(if (busy) tr("Applying …") else tr("Apply"), { onApply(want.toMap()) { step = 3 } },
                            Modifier.weight(1f), enabled = !busy)
                    }
                }
            }
            else -> {
                val todo = items.filter { it.available && !it.switchable && it.on != true && it.source in setOf("client", "install") && it.key != "app" }
                item {
                    GroupCard(tr("Ready")) {
                        Text(tr("Your choice is applied. You can change everything later on the Features page."),
                            style = MaterialTheme.typography.bodyMedium, modifier = Modifier.padding(top = 6.dp))
                        if (todo.isNotEmpty()) {
                            Text(tr("This is set up on the device or in the installation – if you want it:"),
                                style = MaterialTheme.typography.bodySmall, color = K.Muted, modifier = Modifier.padding(top = 10.dp))
                            todo.forEach { t ->
                                Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp)) {
                                    Column(Modifier.weight(1f)) {
                                        Text(t.title, style = MaterialTheme.typography.bodyMedium)
                                        t.needs?.let { n -> Text(n, style = MaterialTheme.typography.bodySmall, color = K.Faint) }
                                    }
                                    t.doc?.let { d -> TextButton(onClick = { runCatching { uri.openUri(d) } }) { Text(tr("How it works"), color = K.Accent) } }
                                }
                            }
                        }
                    }
                }
                item { PrimaryButton(tr("To the overview"), onFinish, Modifier.fillMaxWidth()) }
            }
        }
    }
}

/** App paired before this version: one hint on the new Features page (the setup itself never opens by itself). */
@Composable
fun FeaturesHintDialog(onLook: () -> Unit, onDismiss: () -> Unit) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(tr("New: Features")) },
        text = { Text(tr("Everything the system can do on one page – see what is on and switch it in one place. Nothing has changed in your setup.")) },
        confirmButton = { TextButton(onClick = onLook) { Text(tr("Have a look"), color = K.Accent) } },
        dismissButton = { TextButton(onClick = onDismiss) { Text(tr("OK")) } },
        containerColor = K.Surface,
    )
}


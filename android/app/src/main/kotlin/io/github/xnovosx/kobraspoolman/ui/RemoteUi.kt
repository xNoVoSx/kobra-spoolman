package io.github.xnovosx.kobraspoolman.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import io.github.xnovosx.kobraspoolman.data.Connection
import io.github.xnovosx.kobraspoolman.data.HaRemote
import io.github.xnovosx.kobraspoolman.data.RouteKind
import io.github.xnovosx.kobraspoolman.data.tr
import io.github.xnovosx.kobraspoolman.monitor.VpnApps
import io.github.xnovosx.kobraspoolman.ui.theme.K

fun routeLabel(kind: RouteKind): String = when (kind) {
    RouteKind.LOCAL -> tr("Home network")
    RouteKind.VPN -> tr("Second address (VPN)")
    RouteKind.HA -> tr("Home Assistant")
}

/**
 * Settings -> Remote access: how the app reaches the bridge away from home. Every way is optional; without one the app
 * works as before (home network only).
 */
@Composable
fun RemoteSection(vm: AppViewModel, c: Connection, busy: Boolean) {
    val route by vm.routeKind.collectAsState()
    val info by vm.remoteInfo.collectAsState()
    val test by vm.remoteTest.collectAsState()
    val awayHint by vm.awayHint.collectAsState()
    val vpnApp by vm.vpnApp.collectAsState()
    LaunchedEffect(Unit) { vm.loadRemoteInfo() }

    var vpnUrl by rememberSaveable(c.vpnUrl) { mutableStateOf(c.vpnUrl) }
    var haOn by rememberSaveable(c.ha.on) { mutableStateOf(c.ha.on) }
    var haUrl by rememberSaveable(c.ha.url) { mutableStateOf(c.ha.url) }
    var haToken by rememberSaveable(c.ha.token) { mutableStateOf(c.ha.token) }
    var haIngress by rememberSaveable(c.ha.ingress) { mutableStateOf(c.ha.ingress) }
    // the bridge knows its ingress path as a HA add-on: take it when the way is switched on and the field still empty
    LaunchedEffect(info?.haIngress, haOn) { if (haOn && haIngress.isBlank()) info?.haIngress?.let { haIngress = it } }
    val changed = vpnUrl != c.vpnUrl || haOn != c.ha.on || haUrl != c.ha.url || haToken != c.ha.token || haIngress != c.ha.ingress

    SectionLabel(tr("Remote access"), Modifier.padding(top = 8.dp))
    Text(tr("How the app reaches the bridge away from home. It always tries the home network first, then the second address, then Home Assistant."),
        style = MaterialTheme.typography.bodySmall, color = K.Muted)
    Hint(tr("Connected via: {way}", "way" to (route?.let { routeLabel(it) } ?: "–")))

    OutlinedTextField(vpnUrl, { vpnUrl = it }, label = { Text(tr("Second address (VPN), e.g. 100.92.1.5:7913")) }, singleLine = true,
        modifier = Modifier.fillMaxWidth(), shape = RoundedCornerShape(12.dp), keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri))
    Text(tr("With NetBird, Tailscale or WireGuard: the bridge's address in the VPN. Not needed if the VPN routes the whole home network – then the home address works as it is."),
        style = MaterialTheme.typography.bodySmall, color = K.Muted)

    Row(verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f)) {
            Text(tr("Through Home Assistant"), style = MaterialTheme.typography.bodyLarge)
            Text(tr("For the bridge as a Home Assistant add-on: HA passes the app on (ingress). HA must be reachable from outside (e.g. Home Assistant Cloud)."),
                style = MaterialTheme.typography.bodySmall, color = K.Muted)
        }
        Switch(haOn, { haOn = it })
    }
    if (haOn) {
        if (info != null && info?.addon == false && info?.haIngress == null)
            Hint(tr("This bridge does not run as a Home Assistant add-on – this way needs the add-on."), danger = true)
        OutlinedTextField(haUrl, { haUrl = it }, label = { Text(tr("Home Assistant address from outside")) }, singleLine = true,
            modifier = Modifier.fillMaxWidth(), shape = RoundedCornerShape(12.dp), keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri))
        OutlinedTextField(haToken, { haToken = it.trim() }, label = { Text(tr("Long-lived access token")) }, singleLine = true,
            visualTransformation = PasswordVisualTransformation(), modifier = Modifier.fillMaxWidth(), shape = RoundedCornerShape(12.dp))
        Text(tr("Create it in Home Assistant under Profile → Security. The user needs access to the add-on – usually an administrator, add-ons are admin-only unless they allow others. The token can do what its user may; it is stored encrypted on this phone."),
            style = MaterialTheme.typography.bodySmall, color = K.Muted)
        OutlinedTextField(haIngress, { haIngress = it }, label = { Text(tr("Ingress path of the add-on")) }, singleLine = true,
            modifier = Modifier.fillMaxWidth(), shape = RoundedCornerShape(12.dp))
        Text(if (info?.haIngress != null) tr("Filled in by the bridge.")
            else tr("The bridge fills it in once the web UI was opened in Home Assistant. Or paste it: /api/hassio_ingress/<long code>."),
            style = MaterialTheme.typography.bodySmall, color = K.Muted)
    }
    Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        PrimaryButton(tr("Save"), { vm.saveRemote(vpnUrl, HaRemote(haOn, haUrl, haToken, haIngress)) }, Modifier.weight(1f),
            enabled = changed && !busy)
        SecondaryButton(tr("Test"), { vm.testRemote() }, Modifier.weight(1f), enabled = !changed && !busy)
    }
    test?.let { result ->
        result.forEach { (kind, why) ->
            Hint(routeLabel(kind) + ": " + (why ?: tr("reachable")), danger = why != null)
        }
    }

    Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(top = 4.dp)) {
        Column(Modifier.weight(1f)) {
            Text(tr("Away from home: hint instead of alarm"), style = MaterialTheme.typography.bodyLarge)
            Text(tr("If the bridge is gone during a print while the phone is outside the home network, the monitoring says so quietly – with a button for the VPN app. At home it stays an alarm."),
                style = MaterialTheme.typography.bodySmall, color = K.Muted)
        }
        Switch(awayHint, { vm.setAwayHint(it) })
    }
    if (awayHint) VpnAppChoice(vpnApp) { vm.setVpnApp(it) }
}

/** Which VPN app the away hint opens (only when there is more than one; none = no button). */
@Composable
private fun VpnAppChoice(chosen: String, onChoose: (String) -> Unit) {
    val ctx = LocalContext.current
    val apps = remember { VpnApps.installed(ctx) }
    when {
        apps.isEmpty() -> Text(tr("No VPN app found – the hint comes without a button."), style = MaterialTheme.typography.bodySmall, color = K.Muted)
        apps.size == 1 -> Text(tr("The hint opens {app}.", "app" to apps.single().label), style = MaterialTheme.typography.bodySmall, color = K.Muted)
        else -> Column {
            Text(tr("VPN app for the hint"), style = MaterialTheme.typography.bodyMedium)
            val current = apps.firstOrNull { it.pkg == chosen }?.pkg
            apps.forEach { app ->
                Row(verticalAlignment = Alignment.CenterVertically,
                    modifier = Modifier.fillMaxWidth().clickable(role = Role.RadioButton) { onChoose(app.pkg) }) {
                    RadioButton(app.pkg == current, { onChoose(app.pkg) })
                    Text(app.label, style = MaterialTheme.typography.bodyMedium)
                }
            }
        }
    }
}

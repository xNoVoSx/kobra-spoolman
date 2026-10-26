package io.github.xnovosx.kobraspoolman.data

import android.content.Context
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map

/** Bridge address and app key, stored on the device (not in backups, see manifest), and the ways from outside. */
data class Connection(
    val url: String = "",
    val token: String = "",
    /** Second address of the bridge, e.g. in a VPN (NetBird, Tailscale, WireGuard); "" = none. */
    val vpnUrl: String = "",
    val ha: HaRemote = HaRemote(),
) {
    val configured: Boolean get() = url.isNotBlank()
}

/** Home Assistant as the way from outside (bridge as a HA add-on, see HaIngress). */
data class HaRemote(val on: Boolean = false, val url: String = "", val token: String = "", val ingress: String = "") {
    val ready: Boolean get() = on && url.isNotBlank() && token.isNotBlank() && ingress.isNotBlank()
}

private val Context.store by preferencesDataStore(name = "settings")

class Settings(private val context: Context) {
    private val urlKey = stringPreferencesKey("bridge_url")
    private val tokenKey = stringPreferencesKey("app_token")
    private val monitorKey = booleanPreferencesKey("monitor")
    private val render3dKey = stringPreferencesKey("render3d")
    private val appSetupKey = stringPreferencesKey("app_setup")
    private val vpnUrlKey = stringPreferencesKey("vpn_url")
    private val haOnKey = booleanPreferencesKey("ha_on")
    private val haUrlKey = stringPreferencesKey("ha_url")
    private val haTokenKey = stringPreferencesKey("ha_token_sealed")
    private val haIngressKey = stringPreferencesKey("ha_ingress")
    private val awayHintKey = booleanPreferencesKey("away_hint")
    private val vpnAppKey = stringPreferencesKey("vpn_app")

    /** Setup in the app: "" not decided yet, "pending" = freshly paired (open the setup), "hint" = paired before this
     *  version (show the hint on the Features page once), "seen" = done. */
    val appSetup: Flow<String> = context.store.data.map { it[appSetupKey].orEmpty() }

    suspend fun setAppSetup(v: String) {
        context.store.edit { it[appSetupKey] = v }
    }

    /** 3D model: auto | volume | lines | image (image of the bridge). */
    val render3d: Flow<String> = context.store.data.map { it[render3dKey] ?: "auto" }

    suspend fun setRender3d(v: String) {
        context.store.edit { it[render3dKey] = v }
    }

    /** Print monitoring in the background (notifications), on by default. */
    val monitor: Flow<Boolean> = context.store.data.map { it[monitorKey] ?: true }

    suspend fun setMonitor(on: Boolean) {
        context.store.edit { it[monitorKey] = on }
    }

    val connection: Flow<Connection> = context.store.data.map {
        Connection(it[urlKey].orEmpty(), it[tokenKey].orEmpty(), it[vpnUrlKey].orEmpty(),
            HaRemote(it[haOnKey] ?: false, it[haUrlKey].orEmpty(), Secrets.open(it[haTokenKey].orEmpty()), it[haIngressKey].orEmpty()))
    }

    /** After pairing (or forgetting it): address and key; the ways from outside stay. */
    suspend fun savePairing(url: String, token: String) {
        context.store.edit {
            it[urlKey] = BridgeClient.normalizeUrl(url)
            it[tokenKey] = token.trim()
        }
    }

    /** The ways from outside (Settings -> Remote access); the HA token is stored encrypted (Secrets). */
    suspend fun saveRemote(vpnUrl: String, ha: HaRemote) {
        context.store.edit {
            it[vpnUrlKey] = BridgeClient.normalizeUrl(vpnUrl)
            it[haOnKey] = ha.on
            it[haUrlKey] = HaIngress.normalizeUrl(ha.url)
            it[haTokenKey] = Secrets.seal(ha.token.trim())
            it[haIngressKey] = HaIngress.ingressPath(ha.ingress).orEmpty()
        }
    }

    /** Bridge gone during a print while the phone is away from home: a quiet hint instead of the alarm (on by default). */
    val awayHint: Flow<Boolean> = context.store.data.map { it[awayHintKey] ?: true }

    suspend fun setAwayHint(on: Boolean) {
        context.store.edit { it[awayHintKey] = on }
    }

    /** VPN app the away hint opens: package name, "" = the only one installed (VpnApps). */
    val vpnApp: Flow<String> = context.store.data.map { it[vpnAppKey].orEmpty() }

    suspend fun setVpnApp(pkg: String) {
        context.store.edit { it[vpnAppKey] = pkg }
    }
}

package io.github.xnovosx.kobraspoolman.data

import android.content.Context
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map

/** Bridge address and app key, stored on the device (not in backups, see manifest). */
data class Connection(val url: String = "", val token: String = "") {
    val configured: Boolean get() = url.isNotBlank()
}

private val Context.store by preferencesDataStore(name = "settings")

class Settings(private val context: Context) {
    private val urlKey = stringPreferencesKey("bridge_url")
    private val tokenKey = stringPreferencesKey("app_token")
    private val monitorKey = booleanPreferencesKey("monitor")
    private val render3dKey = stringPreferencesKey("render3d")
    private val appSetupKey = stringPreferencesKey("app_setup")

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
        Connection(it[urlKey].orEmpty(), it[tokenKey].orEmpty())
    }

    suspend fun save(c: Connection) {
        context.store.edit {
            it[urlKey] = BridgeClient.normalizeUrl(c.url)
            it[tokenKey] = c.token.trim()
        }
    }
}

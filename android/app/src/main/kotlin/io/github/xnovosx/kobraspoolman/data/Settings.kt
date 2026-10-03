package io.github.xnovosx.kobraspoolman.data

import android.content.Context
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map

/** Bridge-Adresse und App-Schluessel, gespeichert auf dem Geraet (nicht in Backups, siehe Manifest). */
data class Connection(val url: String = "", val token: String = "") {
    val configured: Boolean get() = url.isNotBlank()
}

private val Context.store by preferencesDataStore(name = "settings")

class Settings(private val context: Context) {
    private val urlKey = stringPreferencesKey("bridge_url")
    private val tokenKey = stringPreferencesKey("app_token")
    private val monitorKey = booleanPreferencesKey("monitor")
    private val render3dKey = stringPreferencesKey("render3d")

    /** 3D-Modell: auto | volume | lines | image (Bild der Bridge). */
    val render3d: Flow<String> = context.store.data.map { it[render3dKey] ?: "auto" }

    suspend fun setRender3d(v: String) {
        context.store.edit { it[render3dKey] = v }
    }

    /** Druck-Ueberwachung im Hintergrund (Benachrichtigungen), Standard an. */
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
